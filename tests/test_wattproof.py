from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from pydantic import ValidationError

from wattproof.app import create_app
from wattproof.audit import UnsupportedBillError, audit_bill, round_money
from wattproof.cli import main
from wattproof.codex import (
    CodexConnectionStatus,
    CodexSessionManager,
    DeviceLogin,
    strict_bill_schema,
)
from wattproof.extract import (
    MAX_FILE_BYTES,
    MAX_PAGES,
    ExtractionUnavailableError,
    InvalidDocumentError,
    UnsupportedDocumentError,
    extract_pdf,
)
from wattproof.fixtures import FIXTURES_DIR, PROJECT_ROOT, load_sample
from wattproof.models import AuditLine, AuditResult, BillExtraction, DateFact, TextFact
from wattproof.tariffs import SourceIntegrityError, load_tariff_bundle


def _lines(result: AuditResult) -> dict[str, AuditLine]:
    return {line.id: line for line in result.lines}


class _FakeCodexClient:
    def __init__(self) -> None:
        self.is_connected = False
        self.closed = False
        self.extractions: list[tuple[str, str]] = []

    @property
    def connected(self) -> bool:
        return self.is_connected

    def start_login(self) -> DeviceLogin:
        return DeviceLogin(
            verification_url="https://auth.openai.com/codex/device",
            user_code="ABCD-1234",
        )

    def status(self) -> CodexConnectionStatus:
        if self.is_connected:
            return CodexConnectionStatus("connected", "plus")
        return CodexConnectionStatus("pending")

    def extract_bill(self, text: str, document_sha256: str) -> BillExtraction:
        self.extractions.append((text, document_sha256))
        raw = load_sample("authentic").model_dump(mode="json")
        raw["fixture_kind"] = "uploaded"
        raw["document_sha256"] = document_sha256
        return BillExtraction.model_validate(raw)

    def close(self) -> None:
        self.closed = True


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


def test_codex_output_schema_is_strict_and_uses_supported_regex() -> None:
    schema = strict_bill_schema()

    def assert_strict(node: object) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                assert node["additionalProperties"] is False
                assert node["required"] == list(properties)
            pattern = node.get("pattern")
            if isinstance(pattern, str):
                assert "(?" not in pattern
            assert "default" not in node
            for value in node.values():
                assert_strict(value)
        elif isinstance(node, list):
            for value in node:
                assert_strict(value)

    assert_strict(schema)


def test_unknown_pdf_can_use_a_connected_model_extractor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "unknown.pdf"
    pdf.write_bytes(b"%PDF-unknown-native-bill")
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr("wattproof.extract._page_count", lambda _path: 1)
    monkeypatch.setattr(
        "wattproof.extract._native_text", lambda _path: "[PAGE 1]\nBill evidence"
    )

    def model_extractor(text: str, digest: str) -> BillExtraction:
        calls.append((text, digest))
        return load_sample("authentic")

    result = extract_pdf(pdf, model_extractor)

    assert result == load_sample("authentic")
    assert calls[0][0] == "[PAGE 1]\nBill evidence"
    assert re.fullmatch(r"[a-f0-9]{64}", calls[0][1])


def test_unknown_pdf_requires_a_connected_codex_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "unknown.pdf"
    pdf.write_bytes(b"%PDF-unknown-native-bill")
    monkeypatch.setattr("wattproof.extract._page_count", lambda _path: 1)
    monkeypatch.setattr(
        "wattproof.extract._native_text", lambda _path: "[PAGE 1]\nBill evidence"
    )

    with pytest.raises(ExtractionUnavailableError, match="Connect Codex"):
        extract_pdf(pdf)


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


def test_reconciliation_only_mismatch_is_review_not_a_zero_dollar_claim() -> None:
    raw = load_sample("authentic").model_dump(mode="json")
    raw["amount_due"]["value"] = "97.24"

    result = audit_bill(BillExtraction.model_validate(raw))

    assert result.verdict == "needs_review"
    assert result.discrepancy_total == Decimal("0.00")
    assert result.headline == "Printed bill totals need review"
    assert result.review_request.grounded_audit_line_ids == ("amount_due",)
    assert "$97.24" in result.review_request.body
    assert "$96.24" in result.review_request.body
    assert "$1.00" in result.review_request.body


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


def test_web_flow_exposes_all_five_steps() -> None:
    client = create_app().test_client()
    response = client.get("/")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    for label in ("Upload", "Review", "Audit", "Compare", "Act"):
        assert f"<b>{label}</b>" in page
    assert "GPT-5.6 may read" in page
    assert "Decimal arithmetic handles money" in page
    assert "Local sample mode" not in page
    assert 'id="global-message-text"' in page
    assert 'class="message-mark" aria-hidden="true"' in page
    assert 'id="charge-review"' in page
    assert 'id="audit-details"' in page
    assert 'id="show-all-lines"' not in page
    assert "logo-mark.png" in page
    assert '<h2 id="comparison-headline"></h2>' not in page
    assert "Interval usage is required." in page


def test_health_check() -> None:
    response = create_app().test_client().get("/healthz")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_codex_device_login_status_and_logout_contract() -> None:
    created: list[_FakeCodexClient] = []

    def factory() -> _FakeCodexClient:
        client = _FakeCodexClient()
        created.append(client)
        return client

    manager = CodexSessionManager(client_factory=factory)
    client = create_app(manager).test_client()

    rejected = client.post("/api/codex/login")
    login = client.post(
        "/api/codex/login", headers={"X-WattProof-Request": "1"}
    )
    pending = client.get("/api/codex/status")
    created[0].is_connected = True
    connected = client.get("/api/codex/status")
    logout = client.post(
        "/api/codex/logout", headers={"X-WattProof-Request": "1"}
    )

    assert rejected.status_code == 403
    assert login.status_code == 200
    assert login.get_json() == {
        "model": "GPT-5.6 Luna",
        "state": "pending",
        "user_code": "ABCD-1234",
        "verification_url": "https://auth.openai.com/codex/device",
    }
    assert pending.get_json()["state"] == "pending"
    assert connected.get_json()["state"] == "connected"
    assert connected.get_json()["plan_type"] == "plus"
    assert logout.get_json() == {"state": "disconnected"}
    assert created[0].closed is True


def test_pending_codex_login_expires_and_destroys_its_client() -> None:
    fake = _FakeCodexClient()
    now = [0.0]
    manager = CodexSessionManager(
        client_factory=lambda: fake,
        clock=lambda: now[0],
    )

    manager.start_login("pending-session")
    now[0] = 601.0
    status = manager.status("pending-session")

    assert status.state == "disconnected"
    assert fake.closed is True


def test_connected_codex_session_extracts_an_unknown_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeCodexClient()
    manager = CodexSessionManager(client_factory=lambda: fake)
    client = create_app(manager).test_client()
    client.post("/api/codex/login", headers={"X-WattProof-Request": "1"})
    fake.is_connected = True

    def fake_extract_pdf(
        _path: Path,
        model_extractor: Callable[[str, str], BillExtraction] | None = None,
    ) -> BillExtraction:
        assert model_extractor is not None
        return model_extractor("[PAGE 1]\nPrivate bill evidence", "f" * 64)

    monkeypatch.setattr("wattproof.app.extract_pdf", fake_extract_pdf)
    response = client.post(
        "/api/extract",
        data={"bill": (BytesIO(b"%PDF-private"), "private.pdf")},
        content_type="multipart/form-data",
        headers={"X-WattProof-Request": "1"},
    )

    assert response.status_code == 200
    assert response.get_json()["extraction"]["fixture_kind"] == "uploaded"
    assert fake.extractions == [("[PAGE 1]\nPrivate bill evidence", "f" * 64)]


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


def test_web_upload_uses_known_public_fixture_without_sign_in() -> None:
    client = create_app().test_client()
    data = (PROJECT_ROOT / "assets/pge-anonymous-3ce-sample-bill.pdf").read_bytes()
    rejected = client.post(
        "/api/extract",
        data={"bill": (BytesIO(data), "public-sample.pdf")},
        content_type="multipart/form-data",
    )
    response = client.post(
        "/api/extract",
        data={"bill": (BytesIO(data), "public-sample.pdf")},
        content_type="multipart/form-data",
        headers={"X-WattProof-Request": "1"},
    )

    assert rejected.status_code == 403
    assert response.status_code == 200
    assert response.get_json()["extraction"]["delivery_schedule"]["value"] == "E-TOU-C"


def test_web_validation_returns_reviewable_field() -> None:
    client = create_app().test_client()
    extraction = load_sample("authentic").model_dump(mode="json")
    extraction["peak_usage"]["value"] = "900"
    response = client.post("/api/audit", json=extraction)

    assert response.status_code == 422
    assert response.get_json()["error"] == (
        "Review: peak and off-peak quantities do not equal total usage"
    )


def test_web_hides_tariff_source_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_audit(_extraction: BillExtraction) -> AuditResult:
        raise SourceIntegrityError("Missing tariff snapshot: /srv/private/rates.pdf")

    monkeypatch.setattr("wattproof.app.audit_bill", broken_audit)
    extraction = load_sample("authentic").model_dump(mode="json")
    response = create_app().test_client().post("/api/audit", json=extraction)

    assert response.status_code == 503
    assert response.get_json()["error"] == (
        "WattProof could not verify its archived tariff evidence. Please try again later."
    )
