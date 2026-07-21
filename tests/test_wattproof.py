from __future__ import annotations

import json
import re
import threading
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
    CodexAppServer,
    CodexConnectionStatus,
    CodexNotConnectedError,
    CodexOutputInvalidError,
    CodexSessionManager,
    CodexUnavailableError,
    DeviceLogin,
    strict_bill_schema,
)
from wattproof.extract import (
    MAX_FILE_BYTES,
    MAX_PAGES,
    ExtractionLoginRequiredError,
    InvalidDocumentError,
    RenderedPage,
    UnsupportedDocumentError,
    extract_pdf,
)
from wattproof.fixtures import FIXTURES_DIR, PROJECT_ROOT, load_sample
from wattproof.models import AuditLine, AuditResult, BillExtraction, DateFact, TextFact
from wattproof.tariffs import SourceIntegrityError, load_tariff_bundle
from wattproof.utility_fixtures import load_utility_sample
from wattproof.utility_models import UtilityDocument


def _lines(result: AuditResult) -> dict[str, AuditLine]:
    return {line.id: line for line in result.lines}


class _FakeCodexClient:
    def __init__(self) -> None:
        self.is_connected = False
        self.closed = False
        self.extractions: list[tuple[tuple[int, ...], str, str, int]] = []

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

    def extract_bill(
        self,
        rendered_pages: tuple[RenderedPage, ...],
        native_hint: str,
        document_sha256: str,
        page_count: int,
    ) -> UtilityDocument:
        self.extractions.append(
            (
                tuple(page.page for page in rendered_pages),
                native_hint,
                document_sha256,
                page_count,
            )
        )
        raw = load_utility_sample("duke").model_dump(mode="json")
        raw["fixture_kind"] = "uploaded"
        raw["document_sha256"] = document_sha256
        raw["page_count"] = page_count
        raw["source_url"] = None
        return UtilityDocument.model_validate(raw)

    def close(self) -> None:
        self.closed = True


def test_authentic_extraction_matches_golden_fixture() -> None:
    extracted = extract_pdf(PROJECT_ROOT / "assets/pge-anonymous-3ce-sample-bill.pdf")
    golden = BillExtraction.model_validate(
        json.loads(
            (FIXTURES_DIR / "authentic-extraction.json").read_text(encoding="utf-8"),
            parse_float=Decimal,
        )
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
    assert "sections" in schema["properties"]
    assert "delivery_provider" not in schema["properties"]


def test_codex_visual_extractor_uses_images_and_server_owned_v2_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    server = object.__new__(CodexAppServer)
    setattr(server, "_state", "connected")
    setattr(server, "_lock", threading.RLock())
    setattr(server, "_extract_lock", threading.Lock())
    setattr(server, "_workspace", tmp_path)
    calls: list[tuple[str, dict[str, object], float]] = []

    def fake_call(
        method: str,
        params: dict[str, object],
        *,
        timeout: float,
    ) -> dict[str, object]:
        calls.append((method, params, timeout))
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}}
        return {"turn": {"id": "turn-1"}}

    raw = load_utility_sample("bloomington").model_dump(mode="json")
    raw["fixture_kind"] = "uploaded"
    raw["document_sha256"] = "a" * 64
    raw["source_url"] = "https://untrusted.example/claimed-source"

    monkeypatch.setattr(server, "_call", fake_call)
    monkeypatch.setattr(
        server,
        "_wait_for_turn",
        lambda _turn_id, timeout: ({"status": "completed"}, json.dumps(raw)),
    )
    rendered_pages = (
        RenderedPage(
            page=1,
            data_url="data:image/png;base64,iVBORw0KGgo=",
        ),
    )

    extracted = server.extract_bill(
        rendered_pages,
        "[PAGE 1]\nUNTRUSTED locator text",
        "f" * 64,
        1,
    )

    turn_params = calls[1][1]
    turn_input = turn_params["input"]
    assert isinstance(turn_input, list)
    assert [item["type"] for item in turn_input] == [
        "text",
        "text",
        "image",
        "text",
    ]
    assert turn_input[2]["url"] == rendered_pages[0].data_url
    assert "UNTRUSTED_NATIVE_TEXT_HINT" in turn_input[-1]["text"]
    assert turn_params["outputSchema"] == strict_bill_schema()
    assert extracted.schema_version == "2.0"
    assert extracted.fixture_kind == "uploaded"
    assert extracted.document_sha256 == "f" * 64
    assert extracted.page_count == 1
    assert extracted.source_url is None


def test_codex_visual_extractor_recovers_once_from_invalid_model_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    server = object.__new__(CodexAppServer)
    setattr(server, "_state", "connected")
    setattr(server, "_lock", threading.RLock())
    setattr(server, "_extract_lock", threading.Lock())
    setattr(server, "_workspace", tmp_path)
    calls: list[tuple[str, dict[str, object], float]] = []

    def fake_call(
        method: str,
        params: dict[str, object],
        *,
        timeout: float,
    ) -> dict[str, object]:
        calls.append((method, params, timeout))
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}}
        turn_number = sum(call[0] == "turn/start" for call in calls)
        return {"turn": {"id": f"turn-{turn_number}"}}

    valid = load_utility_sample("bloomington").model_dump(mode="json")
    invalid = json.loads(json.dumps(valid))
    assert invalid["sections"][0]["provider"]["status"] == "printed"
    invalid["sections"][0]["provider"]["original_value"] = "hidden-invalid"
    answers = {
        "turn-1": json.dumps(invalid),
        "turn-2": json.dumps(valid),
    }

    monkeypatch.setattr(server, "_call", fake_call)
    monkeypatch.setattr(
        server,
        "_wait_for_turn",
        lambda turn_id, timeout: ({"status": "completed"}, answers[turn_id]),
    )

    extracted = server.extract_bill(
        (
            RenderedPage(
                page=1,
                data_url="data:image/png;base64,iVBORw0KGgo=",
            ),
        ),
        "[PAGE 1]\nPRIVATE_NATIVE_MARKER",
        "f" * 64,
        1,
    )

    turn_calls = [
        params for method, params, _timeout in calls if method == "turn/start"
    ]
    assert len(turn_calls) == 2
    retry_input = turn_calls[1]["input"]
    assert isinstance(retry_input, list)
    assert "PRIVATE_NATIVE_MARKER" not in json.dumps(retry_input)
    assert extracted.fixture_kind == "uploaded"
    assert extracted.document_sha256 == "f" * 64


def test_codex_visual_extractor_rejects_repeated_invalid_model_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    server = object.__new__(CodexAppServer)
    setattr(server, "_state", "connected")
    setattr(server, "_lock", threading.RLock())
    setattr(server, "_extract_lock", threading.Lock())
    setattr(server, "_workspace", tmp_path)
    calls: list[tuple[str, dict[str, object], float]] = []

    def fake_call(
        method: str,
        params: dict[str, object],
        *,
        timeout: float,
    ) -> dict[str, object]:
        calls.append((method, params, timeout))
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}}
        turn_number = sum(call[0] == "turn/start" for call in calls)
        return {"turn": {"id": f"turn-{turn_number}"}}

    invalid = load_utility_sample("bloomington").model_dump(mode="json")
    assert invalid["sections"][0]["provider"]["status"] == "printed"
    invalid["sections"][0]["provider"]["original_value"] = "hidden-invalid"

    monkeypatch.setattr(server, "_call", fake_call)
    monkeypatch.setattr(
        server,
        "_wait_for_turn",
        lambda _turn_id, timeout: ({"status": "completed"}, json.dumps(invalid)),
    )

    with pytest.raises(CodexOutputInvalidError):
        server.extract_bill(
            (
                RenderedPage(
                    page=1,
                    data_url="data:image/png;base64,iVBORw0KGgo=",
                ),
            ),
            "[PAGE 1]\nPRIVATE_NATIVE_MARKER",
            "f" * 64,
            1,
        )

    assert sum(method == "turn/start" for method, _params, _timeout in calls) == 2


def test_codex_visual_extractor_fails_closed_when_disconnected(tmp_path: Path) -> None:
    server = object.__new__(CodexAppServer)
    setattr(server, "_state", "disconnected")
    setattr(server, "_lock", threading.RLock())
    setattr(server, "_workspace", tmp_path)

    with pytest.raises(CodexNotConnectedError, match="Connect Codex"):
        server.extract_bill((), "native-only", "f" * 64, 1)


def test_unknown_pdf_can_use_a_connected_model_extractor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "unknown.pdf"
    pdf.write_bytes(b"%PDF-unknown-native-bill")
    calls: list[tuple[tuple[int, ...], str, str, int]] = []

    monkeypatch.setattr("wattproof.extract._page_count", lambda _path: 1)
    monkeypatch.setattr(
        "wattproof.extract._render_pages",
        lambda _path, _count: (
            RenderedPage(
                page=1,
                data_url="data:image/png;base64,iVBORw0KGgo=",
            ),
        ),
    )
    monkeypatch.setattr(
        "wattproof.extract._native_text", lambda _path: "[PAGE 1]\nBill evidence"
    )

    def model_extractor(
        rendered_pages: tuple[RenderedPage, ...],
        native_hint: str,
        digest: str,
        page_count: int,
    ) -> UtilityDocument:
        calls.append(
            (
                tuple(page.page for page in rendered_pages),
                native_hint,
                digest,
                page_count,
            )
        )
        return load_utility_sample("duke")

    result = extract_pdf(pdf, model_extractor)

    assert result == load_utility_sample("duke")
    assert calls[0][0] == (1,)
    assert calls[0][1] == "[PAGE 1]\nBill evidence"
    assert re.fullmatch(r"[a-f0-9]{64}", calls[0][2])
    assert calls[0][3] == 1


def test_unknown_pdf_requires_a_connected_codex_session(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "unknown.pdf"
    pdf.write_bytes(b"%PDF-unknown-native-bill")
    with pytest.raises(ExtractionLoginRequiredError, match="Connect Codex"):
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


def test_oversized_pdf_is_rejected_before_read_render_or_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "sparse-too-large.pdf"
    with file.open("wb") as stream:
        stream.write(b"%PDF-")
        stream.truncate(MAX_FILE_BYTES + 1)

    def unexpected_work(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("oversized PDFs must stop at the stat preflight")

    monkeypatch.setattr(Path, "read_bytes", unexpected_work)
    monkeypatch.setattr("wattproof.extract.subprocess.run", unexpected_work)
    for name in ("_page_count", "_render_pages", "_native_text"):
        monkeypatch.setattr(f"wattproof.extract.{name}", unexpected_work)

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
        extract_pdf(file, lambda *_args: load_utility_sample("duke"))


def test_cli_happy_path_and_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--sample", "authentic"]) == 0
    output = capsys.readouterr()
    assert "Reconciled where" in output.out

    assert main(["--file", "missing.pdf"]) == 2
    output = capsys.readouterr()
    assert "does not exist" in output.err


def test_cli_audits_provider_neutral_extraction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "wattproof.cli.extract_pdf",
        lambda _path: load_utility_sample("duke"),
    )

    assert main(["--file", "unknown.pdf"]) == 0
    output = capsys.readouterr()
    assert "Verification level: Internally reconciled" in output.out
    assert "tariff verified" not in output.out.lower()
    assert output.err == ""


def test_cli_labels_multi_root_dependent_discrepancies(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = load_utility_sample("duke")
    electricity = document.sections[0]
    changed = electricity.model_copy(
        update={
            "charges": tuple(
                charge.model_copy(
                    update={
                        "amount": charge.amount.model_copy(
                            update={"value": charge.amount.value + Decimal("1.00")}
                        )
                    }
                )
                if charge.id in {"energy_tier_1", "energy_tier_2"}
                else charge
                for charge in electricity.charges
            )
        }
    )
    changed_document = document.model_copy(
        update={"sections": (changed, *document.sections[1:])}
    )
    monkeypatch.setattr("wattproof.cli.extract_pdf", lambda _path: changed_document)

    assert main(["--file", "multi-root.pdf"]) == 0
    output = capsys.readouterr()

    assert "Possible discrepancy found" in output.out
    assert "Printed energy tier quantities" not in output.out
    assert "derived from roots: charge::energy_tier_1, charge::energy_tier_2" in (
        output.out
    )


def test_web_flow_exposes_all_five_steps() -> None:
    client = create_app().test_client()
    response = client.get("/")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    for label in ("Upload", "Review", "Verify", "Household", "Next steps"):
        assert f"<b>{label}</b>" in page
    for obsolete_label in ("Audit", "Compare", "Act"):
        assert f"<b>{obsolete_label}</b>" not in page
    assert "Codex reads your PDF into reviewable facts" in page
    assert "Public samples work without it" in page
    assert "WattProof recalculates supported charges and totals" in page
    assert "Local sample mode" not in page
    assert 'id="codex-connect"' in page
    assert 'id="codex-dialog"' in page
    assert "logo-mark.png" in page


def test_web_shell_keeps_provider_neutral_accessibility_contract() -> None:
    page = create_app().test_client().get("/").get_data(as_text=True)

    assert 'aria-label="WattProof home"' in page
    assert 'class="brand-logo"' in page
    assert 'alt=""' in page
    assert "favicon.svg" not in page
    assert "header-proof" not in page
    assert '<h2 id="document-placeholder-title">' in page
    assert '<h3 id="document-placeholder-title">' not in page
    assert (
        '<div class="table-scroll" role="region" '
        'aria-label="Line-by-line calculation ledger" tabindex="0">'
    ) in page
    assert 'id="show-all-lines"' in page
    for obsolete_id in ("charge-review", "audit-details", "copy-letter"):
        assert f'id="{obsolete_id}"' not in page
    for title_id in (
        "upload-title",
        "review-title",
        "verify-title",
        "household-title",
        "next-steps-title",
    ):
        assert f'id="{title_id}" tabindex="-1"' in page


def test_web_script_announces_loading_and_provider_copy_feedback() -> None:
    script = (PROJECT_ROOT / "wattproof/static/app.js").read_text(encoding="utf-8")

    assert 'button.setAttribute("aria-busy", "true");' in script
    assert 'button.removeAttribute("aria-busy");' in script
    assert 'data-copy-request="${index}" aria-live="polite"' in script
    assert 'copyButton.textContent = "Copied — review before sending";' in script
    assert 'copyButton.textContent = "Copy request";' in script
    assert '.focus({ preventScroll: true })' in script


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
        visual_extractor: Callable[
            [tuple[RenderedPage, ...], str, str, int], UtilityDocument
        ]
        | None = None,
    ) -> UtilityDocument:
        assert visual_extractor is not None
        pages = tuple(
            RenderedPage(
                page=page,
                data_url="data:image/png;base64,iVBORw0KGgo=",
            )
            for page in range(1, load_utility_sample("duke").page_count + 1)
        )
        return visual_extractor(
            pages,
            "[PAGE 1]\nPrivate bill evidence",
            "f" * 64,
            len(pages),
        )

    monkeypatch.setattr("wattproof.app.extract_pdf", fake_extract_pdf)
    response = client.post(
        "/api/extract",
        data={"bill": (BytesIO(b"%PDF-private"), "private.pdf")},
        content_type="multipart/form-data",
        headers={"X-WattProof-Request": "1"},
    )

    assert response.status_code == 200
    assert response.get_json()["extraction"]["fixture_kind"] == "uploaded"
    assert fake.extractions == [
        (
            tuple(range(1, load_utility_sample("duke").page_count + 1)),
            "[PAGE 1]\nPrivate bill evidence",
            "f" * 64,
            load_utility_sample("duke").page_count,
        )
    ]


def test_unknown_upload_without_connected_codex_returns_login_required() -> None:
    response = create_app().test_client().post(
        "/api/extract",
        data={"bill": (BytesIO(b"%PDF-private"), "private.pdf")},
        content_type="multipart/form-data",
        headers={"X-WattProof-Request": "1"},
    )

    assert response.status_code == 401
    assert response.get_json()["code"] == "codex_login_required"
    assert "Connect Codex" in response.get_json()["error"]


def test_codex_process_failure_returns_controlled_unavailable_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(_path: Path, _visual_extractor: object = None) -> None:
        raise CodexUnavailableError("Codex could not complete this request.")

    monkeypatch.setattr("wattproof.app.extract_pdf", unavailable)
    response = create_app().test_client().post(
        "/api/extract",
        data={"bill": (BytesIO(b"%PDF-private"), "private.pdf")},
        content_type="multipart/form-data",
        headers={"X-WattProof-Request": "1"},
    )

    assert response.status_code == 503
    assert response.get_json() == {
        "code": "codex_unavailable",
        "error": "Codex could not complete this request.",
    }


def test_invalid_codex_output_returns_specific_retriable_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invalid(_path: Path, _visual_extractor: object = None) -> None:
        raise CodexOutputInvalidError("Codex output did not pass safety checks.")

    monkeypatch.setattr("wattproof.app.extract_pdf", invalid)
    response = create_app().test_client().post(
        "/api/extract",
        data={"bill": (BytesIO(b"%PDF-private"), "private.pdf")},
        content_type="multipart/form-data",
        headers={"X-WattProof-Request": "1"},
    )

    assert response.status_code == 503
    assert response.get_json() == {
        "code": "codex_output_invalid",
        "error": "Codex output did not pass safety checks.",
    }


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
    assert result["review_requests"][0]["requires_user_review"] is True


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


def test_web_upload_returns_provider_neutral_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "wattproof.app.extract_pdf",
        lambda _path, _visual_extractor=None: load_utility_sample("duke"),
    )
    response = create_app().test_client().post(
        "/api/extract",
        data={"bill": (BytesIO(b"%PDF-placeholder"), "duke.pdf")},
        content_type="multipart/form-data",
        headers={"X-WattProof-Request": "1"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["extraction"]["schema_version"] == "2.0"
    assert payload["extraction"]["fixture_kind"] == "duke"


def test_web_validation_returns_reviewable_field() -> None:
    client = create_app().test_client()
    extraction = load_sample("authentic").model_dump(mode="json")
    extraction["peak_usage"]["value"] = "900"
    response = client.post("/api/audit", json=extraction)

    assert response.status_code == 422
    assert "peak and off-peak quantities do not equal total usage" in (
        response.get_json()["error"]
    )


def test_web_hides_tariff_source_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_audit(_extraction: BillExtraction) -> AuditResult:
        raise SourceIntegrityError(
            "Missing tariff snapshot: /srv/private/rates.pdf",
            public_message="Missing tariff snapshot for public evidence.",
        )

    monkeypatch.setattr("wattproof.app.audit_extraction", broken_audit)
    extraction = load_sample("authentic").model_dump(mode="json")
    response = create_app().test_client().post("/api/audit", json=extraction)

    assert response.status_code == 503
    assert response.get_json()["error"] == (
        "WattProof could not verify its archived tariff evidence. Please try again later."
    )
