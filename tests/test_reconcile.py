from collections.abc import Iterator, Mapping
from decimal import Decimal

import pytest
from pydantic import BaseModel

from wattproof.reconcile import compatible_rate, reconcile_document, round_money
from wattproof.utility_models import (
    CalculationSpec,
    ConversionCheck,
    DecimalFactV2,
    EvidenceRef,
    FactStatus,
    MeterCheck,
    MoneyFactV2,
    ServiceSection,
    TextFactV2,
    UtilityCharge,
    UtilityDocument,
)


def evidence(text: str) -> EvidenceRef:
    return EvidenceRef(
        page=1,
        text=text,
        confidence=Decimal("1"),
    )


def decimal_fact(
    value: str,
    unit: str,
    label: str,
    *,
    status: FactStatus = "printed",
    original_value: str | None = None,
) -> DecimalFactV2:
    return DecimalFactV2(
        value=Decimal(value),
        unit=unit,
        status=status,
        evidence=evidence(label),
        original_value=original_value,
    )


def money_fact(
    value: str,
    label: str,
    currency: str = "USD",
    *,
    status: FactStatus = "printed",
    original_value: str | None = None,
) -> MoneyFactV2:
    return MoneyFactV2(
        value=Decimal(value),
        currency=currency,
        status=status,
        evidence=evidence(label),
        original_value=original_value,
    )


def text_fact(value: str, label: str) -> TextFactV2:
    return TextFactV2(value=value, status="printed", evidence=evidence(label))


def nested_values(value: object) -> Iterator[object]:
    yield value
    if isinstance(value, BaseModel):
        for field_name in type(value).model_fields:
            yield from nested_values(getattr(value, field_name))
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from nested_values(item)
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from nested_values(item)


def water_document(
    *,
    water_usage_amount: str = "7.46",
    tax_amount: str = "1.28",
    rate_unit: str = "USD/kgal",
    subtotal: str = "19.53",
    current_charges: str = "19.53",
    outstanding_balance: str | None = None,
    amount_due: str = "19.53",
    provider: str = "City Water",
) -> UtilityDocument:
    usage = UtilityCharge(
        id="water_usage",
        label="Water usage",
        quantity=decimal_fact("2", "kgal", "Usage: 2 kgal"),
        rate=decimal_fact("3.73", rate_unit, f"Rate: 3.73 {rate_unit}"),
        amount=money_fact(water_usage_amount, f"Water usage ${water_usage_amount}"),
        calculation=CalculationSpec(kind="quantity_times_rate"),
    )
    service = UtilityCharge(
        id="service_charge",
        label="Service charge",
        amount=money_fact("7.86", "Service charge $7.86"),
    )
    fire = UtilityCharge(
        id="fire_charge",
        label="Fire protection",
        amount=money_fact("2.93", "Fire protection $2.93"),
    )
    tax = UtilityCharge(
        id="sales_tax",
        label="Sales tax",
        rate=decimal_fact("0.07", "fraction", "Sales tax rate: 0.07"),
        amount=money_fact(tax_amount, f"Sales tax ${tax_amount}"),
        calculation=CalculationSpec(
            kind="percent_of_charges",
            charge_ids=("water_usage", "service_charge", "fire_charge"),
        ),
    )
    section = ServiceSection(
        id="water",
        service_type="water",
        provider=text_fact(provider, f"Provider: {provider}"),
        charges=(usage, service, fire, tax),
        subtotal=money_fact(subtotal, f"Water subtotal ${subtotal}"),
    )
    return UtilityDocument(
        schema_version="2.0",
        fixture_kind="uploaded",
        document_sha256="a" * 64,
        page_count=1,
        currency="USD",
        sections=(section,),
        current_charges=money_fact(
            current_charges, f"Current charges ${current_charges}"
        ),
        outstanding_balance=(
            money_fact(outstanding_balance, f"Outstanding balance ${outstanding_balance}")
            if outstanding_balance is not None
            else None
        ),
        amount_due=money_fact(amount_due, f"Amount due ${amount_due}"),
    )


def gas_document() -> UtilityDocument:
    meter = MeterCheck(
        previous=decimal_fact("137848", "CCF", "Previous meter: 137848 CCF"),
        current=decimal_fact("137956", "CCF", "Current meter: 137956 CCF"),
        usage=decimal_fact("108", "CCF", "Printed usage: 108 CCF"),
    )
    conversion = ConversionCheck(
        id="ccf_to_therms",
        label="CCF to therms",
        source=decimal_fact("108", "CCF", "Conversion source: 108 CCF"),
        factor=decimal_fact(
            "1.03960", "therm/CCF", "Conversion factor: 1.03960 therm/CCF"
        ),
        result=decimal_fact("112.277", "therm", "Converted usage: 112.277 therm"),
    )
    amount = money_fact("10.00", "Gas service $10.00")
    section = ServiceSection(
        id="gas",
        service_type="natural_gas",
        provider=text_fact("Example Gas", "Provider: Example Gas"),
        meter=meter,
        conversions=(conversion,),
        charges=(UtilityCharge(id="gas_service", label="Gas service", amount=amount),),
        subtotal=money_fact("10.00", "Gas subtotal $10.00"),
    )
    return UtilityDocument(
        schema_version="2.0",
        fixture_kind="uploaded",
        document_sha256="b" * 64,
        page_count=1,
        currency="USD",
        sections=(section,),
        current_charges=money_fact("10.00", "Current charges $10.00"),
        amount_due=money_fact("10.00", "Amount due $10.00"),
    )


def water_document_with_usage_status(
    status: FactStatus,
    *,
    original_value: str | None = None,
) -> UtilityDocument:
    document = water_document(water_usage_amount="8.46", tax_amount="1.35")
    section = document.sections[0]
    usage = section.charges[0].model_copy(
        update={
            "amount": money_fact(
                "8.46",
                "Water usage $8.46",
                status=status,
                original_value=original_value,
            )
        }
    )
    changed_section = section.model_copy(
        update={"charges": (usage, *section.charges[1:])}
    )
    return document.model_copy(update={"sections": (changed_section,)})


def water_document_with_usage_operands(
    *,
    quantity: DecimalFactV2 | None = None,
    rate: DecimalFactV2 | None = None,
) -> UtilityDocument:
    document = water_document()
    section = document.sections[0]
    usage = section.charges[0]
    updates: dict[str, DecimalFactV2] = {}
    if quantity is not None:
        updates["quantity"] = quantity
    if rate is not None:
        updates["rate"] = rate
    changed_usage = usage.model_copy(update=updates)
    changed_section = section.model_copy(
        update={"charges": (changed_usage, *section.charges[1:])}
    )
    return document.model_copy(update={"sections": (changed_section,)})


def water_document_with_service_base_status(
    status: FactStatus,
    *,
    original_value: str | None = None,
) -> UtilityDocument:
    document = water_document(
        subtotal="20.53",
        current_charges="20.53",
        amount_due="20.53",
    )
    section = document.sections[0]
    service = section.charges[1].model_copy(
        update={
            "amount": money_fact(
                "8.86",
                "Service charge $8.86",
                status=status,
                original_value=original_value,
            )
        }
    )
    changed_section = section.model_copy(
        update={
            "charges": (
                section.charges[0],
                service,
                *section.charges[2:],
            )
        }
    )
    return document.model_copy(update={"sections": (changed_section,)})


def simple_section(
    *,
    section_id: str,
    charge_id: str,
    provider: str,
    normalized_provider: str | None,
    charge_amount: str,
    subtotal: str,
) -> ServiceSection:
    return ServiceSection(
        id=section_id,
        service_type="other",
        provider=text_fact(provider, f"Provider: {provider}"),
        normalized_provider=normalized_provider,
        charges=(
            UtilityCharge(
                id=charge_id,
                label=f"{section_id} service",
                amount=money_fact(
                    charge_amount,
                    f"{section_id} service ${charge_amount}",
                ),
            ),
        ),
        subtotal=money_fact(subtotal, f"{section_id} subtotal ${subtotal}"),
    )


def document_with_sections(
    sections: tuple[ServiceSection, ...],
    *,
    current_charges: str,
    amount_due: str | None = None,
) -> UtilityDocument:
    due = amount_due if amount_due is not None else current_charges
    return UtilityDocument(
        schema_version="2.0",
        fixture_kind="uploaded",
        document_sha256="c" * 64,
        page_count=1,
        currency="USD",
        sections=sections,
        current_charges=money_fact(
            current_charges,
            f"Current charges ${current_charges}",
        ),
        amount_due=money_fact(due, f"Amount due ${due}"),
    )


def test_round_money_uses_decimal_half_up() -> None:
    assert round_money(Decimal("1.005")) == Decimal("1.01")


def test_compatible_rate_requires_an_exact_currency_per_quantity_unit() -> None:
    assert compatible_rate("kgal", "USD/kgal", "USD") is True
    assert compatible_rate("kgal", "USD/kWh", "USD") is False


def test_water_statement_reconciles_printed_product_percentage_and_rollups() -> None:
    result = reconcile_document(water_document())
    lines = {line.id: line for line in result.lines}

    assert lines["charge::water_usage"].expected_amount == Decimal("7.46")
    assert lines["charge::water_usage"].status == "verified"
    assert lines["charge::sales_tax"].expected_amount == Decimal("1.28")
    assert lines["charge::sales_tax"].status == "verified"
    assert lines["charge::service_charge"].status == "cannot_verify"
    assert lines["charge::service_charge"].expected_amount is None
    assert lines["subtotal::water"].expected_amount == Decimal("19.53")
    assert lines["statement::current_charges"].expected_amount == Decimal("19.53")
    assert lines["statement::amount_due"].expected_amount == Decimal("19.53")
    assert result.verification_level == "internally_reconciled"
    assert result.verdict == "reconciled"
    assert "reconcile" in result.headline.lower()


def test_fixed_printed_charges_do_not_force_user_review() -> None:
    result = reconcile_document(water_document())

    assert result.verdict == "reconciled"
    assert result.review_requests[0].grounded_audit_line_ids == ()
    assert (
        "published rates remain independently unverified"
        in result.review_requests[0].body
    )


def test_gas_meter_and_conversion_use_printed_precision() -> None:
    result = reconcile_document(gas_document())
    lines = {line.id: line for line in result.lines}

    meter = lines["meter::gas"]
    assert meter.expected_amount == Decimal("108")
    assert meter.delta == Decimal("0")
    assert meter.unit == "CCF"
    assert meter.status == "verified"

    conversion = lines["conversion::gas::ccf_to_therms"]
    assert conversion.expected_amount == Decimal("112.277")
    assert conversion.delta == Decimal("0.000")
    assert conversion.unit == "therm"
    assert conversion.status == "verified"
    assert "1.03960" in conversion.formula


def test_charge_discrepancy_is_root_for_subtotal_and_provider_request() -> None:
    document = water_document(water_usage_amount="8.46", tax_amount="1.35")

    result = reconcile_document(document)
    lines = {line.id: line for line in result.lines}

    charge = lines["charge::water_usage"]
    assert charge.delta == Decimal("1.00")
    assert charge.status == "discrepancy"
    assert charge.root_cause_id is None
    assert lines["charge::sales_tax"].status == "verified"
    assert lines["subtotal::water"].root_cause_id == "charge::water_usage"
    assert result.discrepancy_total == Decimal("1.00")
    assert result.verdict == "possible_discrepancy"
    assert result.review_requests[0].grounded_audit_line_ids == (
        "charge::water_usage",
    )
    assert "$1.00" in result.review_requests[0].body


def test_two_direct_charge_roots_keep_subtotal_as_a_separate_root() -> None:
    result = reconcile_document(water_document(water_usage_amount="8.46"))
    lines = {line.id: line for line in result.lines}

    assert lines["charge::water_usage"].root_cause_id is None
    assert lines["charge::sales_tax"].root_cause_id is None
    assert lines["subtotal::water"].root_cause_id is None
    assert result.discrepancy_total == Decimal("2.07")
    assert result.review_requests[0].grounded_audit_line_ids == (
        "charge::water_usage",
        "charge::sales_tax",
        "subtotal::water",
    )


def test_charge_root_does_not_hide_an_independent_subtotal_error() -> None:
    document = water_document(
        water_usage_amount="8.46",
        tax_amount="1.35",
        subtotal="19.00",
        current_charges="19.00",
        amount_due="19.00",
    )

    result = reconcile_document(document)
    lines = {line.id: line for line in result.lines}

    assert lines["charge::water_usage"].root_cause_id is None
    assert lines["subtotal::water"].root_cause_id is None
    assert result.discrepancy_total == Decimal("2.60")
    assert result.review_requests[0].grounded_audit_line_ids == (
        "charge::water_usage",
        "subtotal::water",
    )


def test_quantity_rate_with_incompatible_units_needs_review_without_guessing() -> None:
    result = reconcile_document(water_document(rate_unit="USD/kWh"))
    line = next(line for line in result.lines if line.id == "charge::water_usage")

    assert line.status == "needs_review"
    assert line.expected_amount is None
    assert line.delta is None
    assert result.verdict == "needs_review"
    assert result.discrepancy_total == Decimal("0.00")


def test_meter_with_incompatible_units_needs_review_without_expected_value() -> None:
    document = gas_document()
    section = document.sections[0]
    assert section.meter is not None
    changed_meter = section.meter.model_copy(
        update={
            "usage": decimal_fact("108", "therm", "Printed usage: 108 therm")
        }
    )
    changed_section = section.model_copy(update={"meter": changed_meter})
    changed_document = document.model_copy(update={"sections": (changed_section,)})

    result = reconcile_document(changed_document)
    line = next(line for line in result.lines if line.id == "meter::gas")

    assert line.status == "needs_review"
    assert line.expected_amount is None
    assert line.delta is None


def test_conversion_with_incompatible_units_needs_review_without_guessing() -> None:
    document = gas_document()
    section = document.sections[0]
    conversion = section.conversions[0]
    changed_conversion = conversion.model_copy(
        update={
            "factor": decimal_fact(
                "1.03960", "CCF/therm", "Invalid conversion factor"
            )
        }
    )
    changed_section = section.model_copy(
        update={"conversions": (changed_conversion,)}
    )
    changed_document = document.model_copy(update={"sections": (changed_section,)})

    result = reconcile_document(changed_document)
    line = next(
        line
        for line in result.lines
        if line.id == "conversion::gas::ccf_to_therms"
    )

    assert line.status == "needs_review"
    assert line.expected_amount is None
    assert line.delta is None


def test_percentage_with_non_fraction_rate_needs_review() -> None:
    document = water_document()
    section = document.sections[0]
    tax = section.charges[-1].model_copy(
        update={
            "rate": decimal_fact("0.07", "percent", "Invalid percent rate")
        }
    )
    changed_section = section.model_copy(
        update={"charges": (*section.charges[:-1], tax)}
    )
    changed_document = document.model_copy(update={"sections": (changed_section,)})

    result = reconcile_document(changed_document)
    line = next(line for line in result.lines if line.id == "charge::sales_tax")

    assert line.status == "needs_review"
    assert line.expected_amount is None
    assert line.delta is None


def test_percentage_with_unavailable_printed_base_cannot_be_verified() -> None:
    document = water_document()
    section = document.sections[0]
    tax = section.charges[-1]
    assert tax.calculation is not None
    changed_calculation = tax.calculation.model_copy(
        update={"charge_ids": ("missing_charge",)}
    )
    changed_tax = tax.model_copy(update={"calculation": changed_calculation})
    changed_section = section.model_copy(
        update={"charges": (*section.charges[:-1], changed_tax)}
    )
    changed_document = document.model_copy(update={"sections": (changed_section,)})

    result = reconcile_document(changed_document)
    line = next(line for line in result.lines if line.id == "charge::sales_tax")

    assert line.status == "cannot_verify"
    assert line.expected_amount is None
    assert line.delta is None


def test_percentage_without_any_declared_base_cannot_be_verified() -> None:
    document = water_document()
    section = document.sections[0]
    tax = section.charges[-1]
    assert tax.calculation is not None
    changed_calculation = tax.calculation.model_copy(update={"charge_ids": ()})
    changed_tax = tax.model_copy(update={"calculation": changed_calculation})
    changed_section = section.model_copy(
        update={"charges": (*section.charges[:-1], changed_tax)}
    )
    changed_document = document.model_copy(update={"sections": (changed_section,)})

    result = reconcile_document(changed_document)
    line = next(line for line in result.lines if line.id == "charge::sales_tax")

    assert line.status == "cannot_verify"
    assert line.expected_amount is None
    assert line.delta is None


@pytest.mark.parametrize(
    "charge_ids",
    [
        ("water_usage", "water_usage"),
        ("sales_tax",),
    ],
)
def test_percentage_with_invalid_declared_base_needs_review(
    charge_ids: tuple[str, ...],
) -> None:
    document = water_document()
    section = document.sections[0]
    tax = section.charges[-1]
    assert tax.calculation is not None
    changed_calculation = tax.calculation.model_copy(
        update={"charge_ids": charge_ids}
    )
    changed_tax = tax.model_copy(update={"calculation": changed_calculation})
    changed_section = section.model_copy(
        update={"charges": (*section.charges[:-1], changed_tax)}
    )
    changed_document = document.model_copy(update={"sections": (changed_section,)})

    result = reconcile_document(changed_document)
    line = next(line for line in result.lines if line.id == "charge::sales_tax")

    assert line.status == "needs_review"
    assert line.expected_amount is None
    assert line.delta is None


def test_amount_due_adds_printed_outstanding_balance() -> None:
    document = water_document(
        outstanding_balance="4.20",
        amount_due="23.73",
    )

    result = reconcile_document(document)
    line = next(
        line for line in result.lines if line.id == "statement::amount_due"
    )

    assert line.expected_amount == Decimal("23.73")
    assert line.delta == Decimal("0.00")
    assert line.status == "verified"
    assert line.inputs["outstanding_balance"] == "4.20 USD"
    assert document.outstanding_balance is not None
    assert document.outstanding_balance.evidence in line.evidence


def test_derived_only_subtotal_discrepancy_is_a_counted_root() -> None:
    document = water_document(
        subtotal="19.50",
        current_charges="19.50",
        amount_due="19.50",
    )

    result = reconcile_document(document)
    line = next(line for line in result.lines if line.id == "subtotal::water")

    assert line.status == "discrepancy"
    assert line.delta == Decimal("-0.03")
    assert line.root_cause_id is None
    assert result.discrepancy_total == Decimal("0.03")


def test_current_symptom_points_to_the_proven_single_upstream_root() -> None:
    document = water_document(
        subtotal="20.53",
        current_charges="19.53",
        amount_due="19.53",
    )

    result = reconcile_document(document)
    lines = {line.id: line for line in result.lines}

    assert lines["subtotal::water"].root_cause_id is None
    assert (
        lines["statement::current_charges"].root_cause_id
        == "subtotal::water"
    )
    assert result.discrepancy_total == Decimal("1.00")


def test_direct_charge_root_does_not_hide_an_independent_current_error() -> None:
    document = water_document(
        water_usage_amount="8.46",
        tax_amount="1.35",
        current_charges="20.53",
        amount_due="20.53",
    )

    result = reconcile_document(document)
    lines = {line.id: line for line in result.lines}

    assert lines["subtotal::water"].root_cause_id == "charge::water_usage"
    assert lines["statement::current_charges"].root_cause_id is None
    assert result.discrepancy_total == Decimal("2.00")
    assert result.review_requests[0].grounded_audit_line_ids == (
        "charge::water_usage",
        "statement::current_charges",
    )


def test_amount_due_error_not_explained_by_current_stays_a_root() -> None:
    document = water_document(
        subtotal="20.53",
        current_charges="19.53",
        amount_due="20.53",
    )

    result = reconcile_document(document)
    lines = {line.id: line for line in result.lines}

    assert lines["statement::current_charges"].root_cause_id == "subtotal::water"
    assert lines["statement::amount_due"].root_cause_id is None
    assert result.discrepancy_total == Decimal("2.00")
    assert result.review_requests[0].grounded_audit_line_ids == (
        "subtotal::water",
        "statement::amount_due",
    )


def test_amount_due_symptom_points_to_proven_current_root() -> None:
    document = water_document(current_charges="20.53", amount_due="19.53")

    result = reconcile_document(document)
    lines = {line.id: line for line in result.lines}

    assert lines["statement::current_charges"].root_cause_id is None
    assert (
        lines["statement::amount_due"].root_cause_id
        == "statement::current_charges"
    )
    assert result.discrepancy_total == Decimal("1.00")


def test_single_provider_request_can_ground_a_statement_level_root() -> None:
    result = reconcile_document(water_document(amount_due="20.53"))
    lines = {line.id: line for line in result.lines}

    assert lines["statement::amount_due"].root_cause_id is None
    assert result.discrepancy_total == Decimal("1.00")
    assert result.review_requests[0].grounded_audit_line_ids == (
        "statement::amount_due",
    )
    assert "$1.00" in result.review_requests[0].body


def test_multiple_providers_receive_separate_requests_in_statement_order() -> None:
    water = water_document()
    gas = gas_document()
    combined = water.model_copy(
        update={
            "sections": (water.sections[0], gas.sections[0]),
            "current_charges": money_fact("29.53", "Current charges $29.53"),
            "amount_due": money_fact("29.53", "Amount due $29.53"),
        }
    )

    result = reconcile_document(combined)

    assert [request.provider for request in result.review_requests] == [
        "City Water",
        "Example Gas",
    ]
    assert all(
        request.requires_user_review for request in result.review_requests
    )


def test_two_section_roots_do_not_hide_current_charges_root() -> None:
    water = water_document()
    gas = gas_document()
    water_section = water.sections[0].model_copy(
        update={"subtotal": money_fact("20.53", "Water subtotal $20.53")}
    )
    gas_section = gas.sections[0].model_copy(
        update={"subtotal": money_fact("11.00", "Gas subtotal $11.00")}
    )
    combined = water.model_copy(
        update={
            "sections": (water_section, gas_section),
            "current_charges": money_fact("29.53", "Current charges $29.53"),
            "amount_due": money_fact("29.53", "Amount due $29.53"),
        }
    )

    result = reconcile_document(combined)
    lines = {line.id: line for line in result.lines}

    assert lines["subtotal::water"].root_cause_id is None
    assert lines["subtotal::gas"].root_cause_id is None
    assert lines["statement::current_charges"].root_cause_id is None
    assert result.discrepancy_total == Decimal("4.00")
    assert result.review_requests[0].grounded_audit_line_ids == (
        "subtotal::water",
    )
    assert result.review_requests[1].grounded_audit_line_ids == (
        "subtotal::gas",
    )


def test_multi_provider_current_root_gets_neutral_consolidated_request() -> None:
    water = water_document()
    gas = gas_document()
    combined = water.model_copy(
        update={
            "sections": (water.sections[0], gas.sections[0]),
            "current_charges": money_fact("30.53", "Current charges $30.53"),
            "amount_due": money_fact("30.53", "Amount due $30.53"),
        }
    )

    result = reconcile_document(combined)
    lines = {line.id: line for line in result.lines}

    assert result.verdict == "possible_discrepancy"
    assert lines["statement::current_charges"].root_cause_id is None
    assert result.discrepancy_total == Decimal("1.00")
    assert [request.provider for request in result.review_requests] == [
        "City Water",
        "Example Gas",
        "Consolidated statement",
    ]
    for request in result.review_requests[:2]:
        assert request.grounded_audit_line_ids == ()
        assert "section math reconciled" in request.body
        assert "separate consolidated statement issue" in request.body
    neutral = result.review_requests[-1]
    assert neutral.grounded_audit_line_ids == ("statement::current_charges",)
    assert "not attributed to a particular provider" in neutral.body
    assert "$1.00" in neutral.body


def test_normalized_provider_groups_printed_aliases_into_one_draft() -> None:
    first = simple_section(
        section_id="water_alias",
        charge_id="water_alias_service",
        provider="Metro Water",
        normalized_provider="Metro Utility, Inc.",
        charge_amount="10.00",
        subtotal="11.00",
    )
    second = simple_section(
        section_id="sewer_alias",
        charge_id="sewer_alias_service",
        provider="Metro Sewer Department",
        normalized_provider="Metro Utility, Inc.",
        charge_amount="5.00",
        subtotal="6.00",
    )
    document = document_with_sections(
        (first, second),
        current_charges="17.00",
    )

    result = reconcile_document(document)

    assert [request.provider for request in result.review_requests] == [
        "Metro Utility, Inc.",
    ]
    assert result.review_requests[0].grounded_audit_line_ids == (
        "subtotal::water_alias",
        "subtotal::sewer_alias",
    )


def test_normalized_provider_keeps_colliding_printed_labels_separate() -> None:
    first = simple_section(
        section_id="alpha",
        charge_id="alpha_service",
        provider="Community Utility",
        normalized_provider="Alpha Water LLC",
        charge_amount="10.00",
        subtotal="10.00",
    )
    second = simple_section(
        section_id="beta",
        charge_id="beta_service",
        provider="Community Utility",
        normalized_provider="Beta Gas LLC",
        charge_amount="5.00",
        subtotal="5.00",
    )
    document = document_with_sections(
        (first, second),
        current_charges="16.00",
    )

    result = reconcile_document(document)

    assert [request.provider for request in result.review_requests] == [
        "Alpha Water LLC",
        "Beta Gas LLC",
        "Consolidated statement",
    ]
    assert result.review_requests[0].grounded_audit_line_ids == ()
    assert result.review_requests[1].grounded_audit_line_ids == ()
    assert result.review_requests[2].grounded_audit_line_ids == (
        "statement::current_charges",
    )


def test_user_corrected_billed_value_preserves_provenance_in_line_and_draft() -> None:
    result = reconcile_document(
        water_document_with_usage_status(
            "user_corrected",
            original_value="7.46",
        )
    )
    lines = {line.id: line for line in result.lines}
    charge = lines["charge::water_usage"]
    subtotal = lines["subtotal::water"]

    serialized = charge.model_dump(mode="json")
    assert serialized["billed_status"] == "user_corrected"
    assert serialized["billed_original_value"] == "7.46"
    assert "user-corrected" in subtotal.formula
    assert "original extracted value: 7.46" in subtotal.formula
    assert "user-corrected" in subtotal.inputs["charge::water_usage"]
    body = result.review_requests[0].body
    assert "user-corrected $8.46" in body
    assert "original extracted value: 7.46" in body
    assert "printed $8.46" not in body


def test_inferred_billed_value_is_not_described_as_printed() -> None:
    result = reconcile_document(water_document_with_usage_status("inferred"))
    lines = {line.id: line for line in result.lines}
    charge = lines["charge::water_usage"]
    subtotal = lines["subtotal::water"]

    serialized = charge.model_dump(mode="json")
    assert serialized["billed_status"] == "inferred"
    assert serialized["billed_original_value"] is None
    assert "inferred extraction" in subtotal.formula
    assert "inferred extraction" in subtotal.inputs["charge::water_usage"]
    body = result.review_requests[0].body
    assert "inferred extraction $8.46" in body
    assert "printed $8.46" not in body


def test_request_discloses_user_corrected_quantity_operand() -> None:
    quantity = decimal_fact(
        "3",
        "kgal",
        "Corrected usage: 3 kgal",
        status="user_corrected",
        original_value="2",
    )
    result = reconcile_document(
        water_document_with_usage_operands(quantity=quantity)
    )
    line = next(line for line in result.lines if line.id == "charge::water_usage")

    expected_trace = (
        "3 kgal [user-corrected; original extracted value: 2]"
    )
    assert expected_trace in line.formula
    assert line.inputs["quantity"] == expected_trace
    request = result.review_requests[0]
    assert request.grounded_audit_line_ids == ("charge::water_usage",)
    assert f"Recomputed from quantity={expected_trace}" in request.body


def test_request_discloses_user_corrected_rate_operand() -> None:
    rate = decimal_fact(
        "4.00",
        "USD/kgal",
        "Corrected rate: 4.00 USD/kgal",
        status="user_corrected",
        original_value="3.73",
    )
    result = reconcile_document(water_document_with_usage_operands(rate=rate))
    line = next(line for line in result.lines if line.id == "charge::water_usage")

    expected_trace = (
        "4.00 USD/kgal [user-corrected; original extracted value: 3.73]"
    )
    assert expected_trace in line.formula
    assert line.inputs["rate"] == expected_trace
    request = result.review_requests[0]
    assert request.grounded_audit_line_ids == ("charge::water_usage",)
    assert f"rate={expected_trace}" in request.body


def test_request_discloses_inferred_rate_operand() -> None:
    rate = decimal_fact(
        "4.00",
        "USD/kgal",
        "Inferred rate: 4.00 USD/kgal",
        status="inferred",
    )
    result = reconcile_document(water_document_with_usage_operands(rate=rate))
    line = next(line for line in result.lines if line.id == "charge::water_usage")

    expected_trace = "4.00 USD/kgal [inferred extraction]"
    assert expected_trace in line.formula
    assert line.inputs["rate"] == expected_trace
    request = result.review_requests[0]
    assert request.grounded_audit_line_ids == ("charge::water_usage",)
    assert f"rate={expected_trace}" in request.body
    assert "rate=4.00 USD/kgal [printed]" not in request.body


@pytest.mark.parametrize(
    ("status", "original_value", "expected_trace"),
    [
        (
            "user_corrected",
            "7.86",
            "8.86 USD [user-corrected; original extracted value: 7.86]",
        ),
        ("inferred", None, "8.86 USD [inferred extraction]"),
    ],
)
def test_percent_request_discloses_referenced_base_provenance(
    status: FactStatus,
    original_value: str | None,
    expected_trace: str,
) -> None:
    result = reconcile_document(
        water_document_with_service_base_status(
            status,
            original_value=original_value,
        )
    )
    line = next(line for line in result.lines if line.id == "charge::sales_tax")

    assert expected_trace in line.formula
    assert line.inputs["charge::service_charge"] == expected_trace
    request = result.review_requests[0]
    assert request.grounded_audit_line_ids == ("charge::sales_tax",)
    assert f"charge::service_charge={expected_trace}" in request.body


def test_evidence_is_limited_to_exact_printed_operands() -> None:
    document = water_document()

    result = reconcile_document(document)
    lines = {line.id: line for line in result.lines}
    usage = document.sections[0].charges[0]
    tax = document.sections[0].charges[-1]
    assert usage.quantity is not None
    assert usage.rate is not None
    assert tax.rate is not None

    assert lines["charge::water_usage"].evidence == (
        usage.quantity.evidence,
        usage.rate.evidence,
        usage.amount.evidence,
    )
    assert lines["charge::sales_tax"].evidence == (
        tax.rate.evidence,
        *(charge.amount.evidence for charge in document.sections[0].charges[:-1]),
        tax.amount.evidence,
    )


def test_reconciliation_result_contains_no_float_values() -> None:
    result = reconcile_document(gas_document())

    assert not any(isinstance(value, float) for value in nested_values(result))
    assert result.tariff is None
    assert result.comparison is None


def test_money_tolerance_uses_exact_delta_and_rollups_sum_printed_amounts() -> None:
    document = water_document(
        water_usage_amount="7.471",
        subtotal="19.541",
        current_charges="19.541",
        amount_due="19.541",
    )

    result = reconcile_document(document)
    lines = {line.id: line for line in result.lines}

    assert lines["charge::water_usage"].delta == Decimal("0.011")
    assert lines["charge::water_usage"].status == "discrepancy"
    assert lines["subtotal::water"].expected_amount == Decimal("19.541")
    assert lines["subtotal::water"].status == "verified"
    assert result.discrepancy_total == Decimal("0.011")
