from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from pydantic import ValidationError

from wattproof.app import create_app
from wattproof.audit import UnsupportedBillError, audit_bill, round_money
from wattproof.cli import main
from wattproof.extract import (
    MAX_FILE_BYTES,
    MAX_PAGES,
    InvalidDocumentError,
    UnsupportedDocumentError,
    extract_pdf,
)
from wattproof.fixtures import FIXTURES_DIR, PROJECT_ROOT, load_sample
from wattproof.models import AuditLine, AuditResult, BillExtraction, DateFact, TextFact
from wattproof.tariffs import load_tariff_bundle
from wattproof.utility_fixtures import load_utility_sample


def _lines(result: AuditResult) -> dict[str, AuditLine]:
    return {line.id: line for line in result.lines}


def test_authentic_extraction_matches_golden_fixture() -> None:
    extracted = extract_pdf(PROJECT_ROOT / "assets/pge-anonymous-3ce-sample-bill.pdf")
    golden = BillExtraction.model_validate_json(
        (FIXTURES_DIR / "authentic-extraction.json").read_text(encoding="utf-8")
    )
    assert extracted == golden
    assert extracted.total_usage.value == Decimal("327.119")
    assert extracted.peak_usage.value + extracted.off_peak_usage.value == Decimal(
        "327.119"
    )


def test_authentic_audit_matches_hand_checked_fixture() -> None:
    expected = json.loads(
        (FIXTURES_DIR / "expected-authentic-audit.json").read_text(encoding="utf-8")
    )
    result = audit_bill(load_sample("authentic"))
    lines = _lines(result)

    assert result.verdict == expected["verdict"]
    assert result.discrepancy_total == Decimal(expected["discrepancy_total"])
    for line_id, amount in expected["verified_expected_amounts"].items():
        assert lines[line_id].status == "verified"
        assert lines[line_id].expected_amount == Decimal(amount)
    for line_id in expected["cannot_verify"]:
        assert lines[line_id].status == "cannot_verify"
        assert lines[line_id].expected_amount is None
    assert result.comparison.status == expected["comparison_status"]


def test_synthetic_fixture_catches_exact_five_dollar_error() -> None:
    bill = load_sample("synthetic")
    result = audit_bill(bill)
    lines = _lines(result)

    assert bill.synthetic_notice is not None
    assert "did not appear on a real customer bill" in bill.synthetic_notice
    assert result.verdict == "possible_discrepancy"
    assert result.discrepancy_total == Decimal("5.00")
    assert lines["pge_peak_energy"].expected_amount == Decimal("36.44")
    assert lines["pge_peak_energy"].billed_amount == Decimal("41.44")
    assert lines["pge_peak_energy"].delta == Decimal("5.00")
    assert lines["delivery_subtotal"].delta == Decimal("-5.00")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.004", "1.00"),
        ("1.005", "1.01"),
        ("-1.005", "-1.01"),
    ],
)
def test_decimal_half_up_rounding(raw: str, expected: str) -> None:
    assert round_money(Decimal(raw)) == Decimal(expected)


def test_schema_rejects_impossible_usage_total() -> None:
    raw = load_sample("authentic").model_dump(mode="json")
    raw["total_usage"]["value"] = "999.000"
    with pytest.raises(ValidationError, match="do not equal total usage"):
        BillExtraction.model_validate(raw)


def test_schema_rejects_duplicate_charge_ids() -> None:
    raw = load_sample("authentic").model_dump(mode="json")
    raw["charges"][1]["id"] = raw["charges"][0]["id"]
    with pytest.raises(ValidationError, match="charge line IDs must be unique"):
        BillExtraction.model_validate(raw)


def test_source_snapshots_match_recorded_hashes() -> None:
    bundle = load_tariff_bundle(verify_sources=True)
    assert bundle.version.id == "pge_3ce_e_tou_c_2022_h2"
    assert {citation.local_path for citation in bundle.version.citations} == {
        "sources/pge-residential-inclu-tou-2022-06-01-to-2022-11-30.xlsx",
        "sources/pge-residential-inclu-tou-2022-12-01-to-2022-12-31.xlsx",
        "sources/pge-residential-baseline-2022-06-01-present.xlsx",
        "sources/3ce-residential-rate-sheet-effective-2022-03-01.pdf",
    }


def test_plan_comparison_refuses_to_invent_savings() -> None:
    comparison = audit_bill(load_sample("authentic")).comparison
    assert comparison.status == "cannot_verify"
    assert "interval" in comparison.headline.lower()
    assert "hourly or 15-minute" in comparison.required_data[0]


def test_unsupported_provider_returns_useful_limitation() -> None:
    bill = load_sample("authentic")
    other_provider = TextFact(
        value="Unsupported Utility",
        source_page=3,
        source_text="Unsupported Utility",
        confidence=1,
        status="printed",
    )
    unsupported = bill.model_copy(update={"delivery_provider": other_provider})
    with pytest.raises(UnsupportedBillError, match="PG&E residential"):
        audit_bill(unsupported)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("generation_provider", "Other CCA", "Central Coast Community Energy"),
        ("generation_schedule", "Other schedule", "MBRETCH1 3Cchoice"),
    ],
)
def test_unsupported_generation_contract_is_rejected(
    field: str, value: str, message: str
) -> None:
    bill = load_sample("authentic")
    original = getattr(bill, field)
    changed = TextFact(
        value=value,
        source_page=original.source_page,
        source_text=original.source_text,
        confidence=original.confidence,
        status=original.status,
    )
    unsupported = bill.model_copy(update={field: changed})
    with pytest.raises(UnsupportedBillError, match=message):
        audit_bill(unsupported)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("service_start", date(2022, 5, 31)),
        ("service_end", date(2023, 1, 1)),
    ],
)
def test_tariff_effective_period_boundaries(field: str, value: date) -> None:
    bill = load_sample("authentic")
    original = getattr(bill, field)
    changed = DateFact(
        value=value,
        source_page=original.source_page,
        source_text=original.source_text,
        confidence=original.confidence,
        status=original.status,
    )
    outside_period = bill.model_copy(update={field: changed})
    with pytest.raises(UnsupportedBillError, match="outside the archived"):
        audit_bill(outside_period)


def test_review_request_claims_are_grounded() -> None:
    result = audit_bill(load_sample("synthetic"))
    lines = _lines(result)
    grounded = result.review_request.grounded_audit_line_ids

    assert grounded == ("pge_peak_energy",)
    assert set(grounded) <= set(lines)
    supported_amounts = {
        f"{abs(value):.2f}"
        for line_id in grounded
        for value in (
            lines[line_id].billed_amount,
            lines[line_id].expected_amount,
            lines[line_id].delta,
        )
        if value is not None
    }
    supported_amounts.update(
        value
        for line_id in grounded
        for key, value in lines[line_id].inputs.items()
        if "usd" in key
    )
    letter_amounts = set(re.findall(r"\$(\d+(?:\.\d+)?)", result.review_request.body))
    assert letter_amounts <= supported_amounts
    assert result.review_request.requires_user_review is True


def test_authentic_review_request_grounds_agreement_and_limitations() -> None:
    result = audit_bill(load_sample("authentic"))
    grounded = set(result.review_request.grounded_audit_line_ids)
    line_ids = {line.id for line in result.lines}

    assert {
        "pge_peak_energy",
        "pge_off_peak_energy",
        "pge_baseline_credit",
        "pge_generation_credit",
        "pge_pcia",
    } <= grounded
    assert grounded <= line_ids
    assert "insufficient to independently verify" in result.review_request.body


def test_known_non_bill_is_rejected() -> None:
    with pytest.raises(UnsupportedDocumentError, match="layout explainer"):
        extract_pdf(PROJECT_ROOT / "assets/pge-sample-consolidated-bill.pdf")


def test_non_pdf_is_rejected(tmp_path: Path) -> None:
    file = tmp_path / "not-a-bill.pdf"
    file.write_text("not a PDF", encoding="utf-8")
    with pytest.raises(InvalidDocumentError, match="Only PDF"):
        extract_pdf(file)


def test_oversized_pdf_is_rejected_before_processing(tmp_path: Path) -> None:
    file = tmp_path / "too-large.pdf"
    file.write_bytes(b"%PDF-" + b"x" * MAX_FILE_BYTES)
    with pytest.raises(InvalidDocumentError, match="10 MB"):
        extract_pdf(file)


def test_excess_page_count_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "too-many-pages.pdf"
    file.write_bytes(b"%PDF-placeholder")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def page_count(_path: Path) -> int:
        return MAX_PAGES + 1

    monkeypatch.setattr("wattproof.extract._page_count", page_count)
    with pytest.raises(InvalidDocumentError, match="20 pages"):
        extract_pdf(file)


def test_cli_happy_path_and_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--sample", "authentic"]) == 0
    output = capsys.readouterr()
    assert "Reconciled where" in output.out

    assert main(["--file", "missing.pdf"]) == 2
    output = capsys.readouterr()
    assert "does not exist" in output.err


def test_cli_reports_temporary_provider_neutral_routing_boundary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "wattproof.cli.extract_pdf",
        lambda _path: load_utility_sample("duke"),
    )

    assert main(["--file", "unknown.pdf"]) == 2
    output = capsys.readouterr()
    assert "provider-neutral CLI audit routing is not available yet" in output.err
    assert "AttributeError" not in output.err


def test_web_flow_exposes_all_five_steps() -> None:
    client = create_app().test_client()
    response = client.get("/")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    for label in ("Upload", "Review", "Audit", "Compare", "Act"):
        assert f"<b>{label}</b>" in page
    assert "GPT-5.6 may read" in page
    assert "Decimal arithmetic handles money" in page


def test_health_check() -> None:
    response = create_app().test_client().get("/healthz")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_web_sample_review_to_audit_api() -> None:
    client = create_app().test_client()
    extraction_response = client.get("/api/sample/authentic")
    extraction = extraction_response.get_json()["extraction"]
    audit_response = client.post("/api/audit", json=extraction)
    result = audit_response.get_json()["audit"]

    assert extraction_response.status_code == 200
    assert audit_response.status_code == 200
    assert result["verdict"] == "reconciled"
    assert result["comparison"]["status"] == "cannot_verify"
    assert result["review_request"]["requires_user_review"] is True


def test_web_upload_uses_known_public_fixture_without_api_key() -> None:
    client = create_app().test_client()
    data = (PROJECT_ROOT / "assets/pge-anonymous-3ce-sample-bill.pdf").read_bytes()
    response = client.post(
        "/api/extract",
        data={"bill": (BytesIO(data), "public-sample.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.get_json()["extraction"]["delivery_schedule"]["value"] == "E-TOU-C"


def test_web_upload_reports_temporary_provider_neutral_routing_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "wattproof.app.extract_pdf",
        lambda _path: load_utility_sample("duke"),
    )
    response = create_app().test_client().post(
        "/api/extract",
        data={"bill": (BytesIO(b"%PDF-placeholder"), "duke.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 422
    payload = response.get_json()
    assert "provider-neutral CLI audit routing is not available yet" in payload["error"]
    assert "extraction" not in payload


def test_web_validation_returns_reviewable_field() -> None:
    client = create_app().test_client()
    extraction = load_sample("authentic").model_dump(mode="json")
    extraction["peak_usage"]["value"] = "900"
    response = client.post("/api/audit", json=extraction)

    assert response.status_code == 422
    assert "peak and off-peak quantities" in response.get_json()["error"]
