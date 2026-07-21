from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from datetime import date
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import Citation, PlanComparison, TariffVersion
from .numeric import ConfidenceDecimal, UtilityDecimal, UtilityInteger

FactStatus = Literal["printed", "inferred", "user_corrected"]
ServiceType = Literal[
    "electricity",
    "natural_gas",
    "water",
    "wastewater",
    "stormwater",
    "sanitation",
    "other",
]
AuditStatusV2 = Literal["verified", "discrepancy", "cannot_verify", "needs_review"]
AuditScope = Literal["printed_math", "statement_reconciliation", "published_tariff"]
VerificationLevel = Literal[
    "evidence_extracted",
    "internally_reconciled",
    "tariff_verified",
]


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    page: UtilityInteger = Field(ge=1, le=20)
    text: str = Field(min_length=1)
    confidence: ConfidenceDecimal
    provenance: Literal["rendered_page"] = "rendered_page"


class FactBaseV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: FactStatus
    evidence: EvidenceRef
    original_value: str | None = None

    @model_validator(mode="after")
    def validate_correction(self) -> Self:
        if self.status == "user_corrected" and self.original_value is None:
            raise ValueError("user-corrected facts require original_value")
        if self.status != "user_corrected" and self.original_value is not None:
            raise ValueError("original_value is only valid for user-corrected facts")
        return self


class TextFactV2(FactBaseV2):
    value: str = Field(min_length=1)


class DateFactV2(FactBaseV2):
    value: date


class IntegerFactV2(FactBaseV2):
    value: UtilityInteger
    unit: str | None = None


class DecimalFactV2(FactBaseV2):
    value: UtilityDecimal
    unit: str = Field(min_length=1)


class MoneyFactV2(FactBaseV2):
    value: UtilityDecimal
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class NamedFactV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    fact: TextFactV2 | IntegerFactV2 | DecimalFactV2


class CalculationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["quantity_times_rate", "percent_of_charges"]
    charge_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_charge_ids(self) -> Self:
        if self.kind == "percent_of_charges" and not self.charge_ids:
            raise ValueError("percent_of_charges requires charge_ids")
        if self.kind == "quantity_times_rate" and self.charge_ids:
            raise ValueError("quantity_times_rate does not accept charge_ids")
        return self


class UtilityCharge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    label: str = Field(min_length=1)
    period: str | None = None
    quantity: DecimalFactV2 | None = None
    rate: DecimalFactV2 | None = None
    amount: MoneyFactV2
    calculation: CalculationSpec | None = None

    @model_validator(mode="after")
    def validate_calculation_operands(self) -> Self:
        if (
            self.calculation is not None
            and self.calculation.kind == "quantity_times_rate"
            and (self.quantity is None or self.rate is None)
        ):
            raise ValueError("quantity_times_rate requires both quantity and rate")
        return self


class MeterCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    previous: DecimalFactV2
    current: DecimalFactV2
    usage: DecimalFactV2


class ConversionCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    label: str
    source: DecimalFactV2
    factor: DecimalFactV2
    result: DecimalFactV2


class QuantitySumCheck(BaseModel):
    """A declared sum of charge quantities against one printed target.

    Charge IDs make the relationship explicit so reconciliation never guesses from
    provider-specific labels such as "tier" or "block".
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    label: str = Field(min_length=1)
    charge_ids: tuple[str, ...] = Field(min_length=1)
    target: DecimalFactV2

    @model_validator(mode="after")
    def validate_charge_ids(self) -> Self:
        if len(self.charge_ids) != len(set(self.charge_ids)):
            raise ValueError("quantity-sum charge_ids must be unique")
        return self


class ServiceSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    service_type: ServiceType
    provider: TextFactV2
    normalized_provider: str | None = None
    jurisdiction: TextFactV2 | None = None
    schedule: TextFactV2 | None = None
    service_start: DateFactV2 | None = None
    service_end: DateFactV2 | None = None
    usage: DecimalFactV2 | None = None
    meter: MeterCheck | None = None
    conversions: tuple[ConversionCheck, ...] = ()
    quantity_sums: tuple[QuantitySumCheck, ...] = ()
    supplemental_facts: tuple[NamedFactV2, ...] = ()
    charges: tuple[UtilityCharge, ...] = Field(min_length=1)
    subtotal: MoneyFactV2

    @model_validator(mode="after")
    def validate_section_invariants(self) -> Self:
        if (
            self.service_start is not None
            and self.service_end is not None
            and self.service_start.value > self.service_end.value
        ):
            raise ValueError("service_start must be on or before service_end")

        conversion_ids = [conversion.id for conversion in self.conversions]
        if len(conversion_ids) != len(set(conversion_ids)):
            raise ValueError("conversion IDs must be unique within a section")

        supplemental_fact_ids = [fact.id for fact in self.supplemental_facts]
        if len(supplemental_fact_ids) != len(set(supplemental_fact_ids)):
            raise ValueError("supplemental fact IDs must be unique within a section")

        quantity_sum_ids = [quantity_sum.id for quantity_sum in self.quantity_sums]
        if len(quantity_sum_ids) != len(set(quantity_sum_ids)):
            raise ValueError("quantity-sum IDs must be unique within a section")

        known_charge_ids = {charge.id for charge in self.charges}
        for quantity_sum in self.quantity_sums:
            unknown_ids = [
                charge_id
                for charge_id in quantity_sum.charge_ids
                if charge_id not in known_charge_ids
            ]
            if unknown_ids:
                raise ValueError(
                    "quantity-sum references unknown charge ID: "
                    f"{unknown_ids[0]}"
                )
        return self


def _walk_nested(value: object) -> Iterator[object]:
    yield value
    if isinstance(value, BaseModel):
        for field_name in type(value).model_fields:
            yield from _walk_nested(getattr(value, field_name))
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_nested(item)
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _walk_nested(item)


class UtilityDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["2.0"]
    fixture_kind: Literal[
        "authentic",
        "synthetic",
        "duke",
        "centerpoint",
        "bloomington",
        "uploaded",
    ]
    document_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_count: UtilityInteger = Field(ge=1, le=20)
    source_url: str | None = None
    statement_date: DateFactV2 | None = None
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    sections: tuple[ServiceSection, ...] = Field(min_length=1)
    current_charges: MoneyFactV2
    outstanding_balance: MoneyFactV2 | None = None
    amount_due: MoneyFactV2
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_document_invariants(self) -> Self:
        section_ids = [section.id for section in self.sections]
        if len(section_ids) != len(set(section_ids)):
            raise ValueError("section IDs must be unique")

        charge_ids = [charge.id for section in self.sections for charge in section.charges]
        if len(charge_ids) != len(set(charge_ids)):
            raise ValueError("charge IDs must be unique across all sections")

        known_charge_ids = set(charge_ids)
        for section in self.sections:
            for charge in section.charges:
                calculation = charge.calculation
                if calculation is None or calculation.kind != "percent_of_charges":
                    continue
                references = calculation.charge_ids
                if len(references) != len(set(references)):
                    raise ValueError(
                        "percent_of_charges charge_ids must be unique"
                    )
                if charge.id in references:
                    raise ValueError(
                        "percent_of_charges cannot reference its own charge ID"
                    )
                unknown = [
                    reference
                    for reference in references
                    if reference not in known_charge_ids
                ]
                if unknown:
                    raise ValueError(
                        f"percent_of_charges references unknown charge ID: {unknown[0]}"
                    )

        nested = tuple(_walk_nested(self))
        if any(
            isinstance(value, MoneyFactV2) and value.currency != self.currency
            for value in nested
        ):
            raise ValueError("every money fact currency must match the document currency")

        if any(
            isinstance(value, EvidenceRef) and value.page > self.page_count
            for value in nested
        ):
            raise ValueError("evidence page cannot exceed the trusted page_count")

        return self


class UtilityAuditLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    section_id: str | None
    label: str
    scope: AuditScope
    unit: str
    billed_amount: Decimal | None
    billed_status: FactStatus | None = None
    billed_original_value: str | None = None
    expected_amount: Decimal | None
    delta: Decimal | None
    formula: str
    inputs: dict[str, str]
    evidence: tuple[EvidenceRef, ...]
    citations: tuple[Citation, ...] = ()
    status: AuditStatusV2
    limitation: str | None = None
    root_cause_id: str | None = None
    root_cause_ids: tuple[str, ...] = Field(
        default=(),
        exclude_if=lambda root_ids: not root_ids,
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_root_cause_fields(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        fields = dict(value)
        single = fields.get("root_cause_id")
        raw_multiple = fields.get("root_cause_ids", ())
        if raw_multiple is not None and not isinstance(raw_multiple, (list, tuple)):
            raise ValueError("root_cause_ids must be an array of audit line IDs")
        multiple = tuple(raw_multiple) if raw_multiple is not None else ()
        if single is not None and multiple and multiple != (single,):
            raise ValueError(
                "root_cause_id must match the sole root_cause_ids dependency"
            )
        if single is not None and not multiple:
            multiple = (single,)
        if single is None and len(multiple) == 1:
            single = multiple[0]
        fields["root_cause_id"] = single
        fields["root_cause_ids"] = multiple
        return fields

    @model_validator(mode="after")
    def validate_line_invariants(self) -> Self:
        if self.billed_status == "user_corrected" and self.billed_original_value is None:
            raise ValueError(
                "billed_original_value is required for a user-corrected billed fact"
            )
        if self.billed_status != "user_corrected" and self.billed_original_value is not None:
            raise ValueError(
                "billed_original_value is only valid for a user-corrected billed fact"
            )
        root_ids = self.root_cause_ids
        if len(root_ids) != len(set(root_ids)):
            raise ValueError("root cause dependencies must be distinct")
        if any(not root_id for root_id in root_ids):
            raise ValueError("root cause dependency IDs must not be empty")
        if self.id in root_ids:
            raise ValueError("an audit line cannot name itself as a root cause")
        if root_ids and self.status != "discrepancy":
            raise ValueError("only discrepancy lines may declare root causes")
        if len(root_ids) == 1 and self.root_cause_id != root_ids[0]:
            raise ValueError("root_cause_id must match the sole root cause dependency")
        if len(root_ids) != 1 and self.root_cause_id is not None:
            raise ValueError(
                "root_cause_id is only valid for one root cause dependency"
            )
        return self


def ordered_root_cause_ids(*groups: Iterable[str]) -> tuple[str, ...]:
    """Merge root IDs in first-seen order without duplicating dependencies."""

    ordered: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for root_id in group:
            if root_id in seen:
                continue
            seen.add(root_id)
            ordered.append(root_id)
    return tuple(ordered)


def root_cause_ids_for(line: UtilityAuditLine) -> tuple[str, ...]:
    """Read both the multi-root field and the retained legacy single-root field."""

    if line.root_cause_ids:
        return line.root_cause_ids
    if line.root_cause_id is not None:
        return (line.root_cause_id,)
    return ()


def root_cause_update(root_ids: Iterable[str]) -> dict[str, object]:
    """Return a canonical model-copy update for zero, one, or many roots."""

    ordered = ordered_root_cause_ids(root_ids)
    return {
        "root_cause_id": ordered[0] if len(ordered) == 1 else None,
        "root_cause_ids": ordered,
    }


def order_audit_lines_by_dependencies(
    lines: Iterable[UtilityAuditLine],
) -> tuple[UtilityAuditLine, ...]:
    """Keep producer order stable while moving dependents behind every root."""

    original = tuple(lines)
    original_order = {line.id: index for index, line in enumerate(original)}
    canonical = tuple(
        line.model_copy(
            update=root_cause_update(
                sorted(
                    root_cause_ids_for(line),
                    key=lambda root_id: original_order.get(root_id, len(original)),
                )
            )
        )
        if root_cause_ids_for(line)
        else line
        for line in original
    )

    ordered: list[UtilityAuditLine] = []
    emitted_ids: set[str] = set()
    pending = list(canonical)
    while pending:
        for index, line in enumerate(pending):
            if all(root_id in emitted_ids for root_id in root_cause_ids_for(line)):
                ready = pending.pop(index)
                ordered.append(ready)
                emitted_ids.add(ready.id)
                break
        else:
            # Leave malformed missing/cyclic dependencies for result validation to
            # reject with its controlled schema error.
            ordered.extend(pending)
            break
    return tuple(ordered)


class ProviderReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    subject: str
    body: str
    grounded_audit_line_ids: tuple[str, ...]
    requires_user_review: Literal[True] = True


class UtilityAuditResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["2.0"]
    fixture_kind: str
    verdict: Literal["reconciled", "possible_discrepancy", "needs_review"]
    verification_level: VerificationLevel
    headline: str
    discrepancy_total: Decimal
    currency: str
    lines: tuple[UtilityAuditLine, ...]
    tariff: TariffVersion | None = None
    comparison: PlanComparison | None = None
    review_requests: tuple[ProviderReviewRequest, ...] = ()

    @model_validator(mode="after")
    def validate_result_invariants(self) -> Self:
        line_ids = tuple(line.id for line in self.lines)
        if len(line_ids) != len(set(line_ids)):
            raise ValueError("audit line IDs must be unique")
        lines_by_id = {line.id: line for line in self.lines}
        line_order = {line_id: index for index, line_id in enumerate(line_ids)}
        for line in self.lines:
            root_ids = root_cause_ids_for(line)
            if len(root_ids) != len(set(root_ids)):
                raise ValueError("root cause dependencies must be distinct")
            if line.id in root_ids:
                raise ValueError("an audit line cannot name itself as a root cause")
            expected_single = root_ids[0] if len(root_ids) == 1 else None
            if line.root_cause_id != expected_single:
                raise ValueError(
                    "root_cause_id must preserve single-root compatibility"
                )
            missing = tuple(root_id for root_id in root_ids if root_id not in lines_by_id)
            if missing:
                raise ValueError(
                    f"root cause dependency references missing audit line: {missing[0]}"
                )
            later_roots = tuple(
                root_id
                for root_id in root_ids
                if line_order[root_id] >= line_order[line.id]
            )
            if later_roots:
                raise ValueError(
                    "root cause dependency must appear before the dependent "
                    f"audit line: {later_roots[0]}"
                )
            expected_order = tuple(
                sorted(root_ids, key=line_order.__getitem__)
            )
            if root_ids != expected_order:
                raise ValueError(
                    "root cause dependencies must follow stable audit-line order"
                )
            for root_id in root_ids:
                root = lines_by_id[root_id]
                if root.status != "discrepancy" or root_cause_ids_for(root):
                    raise ValueError(
                        "root cause dependencies must reference independent "
                        "discrepancy lines"
                    )

        for request in self.review_requests:
            grounded = request.grounded_audit_line_ids
            if len(grounded) != len(set(grounded)):
                raise ValueError("review request grounding IDs must be distinct")
            for line_id in grounded:
                grounded_line = lines_by_id.get(line_id)
                if grounded_line is None:
                    raise ValueError(
                        f"review request references missing audit line: {line_id}"
                    )
                if root_cause_ids_for(grounded_line):
                    raise ValueError(
                        "review request cannot ground a dependent audit line"
                    )

        published = tuple(
            line for line in self.lines if line.scope == "published_tariff"
        )
        if not published:
            return self
        if self.tariff is None:
            raise ValueError(
                "published_tariff lines require attached tariff archive metadata"
            )
        archived = self.tariff.citations
        for line in published:
            if not line.citations:
                raise ValueError(
                    "published_tariff lines require archived citations"
                )
            for citation in line.citations:
                if citation not in archived:
                    raise ValueError(
                        "published_tariff citations must be attached to the tariff archive"
                    )
                if not (
                    citation.label.strip()
                    and citation.source_url.strip()
                    and citation.local_path.strip()
                ):
                    raise ValueError(
                        "published_tariff citations require complete archive metadata"
                    )
        return self
