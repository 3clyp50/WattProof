"""Deterministic public multi-utility sample documents."""

from datetime import date
from decimal import Decimal
from typing import Literal

from .utility_models import (
    CalculationSpec,
    ConversionCheck,
    DateFactV2,
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


def _evidence(page: int, text: str) -> EvidenceRef:
    return EvidenceRef(
        page=page,
        text=text,
        confidence=Decimal("1"),
        provenance="rendered_page",
    )


def _text_fact(value: str, page: int, text: str) -> TextFactV2:
    return TextFactV2(
        value=value,
        status="printed",
        evidence=_evidence(page, text),
    )


def _date_fact(value: date, page: int, text: str) -> DateFactV2:
    return DateFactV2(
        value=value,
        status="printed",
        evidence=_evidence(page, text),
    )


def _decimal_fact(
    value: str,
    unit: str,
    page: int,
    text: str,
) -> DecimalFactV2:
    return DecimalFactV2(
        value=Decimal(value),
        unit=unit,
        status="printed",
        evidence=_evidence(page, text),
    )


def _money_fact(
    value: str,
    page: int,
    text: str,
    *,
    status: FactStatus = "printed",
) -> MoneyFactV2:
    return MoneyFactV2(
        value=Decimal(value),
        currency="USD",
        status=status,
        evidence=_evidence(page, text),
    )


def _fixed_charge(
    charge_id: str,
    label: str,
    amount: str,
    page: int,
    text: str,
) -> UtilityCharge:
    return UtilityCharge(
        id=charge_id,
        label=label,
        amount=_money_fact(amount, page, text),
    )


def _product_charge(
    charge_id: str,
    label: str,
    quantity: str,
    quantity_unit: str,
    rate: str,
    amount: str,
    page: int,
    text: str,
) -> UtilityCharge:
    evidence = _evidence(page, text)
    return UtilityCharge(
        id=charge_id,
        label=label,
        quantity=DecimalFactV2(
            value=Decimal(quantity),
            unit=quantity_unit,
            status="printed",
            evidence=evidence,
        ),
        rate=DecimalFactV2(
            value=Decimal(rate),
            unit=f"USD/{quantity_unit}",
            status="printed",
            evidence=evidence,
        ),
        amount=MoneyFactV2(
            value=Decimal(amount),
            currency="USD",
            status="printed",
            evidence=evidence,
        ),
        calculation=CalculationSpec(kind="quantity_times_rate"),
    )


def _duke_document() -> UtilityDocument:
    provider = _text_fact("Duke Energy", 1, "DUKE ENERGY")
    jurisdiction = _text_fact(
        "Indiana",
        3,
        "Indiana applies a 7% state sales tax to electricity service",
    )
    service_start = _date_fact(
        date(2026, 2, 7),
        1,
        "For Feb 7 - Mar 6",
    )
    service_end = _date_fact(
        date(2026, 3, 6),
        1,
        "For Feb 7 - Mar 6",
    )
    pre_tax_charges = (
        _fixed_charge(
            "connection_charge",
            "Connection Charge",
            "13.70",
            2,
            "Connection Charge $13.70",
        ),
        _product_charge(
            "energy_tier_1",
            "Energy Charge — first 300 kWh",
            "300",
            "kWh",
            "0.186556",
            "55.97",
            2,
            "300.000 kWh @ $0.18655600 55.97",
        ),
        _product_charge(
            "energy_tier_2",
            "Energy Charge — next 700 kWh",
            "700",
            "kWh",
            "0.135777",
            "95.04",
            2,
            "700.000 kWh @ $0.13577700 95.04",
        ),
        _product_charge(
            "energy_tier_3",
            "Energy Charge — remaining kWh",
            "1",
            "kWh",
            "0.123051",
            "0.12",
            2,
            "1.000 kWh @ $0.12305100 0.12",
        ),
        _product_charge(
            "rider_60",
            "Rider No. 60 Fuel Cost Adjustment",
            "1001",
            "kWh",
            "0.006090",
            "6.10",
            2,
            "Rider No. 60 Fuel Cost Adjustment 1,001.000 kWh @ $0.00609000 6.10",
        ),
        _product_charge(
            "rider_62",
            "Rider No. 62 Environmental Compliance Adjustment",
            "1001",
            "kWh",
            "-0.003619",
            "-3.62",
            2,
            "Rider No. 62 Environmental Compliance Adjustment "
            "1,001.000 kWh @ $-0.00361900 -3.62",
        ),
        _product_charge(
            "rider_65",
            "Rider No. 65 Transmission and Distribution Infrastructure Improvement",
            "1001",
            "kWh",
            "0.002259",
            "2.26",
            2,
            "Rider No. 65 Trans and Distrib Infrastructure Improvement "
            "1,001.000 kWh @ $0.00225900 2.26",
        ),
        _product_charge(
            "rider_66",
            "Rider No. 66 Energy Efficiency Revenue Adjustment",
            "1001",
            "kWh",
            "0.002717",
            "2.72",
            2,
            "Rider No. 66 Energy Efficiency Revenue Adjustment "
            "1,001.000 kWh @ $0.00271700 2.72",
        ),
        _product_charge(
            "rider_67",
            "Rider No. 67 Credits Adjustment",
            "1001",
            "kWh",
            "-0.006040",
            "-6.05",
            2,
            "Rider No. 67 Credits Adjustment 1,001.000 kWh @ $-0.00604000 -6.05",
        ),
        _product_charge(
            "rider_68",
            "Rider No. 68 Regional Transmission Operator Non-Fuel Costs and Revenue",
            "1001",
            "kWh",
            "0.001947",
            "1.95",
            2,
            "Rider No. 68 Regional Transmission Operator (RTO) Non-Fuel Costs and "
            "Revenue Adj 1,001.000 kWh @ $0.00194700 1.95",
        ),
        _product_charge(
            "rider_70",
            "Rider No. 70 Reliability Adjustment",
            "1001",
            "kWh",
            "0.000496",
            "0.50",
            2,
            "Rider No. 70 Reliability Adjustment 1,001.000 kWh @ $0.00049600 0.50",
        ),
        _product_charge(
            "rider_73",
            "Rider No. 73 Renewable Energy Project Revenue Adjustment",
            "1001",
            "kWh",
            "0.000036",
            "0.04",
            2,
            "Rider No. 73 Renewable Energy Project Revenue Adjustment "
            "1,001.000 kWh @ $0.00003600 0.04",
        ),
        _product_charge(
            "rider_74",
            "Rider No. 74 Load Control Adjustment Rider",
            "1001",
            "kWh",
            "-0.001064",
            "-1.07",
            2,
            "Rider No. 74 Load Control Adj Rider "
            "1,001.000 kWh @ $-0.00106400 -1.07",
        ),
    )
    electricity = ServiceSection(
        id="electricity",
        service_type="electricity",
        provider=provider,
        normalized_provider="Duke Energy Indiana, LLC",
        jurisdiction=jurisdiction,
        schedule=_text_fact(
            "Residential Electric Service (RS)",
            2,
            "Your current rate is Residential Electric Service (RS).",
        ),
        service_start=service_start,
        service_end=service_end,
        usage=_decimal_fact("1001", "kWh", 1, "Electric (kWh) 1,001"),
        meter=MeterCheck(
            previous=_decimal_fact(
                "137956",
                "kWh",
                1,
                "Previous reading on Feb 7 137956",
            ),
            current=_decimal_fact(
                "138957",
                "kWh",
                1,
                "Actual reading on Mar 6 138957",
            ),
            usage=_decimal_fact("1001", "kWh", 1, "Energy Used 1,001 kWh"),
        ),
        charges=pre_tax_charges,
        subtotal=_money_fact(
            "167.66",
            2,
            "Total Current Charges $167.66",
        ),
    )
    state_tax = UtilityCharge(
        id="state_tax",
        label="Indiana State Tax",
        rate=_decimal_fact(
            "0.07",
            "fraction",
            3,
            "Indiana applies a 7% state sales tax to electricity service",
        ),
        amount=_money_fact("11.74", 3, "Indiana State Tax $11.74"),
        calculation=CalculationSpec(
            kind="percent_of_charges",
            charge_ids=tuple(charge.id for charge in pre_tax_charges),
        ),
    )
    taxes = ServiceSection(
        id="taxes",
        service_type="other",
        provider=provider,
        normalized_provider="Duke Energy Indiana, LLC",
        jurisdiction=jurisdiction,
        service_start=service_start,
        service_end=service_end,
        charges=(state_tax,),
        subtotal=_money_fact("11.74", 3, "Total Taxes $11.74"),
    )
    # The generic document rollup aggregates every current service and tax section.
    current_charges = _money_fact(
        "179.40",
        1,
        "Current Electric Charges 167.66; Taxes 11.74; Total Amount Due Mar 31 $179.40",
        status="inferred",
    )
    return UtilityDocument(
        schema_version="2.0",
        fixture_kind="duke",
        document_sha256=(
            "b131c36a215762796e72f3d20986fbea7e64e2dd611081d8936f8442102c3e9a"
        ),
        page_count=3,
        source_url=(
            "https://www.duke-energy.com/-/media/pdfs/bill-examples/"
            "260482-bill-tutorial-handout-res-dei.pdf"
        ),
        statement_date=_date_fact(
            date(2026, 3, 10),
            1,
            "Bill date Mar 10, 2026",
        ),
        currency="USD",
        sections=(electricity, taxes),
        current_charges=current_charges,
        amount_due=_money_fact(
            "179.40",
            1,
            "Total Amount Due Mar 31 $179.40",
        ),
    )


def _centerpoint_document() -> UtilityDocument:
    statement_line = "Billing Period 11/30/23 - 12/22/23"
    conversion_line = (
        "108 x 1.03960 (Therm Conversion) = Therms Used of 112.277 THM"
    )
    distribution = _fixed_charge(
        "distribution_and_service",
        "Distribution and Service Charges",
        "96.03",
        2,
        "Distribution and Service Charges $96.03",
    )
    gas_cost = _fixed_charge(
        "gas_cost",
        "Gas Cost Charge",
        "27.51",
        2,
        "Gas Cost Charge $27.51",
    )
    state_tax = UtilityCharge(
        id="state_tax",
        label="State Sales Tax",
        rate=_decimal_fact("0.07", "fraction", 2, "State Sales Tax 7.00%"),
        amount=_money_fact("8.65", 2, "State Sales Tax 7.00% $8.65"),
        calculation=CalculationSpec(
            kind="percent_of_charges",
            charge_ids=(distribution.id, gas_cost.id),
        ),
    )
    gas = ServiceSection(
        id="gas",
        service_type="natural_gas",
        provider=_text_fact("CenterPoint Energy", 2, "CenterPoint Energy"),
        normalized_provider=(
            "Indiana Gas Company, Inc. d/b/a CenterPoint Energy Indiana North"
        ),
        jurisdiction=_text_fact(
            "Indiana",
            2,
            "Indiana Gas Company d/b/a CenterPoint Energy Indiana North",
        ),
        schedule=_text_fact(
            "RES 110_IN S 110 Residential Service",
            2,
            "Rate: RES 110_IN S 110 Residential Service",
        ),
        service_start=_date_fact(date(2023, 11, 30), 2, statement_line),
        service_end=_date_fact(date(2023, 12, 22), 2, statement_line),
        usage=_decimal_fact("112.277", "therm", 2, conversion_line),
        conversions=(
            ConversionCheck(
                id="therms",
                label="CCF to therm conversion",
                source=_decimal_fact("108", "CCF", 2, conversion_line),
                factor=_decimal_fact(
                    "1.03960",
                    "therm/CCF",
                    2,
                    conversion_line,
                ),
                result=_decimal_fact("112.277", "therm", 2, conversion_line),
            ),
        ),
        charges=(distribution, gas_cost, state_tax),
        subtotal=_money_fact(
            "132.19",
            2,
            "Total Current Gas Charges $132.19",
        ),
    )
    return UtilityDocument(
        schema_version="2.0",
        fixture_kind="centerpoint",
        document_sha256=(
            "c0b7d9b0252226078b39d6760308506c28b388729906d3ac54db950b9f819262"
        ),
        page_count=2,
        source_url=(
            "https://www.centerpointenergy.com/en-us/CustomerService/Documents/"
            "bill-guides/240312-20-EIP-IN%20Gas-bill-guide.pdf"
        ),
        statement_date=_date_fact(
            date(2024, 1, 4),
            2,
            "DATE MAILED Jan 04, 2024",
        ),
        currency="USD",
        sections=(gas,),
        current_charges=_money_fact(
            "132.19",
            2,
            "Total Current Gas Charges $132.19",
        ),
        amount_due=_money_fact("132.19", 2, "AMOUNT DUE $132.19"),
    )


def _bloomington_document() -> UtilityDocument:
    provider = _text_fact(
        "City of Bloomington Utilities",
        1,
        "CITY OF BLOOMINGTON UTILITIES",
    )
    jurisdiction = _text_fact(
        "Bloomington, Indiana",
        1,
        "WWW.BLOOMINGTON.IN.GOV",
    )
    service_period = "Service Period 03/01/2018 to 04/01/2018"
    service_start = _date_fact(date(2018, 3, 1), 1, service_period)
    service_end = _date_fact(date(2018, 4, 1), 1, service_period)
    shared_section_facts = {
        "provider": provider,
        "normalized_provider": "City of Bloomington Utilities",
        "jurisdiction": jurisdiction,
        "service_start": service_start,
        "service_end": service_end,
    }

    water_line = "WATER Usage (DOM) $3.73 2 $7.46"
    water_usage = _product_charge(
        "water_usage",
        "Water usage",
        "2",
        "kgal",
        "3.73",
        "7.46",
        1,
        water_line,
    )
    water_service = _fixed_charge(
        "water_service",
        "Water Service",
        "7.86",
        1,
        "Water Service $7.86",
    )
    fire_protection = _fixed_charge(
        "fire_protection",
        "Fire Protection",
        "2.93",
        1,
        "Fire Protection $2.93",
    )
    sales_tax = _fixed_charge(
        "sales_tax",
        "Sales Tax",
        "1.28",
        1,
        "Sales Tax $1.28",
    )
    water = ServiceSection(
        id="water",
        service_type="water",
        **shared_section_facts,
        usage=_decimal_fact("2", "kgal", 1, water_line),
        charges=(water_usage, water_service, fire_protection, sales_tax),
        subtotal=_money_fact(
            "19.53",
            1,
            "Usage (DOM) $3.73 2 $7.46; Water Service $7.86; "
            "Fire Protection $2.93; Sales Tax $1.28",
            status="inferred",
        ),
    )

    wastewater_line = "WASTEWATER Usage $7.76 2 $15.52"
    wastewater_usage = _product_charge(
        "wastewater_usage",
        "Wastewater usage",
        "2",
        "kgal",
        "7.76",
        "15.52",
        1,
        wastewater_line,
    )
    wastewater_service = _fixed_charge(
        "wastewater_service",
        "Wastewater Service",
        "7.95",
        1,
        "Wastewater Service $7.95",
    )
    wastewater = ServiceSection(
        id="wastewater",
        service_type="wastewater",
        **shared_section_facts,
        usage=_decimal_fact("2", "kgal", 1, wastewater_line),
        charges=(wastewater_usage, wastewater_service),
        subtotal=_money_fact(
            "23.47",
            1,
            "WASTEWATER Usage $7.76 2 $15.52; Wastewater Service $7.95",
            status="inferred",
        ),
    )

    stormwater_charge = _fixed_charge(
        "stormwater",
        "Stormwater Charge",
        "2.70",
        1,
        "STORMWATER Stormwater Charge $2.70",
    )
    stormwater = ServiceSection(
        id="stormwater",
        service_type="stormwater",
        **shared_section_facts,
        charges=(stormwater_charge,),
        subtotal=_money_fact(
            "2.70",
            1,
            "STORMWATER Stormwater Charge $2.70",
            status="inferred",
        ),
    )

    sanitation_charge = _fixed_charge(
        "sanitation",
        "Small Cart",
        "6.22",
        1,
        "SANITATION Small Cart $6.22 1 $6.22",
    )
    sanitation = ServiceSection(
        id="sanitation",
        service_type="sanitation",
        **shared_section_facts,
        charges=(sanitation_charge,),
        subtotal=_money_fact(
            "6.22",
            1,
            "SANITATION Small Cart $6.22 1 $6.22",
            status="inferred",
        ),
    )

    return UtilityDocument(
        schema_version="2.0",
        fixture_kind="bloomington",
        document_sha256=(
            "a414c296e3dd71a08aa459bb1a7c38fcdeab0c90aa0bb05f7c4e39ae9d70b79c"
        ),
        page_count=1,
        source_url=(
            "https://bloomington.in.gov/sites/default/files/2026-02/"
            "Understanding%20Your%20Water%20Bill%202026%20Accessible.pdf"
        ),
        currency="USD",
        sections=(water, wastewater, stormwater, sanitation),
        current_charges=_money_fact(
            "51.92",
            1,
            "TOTAL CURRENT CHARGES $51.92",
        ),
        amount_due=_money_fact("51.92", 1, "Total Due $51.92"),
    )


def load_utility_sample(
    kind: Literal["duke", "centerpoint", "bloomington"],
) -> UtilityDocument:
    if kind == "duke":
        return _duke_document()
    if kind == "centerpoint":
        return _centerpoint_document()
    if kind == "bloomington":
        return _bloomington_document()
    raise ValueError(
        f"Unsupported utility sample {kind!r}. Choose one of: "
        "duke, centerpoint, bloomington."
    )
