from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


EvidenceStatus = Literal["printed", "inferred"]
AuditStatus = Literal[
    "verified", "discrepancy", "estimated", "cannot_verify", "needs_review"
]


class EvidenceBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_page: int = Field(ge=1)
    source_text: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    status: EvidenceStatus


class TextFact(EvidenceBase):
    value: str = Field(min_length=1)


class DateFact(EvidenceBase):
    value: date


class IntegerFact(EvidenceBase):
    value: int
    unit: str | None = None


class DecimalFact(EvidenceBase):
    value: Decimal
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


class BillExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    fixture_kind: Literal["authentic", "synthetic", "uploaded"]
    synthetic_notice: str | None = None
    document_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
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

        if abs(
            self.peak_usage.value
            + self.off_peak_usage.value
            - self.total_usage.value
        ) > Decimal("0.001"):
            raise ValueError("peak and off-peak quantities do not equal total usage")

        charge_ids = [line.id for line in self.charges]
        if len(charge_ids) != len(set(charge_ids)):
            raise ValueError("charge line IDs must be unique")

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
