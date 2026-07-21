from collections.abc import Iterator, Mapping
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

import pytest
from pydantic import BaseModel

import wattproof.utility_fixtures as fixture_module
from wattproof.reconcile import reconcile_document
from wattproof.utility_fixtures import load_utility_sample
from wattproof.utility_models import (
    CalculationSpec,
    EvidenceRef,
    FactBaseV2,
    UtilityCharge,
    UtilityDocument,
)

UtilitySampleKind = Literal["duke", "centerpoint", "bloomington"]


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


def charges_by_id(document: UtilityDocument) -> dict[str, UtilityCharge]:
    return {
        charge.id: charge
        for section in document.sections
        for charge in section.charges
    }


def test_unsupported_utility_sample_kind_has_actionable_error() -> None:
    unsupported = cast(UtilitySampleKind, "solar")

    with pytest.raises(
        ValueError,
        match=(
            "Unsupported utility sample 'solar'.*"
            "duke.*centerpoint.*bloomington"
        ),
    ):
        load_utility_sample(unsupported)


def test_duke_fixture_reconciles_every_visible_product_tax_and_rollup() -> None:
    document = load_utility_sample("duke")
    electricity, taxes = document.sections
    charges = charges_by_id(document)

    assert document.statement_date is not None
    assert document.statement_date.value == date(2026, 3, 10)
    assert [section.id for section in document.sections] == ["electricity", "taxes"]
    assert electricity.service_type == "electricity"
    assert electricity.provider.value == "Duke Energy"
    assert electricity.normalized_provider == "Duke Energy Indiana, LLC"
    assert electricity.jurisdiction is not None
    assert electricity.jurisdiction.value == "Indiana"
    assert electricity.schedule is not None
    assert electricity.schedule.value == "Residential Electric Service (RS)"
    assert electricity.service_start is not None
    assert electricity.service_start.value == date(2026, 2, 7)
    assert electricity.service_end is not None
    assert electricity.service_end.value == date(2026, 3, 6)
    assert electricity.usage is not None
    assert electricity.usage.value == Decimal("1001")
    assert electricity.usage.unit == "kWh"
    assert electricity.meter is not None
    assert electricity.meter.previous.value == Decimal("137956")
    assert electricity.meter.current.value == Decimal("138957")
    assert electricity.meter.usage.value == Decimal("1001")

    assert charges["connection_charge"].amount.value == Decimal("13.70")
    assert charges["connection_charge"].calculation is None
    products = {
        "energy_tier_1": ("300", "0.186556", "55.97"),
        "energy_tier_2": ("700", "0.135777", "95.04"),
        "energy_tier_3": ("1", "0.123051", "0.12"),
        "rider_60": ("1001", "0.006090", "6.10"),
        "rider_62": ("1001", "-0.003619", "-3.62"),
        "rider_65": ("1001", "0.002259", "2.26"),
        "rider_66": ("1001", "0.002717", "2.72"),
        "rider_67": ("1001", "-0.006040", "-6.05"),
        "rider_68": ("1001", "0.001947", "1.95"),
        "rider_70": ("1001", "0.000496", "0.50"),
        "rider_73": ("1001", "0.000036", "0.04"),
        "rider_74": ("1001", "-0.001064", "-1.07"),
    }
    for charge_id, (quantity, rate, amount) in products.items():
        charge = charges[charge_id]
        assert charge.quantity is not None
        assert charge.quantity.value == Decimal(quantity)
        assert charge.quantity.unit == "kWh"
        assert charge.rate is not None
        assert charge.rate.value == Decimal(rate)
        assert charge.rate.unit == "USD/kWh"
        assert charge.amount.value == Decimal(amount)
        assert charge.calculation == CalculationSpec(kind="quantity_times_rate")
        assert charge.quantity.evidence.page == 2
        assert charge.rate.evidence.page == 2
        assert charge.amount.evidence.page == 2

    pre_tax_ids = ("connection_charge", *products)
    state_tax = charges["state_tax"]
    assert taxes.service_type == "other"
    assert taxes.provider.value == "Duke Energy"
    assert taxes.normalized_provider == "Duke Energy Indiana, LLC"
    assert state_tax.rate is not None
    assert state_tax.rate.value == Decimal("0.07")
    assert state_tax.rate.unit == "fraction"
    assert state_tax.amount.value == Decimal("11.74")
    assert state_tax.amount.evidence.page == 3
    assert state_tax.calculation == CalculationSpec(
        kind="percent_of_charges",
        charge_ids=pre_tax_ids,
    )
    assert electricity.subtotal.value == Decimal("167.66")
    assert taxes.subtotal.value == Decimal("11.74")
    assert document.current_charges.value == Decimal("179.40")
    assert document.current_charges.status == "inferred"
    assert document.outstanding_balance is None
    assert document.amount_due.value == Decimal("179.40")

    result = reconcile_document(document)
    lines = {line.id: line for line in result.lines}
    assert lines["meter::electricity"].expected_amount == Decimal("1001")
    for charge_id, (_, _, amount) in products.items():
        assert lines[f"charge::{charge_id}"].expected_amount == Decimal(amount)
    assert lines["charge::state_tax"].expected_amount == Decimal("11.74")
    assert lines["subtotal::electricity"].expected_amount == Decimal("167.66")
    assert lines["subtotal::taxes"].expected_amount == Decimal("11.74")
    assert lines["statement::current_charges"].expected_amount == Decimal("179.40")
    assert lines["statement::amount_due"].expected_amount == Decimal("179.40")
    assert result.verdict == "reconciled"
    assert result.verification_level == "internally_reconciled"
    assert result.tariff is None
    assert result.comparison is None


def test_centerpoint_fixture_uses_only_rendered_gas_values_and_reconciles() -> None:
    document = load_utility_sample("centerpoint")
    gas = document.sections[0]
    charges = charges_by_id(document)

    assert document.statement_date is not None
    assert document.statement_date.value == date(2024, 1, 4)
    assert gas.id == "gas"
    assert gas.service_type == "natural_gas"
    assert gas.provider.value == "CenterPoint Energy"
    assert (
        gas.normalized_provider
        == "Indiana Gas Company, Inc. d/b/a CenterPoint Energy Indiana North"
    )
    assert gas.jurisdiction is not None
    assert gas.jurisdiction.value == "Indiana"
    assert gas.schedule is not None
    assert gas.schedule.value == "RES 110_IN S 110 Residential Service"
    assert gas.service_start is not None
    assert gas.service_start.value == date(2023, 11, 30)
    assert gas.service_end is not None
    assert gas.service_end.value == date(2023, 12, 22)
    assert gas.usage is not None
    assert gas.usage.value == Decimal("112.277")
    assert gas.usage.unit == "therm"
    assert gas.meter is None
    assert len(gas.conversions) == 1
    conversion = gas.conversions[0]
    assert conversion.id == "therms"
    assert conversion.source.value == Decimal("108")
    assert conversion.source.unit == "CCF"
    assert conversion.factor.value == Decimal("1.03960")
    assert conversion.factor.unit == "therm/CCF"
    assert conversion.result.value == Decimal("112.277")
    assert conversion.result.unit == "therm"

    assert charges["distribution_and_service"].amount.value == Decimal("96.03")
    assert charges["distribution_and_service"].calculation is None
    assert charges["gas_cost"].amount.value == Decimal("27.51")
    assert charges["gas_cost"].calculation is None
    state_tax = charges["state_tax"]
    assert state_tax.rate is not None
    assert state_tax.rate.value == Decimal("0.07")
    assert state_tax.rate.unit == "fraction"
    assert state_tax.amount.value == Decimal("8.65")
    assert state_tax.calculation == CalculationSpec(
        kind="percent_of_charges",
        charge_ids=("distribution_and_service", "gas_cost"),
    )
    assert gas.subtotal.value == Decimal("132.19")
    assert document.current_charges.value == Decimal("132.19")
    assert document.amount_due.value == Decimal("132.19")

    result = reconcile_document(document)
    lines = {line.id: line for line in result.lines}
    assert lines["conversion::gas::therms"].expected_amount == Decimal("112.277")
    assert lines["charge::state_tax"].expected_amount == Decimal("8.65")
    assert lines["subtotal::gas"].expected_amount == Decimal("132.19")
    assert lines["statement::amount_due"].expected_amount == Decimal("132.19")
    assert result.verdict == "reconciled"
    assert result.verification_level == "internally_reconciled"

    forbidden_native_values = ("534", "6.326", "134.69", "28.79")
    serialized = document.model_dump_json()
    assert fixture_module.__file__ is not None
    module_source = Path(fixture_module.__file__).read_text(encoding="utf-8")
    for value in forbidden_native_values:
        assert value not in serialized
        assert value not in module_source


def test_bloomington_fixture_reconciles_each_visible_service_section() -> None:
    document = load_utility_sample("bloomington")
    charges = charges_by_id(document)

    assert document.statement_date is None
    assert [section.id for section in document.sections] == [
        "water",
        "wastewater",
        "stormwater",
        "sanitation",
    ]
    assert [section.service_type for section in document.sections] == [
        "water",
        "wastewater",
        "stormwater",
        "sanitation",
    ]
    for section in document.sections:
        assert section.provider.value == "City of Bloomington Utilities"
        assert section.normalized_provider == "City of Bloomington Utilities"
        assert section.jurisdiction is not None
        assert section.jurisdiction.value == "Bloomington, Indiana"
        assert section.service_start is not None
        assert section.service_start.value == date(2018, 3, 1)
        assert section.service_end is not None
        assert section.service_end.value == date(2018, 4, 1)

    water, wastewater, stormwater, sanitation = document.sections
    assert water.usage is not None
    assert water.usage.value == Decimal("2")
    assert water.usage.unit == "kgal"
    assert wastewater.usage is not None
    assert wastewater.usage.value == Decimal("2")
    assert wastewater.usage.unit == "kgal"
    assert stormwater.usage is None
    assert sanitation.usage is None

    billed_amounts = {
        "water_usage": "7.46",
        "water_service": "7.86",
        "fire_protection": "2.93",
        "sales_tax": "1.28",
        "wastewater_usage": "15.52",
        "wastewater_service": "7.95",
        "stormwater": "2.70",
        "sanitation": "6.22",
    }
    assert {charge.id for charge in charges.values()} == set(billed_amounts)
    for charge_id, amount in billed_amounts.items():
        assert charges[charge_id].amount.value == Decimal(amount)

    water_usage = charges["water_usage"]
    assert water_usage.quantity is not None
    assert water_usage.quantity.value == Decimal("2")
    assert water_usage.quantity.unit == "kgal"
    assert water_usage.rate is not None
    assert water_usage.rate.value == Decimal("3.73")
    assert water_usage.rate.unit == "USD/kgal"
    assert water_usage.calculation == CalculationSpec(kind="quantity_times_rate")
    wastewater_usage = charges["wastewater_usage"]
    assert wastewater_usage.quantity is not None
    assert wastewater_usage.quantity.value == Decimal("2")
    assert wastewater_usage.quantity.unit == "kgal"
    assert wastewater_usage.rate is not None
    assert wastewater_usage.rate.value == Decimal("7.76")
    assert wastewater_usage.rate.unit == "USD/kgal"
    assert wastewater_usage.calculation == CalculationSpec(
        kind="quantity_times_rate"
    )
    sales_tax = charges["sales_tax"]
    assert sales_tax.rate is None
    assert sales_tax.calculation is None
    assert [section.subtotal.value for section in document.sections] == [
        Decimal("19.53"),
        Decimal("23.47"),
        Decimal("2.70"),
        Decimal("6.22"),
    ]
    assert document.current_charges.value == Decimal("51.92")
    assert document.amount_due.value == Decimal("51.92")

    result = reconcile_document(document)
    lines = {line.id: line for line in result.lines}
    assert {f"charge::{charge_id}" for charge_id in billed_amounts} <= lines.keys()
    assert lines["charge::water_usage"].expected_amount == Decimal("7.46")
    assert lines["charge::sales_tax"].billed_amount == Decimal("1.28")
    assert lines["charge::sales_tax"].expected_amount is None
    assert lines["charge::sales_tax"].delta is None
    assert lines["charge::sales_tax"].status == "cannot_verify"
    assert lines["charge::wastewater_usage"].expected_amount == Decimal("15.52")
    for fixed_id in (
        "water_service",
        "fire_protection",
        "wastewater_service",
        "stormwater",
        "sanitation",
    ):
        assert lines[f"charge::{fixed_id}"].expected_amount is None
        assert lines[f"charge::{fixed_id}"].status == "cannot_verify"
    assert lines["subtotal::water"].expected_amount == Decimal("19.53")
    assert lines["subtotal::wastewater"].expected_amount == Decimal("23.47")
    assert lines["subtotal::stormwater"].expected_amount == Decimal("2.70")
    assert lines["subtotal::sanitation"].expected_amount == Decimal("6.22")
    assert lines["statement::current_charges"].expected_amount == Decimal("51.92")
    assert lines["statement::amount_due"].expected_amount == Decimal("51.92")
    assert result.verdict == "reconciled"
    assert result.verification_level == "internally_reconciled"


@pytest.mark.parametrize(
    ("kind", "source_url", "digest", "page_count"),
    [
        (
            "duke",
            "https://www.duke-energy.com/-/media/pdfs/bill-examples/"
            "260482-bill-tutorial-handout-res-dei.pdf",
            "b131c36a215762796e72f3d20986fbea7e64e2dd611081d8936f8442102c3e9a",
            3,
        ),
        (
            "centerpoint",
            "https://www.centerpointenergy.com/en-us/CustomerService/Documents/"
            "bill-guides/240312-20-EIP-IN%20Gas-bill-guide.pdf",
            "c0b7d9b0252226078b39d6760308506c28b388729906d3ac54db950b9f819262",
            2,
        ),
        (
            "bloomington",
            "https://bloomington.in.gov/sites/default/files/2026-02/"
            "Understanding%20Your%20Water%20Bill%202026%20Accessible.pdf",
            "a414c296e3dd71a08aa459bb1a7c38fcdeab0c90aa0bb05f7c4e39ae9d70b79c",
            1,
        ),
    ],
)
def test_public_fixture_metadata_and_rendered_evidence_are_exact(
    kind: UtilitySampleKind,
    source_url: str,
    digest: str,
    page_count: int,
) -> None:
    document = load_utility_sample(kind)

    assert document.schema_version == "2.0"
    assert document.fixture_kind == kind
    assert document.currency == "USD"
    assert document.source_url == source_url
    assert document.document_sha256 == digest
    assert document.page_count == page_count
    assert document.warnings == ()

    evidence_refs = [
        value for value in nested_values(document) if isinstance(value, EvidenceRef)
    ]
    assert evidence_refs
    assert all(evidence.provenance == "rendered_page" for evidence in evidence_refs)
    assert all(1 <= evidence.page <= page_count for evidence in evidence_refs)

    private_markers = (
        "sample",
        "sally",
        "jane",
        "123456789",
        "9999 9999 9999",
        "000000000",
        "123 sample st",
        "0000 boulevard",
        "1111 e btown way",
    )
    for evidence in evidence_refs:
        text = evidence.text.casefold()
        assert not any(marker in text for marker in private_markers)

    facts = [
        value for value in nested_values(document) if isinstance(value, FactBaseV2)
    ]
    inferred = [fact for fact in facts if fact.status == "inferred"]
    if kind == "duke":
        assert inferred == [document.current_charges]
    elif kind == "bloomington":
        assert inferred == [section.subtotal for section in document.sections]
    else:
        assert inferred == []
    assert all(fact.status in {"printed", "inferred"} for fact in facts)
    assert all(fact.original_value is None for fact in facts)


@pytest.mark.parametrize("kind", ["duke", "centerpoint", "bloomington"])
def test_public_fixtures_never_claim_tariff_verification(
    kind: UtilitySampleKind,
) -> None:
    result = reconcile_document(load_utility_sample(kind))

    assert result.tariff is None
    assert result.comparison is None
    assert result.verification_level == "internally_reconciled"
    assert "tariff_verified" not in result.model_dump_json()
