from __future__ import annotations

from decimal import ROUND_DOWN, Decimal, localcontext
from typing import Any, Literal

import pytest
from pydantic import ValidationError

from wattproof.app import create_app
from wattproof.audit import round_money as round_legacy_money
from wattproof.audit_service import audit_extraction
from wattproof.cli import main
from wattproof.fixtures import load_sample
from wattproof.legacy import translate_legacy_bill
from wattproof.models import BillExtraction, DecimalFact, IntegerFact
from wattproof.reconcile import reconcile_document
from wattproof.utility_fixtures import load_utility_sample
from wattproof.utility_models import (
    DecimalFactV2,
    EvidenceRef,
    IntegerFactV2,
    MoneyFactV2,
    UtilityDocument,
)


def _legacy_decimal_payload(value: str) -> dict[str, Any]:
    payload = load_sample("authentic").total_usage.model_dump(mode="json")
    payload["value"] = value
    return payload


def _v2_decimal_payload(value: str) -> dict[str, Any]:
    payload = load_utility_sample("duke").sections[0].charges[1].quantity
    assert payload is not None
    serialized = payload.model_dump(mode="json")
    serialized["value"] = value
    return serialized


def _v2_money_payload(value: str) -> dict[str, Any]:
    payload = load_utility_sample("duke").current_charges.model_dump(mode="json")
    payload["value"] = value
    return payload


def _legacy_integer_payload(value: object) -> dict[str, Any]:
    payload = load_sample("authentic").billing_days.model_dump(mode="json")
    payload["value"] = value
    return payload


def _v2_integer_payload(value: object) -> dict[str, Any]:
    translated = translate_legacy_bill(load_sample("authentic"))
    fact = translated.sections[0].supplemental_facts[0].fact
    assert isinstance(fact, IntegerFactV2)
    payload = fact.model_dump(mode="json")
    payload["value"] = value
    return payload


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (DecimalFact, _legacy_decimal_payload("1e1000")),
        (DecimalFactV2, _v2_decimal_payload("1e1000")),
        (MoneyFactV2, _v2_money_payload("1e1000")),
    ],
)
def test_numeric_fact_wrappers_reject_extreme_exponents(
    model: type[DecimalFact] | type[DecimalFactV2] | type[MoneyFactV2],
    payload: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError, match="utility-bill decimal") as caught:
        model.model_validate(payload)

    assert caught.value.errors(include_url=False)[0]["loc"] == ("value",)


@pytest.mark.parametrize(
    "value",
    [
        "12345678901.123456789012345678",
        "1e-19",
        "0e1000",
        "NaN",
        "Infinity",
        "-Infinity",
    ],
)
def test_numeric_fact_rejects_unsupported_precision_and_non_finite_values(
    value: str,
) -> None:
    with pytest.raises(ValidationError):
        DecimalFactV2.model_validate(_v2_decimal_payload(value))


def test_numeric_string_is_length_bounded_before_decimal_construction() -> None:
    with pytest.raises(ValidationError, match="spelling is limited to 64 characters"):
        DecimalFactV2.model_validate(_v2_decimal_payload("9" * 10_000))


def test_numeric_domain_preserves_high_precision_ordinary_utility_values() -> None:
    fact = DecimalFactV2.model_validate(
        _v2_decimal_payload("99999999999.12345678901234567")
    )

    assert fact.value == Decimal("99999999999.12345678901234567")
    assert fact.value.as_tuple().exponent == -17


def test_evidence_confidence_cannot_bypass_numeric_domain() -> None:
    payload = load_utility_sample("duke").sections[0].provider.evidence.model_dump(
        mode="json"
    )
    payload["confidence"] = "1e-1000"

    with pytest.raises(ValidationError, match="utility-bill decimal") as caught:
        EvidenceRef.model_validate(payload)

    assert caught.value.errors(include_url=False)[0]["loc"] == ("confidence",)


def test_schema_one_confidence_preserves_exact_decimal_through_translation() -> None:
    payload = load_sample("authentic").model_dump(mode="json")
    payload["total_usage"]["confidence"] = "0.123456789012345678"

    bill = BillExtraction.model_validate(payload)
    translated = translate_legacy_bill(bill)

    assert bill.total_usage.confidence == Decimal("0.123456789012345678")
    assert bill.model_dump(mode="json")["total_usage"]["confidence"] == (
        "0.123456789012345678"
    )
    assert translated.sections[0].usage is not None
    assert translated.sections[0].usage.evidence.confidence == Decimal(
        "0.123456789012345678"
    )


def test_schema_one_confidence_rejects_pathological_exponent() -> None:
    payload = load_sample("authentic").model_dump(mode="json")
    payload["total_usage"]["confidence"] = "1e-1000"

    with pytest.raises(ValidationError, match="utility-bill decimal") as caught:
        BillExtraction.model_validate(payload)

    assert caught.value.errors(include_url=False)[0]["loc"] == (
        "total_usage",
        "confidence",
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("999999999999", 999999999999),
        (b"-999999999999", -999999999999),
        (999999999999, 999999999999),
        ("31.0", 31),
        ("3.1e1", 31),
        (Decimal("31.000"), 31),
    ],
)
@pytest.mark.parametrize("model", [IntegerFact, IntegerFactV2])
def test_integer_fact_accepts_only_exact_integers_within_boundary(
    model: type[IntegerFact] | type[IntegerFactV2],
    value: object,
    expected: int,
) -> None:
    payload = (
        _legacy_integer_payload(value)
        if model is IntegerFact
        else _v2_integer_payload(value)
    )

    assert model.model_validate(payload).value == expected


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        31.0,
        999999999999.0,
        31.5,
        float("nan"),
        float("inf"),
        "31.5",
        "3.15e1",
        b"31.5",
        "9" * 10_000,
        b"9" * 10_000,
        10**12,
        -(10**12),
        10**100,
    ],
)
@pytest.mark.parametrize("model", [IntegerFact, IntegerFactV2])
def test_integer_fact_rejects_non_exact_or_out_of_domain_values(
    model: type[IntegerFact] | type[IntegerFactV2],
    value: object,
) -> None:
    payload = (
        _legacy_integer_payload(value)
        if model is IntegerFact
        else _v2_integer_payload(value)
    )

    with pytest.raises(ValidationError, match="utility-bill integer") as caught:
        model.model_validate(payload)

    assert caught.value.errors(include_url=False)[0]["loc"] == ("value",)


@pytest.mark.parametrize(
    ("path", "expected_location"),
    [
        (("quantity", "value"), "sections.0.charges.1.quantity.value"),
        (("rate", "value"), "sections.0.charges.1.rate.value"),
        (("amount", "value"), "sections.0.charges.1.amount.value"),
    ],
)
def test_schema_two_api_rejects_pathological_nested_numbers_with_field_error(
    path: tuple[str, str],
    expected_location: str,
) -> None:
    client = create_app().test_client()
    payload = client.get("/api/sample/duke").get_json()["extraction"]
    payload["sections"][0]["charges"][1][path[0]][path[1]] = "1e1000"

    response = client.post("/api/audit", json=payload)

    assert response.status_code == 422
    assert response.is_json
    assert expected_location in response.get_json()["error"]
    assert "utility-bill decimal" in response.get_json()["error"]
    assert "Traceback" not in response.get_data(as_text=True)


@pytest.mark.parametrize("value", [10**12, 1e100])
def test_schema_two_api_applies_numeric_domain_to_json_numbers(
    value: int | float,
) -> None:
    client = create_app().test_client()
    payload = client.get("/api/sample/duke").get_json()["extraction"]
    payload["sections"][0]["charges"][1]["quantity"]["value"] = value

    response = client.post("/api/audit", json=payload)

    assert response.status_code == 422
    assert "sections.0.charges.1.quantity.value" in response.get_json()["error"]
    assert "utility-bill decimal" in response.get_json()["error"]


@pytest.mark.parametrize(
    ("mutate", "expected_location"),
    [
        ("usage", "total_usage.value"),
        ("rate", "charges.0.rate.value"),
    ],
)
def test_schema_one_api_rejects_pathological_numbers_before_legacy_translation(
    mutate: str,
    expected_location: str,
) -> None:
    client = create_app().test_client()
    payload = client.get("/api/sample/authentic").get_json()["extraction"]
    if mutate == "usage":
        payload["total_usage"]["value"] = "1e1000"
    else:
        payload["charges"][0]["rate"]["value"] = "1e1000"

    response = client.post("/api/audit", json=payload)

    assert response.status_code == 422
    assert response.is_json
    assert expected_location in response.get_json()["error"]
    assert "utility-bill decimal" in response.get_json()["error"]


def test_schema_one_api_rejects_pathological_confidence_with_field_error() -> None:
    client = create_app().test_client()
    payload = client.get("/api/sample/authentic").get_json()["extraction"]
    payload["total_usage"]["confidence"] = "1e-1000"

    response = client.post("/api/audit", json=payload)

    assert response.status_code == 422
    assert response.is_json
    assert "total_usage.confidence" in response.get_json()["error"]
    assert "utility-bill decimal" in response.get_json()["error"]


def test_schema_one_api_rejects_out_of_domain_integer_with_field_error() -> None:
    client = create_app().test_client()
    payload = client.get("/api/sample/authentic").get_json()["extraction"]
    payload["billing_days"]["value"] = 10**12

    response = client.post("/api/audit", json=payload)

    assert response.status_code == 422
    assert response.is_json
    assert "billing_days.value" in response.get_json()["error"]
    assert "utility-bill integer" in response.get_json()["error"]


def test_schema_two_api_rejects_out_of_domain_supplemental_integer() -> None:
    client = create_app().test_client()
    payload = translate_legacy_bill(load_sample("authentic")).model_dump(mode="json")
    payload["sections"][0]["supplemental_facts"][0]["fact"]["value"] = 10**100

    response = client.post("/api/audit", json=payload)

    assert response.status_code == 422
    assert response.is_json
    error = response.get_json()["error"]
    assert "sections.0.supplemental_facts.0.fact" in error
    assert "utility-bill" in error
    assert "Traceback" not in response.get_data(as_text=True)


def test_schema_one_model_rejects_excessive_significant_digits() -> None:
    payload = load_sample("authentic").model_dump(mode="json")
    payload["charges"][0]["rate"]["value"] = "12345678901.123456789012345678"

    with pytest.raises(ValidationError, match="significant digits"):
        BillExtraction.model_validate(payload)


def test_reconciliation_handles_largest_supported_operand_product() -> None:
    payload = load_utility_sample("duke").model_dump(mode="json")
    charge = payload["sections"][0]["charges"][1]
    charge["quantity"]["value"] = "999999999999"
    charge["rate"]["value"] = "999999999999"
    document = UtilityDocument.model_validate(payload)

    result = reconcile_document(document)

    line = next(item for item in result.lines if item.id == "charge::energy_tier_1")
    assert line.expected_amount == Decimal("999999999998000000000001.00")
    assert line.status == "discrepancy"


def test_percentage_reconciliation_handles_largest_supported_operands() -> None:
    payload = load_utility_sample("duke").model_dump(mode="json")
    for charge in payload["sections"][0]["charges"]:
        charge["amount"]["value"] = "999999999999.9999999999999999"
    tax = payload["sections"][1]["charges"][0]
    tax["rate"]["value"] = "999999999999"
    document = UtilityDocument.model_validate(payload)

    result = reconcile_document(document)

    line = next(item for item in result.lines if item.id == "charge::state_tax")
    assert line.expected_amount == Decimal("12999999999987000000000000.00")
    assert line.status == "discrepancy"


def test_meter_reconciliation_quantizes_largest_supported_reads_at_finest_scale() -> None:
    payload = load_utility_sample("duke").model_dump(mode="json")
    meter = payload["sections"][0]["meter"]
    meter["previous"]["value"] = "-999999999999"
    meter["current"]["value"] = "999999999999"
    meter["usage"]["value"] = "0.000000000000000001"
    document = UtilityDocument.model_validate(payload)

    result = reconcile_document(document)

    line = next(item for item in result.lines if item.id == "meter::electricity")
    assert line.expected_amount == Decimal("1999999999998.000000000000000000")
    assert line.delta == Decimal("-1999999999997.999999999999999999")


def test_conversion_reconciliation_quantizes_largest_product_at_finest_scale() -> None:
    payload = load_utility_sample("centerpoint").model_dump(mode="json")
    conversion = payload["sections"][0]["conversions"][0]
    conversion["source"]["value"] = "999999999999"
    conversion["factor"]["value"] = "999999999999"
    conversion["result"]["value"] = "0.000000000000000001"
    document = UtilityDocument.model_validate(payload)

    result = reconcile_document(document)

    line = next(item for item in result.lines if item.id == "conversion::gas::therms")
    assert line.expected_amount == Decimal("999999999998000000000001.000000000000000000")
    assert line.delta == Decimal("-999999999998000000000000.999999999999999999")


def test_legacy_money_quantizer_handles_largest_supported_operand_product() -> None:
    assert round_legacy_money(Decimal("999999999999") * Decimal("999999999999")) == (
        Decimal("999999999998000000000001.00")
    )


def test_cli_reports_numeric_validation_location_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def invalid_extraction(_path: object) -> UtilityDocument:
        payload = load_utility_sample("duke").model_dump(mode="json")
        payload["sections"][0]["charges"][1]["quantity"]["value"] = "1e1000"
        return UtilityDocument.model_validate(payload)

    monkeypatch.setattr("wattproof.cli.extract_pdf", invalid_extraction)

    assert main(["--file", "pathological.pdf"]) == 2
    captured = capsys.readouterr()
    assert "sections.0.charges.1.quantity.value" in captured.err
    assert "utility-bill decimal" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


@pytest.mark.parametrize(
    ("field", "expected_location", "expected_contract"),
    [
        ("confidence", "total_usage.confidence", "utility-bill decimal"),
        ("integer", "billing_days.value", "utility-bill integer"),
    ],
)
def test_cli_reports_schema_one_boundary_validation(
    field: str,
    expected_location: str,
    expected_contract: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def invalid_extraction(_path: object) -> BillExtraction:
        payload = load_sample("authentic").model_dump(mode="json")
        if field == "confidence":
            payload["total_usage"]["confidence"] = "1e-1000"
        else:
            payload["billing_days"]["value"] = 10**12
        return BillExtraction.model_validate(payload)

    monkeypatch.setattr("wattproof.cli.extract_pdf", invalid_extraction)

    assert main(["--file", "pathological.pdf"]) == 2
    captured = capsys.readouterr()
    assert expected_location in captured.err
    assert expected_contract in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_cli_formats_discrepancies_with_their_actual_units(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = audit_extraction(load_utility_sample("centerpoint"))
    conversion = next(line for line in result.lines if line.id == "conversion::gas::therms")
    usage_discrepancy = conversion.model_copy(
        update={
            "billed_amount": Decimal("113.277"),
            "expected_amount": Decimal("112.277"),
            "delta": Decimal("1.000"),
            "status": "discrepancy",
        }
    )
    subtotal = next(line for line in result.lines if line.id == "subtotal::gas")
    money_discrepancy = subtotal.model_copy(
        update={
            "billed_amount": Decimal("133.19"),
            "expected_amount": Decimal("132.19"),
            "delta": Decimal("1.00"),
            "status": "discrepancy",
        }
    )
    result = result.model_copy(update={"lines": (usage_discrepancy, money_discrepancy)})
    monkeypatch.setattr("wattproof.cli.audit_extraction", lambda _document: result)

    assert main(["--sample", "centerpoint"]) == 0
    output = capsys.readouterr().out
    assert "billed 113.277 therm" in output
    assert "expected 112.277 therm" in output
    assert "delta 1.000 therm" in output
    assert "billed $133.19" in output
    assert "expected $132.19" in output
    assert "delta $1.00" in output
    assert "$113.28" not in output


def test_schema_one_validation_is_invariant_to_ambient_decimal_context() -> None:
    payload = load_sample("authentic").model_dump(mode="json")

    with localcontext() as context:
        context.prec = 4
        context.rounding = ROUND_DOWN
        bill = BillExtraction.model_validate(payload)

    assert bill.total_usage.value == Decimal("327.119")


def test_all_audit_outputs_are_invariant_to_ambient_decimal_context() -> None:
    schema_one_kinds: tuple[Literal["authentic", "synthetic"], ...] = (
        "authentic",
        "synthetic",
    )
    utility_kinds: tuple[Literal["duke", "centerpoint", "bloomington"], ...] = (
        "duke",
        "centerpoint",
        "bloomington",
    )
    schema_one_baseline = {
        kind: audit_extraction(load_sample(kind)).model_dump(mode="json")
        for kind in schema_one_kinds
    }
    utility_baseline = {
        kind: audit_extraction(load_utility_sample(kind)).model_dump(mode="json")
        for kind in utility_kinds
    }

    with localcontext() as context:
        context.prec = 4
        context.rounding = ROUND_DOWN
        schema_one_hostile = {
            kind: audit_extraction(load_sample(kind)).model_dump(mode="json")
            for kind in schema_one_kinds
        }
        utility_hostile = {
            kind: audit_extraction(load_utility_sample(kind)).model_dump(mode="json")
            for kind in utility_kinds
        }

    assert schema_one_hostile == schema_one_baseline
    assert utility_hostile == utility_baseline

    synthetic = schema_one_hostile["synthetic"]
    assert synthetic["verdict"] == "possible_discrepancy"
    assert synthetic["discrepancy_total"] == "5.00"
    roots = {line["id"]: line["root_cause_id"] for line in synthetic["lines"]}
    assert roots["delivery_subtotal"] == "pge_peak_energy"
    percentage_formulas = [
        line["formula"] for line in schema_one_hostile["authentic"]["lines"]
        if "%" in line["formula"]
    ]
    assert percentage_formulas == [
        "$25.50 taxable generation × 1.00000%",
        "$8.40 taxable generation × 1.00000%",
    ]
