from __future__ import annotations

import json
import subprocess
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from wattproof.app import create_app
from wattproof.audit_service import audit_extraction
from wattproof.cli import main
from wattproof.utility_fixtures import load_utility_sample
from wattproof.utility_models import UtilityAuditResult, UtilityDocument

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_JAVASCRIPT = PROJECT_ROOT / "wattproof" / "static" / "app.js"


def _exercise_javascript_contract(
    extraction: dict[str, Any],
    audit: dict[str, Any],
    *,
    mode: str,
) -> dict[str, Any]:
    harness = r"""
const fs = require("node:fs");
const vm = require("node:vm");

class FakeElement {
  constructor(id) {
    this.id = id;
    this.innerHTML = "";
    this.textContent = "";
    this.value = "";
    this.hidden = false;
    this.disabled = false;
    this.files = [];
    this.dataset = {};
    this.className = "";
    this.src = "";
    this.listeners = {};
    this.attributes = {};
    this.classList = {
      toggle() {},
      add() {},
      remove() {},
    };
  }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  querySelector() { return new FakeElement(`${this.id}-child`); }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) {
    delete this.attributes[name];
    if (name === "src") this.src = "";
  }
  scrollIntoView() {}
  select() {}
  click() {}
}

const elements = new Map();
const element = (id) => {
  if (!elements.has(id)) elements.set(id, new FakeElement(id));
  return elements.get(id);
};
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const context = {
  Blob,
  console,
  elements,
  FormData,
  payload,
  URL: { createObjectURL: () => "blob:test", revokeObjectURL() {} },
  navigator: { clipboard: { writeText: async () => {} } },
  fetch: async () => { throw new Error("Unexpected fetch in renderer contract"); },
  document: {
    createElement: (tag) => element(`created-${tag}`),
    execCommand: () => true,
    getElementById: element,
    querySelector: () => null,
    querySelectorAll: () => [],
  },
  window: {
    location: { reload() {} },
    scrollTo() {},
  },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(payload.appPath, "utf8"), context);

const output = vm.runInContext(`(() => {
  state.extraction = payload.extraction;
  renderReview(payload.mode);
  state.audit = payload.audit;
  state.compactAudit = true;
  renderAudit();

  const corrected = { value: 10, status: "printed" };
  markCorrected(corrected, "11");
  markCorrected(corrected, "12");
  const legacyEvidence = evidenceFor({
    source_page: 4,
    source_text: "Legacy rendered evidence",
    confidence: 0.75,
  });

  return {
    utilityDocument: isUtilityDocument(payload.extraction),
    reviewHtml: byId("service-review-sections").innerHTML,
    verificationHtml: byId("verification-level").innerHTML,
    verificationText: byId("verification-level").textContent,
    servicesHtml: byId("service-results").innerHTML,
    auditHtml: byId("audit-lines").innerHTML,
    comparisonHtml: byId("optional-comparison").innerHTML,
    comparisonHidden: byId("optional-comparison").hidden,
    requestsHtml: byId("provider-review-requests").innerHTML,
    corrected,
    legacyEvidence,
  };
})()` , context);
process.stdout.write(JSON.stringify(output));
"""
    payload = {
        "appPath": str(APP_JAVASCRIPT),
        "extraction": extraction,
        "audit": audit,
        "mode": mode,
    }
    completed = subprocess.run(
        ["node", "-e", harness],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )
    result: dict[str, Any] = json.loads(completed.stdout)
    return result


@pytest.mark.parametrize(
    ("kind", "schema_version"),
    [
        ("authentic", "1.0"),
        ("synthetic", "1.0"),
        ("duke", "2.0"),
        ("centerpoint", "2.0"),
        ("bloomington", "2.0"),
    ],
)
def test_web_exposes_all_deterministic_samples(
    kind: str,
    schema_version: str,
) -> None:
    response = create_app().test_client().get(f"/api/sample/{kind}")

    assert response.status_code == 200
    assert response.get_json()["extraction"]["schema_version"] == schema_version


def test_web_sample_not_found_is_controlled() -> None:
    response = create_app().test_client().get("/api/sample/not-a-sample")

    assert response.status_code == 404
    assert response.is_json
    error = response.get_json()["error"]
    for kind in ("authentic", "synthetic", "duke", "centerpoint", "bloomington"):
        assert kind in error
    assert "Traceback" not in response.get_data(as_text=True)


def test_web_audits_legacy_authentic_payload() -> None:
    client = create_app().test_client()
    extraction_response = client.get("/api/sample/authentic")
    extraction = extraction_response.get_json()["extraction"]

    response = client.post("/api/audit", json=extraction)

    assert extraction_response.status_code == 200
    assert response.status_code == 200
    result = response.get_json()["audit"]
    assert result["fixture_kind"] == "authentic"
    assert result["verification_level"] == "tariff_verified"
    assert result["tariff"] is not None
    assert result["comparison"] is not None


@pytest.mark.parametrize("kind", ["duke", "centerpoint", "bloomington"])
def test_web_audits_provider_neutral_payload_without_tariff_claim(kind: str) -> None:
    client = create_app().test_client()
    extraction = client.get(f"/api/sample/{kind}").get_json()["extraction"]

    response = client.post("/api/audit", json=extraction)

    assert response.status_code == 200
    result = response.get_json()["audit"]
    assert result["verification_level"] == "internally_reconciled"
    assert result["tariff"] is None
    assert result["comparison"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": "9.0", "account_number": "private-account-123"},
        {"account_number": "private-account-123"},
    ],
)
def test_web_rejects_unknown_or_missing_schema_without_echoing_payload(
    payload: dict[str, str],
) -> None:
    response = create_app().test_client().post("/api/audit", json=payload)

    assert response.status_code == 422
    assert response.is_json
    body = response.get_data(as_text=True)
    assert "schema_version" in response.get_json()["error"]
    assert "private-account-123" not in body
    assert "Traceback" not in body


def test_web_rejects_malformed_schema_two_payload_without_sensitive_detail() -> None:
    payload = load_utility_sample("duke").model_dump(mode="json")
    payload["sections"][0]["charges"][0]["amount"]["value"] = (
        "private-account-123"
    )

    response = create_app().test_client().post("/api/audit", json=payload)

    assert response.status_code == 422
    assert response.is_json
    body = response.get_data(as_text=True)
    assert "sections.0.charges.0.amount.value" in response.get_json()["error"]
    assert "private-account-123" not in body
    assert "Traceback" not in body


def test_web_does_not_echo_unknown_charge_reference() -> None:
    payload = load_utility_sample("duke").model_dump(mode="json")
    payload["sections"][1]["charges"][0]["calculation"]["charge_ids"] = [
        "private-account-123"
    ]

    response = create_app().test_client().post("/api/audit", json=payload)

    assert response.status_code == 422
    assert response.is_json
    body = response.get_data(as_text=True)
    assert "unknown charge ID" in response.get_json()["error"]
    assert "private-account-123" not in body
    assert "Traceback" not in body


def test_web_upload_returns_provider_neutral_extraction(
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

    assert response.status_code == 200
    assert response.get_json()["extraction"]["schema_version"] == "2.0"


def test_page_uses_provider_neutral_five_step_language() -> None:
    page = create_app().test_client().get("/").get_data(as_text=True)
    for label in ("Upload", "Review", "Verify", "Household", "Next steps"):
        assert f"<b>{label}</b>" in page
    assert "Choose a utility bill" in page
    assert "Your utility bill has a formula." in page
    assert "PG&amp;E-first" not in page
    assert "Indiana-only" not in page
    for sample_id in ("duke-sample", "centerpoint-sample", "bloomington-sample"):
        assert f'id="{sample_id}"' in page
    assert page.index('id="authentic-sample"') < page.index('id="duke-sample"')
    assert page.index('id="synthetic-sample"') < page.index('id="duke-sample"')


def test_result_markup_exposes_neutral_contract() -> None:
    page = create_app().test_client().get("/").get_data(as_text=True)
    for element_id in (
        "verification-level",
        "service-results",
        "optional-comparison",
        "service-review-sections",
        "provider-review-requests",
        "add-another-bill",
        "finish-household-review",
    ):
        assert f'id="{element_id}"' in page
    assert 'id="optional-comparison"' in page
    assert "hidden" in page[page.index('id="optional-comparison"') :][:160]


def test_javascript_keeps_exact_schema_and_correction_helpers() -> None:
    source = APP_JAVASCRIPT.read_text(encoding="utf-8")
    for helper in (
        '''function isUtilityDocument(extraction) {
  return extraction?.schema_version === "2.0";
}''',
        '''function evidenceFor(fact) {
  return fact.evidence || {
    page: fact.source_page,
    text: fact.source_text,
    confidence: fact.confidence,
  };
}''',
        '''function markCorrected(fact, nextValue) {
  if (fact.status !== "user_corrected") fact.original_value = String(fact.value);
  fact.value = nextValue;
  fact.status = "user_corrected";
}''',
    ):
        assert helper in source


@pytest.mark.parametrize(
    ("kind", "mode", "verification_label", "expected_units"),
    [
        ("authentic", "authentic", "Tariff verified", ("kWh",)),
        ("synthetic", "synthetic", "Tariff verified", ("kWh",)),
        ("duke", "uploaded", "Internally reconciled", ("kWh",)),
        ("centerpoint", "centerpoint", "Internally reconciled", ("therm", "CCF")),
        ("bloomington", "bloomington", "Internally reconciled", ("kgal",)),
    ],
)
def test_javascript_renders_both_schemas_and_unified_results_without_crashing(
    kind: str,
    mode: str,
    verification_label: str,
    expected_units: tuple[str, ...],
) -> None:
    client = create_app().test_client()
    extraction = client.get(f"/api/sample/{kind}").get_json()["extraction"]
    audit = client.post("/api/audit", json=extraction).get_json()["audit"]

    rendered = _exercise_javascript_contract(extraction, audit, mode=mode)

    assert rendered["utilityDocument"] is (extraction["schema_version"] == "2.0")
    assert verification_label in (
        rendered["verificationHtml"] + rendered["verificationText"]
    )
    for unit in expected_units:
        assert unit in rendered["reviewHtml"] + rendered["servicesHtml"]
    assert audit["headline"] in rendered["verificationHtml"] + rendered["servicesHtml"]
    assert rendered["comparisonHidden"] is (audit["comparison"] is None)
    if audit["comparison"] is not None:
        assert audit["comparison"]["headline"] in rendered["comparisonHtml"]
    for request in audit["review_requests"]:
        assert escape(request["provider"]) in rendered["requestsHtml"]
        assert escape(request["subject"]) in rendered["requestsHtml"]
    assert rendered["corrected"] == {
        "value": "12",
        "status": "user_corrected",
        "original_value": "10",
    }
    assert rendered["legacyEvidence"] == {
        "page": 4,
        "text": "Legacy rendered evidence",
        "confidence": 0.75,
    }


def test_schema_two_review_is_grouped_by_service_sections() -> None:
    client = create_app().test_client()
    extraction = client.get("/api/sample/bloomington").get_json()["extraction"]
    audit = client.post("/api/audit", json=extraction).get_json()["audit"]

    rendered = _exercise_javascript_contract(extraction, audit, mode="uploaded")

    review = rendered["reviewHtml"]
    for service in ("Water", "Wastewater", "Stormwater", "Sanitation"):
        assert service in review
    assert "City of Bloomington Utilities" in review
    assert "Page 1" in review
    assert "printed" in review
    assert "inferred" in review


@pytest.mark.parametrize(
    ("kind", "label", "has_comparison"),
    [
        ("authentic", "Tariff verified", True),
        ("synthetic", "Tariff verified", True),
        ("duke", "Internally reconciled", False),
        ("centerpoint", "Internally reconciled", False),
        ("bloomington", "Internally reconciled", False),
    ],
)
def test_cli_exposes_all_samples_with_approved_verification_labels(
    kind: str,
    label: str,
    has_comparison: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--sample", kind]) == 0

    captured = capsys.readouterr()
    assert f"Verification level: {label}" in captured.out
    assert ("Plan comparison:" in captured.out) is has_comparison
    if kind in {"duke", "centerpoint", "bloomington"}:
        assert "tariff verified" not in captured.out.lower()
    assert captured.err == ""


def test_cli_prints_evidence_extracted_label(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = audit_extraction(load_utility_sample("duke")).model_dump(mode="json")
    payload["verification_level"] = "evidence_extracted"
    payload["headline"] = "Evidence extracted for review"
    result = UtilityAuditResult.model_validate(payload)

    def return_result(_extraction: object) -> UtilityAuditResult:
        return result

    monkeypatch.setattr("wattproof.cli.audit_extraction", return_result)

    assert main(["--sample", "duke"]) == 0
    assert "Verification level: Evidence extracted" in capsys.readouterr().out


def test_cli_audits_extracted_provider_neutral_document(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "wattproof.cli.extract_pdf",
        lambda _path: load_utility_sample("duke"),
    )

    assert main(["--file", "duke.pdf"]) == 0
    output = capsys.readouterr()
    assert "Verification level: Internally reconciled" in output.out
    assert "tariff verified" not in output.out.lower()
    assert output.err == ""


def test_cli_returns_nonzero_for_sample_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def invalid_sample(_kind: object) -> UtilityDocument:
        return UtilityDocument.model_validate({"schema_version": "2.0"})

    monkeypatch.setattr("wattproof.cli.load_utility_sample", invalid_sample)

    assert main(["--sample", "duke"]) == 2
    captured = capsys.readouterr()
    assert "WattProof could not audit this document" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""
