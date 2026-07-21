from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .numeric import (
    ConfidenceDecimal,
    UtilityDecimal,
    UtilityInteger,
    abs_exact,
    add_exact,
    subtract_exact,
)

EvidenceStatus = Literal["printed", "inferred", "user_corrected"]
AuditStatus = Literal[
    "verified", "discrepancy", "estimated", "cannot_verify", "needs_review"
]


class EvidenceBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_page: UtilityInteger = Field(ge=1, le=20)
    source_text: str = Field(min_length=1)
    confidence: ConfidenceDecimal
    status: EvidenceStatus
    original_value: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def validate_correction(self) -> Self:
        if self.status == "user_corrected" and self.original_value is None:
            raise ValueError("user-corrected facts require original_value")
        if self.status != "user_corrected" and self.original_value is not None:
            raise ValueError("original_value is only valid for user-corrected facts")
        return self


class TextFact(EvidenceBase):
    value: str = Field(min_length=1)


class DateFact(EvidenceBase):
    value: date


class IntegerFact(EvidenceBase):
    value: UtilityInteger
    unit: str | None = None


class DecimalFact(EvidenceBase):
    value: UtilityDecimal
    unit: str


class ChargeLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    section: Literal["pge_delivery", "cca_generation"]
    label: str
    period: str | None = None
    quantity: DecimalFact | None = None
    rate: DecimalFact | None = None
    billed_amount: DecimalFact


def iter_bill_evidence(bill: BillExtraction) -> Iterator[EvidenceBase]:
    yield bill.delivery_provider
    yield bill.generation_provider
    yield bill.delivery_schedule
    yield bill.generation_schedule
    yield bill.statement_date
    yield bill.service_start
    yield bill.service_end
    yield bill.billing_days
    yield bill.total_usage
    yield bill.peak_usage
    yield bill.off_peak_usage
    yield bill.baseline_territory
    yield bill.heat_source
    yield bill.baseline_allowance
    yield bill.daily_baseline_quantity
    if bill.meter_read_status is not None:
        yield bill.meter_read_status
    for line in bill.charges:
        if line.quantity is not None:
            yield line.quantity
        if line.rate is not None:
            yield line.rate
        yield line.billed_amount
    yield bill.delivery_subtotal
    yield bill.generation_subtotal
    yield bill.current_charges
    yield bill.outstanding_balance
    yield bill.amount_due


class BillExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    fixture_kind: Literal["authentic", "synthetic", "uploaded"]
    synthetic_notice: str | None = None
    document_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_count: UtilityInteger | None = Field(default=None, ge=1, le=20)
    delivery_provider: TextFact
    generation_provider: TextFact
    delivery_schedule: TextFact
    generation_schedule: TextFact
    statement_date: DateFact
    service_start: DateFact
    service_end: DateFact
    billing_days: IntegerFact
    total_usage: DecimalFact
    peak_usage: DecimalFact
    off_peak_usage: DecimalFact
    baseline_territory: TextFact
    heat_source: TextFact
    baseline_allowance: DecimalFact
    daily_baseline_quantity: DecimalFact
    meter_read_status: TextFact | None
    charges: tuple[ChargeLine, ...]
    delivery_subtotal: DecimalFact
    generation_subtotal: DecimalFact
    current_charges: DecimalFact
    outstanding_balance: DecimalFact
    amount_due: DecimalFact

    @model_validator(mode="after")
    def validate_invariants(self) -> BillExtraction:
        if self.service_end.value <= self.service_start.value:
            raise ValueError("service_end must be after service_start")

        day_span = (self.service_end.value - self.service_start.value).days
        if self.billing_days.value not in {day_span, day_span + 1}:
            raise ValueError("billing_days does not match the printed service period")

        usage_sum = add_exact(self.peak_usage.value, self.off_peak_usage.value)
        if abs_exact(subtract_exact(usage_sum, self.total_usage.value)) > Decimal(
            "0.001"
        ):
            raise ValueError("peak and off-peak quantities do not equal total usage")

        charge_ids = [line.id for line in self.charges]
        if len(charge_ids) != len(set(charge_ids)):
            raise ValueError("charge line IDs must be unique")

        charge_sections = {line.section for line in self.charges}
        for required_section in ("pge_delivery", "cca_generation"):
            if required_section not in charge_sections:
                raise ValueError(
                    f"charges must include at least one {required_section} charge"
                )

        if self.page_count is not None and any(
            fact.source_page > self.page_count for fact in iter_bill_evidence(self)
        ):
            raise ValueError(
                "evidence source_page cannot exceed authoritative page_count"
            )

        if self.fixture_kind == "synthetic" and not self.synthetic_notice:
            raise ValueError("synthetic fixtures require a visible notice")
        if self.fixture_kind != "synthetic" and self.synthetic_notice:
            raise ValueError("only synthetic fixtures may include a synthetic notice")

        return self


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    source_url: str
    local_path: str
    effective_start: date | None = None
    effective_end: date | None = None
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class TariffVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    provider: str
    schedule: str
    jurisdiction: str
    effective_start: date
    effective_end: date
    retrieved_on: date
    citations: tuple[Citation, ...]


class AuditLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    label: str
    category: Literal["tariff", "reconciliation"]
    unit: Literal["USD", "kWh"]
    billed_amount: Decimal
    expected_amount: Decimal | None
    delta: Decimal | None
    formula: str
    inputs: dict[str, str]
    source_page: int = Field(ge=1)
    source_text: str
    citations: tuple[Citation, ...] = ()
    status: AuditStatus
    limitation: str | None = None


class PlanComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["supported", "cannot_verify"]
    headline: str
    explanation: str
    required_data: tuple[str, ...] = ()


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: str
    body: str
    grounded_audit_line_ids: tuple[str, ...]
    requires_user_review: Literal[True] = True


class AuditResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    fixture_kind: Literal["authentic", "synthetic", "uploaded"]
    verdict: Literal["reconciled", "possible_discrepancy", "needs_review"]
    headline: str
    discrepancy_total: Decimal
    tariff: TariffVersion
    lines: tuple[AuditLine, ...]
    comparison: PlanComparison
    review_request: ReviewRequest
