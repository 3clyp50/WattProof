from __future__ import annotations

from typing import cast

from .models import (
    BillExtraction,
    ChargeLine,
    DateFact,
    DecimalFact,
    EvidenceBase,
    IntegerFact,
    TextFact,
    iter_bill_evidence,
)
from .utility_models import (
    CalculationSpec,
    DateFactV2,
    DecimalFactV2,
    EvidenceRef,
    FactStatus,
    IntegerFactV2,
    MoneyFactV2,
    NamedFactV2,
    ServiceSection,
    TextFactV2,
    UtilityCharge,
    UtilityDocument,
)

_PERCENT_BASES: dict[str, tuple[str, str]] = {
    "cca_nov_uut": ("cca_nov_peak", "cca_nov_off_peak"),
    "cca_dec_uut": ("cca_dec_peak", "cca_dec_off_peak"),
}
_MISSING_PAGE_COUNT_WARNING = (
    "Legacy schema 1.0 omitted authoritative page count; page_count is an "
    "evidence-page lower bound."
)


def _evidence(fact: EvidenceBase) -> EvidenceRef:
    return EvidenceRef(
        page=fact.source_page,
        text=fact.source_text,
        confidence=fact.confidence,
        provenance="rendered_page",
    )


def _status(fact: EvidenceBase) -> FactStatus:
    status = str(fact.status)
    if status not in {"printed", "inferred", "user_corrected"}:
        raise ValueError(f"unsupported legacy fact status: {status}")
    return cast(FactStatus, status)


def _original_value(fact: EvidenceBase) -> str | None:
    return fact.original_value


def _text_fact(fact: TextFact) -> TextFactV2:
    return TextFactV2(
        value=fact.value,
        status=_status(fact),
        evidence=_evidence(fact),
        original_value=_original_value(fact),
    )


def _date_fact(fact: DateFact) -> DateFactV2:
    return DateFactV2(
        value=fact.value,
        status=_status(fact),
        evidence=_evidence(fact),
        original_value=_original_value(fact),
    )


def _decimal_fact(fact: DecimalFact) -> DecimalFactV2:
    return DecimalFactV2(
        value=fact.value,
        unit=fact.unit,
        status=_status(fact),
        evidence=_evidence(fact),
        original_value=_original_value(fact),
    )


def _integer_fact(fact: IntegerFact) -> IntegerFactV2:
    return IntegerFactV2(
        value=fact.value,
        unit=fact.unit,
        status=_status(fact),
        evidence=_evidence(fact),
        original_value=_original_value(fact),
    )


def _money_fact(fact: DecimalFact) -> MoneyFactV2:
    return MoneyFactV2(
        value=fact.value,
        currency=fact.unit,
        status=_status(fact),
        evidence=_evidence(fact),
        original_value=_original_value(fact),
    )


def _calculation(line: ChargeLine) -> CalculationSpec | None:
    percent_bases = _PERCENT_BASES.get(line.id)
    if percent_bases is not None:
        return CalculationSpec(kind="percent_of_charges", charge_ids=percent_bases)
    if line.quantity is not None and line.rate is not None:
        return CalculationSpec(kind="quantity_times_rate")
    return None


def _charge(line: ChargeLine) -> UtilityCharge:
    return UtilityCharge(
        id=line.id,
        label=line.label,
        period=line.period,
        quantity=_decimal_fact(line.quantity) if line.quantity is not None else None,
        rate=_decimal_fact(line.rate) if line.rate is not None else None,
        amount=_money_fact(line.billed_amount),
        calculation=_calculation(line),
    )


def _supplemental_facts(bill: BillExtraction) -> tuple[NamedFactV2, ...]:
    facts = [
        NamedFactV2(id="billing_days", fact=_integer_fact(bill.billing_days)),
        NamedFactV2(id="peak_usage", fact=_decimal_fact(bill.peak_usage)),
        NamedFactV2(id="off_peak_usage", fact=_decimal_fact(bill.off_peak_usage)),
        NamedFactV2(id="baseline_territory", fact=_text_fact(bill.baseline_territory)),
        NamedFactV2(id="heat_source", fact=_text_fact(bill.heat_source)),
        NamedFactV2(
            id="baseline_allowance", fact=_decimal_fact(bill.baseline_allowance)
        ),
        NamedFactV2(
            id="daily_baseline_quantity",
            fact=_decimal_fact(bill.daily_baseline_quantity),
        ),
    ]
    if bill.meter_read_status is not None:
        facts.append(
            NamedFactV2(
                id="meter_read_status", fact=_text_fact(bill.meter_read_status)
            )
        )
    return tuple(facts)


def translate_legacy_bill(bill: BillExtraction) -> UtilityDocument:
    """Translate a schema-1 PG&E extraction without tariff lookup or arithmetic."""

    delivery_charges = tuple(
        _charge(line) for line in bill.charges if line.section == "pge_delivery"
    )
    generation_charges = tuple(
        _charge(line) for line in bill.charges if line.section == "cca_generation"
    )
    sections = (
        ServiceSection(
            id="pge_delivery",
            service_type="electricity",
            provider=_text_fact(bill.delivery_provider),
            schedule=_text_fact(bill.delivery_schedule),
            service_start=_date_fact(bill.service_start),
            service_end=_date_fact(bill.service_end),
            usage=_decimal_fact(bill.total_usage),
            supplemental_facts=_supplemental_facts(bill),
            charges=delivery_charges,
            subtotal=_money_fact(bill.delivery_subtotal),
        ),
        ServiceSection(
            id="cca_generation",
            service_type="electricity",
            provider=_text_fact(bill.generation_provider),
            schedule=_text_fact(bill.generation_schedule),
            service_start=_date_fact(bill.service_start),
            service_end=_date_fact(bill.service_end),
            charges=generation_charges,
            subtotal=_money_fact(bill.generation_subtotal),
        ),
    )
    warnings = [bill.synthetic_notice] if bill.synthetic_notice is not None else []
    if bill.page_count is None:
        page_count = max(fact.source_page for fact in iter_bill_evidence(bill))
        warnings.append(_MISSING_PAGE_COUNT_WARNING)
    else:
        page_count = bill.page_count

    return UtilityDocument(
        schema_version="2.0",
        fixture_kind=bill.fixture_kind,
        document_sha256=bill.document_sha256,
        page_count=page_count,
        statement_date=_date_fact(bill.statement_date),
        currency=bill.current_charges.unit,
        sections=sections,
        current_charges=_money_fact(bill.current_charges),
        outstanding_balance=_money_fact(bill.outstanding_balance),
        amount_due=_money_fact(bill.amount_due),
        warnings=tuple(warnings),
    )
