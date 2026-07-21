from __future__ import annotations

import json
from collections.abc import Callable
from decimal import (
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_UP,
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
from wattproof.audit import audit_bill
from wattproof.audit_service import audit_extraction
from wattproof.cli import main
from wattproof.fixtures import load_sample
from wattproof.models import BillExtraction
from wattproof.numeric import format_decimal_exact, format_fixed_exact, format_usd_exact
from wattproof.utility_fixtures import load_utility_sample
from wattproof.utility_models import UtilityDocument

PageTarget = Literal[
    "legacy_source_page",
    "legacy_page_count",
    "v2_evidence_page",
    "v2_page_count",
]


def _set_path(payload: object, path: tuple[str | int, ...], value: object) -> None:
    target = payload
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]


def _page_case(
    target: PageTarget,
    value: object,
) -> tuple[type[BillExtraction] | type[UtilityDocument], dict[str, Any], tuple[object, ...]]:
    if target.startswith("legacy_"):
        model: type[BillExtraction] | type[UtilityDocument] = BillExtraction
        payload = load_sample("authentic").model_dump(mode="json")
        if target == "legacy_source_page":
            path: tuple[str | int, ...] = ("total_usage", "source_page")
        else:
            path = ("page_count",)
    else:
        model = UtilityDocument
        payload = load_utility_sample("duke").model_dump(mode="json")
        if target == "v2_evidence_page":
            path = ("sections", 0, "provider", "evidence", "page")
        else:
            path = ("page_count",)
    _set_path(payload, path, value)
    return model, payload, tuple(path)


@pytest.mark.parametrize(
    "target",
    (
        "legacy_source_page",
        "legacy_page_count",
        "v2_evidence_page",
        "v2_page_count",
    ),
)
@pytest.mark.parametrize(
    "value",
    (
        True,
        4.0,
        4.5,
        Decimal("4.5"),
        "4e-1",
        0,
        21,
        10**100,
    ),
)
def test_external_page_integers_reject_inexact_or_unbounded_forms(
    target: PageTarget,
    value: object,
) -> None:
    model, payload, expected_location = _page_case(target, value)

    with pytest.raises(ValidationError, match="integer|greater than|less than") as caught:
        model.model_validate(payload)

    assert caught.value.errors(include_url=False)[0]["loc"] == expected_location


@pytest.mark.parametrize(
    ("target", "value", "expected"),
    (
        ("legacy_source_page", 4, 4),
        ("legacy_source_page", "4", 4),
        ("legacy_source_page", Decimal("4.0"), 4),
        ("legacy_source_page", "4e0", 4),
        ("legacy_page_count", 6, 6),
        ("legacy_page_count", "6.0", 6),
        ("v2_evidence_page", b"1", 1),
        ("v2_evidence_page", "1e0", 1),
        ("v2_page_count", Decimal("6.0"), 6),
        ("v2_page_count", "6", 6),
    ),
)
def test_external_page_integers_accept_exact_bounded_forms(
    target: PageTarget,
    value: object,
    expected: int,
) -> None:
    model, payload, location = _page_case(target, value)

    parsed = model.model_validate(payload)
    actual: object = parsed
    for part in location:
        actual = getattr(actual, part) if isinstance(part, str) else actual[part]  # type: ignore[index]

    assert actual == expected
    assert isinstance(actual, int)


def _raw_page_body(target: PageTarget, token: str) -> str:
    _, payload, path = _page_case(target, "__RAW_PAGE__")
    encoded = json.dumps(payload, separators=(",", ":"))
    sentinel = json.dumps("__RAW_PAGE__")
    assert encoded.count(sentinel) == 1
    return encoded.replace(sentinel, token)


@pytest.mark.parametrize(
    ("target", "token", "expected_location"),
    (
        ("legacy_source_page", "4.5", "total_usage.source_page"),
        ("legacy_page_count", "1e-1", "page_count"),
        (
            "v2_evidence_page",
            "4.5",
            "sections.0.provider.evidence.page",
        ),
        ("v2_page_count", "1e100", "page_count"),
    ),
)
def test_api_reports_external_page_integer_errors_at_the_field(
    target: PageTarget,
    token: str,
    expected_location: str,
) -> None:
    response = create_app().test_client().post(
        "/api/audit",
        data=_raw_page_body(target, token),
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.is_json
    assert expected_location in response.get_json()["error"]
    assert "utility-bill integer" in response.get_json()["error"]
    assert "Traceback" not in response.get_data(as_text=True)


@pytest.mark.parametrize("schema", ("legacy", "v2"))
def test_cli_reports_page_integer_errors_without_traceback(
    schema: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def invalid_extraction(_path: object) -> BillExtraction | UtilityDocument:
        target: PageTarget = (
            "legacy_source_page" if schema == "legacy" else "v2_evidence_page"
        )
        model, payload, _ = _page_case(target, 1.5)
        return model.model_validate(payload)

    monkeypatch.setattr("wattproof.cli.extract_pdf", invalid_extraction)

    assert main(["--file", "invalid-page.pdf"]) == 2
    captured = capsys.readouterr()
    expected = (
        "total_usage.source_page"
        if schema == "legacy"
        else "sections.0.provider.evidence.page"
    )
    assert expected in captured.err
    assert "utility-bill integer" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


@pytest.mark.parametrize(
    "body",
    (
        '{"nested":' * 10_000 + "0" + "}" * 10_000,
        "[" * 10_000 + "0" + "]" * 10_000,
    ),
)
def test_deeply_nested_audit_json_returns_controlled_400(body: str) -> None:
    response = create_app().test_client().post(
        "/api/audit",
        data=body,
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.is_json
    assert response.get_json() == {"error": "The reviewed extraction is missing."}
    assert "Traceback" not in response.get_data(as_text=True)


def _rounding_duke_document() -> UtilityDocument:
    payload = load_utility_sample("duke").model_dump(mode="json")
    payload["sections"][0]["charges"][1]["amount"]["value"] = "100.005"
    return UtilityDocument.model_validate(payload)


def _rounding_legacy_bill() -> BillExtraction:
    payload = load_sample("synthetic").model_dump(mode="json")
    payload["charges"][0]["billed_amount"]["value"] = "100.005"
    payload["charges"][1]["billed_amount"]["value"] = "50.005"
    return BillExtraction.model_validate(payload)


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


def _round_down(context: Context) -> None:
    context.prec = 4
    context.rounding = ROUND_DOWN


def _round_up(context: Context) -> None:
    context.prec = 4
    context.rounding = ROUND_UP


def _round_floor(context: Context) -> None:
    context.prec = 4
    context.rounding = ROUND_FLOOR


def _tight_exponents(context: Context) -> None:
    context.prec = 4
    context.rounding = ROUND_DOWN
    context.Emax = 1
    context.Emin = -1
    context.clamp = 1


def _trapping_context(context: Context) -> None:
    context.prec = 4
    for signal in (Inexact, Rounded, Subnormal, Underflow, Overflow, Clamped):
        context.traps[signal] = True


PRESENTATION_CONTEXTS: tuple[Callable[[Context], None], ...] = (
    _round_down,
    _round_up,
    _round_floor,
    _tight_exponents,
    _trapping_context,
)


@pytest.mark.parametrize("configure", PRESENTATION_CONTEXTS)
def test_exact_formatters_round_half_up_and_canonicalize_zero(
    configure: Callable[[Context], None],
) -> None:
    with localcontext() as context:
        configure(context)
        context.capitals = 0
        context.clear_flags()
        before = _context_state(context)
        rendered = (
            format_fixed_exact(Decimal("100.005"), Decimal("0.01")),
            format_fixed_exact(Decimal("-0.001"), Decimal("0.01")),
            format_usd_exact(Decimal("-0.001")),
            format_decimal_exact(Decimal("-0.00")),
            format_decimal_exact(Decimal("1e10")),
        )
        after = _context_state(context)

    assert rendered == ("100.01", "0.00", "$0.00", "0.00", "10000000000")
    assert after == before


def _presentation_snapshots(
    legacy: BillExtraction,
    duke: UtilityDocument,
) -> dict[str, dict[str, Any]]:
    return {
        "legacy": audit_bill(legacy).model_dump(mode="json"),
        "adapted_legacy": audit_extraction(legacy).model_dump(mode="json"),
        "duke": audit_extraction(duke).model_dump(mode="json"),
    }


@pytest.mark.parametrize("configure", PRESENTATION_CONTEXTS)
def test_all_decimal_presentations_are_half_up_and_context_invariant(
    configure: Callable[[Context], None],
) -> None:
    legacy = _rounding_legacy_bill()
    duke = _rounding_duke_document()
    baseline = _presentation_snapshots(legacy, duke)

    with localcontext() as context:
        configure(context)
        context.clear_flags()
        before = _context_state(context)
        hostile = _presentation_snapshots(legacy, duke)
        after = _context_state(context)

    assert hostile == baseline
    assert after == before

    legacy_body = baseline["legacy"]["review_request"]["body"]
    adapted_body = baseline["adapted_legacy"]["review_requests"][0]["body"]
    duke_body = baseline["duke"]["review_requests"][0]["body"]
    assert "shows $100.01" in legacy_body
    assert "shows $100.01" in adapted_body
    assert "printed $100.01" in duke_body
    assert "difference $44.04" in duke_body


@pytest.mark.parametrize("configure", PRESENTATION_CONTEXTS)
def test_cli_decimal_presentation_is_half_up_and_preserves_context(
    configure: Callable[[Context], None],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = _rounding_duke_document()
    monkeypatch.setattr("wattproof.cli._load_bundled_sample", lambda _kind: document)

    assert main(["--sample", "duke"]) == 0
    baseline = capsys.readouterr()

    with localcontext() as context:
        configure(context)
        context.clear_flags()
        before = _context_state(context)
        assert main(["--sample", "duke"]) == 0
        hostile = capsys.readouterr()
        after = _context_state(context)

    assert hostile == baseline
    assert after == before
    assert "billed $100.01" in hostile.out
    assert "delta $44.04" in hostile.out
    assert "-0.00" not in hostile.out
