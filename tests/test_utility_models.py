from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from wattproof.fixtures import load_sample
from wattproof.legacy import translate_legacy_bill
from wattproof.utility_models import (
    CalculationSpec,
    DateFactV2,
    EvidenceRef,
    MoneyFactV2,
    ServiceSection,
    TextFactV2,
    UtilityCharge,
    UtilityDocument,
)


def evidence() -> EvidenceRef:
    return EvidenceRef(page=1, text="visible statement text", confidence=Decimal("1"))


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


def test_legacy_translation_preserves_user_correction_provenance_if_present() -> None:
    legacy = load_sample("authentic")
    corrected_provider = legacy.delivery_provider.model_copy(
        update={
            "value": "PG&E",
            "status": "user_corrected",
            "original_value": legacy.delivery_provider.value,
        }
    )
    corrected_bill = legacy.model_copy(update={"delivery_provider": corrected_provider})

    translated = translate_legacy_bill(corrected_bill)

    assert translated.sections[0].provider.status == "user_corrected"
    assert translated.sections[0].provider.value == "PG&E"
    assert translated.sections[0].provider.original_value == legacy.delivery_provider.value


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


def test_percent_calculation_requires_charge_ids() -> None:
    with pytest.raises(ValidationError, match="charge_ids"):
        CalculationSpec(kind="percent_of_charges")


def test_quantity_times_rate_rejects_charge_ids() -> None:
    with pytest.raises(ValidationError, match="charge_ids"):
        CalculationSpec(kind="quantity_times_rate", charge_ids=("other_charge",))


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
