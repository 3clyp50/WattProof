from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from wattproof.fixtures import load_sample
from wattproof.legacy import translate_legacy_bill
from wattproof.models import BillExtraction, EvidenceBase
from wattproof.utility_fixtures import load_utility_sample
from wattproof.utility_models import (
    CalculationSpec,
    DateFactV2,
    DecimalFactV2,
    EvidenceRef,
    FactBaseV2,
    IntegerFactV2,
    MoneyFactV2,
    ProviderReviewRequest,
    QuantitySumCheck,
    ServiceSection,
    TextFactV2,
    UtilityAuditLine,
    UtilityAuditResult,
    UtilityCharge,
    UtilityDocument,
)


def evidence() -> EvidenceRef:
    return EvidenceRef(page=1, text="visible statement text", confidence=Decimal("1"))


def audit_line_payload() -> dict[str, Any]:
    return {
        "id": "charge::example",
        "section_id": "water",
        "label": "Example charge",
        "scope": "printed_math",
        "unit": "USD",
        "billed_amount": Decimal("10.00"),
        "expected_amount": Decimal("10.00"),
        "delta": Decimal("0.00"),
        "formula": "10.00 USD",
        "inputs": {"amount": "10.00 USD"},
        "evidence": (evidence(),),
        "status": "verified",
    }


def test_audit_line_serializes_typed_billed_provenance() -> None:
    line = UtilityAuditLine(
        **audit_line_payload(),
        billed_status="printed",
    )

    serialized = line.model_dump(mode="json")
    assert serialized["billed_status"] == "printed"
    assert serialized["billed_original_value"] is None


def test_audit_line_user_correction_requires_original_value() -> None:
    with pytest.raises(ValidationError, match="billed_original_value"):
        UtilityAuditLine(
            **audit_line_payload(),
            billed_status="user_corrected",
        )


def test_audit_line_non_correction_rejects_original_value() -> None:
    with pytest.raises(ValidationError, match="billed_original_value"):
        UtilityAuditLine(
            **audit_line_payload(),
            billed_status="inferred",
            billed_original_value="9.00",
        )


def test_audit_line_allows_legacy_provenance_to_remain_absent() -> None:
    line = UtilityAuditLine(**audit_line_payload())

    assert line.billed_status is None
    assert line.billed_original_value is None


def discrepancy_line_payload(line_id: str) -> dict[str, Any]:
    payload = audit_line_payload()
    payload.update(
        id=line_id,
        label=line_id,
        billed_amount=Decimal("10.00"),
        expected_amount=Decimal("9.00"),
        delta=Decimal("1.00"),
        status="discrepancy",
    )
    return payload


def audit_result_with_lines(*lines: UtilityAuditLine) -> UtilityAuditResult:
    return UtilityAuditResult(
        schema_version="2.0",
        fixture_kind="uploaded",
        verdict="possible_discrepancy",
        verification_level="internally_reconciled",
        headline="Possible discrepancy",
        discrepancy_total=Decimal("1.00"),
        currency="USD",
        lines=lines,
    )


def test_single_root_cause_id_remains_backward_compatible_json() -> None:
    line = UtilityAuditLine(
        **discrepancy_line_payload("dependent"),
        root_cause_id="root",
    )

    assert line.root_cause_id == "root"
    assert line.root_cause_ids == ("root",)
    assert line.model_dump(mode="json")["root_cause_id"] == "root"
    assert line.model_dump(mode="json")["root_cause_ids"] == ["root"]


def test_multi_root_dependency_serializes_without_a_false_single_root() -> None:
    roots = (
        UtilityAuditLine(**discrepancy_line_payload("root_a")),
        UtilityAuditLine(**discrepancy_line_payload("root_b")),
    )
    dependent = UtilityAuditLine(
        **discrepancy_line_payload("dependent"),
        root_cause_ids=("root_a", "root_b"),
    )

    result = audit_result_with_lines(*roots, dependent)
    serialized = result.model_dump(mode="json")["lines"][-1]

    assert dependent.root_cause_id is None
    assert dependent.root_cause_ids == ("root_a", "root_b")
    assert serialized["root_cause_id"] is None
    assert serialized["root_cause_ids"] == ["root_a", "root_b"]


@pytest.mark.parametrize(
    "root_cause_ids",
    [
        ("root", "root"),
        ("dependent",),
    ],
)
def test_audit_line_rejects_duplicate_or_self_root_dependencies(
    root_cause_ids: tuple[str, ...],
) -> None:
    with pytest.raises(ValidationError, match="root cause"):
        UtilityAuditLine(
            **discrepancy_line_payload("dependent"),
            root_cause_ids=root_cause_ids,
        )


def test_audit_line_rejects_conflicting_single_and_multi_root_fields() -> None:
    with pytest.raises(ValidationError, match="root_cause_id"):
        UtilityAuditLine(
            **discrepancy_line_payload("dependent"),
            root_cause_id="root_a",
            root_cause_ids=("root_a", "root_b"),
        )


def test_audit_line_rejects_unordered_root_dependency_input() -> None:
    with pytest.raises(ValidationError, match="must be an array"):
        UtilityAuditLine.model_validate(
            {
                **discrepancy_line_payload("dependent"),
                "root_cause_ids": {"root"},
            }
        )


def test_audit_result_rejects_missing_or_out_of_order_root_dependencies() -> None:
    root_a = UtilityAuditLine(**discrepancy_line_payload("root_a"))
    root_b = UtilityAuditLine(**discrepancy_line_payload("root_b"))
    missing = UtilityAuditLine(
        **discrepancy_line_payload("missing_dependent"),
        root_cause_ids=("missing",),
    )
    out_of_order = UtilityAuditLine(
        **discrepancy_line_payload("ordered_dependent"),
        root_cause_ids=("root_b", "root_a"),
    )

    with pytest.raises(ValidationError, match="missing audit line"):
        audit_result_with_lines(root_a, missing)
    with pytest.raises(ValidationError, match="stable audit-line order"):
        audit_result_with_lines(root_a, root_b, out_of_order)


def test_audit_result_rejects_review_grounding_to_a_dependent_symptom() -> None:
    root = UtilityAuditLine(**discrepancy_line_payload("root"))
    dependent = UtilityAuditLine(
        **discrepancy_line_payload("dependent"),
        root_cause_id="root",
    )
    request = ProviderReviewRequest(
        provider="Example Utility",
        subject="Review",
        body="Review this calculation.",
        grounded_audit_line_ids=("dependent",),
    )

    with pytest.raises(ValidationError, match="dependent audit line"):
        UtilityAuditResult(
            schema_version="2.0",
            fixture_kind="uploaded",
            verdict="possible_discrepancy",
            verification_level="internally_reconciled",
            headline="Possible discrepancy",
            discrepancy_total=Decimal("1.00"),
            currency="USD",
            lines=(root, dependent),
            review_requests=(request,),
        )


def test_document_supports_multiple_service_sections() -> None:
    provider = TextFactV2(value="Example Utility", status="printed", evidence=evidence())
    start = DateFactV2(value=date(2026, 1, 1), status="printed", evidence=evidence())
    end = DateFactV2(value=date(2026, 1, 31), status="printed", evidence=evidence())
    amount = MoneyFactV2(
        value=Decimal("10.00"), currency="USD", status="printed", evidence=evidence()
    )
    section = ServiceSection(
        id="water",
        service_type="water",
        provider=provider,
        service_start=start,
        service_end=end,
        charges=(UtilityCharge(id="water_service", label="Water service", amount=amount),),
        subtotal=amount,
    )
    document = UtilityDocument(
        schema_version="2.0",
        fixture_kind="uploaded",
        document_sha256="a" * 64,
        page_count=1,
        statement_date=end,
        currency="USD",
        sections=(section,),
        current_charges=amount,
        amount_due=amount,
    )
    assert document.sections[0].service_type == "water"


def test_user_correction_requires_original_value() -> None:
    with pytest.raises(ValidationError, match="original_value"):
        TextFactV2(value="Corrected Utility", status="user_corrected", evidence=evidence())


def test_printed_fact_rejects_original_value() -> None:
    with pytest.raises(ValidationError, match="original_value"):
        TextFactV2(
            value="Example Utility",
            status="printed",
            evidence=evidence(),
            original_value="Other Utility",
        )


def test_legacy_translation_preserves_pg_and_e_statement() -> None:
    translated = translate_legacy_bill(load_sample("authentic"))
    assert [section.id for section in translated.sections] == [
        "pge_delivery",
        "cca_generation",
    ]
    assert translated.sections[0].usage is not None
    assert translated.sections[0].usage.value == Decimal("327.119")
    assert translated.current_charges.value == Decimal("96.44")
    assert translated.amount_due.value == Decimal("96.24")


def test_legacy_translation_preserves_authoritative_page_count() -> None:
    legacy = load_sample("authentic")

    translated = translate_legacy_bill(legacy)

    assert max(line.billed_amount.source_page for line in legacy.charges) == 4
    assert legacy.page_count == 6
    assert translated.page_count == 6
    assert not any("evidence-page lower bound" in warning for warning in translated.warnings)


def test_legacy_schema_one_payload_without_page_count_still_validates() -> None:
    payload = load_sample("authentic").model_dump(mode="json")
    payload.pop("page_count")

    legacy = BillExtraction.model_validate(payload)

    assert legacy.schema_version == "1.0"
    assert legacy.page_count is None


def test_legacy_translation_warns_when_page_count_is_only_a_lower_bound() -> None:
    payload = load_sample("authentic").model_dump(mode="json")
    payload.pop("page_count")
    legacy = BillExtraction.model_validate(payload)

    translated = translate_legacy_bill(legacy)

    assert translated.page_count == 4
    assert (
        "Legacy schema 1.0 omitted authoritative page count; page_count is an "
        "evidence-page lower bound."
    ) in translated.warnings


def test_legacy_translation_preserves_charge_math_and_evidence() -> None:
    legacy = load_sample("authentic")
    translated = translate_legacy_bill(legacy)
    charges = {
        charge.id: charge
        for section in translated.sections
        for charge in section.charges
    }

    peak = charges["pge_peak_energy"]
    assert peak.quantity is not None
    assert peak.quantity.value == Decimal("92.965")
    assert peak.rate is not None
    assert peak.rate.value == Decimal("0.39193")
    assert peak.amount.evidence.page == 3
    assert peak.amount.evidence.text == legacy.charges[0].billed_amount.source_text
    assert peak.amount.evidence.confidence == Decimal("1.0")
    assert peak.calculation == CalculationSpec(kind="quantity_times_rate")

    assert charges["cca_nov_uut"].calculation == CalculationSpec(
        kind="percent_of_charges",
        charge_ids=("cca_nov_peak", "cca_nov_off_peak"),
    )
    assert charges["cca_dec_uut"].calculation == CalculationSpec(
        kind="percent_of_charges",
        charge_ids=("cca_dec_peak", "cca_dec_off_peak"),
    )


def assert_legacy_fact_preserved(
    source: EvidenceBase, translated: FactBaseV2
) -> None:
    assert getattr(translated, "value") == getattr(source, "value")
    assert getattr(translated, "unit", None) == getattr(source, "unit", None)
    assert translated.status == source.status
    assert translated.original_value == source.original_value
    assert translated.evidence.page == source.source_page
    assert translated.evidence.text == source.source_text
    assert translated.evidence.confidence == Decimal(str(source.confidence))
    assert translated.evidence.provenance == "rendered_page"


def test_legacy_translation_preserves_all_material_facts_and_charge_periods() -> None:
    legacy = load_sample("authentic")
    translated = translate_legacy_bill(legacy)
    delivery = translated.sections[0]
    translated_facts = {
        named_fact.id: named_fact.fact for named_fact in delivery.supplemental_facts
    }
    legacy_facts = {
        "billing_days": legacy.billing_days,
        "peak_usage": legacy.peak_usage,
        "off_peak_usage": legacy.off_peak_usage,
        "baseline_territory": legacy.baseline_territory,
        "heat_source": legacy.heat_source,
        "baseline_allowance": legacy.baseline_allowance,
        "daily_baseline_quantity": legacy.daily_baseline_quantity,
    }

    assert translated_facts.keys() == legacy_facts.keys()
    assert isinstance(translated_facts["billing_days"], IntegerFactV2)
    for fact_id, source in legacy_facts.items():
        assert_legacy_fact_preserved(source, translated_facts[fact_id])

    translated_periods = {
        charge.id: charge.period
        for section in translated.sections
        for charge in section.charges
    }
    assert translated_periods == {line.id: line.period for line in legacy.charges}


def test_legacy_translation_preserves_meter_read_status_when_present() -> None:
    payload = load_sample("authentic").model_dump(mode="json")
    payload["meter_read_status"] = {
        **payload["heat_source"],
        "value": "Estimated read",
        "source_text": "Meter read status: Estimated",
    }
    legacy = BillExtraction.model_validate(payload)

    translated = translate_legacy_bill(legacy)
    translated_facts = {
        named_fact.id: named_fact.fact
        for named_fact in translated.sections[0].supplemental_facts
    }

    assert legacy.meter_read_status is not None
    assert_legacy_fact_preserved(
        legacy.meter_read_status, translated_facts["meter_read_status"]
    )


def test_legacy_translation_preserves_user_correction_provenance_if_present() -> None:
    payload = load_sample("authentic").model_dump(mode="json")
    original_value = payload["delivery_provider"]["value"]
    payload["delivery_provider"].update(
        value="PG&E",
        status="user_corrected",
        original_value=original_value,
    )
    corrected_bill = BillExtraction.model_validate(payload)

    translated = translate_legacy_bill(corrected_bill)
    revalidated = UtilityDocument.model_validate_json(translated.model_dump_json())
    provider = revalidated.sections[0].provider

    assert provider.status == "user_corrected"
    assert provider.value == "PG&E"
    assert provider.original_value == original_value
    assert provider.evidence.page == corrected_bill.delivery_provider.source_page
    assert provider.evidence.text == corrected_bill.delivery_provider.source_text
    assert provider.evidence.confidence == Decimal(
        str(corrected_bill.delivery_provider.confidence)
    )


def test_legacy_user_correction_requires_original_value() -> None:
    payload = load_sample("authentic").model_dump(mode="json")
    payload["delivery_provider"]["status"] = "user_corrected"

    with pytest.raises(ValidationError, match="original_value"):
        BillExtraction.model_validate(payload)


@pytest.mark.parametrize("status", ["printed", "inferred"])
def test_legacy_non_corrected_fact_rejects_original_value(status: str) -> None:
    payload = load_sample("authentic").model_dump(mode="json")
    payload["delivery_provider"].update(
        status=status,
        original_value="Original Utility",
    )

    with pytest.raises(ValidationError, match="original_value"):
        BillExtraction.model_validate(payload)


def test_legacy_bill_requires_pge_delivery_charge() -> None:
    payload = load_sample("authentic").model_dump(mode="json")
    payload["charges"] = [
        charge for charge in payload["charges"] if charge["section"] != "pge_delivery"
    ]

    with pytest.raises(ValidationError, match="at least one pge_delivery charge"):
        BillExtraction.model_validate(payload)


def test_legacy_bill_requires_cca_generation_charge() -> None:
    payload = load_sample("authentic").model_dump(mode="json")
    payload["charges"] = [
        charge for charge in payload["charges"] if charge["section"] != "cca_generation"
    ]

    with pytest.raises(ValidationError, match="at least one cca_generation charge"):
        BillExtraction.model_validate(payload)


def test_legacy_bill_rejects_evidence_after_authoritative_page_count() -> None:
    payload = load_sample("authentic").model_dump(mode="json")
    payload["page_count"] = 3

    with pytest.raises(ValidationError, match="source_page.*page_count"):
        BillExtraction.model_validate(payload)


@pytest.mark.parametrize("fact_name", ["quantity", "rate", "billed_amount"])
def test_legacy_bill_rejects_charge_evidence_after_page_count(
    fact_name: str,
) -> None:
    payload = load_sample("authentic").model_dump(mode="json")
    charge = next(
        charge for charge in payload["charges"] if charge["id"] == "cca_nov_peak"
    )
    charge[fact_name]["source_page"] = payload["page_count"] + 1

    with pytest.raises(ValidationError, match="source_page.*page_count"):
        BillExtraction.model_validate(payload)


def test_document_rejects_duplicate_charge_ids() -> None:
    bill = translate_legacy_bill(load_sample("authentic"))
    duplicate = bill.sections[0].charges[0].model_copy(
        update={"id": bill.sections[1].charges[0].id}
    )
    changed = bill.sections[0].model_copy(
        update={"charges": (duplicate,) + bill.sections[0].charges[1:]}
    )
    with pytest.raises(ValidationError, match="charge IDs must be unique"):
        UtilityDocument.model_validate(
            bill.model_copy(update={"sections": (changed, bill.sections[1])}).model_dump()
        )


def test_document_rejects_duplicate_section_ids() -> None:
    bill = translate_legacy_bill(load_sample("authentic"))
    duplicate = bill.sections[1].model_copy(update={"id": bill.sections[0].id})

    with pytest.raises(ValidationError, match="section IDs must be unique"):
        UtilityDocument.model_validate(
            bill.model_copy(update={"sections": (bill.sections[0], duplicate)}).model_dump()
        )


def test_service_section_rejects_duplicate_conversion_ids() -> None:
    payload = load_utility_sample("centerpoint").model_dump()
    conversion = payload["sections"][0]["conversions"][0]
    payload["sections"][0]["conversions"] += (conversion.copy(),)

    with pytest.raises(ValidationError, match="conversion IDs must be unique"):
        UtilityDocument.model_validate(payload)


def test_service_section_rejects_duplicate_supplemental_fact_ids() -> None:
    payload = translate_legacy_bill(load_sample("authentic")).model_dump()
    fact = payload["sections"][0]["supplemental_facts"][0]
    payload["sections"][0]["supplemental_facts"] += (fact.copy(),)

    with pytest.raises(ValidationError, match="supplemental fact IDs must be unique"):
        UtilityDocument.model_validate(payload)


def test_service_section_rejects_duplicate_quantity_sum_ids() -> None:
    payload = load_utility_sample("duke").model_dump()
    quantity_sum = payload["sections"][0]["quantity_sums"][0]
    payload["sections"][0]["quantity_sums"] += (quantity_sum.copy(),)

    with pytest.raises(ValidationError, match="quantity-sum IDs must be unique"):
        UtilityDocument.model_validate(payload)


def test_quantity_sum_rejects_duplicate_component_charge_ids() -> None:
    with pytest.raises(ValidationError, match="charge_ids must be unique"):
        QuantitySumCheck(
            id="tiers",
            label="Printed tier quantities",
            charge_ids=("tier_one", "tier_one"),
            target=DecimalFactV2(
                value=Decimal("1001"),
                unit="kWh",
                status="printed",
                evidence=evidence(),
            ),
        )


def test_service_section_rejects_unknown_quantity_sum_charge_reference() -> None:
    payload = load_utility_sample("duke").model_dump()
    payload["sections"][0]["quantity_sums"][0]["charge_ids"] = [
        "energy_tier_1",
        "missing_tier",
    ]

    with pytest.raises(ValidationError, match="unknown charge ID"):
        UtilityDocument.model_validate(payload)


def test_percent_calculation_requires_charge_ids() -> None:
    with pytest.raises(ValidationError, match="charge_ids"):
        CalculationSpec(kind="percent_of_charges")


def test_quantity_times_rate_rejects_charge_ids() -> None:
    with pytest.raises(ValidationError, match="charge_ids"):
        CalculationSpec(kind="quantity_times_rate", charge_ids=("other_charge",))


def test_quantity_times_rate_requires_quantity() -> None:
    amount = MoneyFactV2(
        value=Decimal("10.00"), currency="USD", status="printed", evidence=evidence()
    )
    rate = DecimalFactV2(
        value=Decimal("5.00"), unit="USD/kgal", status="printed", evidence=evidence()
    )

    with pytest.raises(ValidationError, match="requires both quantity and rate"):
        UtilityCharge(
            id="water_usage",
            label="Water usage",
            rate=rate,
            amount=amount,
            calculation=CalculationSpec(kind="quantity_times_rate"),
        )


def test_quantity_times_rate_requires_rate() -> None:
    amount = MoneyFactV2(
        value=Decimal("10.00"), currency="USD", status="printed", evidence=evidence()
    )
    quantity = DecimalFactV2(
        value=Decimal("2"), unit="kgal", status="printed", evidence=evidence()
    )

    with pytest.raises(ValidationError, match="requires both quantity and rate"):
        UtilityCharge(
            id="water_usage",
            label="Water usage",
            quantity=quantity,
            amount=amount,
            calculation=CalculationSpec(kind="quantity_times_rate"),
        )


def test_quantity_times_rate_accepts_both_operands() -> None:
    amount = MoneyFactV2(
        value=Decimal("10.00"), currency="USD", status="printed", evidence=evidence()
    )
    quantity = DecimalFactV2(
        value=Decimal("2"), unit="kgal", status="printed", evidence=evidence()
    )
    rate = DecimalFactV2(
        value=Decimal("5.00"), unit="USD/kgal", status="printed", evidence=evidence()
    )

    charge = UtilityCharge(
        id="water_usage",
        label="Water usage",
        quantity=quantity,
        rate=rate,
        amount=amount,
        calculation=CalculationSpec(kind="quantity_times_rate"),
    )

    assert charge.quantity == quantity
    assert charge.rate == rate


def document_with_percent_references(charge_ids: tuple[str, ...]) -> dict[str, Any]:
    payload = translate_legacy_bill(load_sample("authentic")).model_dump()
    for section in payload["sections"]:
        for charge in section["charges"]:
            if charge["id"] == "cca_nov_uut":
                charge["calculation"]["charge_ids"] = charge_ids
                return payload
    raise AssertionError("cca_nov_uut fixture charge not found")


def test_document_rejects_unknown_percent_charge_reference() -> None:
    with pytest.raises(ValidationError, match="unknown charge ID"):
        UtilityDocument.model_validate(
            document_with_percent_references(("missing_charge",))
        )


def test_document_rejects_duplicate_percent_charge_references() -> None:
    with pytest.raises(ValidationError, match="charge_ids must be unique"):
        UtilityDocument.model_validate(
            document_with_percent_references(("cca_nov_peak", "cca_nov_peak"))
        )


def test_document_rejects_self_referencing_percent_charge() -> None:
    with pytest.raises(ValidationError, match="cannot reference its own charge ID"):
        UtilityDocument.model_validate(
            document_with_percent_references(("cca_nov_uut",))
        )


def test_document_rejects_evidence_after_last_page() -> None:
    bill = translate_legacy_bill(load_sample("authentic"))
    payload = bill.model_dump()
    payload["sections"][0]["provider"]["evidence"]["page"] = bill.page_count + 1
    with pytest.raises(ValidationError, match="page_count"):
        UtilityDocument.model_validate(payload)


def test_service_section_rejects_decreasing_dates() -> None:
    amount = MoneyFactV2(
        value=Decimal("10.00"), currency="USD", status="printed", evidence=evidence()
    )
    with pytest.raises(ValidationError, match="service_start"):
        ServiceSection(
            id="water",
            service_type="water",
            provider=TextFactV2(
                value="Example Utility", status="printed", evidence=evidence()
            ),
            service_start=DateFactV2(
                value=date(2026, 2, 1), status="printed", evidence=evidence()
            ),
            service_end=DateFactV2(
                value=date(2026, 1, 31), status="printed", evidence=evidence()
            ),
            charges=(UtilityCharge(id="water_service", label="Water service", amount=amount),),
            subtotal=amount,
        )


def test_document_rejects_inconsistent_money_currency() -> None:
    document = translate_legacy_bill(load_sample("authentic"))
    payload = document.model_dump()
    payload["sections"][0]["charges"][0]["amount"]["currency"] = "EUR"

    with pytest.raises(ValidationError, match="currency"):
        UtilityDocument.model_validate(payload)
