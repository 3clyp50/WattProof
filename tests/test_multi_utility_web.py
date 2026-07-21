from __future__ import annotations

from io import BytesIO

import pytest

from wattproof.app import create_app
from wattproof.audit_service import audit_extraction
from wattproof.cli import main
from wattproof.utility_fixtures import load_utility_sample
from wattproof.utility_models import UtilityAuditResult, UtilityDocument


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
