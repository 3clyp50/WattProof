from __future__ import annotations

import json
import re
from collections.abc import Callable
from decimal import (
    ROUND_DOWN,
    ROUND_FLOOR,
    Clamped,
    Context,
    Decimal,
    Inexact,
    Overflow,
    Rounded,
    Subnormal,
    Underflow,
    localcontext,
)
from typing import Any, Literal

import pytest
from pydantic import ValidationError

from wattproof.app import create_app
from wattproof.audit_service import audit_extraction
from wattproof.cli import main
from wattproof.fixtures import load_sample
from wattproof.models import DecimalFact
from wattproof.numeric import add_exact, multiply_exact, quantize_exact, subtract_exact
from wattproof.utility_fixtures import load_utility_sample
from wattproof.utility_models import DecimalFactV2, EvidenceRef, MoneyFactV2

SchemaOneKind = Literal["authentic", "synthetic"]
UtilityKind = Literal["duke", "centerpoint", "bloomington"]
SCHEMA_ONE_KINDS: tuple[SchemaOneKind, ...] = ("authentic", "synthetic")
UTILITY_KINDS: tuple[UtilityKind, ...] = ("duke", "centerpoint", "bloomington")
RAW_SENTINEL = "__WATTPROOF_RAW_NUMBER__"


def _set_path(payload: object, path: tuple[str | int, ...], value: object) -> None:
    target = payload
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]


def _raw_audit_body(
    kind: str,
    path: tuple[str | int, ...],
    numeric_token: str,
) -> str:
    client = create_app().test_client()
    payload = client.get(f"/api/sample/{kind}").get_json()["extraction"]
    _set_path(payload, path, RAW_SENTINEL)
    body = json.dumps(payload, separators=(",", ":"))
    encoded_sentinel = json.dumps(RAW_SENTINEL)
    assert body.count(encoded_sentinel) == 1
    return body.replace(encoded_sentinel, numeric_token)


def _post_raw(body: str, *, content_type: str = "application/json") -> Any:
    return create_app().test_client().post(
        "/api/audit",
        data=body.encode("utf-8"),
        content_type=content_type,
    )


def test_raw_schema_one_confidence_preserves_high_precision_token() -> None:
    token = "0.123456789012345678"
    body = _raw_audit_body(
        "authentic",
        ("total_usage", "confidence"),
        token,
    )

    response = _post_raw(body)

    assert response.status_code == 200
    meter = next(
        line for line in response.get_json()["audit"]["lines"]
        if line["id"] == "meter_delta"
    )
    assert meter["evidence"][0]["confidence"] == token


def test_raw_schema_two_confidence_preserves_exact_exponent_token() -> None:
    body = _raw_audit_body(
        "duke",
        ("sections", 0, "charges", 1, "amount", "evidence", "confidence"),
        "1e-6",
    )

    response = _post_raw(body)

    assert response.status_code == 200
    charge = next(
        line for line in response.get_json()["audit"]["lines"]
        if line["id"] == "charge::energy_tier_1"
    )
    assert charge["evidence"][2]["confidence"] == "0.000001"


@pytest.mark.parametrize("token", ["1e-1000", "1e1000"])
def test_raw_json_decimal_exponents_return_field_specific_422(token: str) -> None:
    body = _raw_audit_body(
        "authentic",
        ("total_usage", "confidence"),
        token,
    )

    response = _post_raw(body)

    assert response.status_code == 422
    assert response.is_json
    assert "total_usage.confidence" in response.get_json()["error"]
    assert "utility-bill decimal" in response.get_json()["error"]
    assert "Traceback" not in response.get_data(as_text=True)


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        ("{", "application/json"),
        ("", "application/json"),
        ("[]", "application/json"),
        ("null", "application/json"),
        ('"statement"', "application/json"),
        ("{}", "text/plain"),
        ('{"schema_version": NaN}', "application/json"),
    ],
)
def test_raw_audit_json_boundary_returns_controlled_400(
    body: str,
    content_type: str,
) -> None:
    response = _post_raw(body, content_type=content_type)

    assert response.status_code == 400
    assert response.is_json
    assert response.get_json() == {"error": "The reviewed extraction is missing."}
    assert "Traceback" not in response.get_data(as_text=True)


def test_raw_audit_rejects_oversized_numeric_token_before_numeric_construction() -> None:
    response = _post_raw('{"schema_version":' + "1" * 10_000 + "}")

    assert response.status_code == 400
    assert response.is_json
    assert response.get_json() == {"error": "The reviewed extraction is missing."}


def _legacy_decimal_payload(value: object) -> dict[str, Any]:
    payload = load_sample("authentic").total_usage.model_dump(mode="json")
    payload["value"] = value
    return payload


def _v2_decimal_payload(value: object) -> dict[str, Any]:
    quantity = load_utility_sample("duke").sections[0].charges[1].quantity
    assert quantity is not None
    payload = quantity.model_dump(mode="json")
    payload["value"] = value
    return payload


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (DecimalFact, _legacy_decimal_payload(0.5)),
        (DecimalFactV2, _v2_decimal_payload(0.5)),
        (
            MoneyFactV2,
            {
                **load_utility_sample("duke").current_charges.model_dump(mode="json"),
                "value": 0.5,
            },
        ),
        (
            EvidenceRef,
            {
                **load_utility_sample("duke")
                .sections[0]
                .provider.evidence.model_dump(mode="json"),
                "confidence": 0.5,
            },
        ),
    ],
)
def test_direct_binary_float_cannot_enter_utility_decimal(
    model: type[DecimalFact]
    | type[DecimalFactV2]
    | type[MoneyFactV2]
    | type[EvidenceRef],
    payload: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError, match="binary float"):
        model.model_validate(payload)


def _audit_snapshots() -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {
        kind: audit_extraction(load_sample(kind)).model_dump(mode="json")
        for kind in SCHEMA_ONE_KINDS
    }
    snapshots.update(
        {
            kind: audit_extraction(load_utility_sample(kind)).model_dump(mode="json")
            for kind in UTILITY_KINDS
        }
    )
    return snapshots


def _context_state(context: Context) -> tuple[object, ...]:
    return (
        context.prec,
        context.rounding,
        context.Emax,
        context.Emin,
        context.capitals,
        context.clamp,
        tuple((signal.__name__, enabled) for signal, enabled in context.traps.items()),
        tuple((signal.__name__, enabled) for signal, enabled in context.flags.items()),
    )


def _hostile_rounding(context: Context) -> None:
    context.prec = 4
    context.rounding = ROUND_FLOOR


def _hostile_exponents(context: Context) -> None:
    context.prec = 4
    context.rounding = ROUND_DOWN
    context.Emax = 1
    context.Emin = -1
    context.clamp = 1


def _hostile_traps(context: Context) -> None:
    context.prec = 4
    for signal in (Inexact, Rounded, Subnormal, Underflow, Overflow, Clamped):
        context.traps[signal] = True


HOSTILE_CONTEXTS: tuple[Callable[[Context], None], ...] = (
    _hostile_rounding,
    _hostile_exponents,
    _hostile_traps,
)


def _assert_no_negative_zero(value: object) -> None:
    encoded = json.dumps(value, sort_keys=True)
    pattern = r"(?<![0-9.])-0(?:\.0+)?(?![0-9.])"
    assert re.search(pattern, encoded) is None


@pytest.mark.parametrize("configure", HOSTILE_CONTEXTS)
def test_all_serialized_results_ignore_hostile_decimal_context(
    configure: Callable[[Context], None],
) -> None:
    baseline = _audit_snapshots()

    with localcontext() as context:
        configure(context)
        context.clear_flags()
        before = _context_state(context)
        hostile = _audit_snapshots()
        after = _context_state(context)

    assert hostile == baseline
    assert after == before
    _assert_no_negative_zero(hostile)
    synthetic = hostile["synthetic"]
    assert synthetic["discrepancy_total"] == "5.00"
    roots = {line["id"]: line["root_cause_id"] for line in synthetic["lines"]}
    assert roots["delivery_subtotal"] == "pge_peak_energy"


@pytest.mark.parametrize("configure", HOSTILE_CONTEXTS)
def test_cli_ignores_and_preserves_hostile_decimal_context(
    configure: Callable[[Context], None],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--sample", "synthetic"]) == 0
    baseline = capsys.readouterr()

    with localcontext() as context:
        configure(context)
        context.clear_flags()
        before = _context_state(context)
        assert main(["--sample", "synthetic"]) == 0
        hostile = capsys.readouterr()
        after = _context_state(context)

    assert hostile == baseline
    assert after == before
    assert "Possible $5.00" in hostile.out
    assert "-0.00" not in hostile.out


@pytest.mark.parametrize("configure", HOSTILE_CONTEXTS)
def test_exact_helpers_canonicalize_zero_and_preserve_caller_context(
    configure: Callable[[Context], None],
) -> None:
    with localcontext() as context:
        configure(context)
        context.clear_flags()
        before = _context_state(context)
        results = (
            add_exact(Decimal("1.00"), Decimal("-1.00")),
            subtract_exact(Decimal("1.00"), Decimal("1.00")),
            multiply_exact(Decimal("0.00"), Decimal("-2")),
            quantize_exact(Decimal("-0.001"), Decimal("0.01")),
        )
        after = _context_state(context)

    assert after == before
    assert [value.as_tuple().exponent for value in results] == [-2, -2, -2, -2]
    assert all(value.is_zero() and not value.is_signed() for value in results)
