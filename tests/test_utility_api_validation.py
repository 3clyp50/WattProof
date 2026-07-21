from decimal import Decimal

from wattproof.app import create_app
from wattproof.utility_fixtures import CENTERPOINT_HIDDEN_TEXT_WARNING


def test_centerpoint_sample_api_exposes_rendered_evidence_warning_before_audit() -> None:
    client = create_app().test_client()

    response = client.get("/api/sample/centerpoint")

    assert response.status_code == 200
    extraction = response.get_json()["extraction"]
    assert extraction["warnings"] == [CENTERPOINT_HIDDEN_TEXT_WARNING]
    assert extraction["sections"][0]["usage"]["value"] == "112.277"
    assert extraction["current_charges"]["value"] == "132.19"


def test_audit_api_rejects_duplicate_conversion_ids_without_a_server_error() -> None:
    client = create_app().test_client()
    payload = client.get("/api/sample/centerpoint").get_json()["extraction"]
    conversion = payload["sections"][0]["conversions"][0]
    payload["sections"][0]["conversions"].append(conversion.copy())

    response = client.post("/api/audit", json=payload)

    assert response.status_code == 422
    assert response.is_json
    assert "conversion IDs must be unique" in response.get_json()["error"]
    assert "Traceback" not in response.get_data(as_text=True)


def test_audit_api_rejects_duplicate_supplemental_fact_ids() -> None:
    client = create_app().test_client()
    utility_payload = client.get("/api/sample/duke").get_json()["extraction"]
    section = utility_payload["sections"][0]
    evidence = section["provider"]["evidence"]
    duplicate = {
        "id": "billing_note",
        "fact": {
            "value": "Printed note",
            "status": "printed",
            "evidence": evidence,
            "original_value": None,
        },
    }
    section["supplemental_facts"] = [duplicate, duplicate.copy()]

    response = client.post("/api/audit", json=utility_payload)

    assert response.status_code == 422
    assert "supplemental fact IDs must be unique" in response.get_json()["error"]


def test_schema_one_api_serializes_ordered_multi_root_dependencies() -> None:
    client = create_app().test_client()
    payload = client.get("/api/sample/synthetic").get_json()["extraction"]
    off_peak = next(
        charge for charge in payload["charges"] if charge["id"] == "pge_off_peak_energy"
    )
    off_peak["billed_amount"]["value"] = str(
        Decimal(off_peak["billed_amount"]["value"]) + Decimal("2.00")
    )

    response = client.post("/api/audit", json=payload)
    audit = response.get_json()["audit"]
    lines = {line["id"]: line for line in audit["lines"]}

    assert response.status_code == 200
    assert audit["discrepancy_total"] == "7.00"
    assert lines["delivery_subtotal"]["root_cause_id"] is None
    assert lines["delivery_subtotal"]["root_cause_ids"] == [
        "pge_peak_energy",
        "pge_off_peak_energy",
    ]


def test_schema_two_api_serializes_only_duke_root_tiers_in_review_draft() -> None:
    client = create_app().test_client()
    payload = client.get("/api/sample/duke").get_json()["extraction"]
    charges = payload["sections"][0]["charges"]
    for charge_id in ("energy_tier_1", "energy_tier_2"):
        charge = next(charge for charge in charges if charge["id"] == charge_id)
        charge["amount"]["value"] = str(
            Decimal(charge["amount"]["value"]) + Decimal("1.00")
        )

    response = client.post("/api/audit", json=payload)
    audit = response.get_json()["audit"]
    lines = {line["id"]: line for line in audit["lines"]}
    roots = ["charge::energy_tier_1", "charge::energy_tier_2"]

    assert response.status_code == 200
    assert audit["discrepancy_total"] == "2.00"
    assert lines["charge::state_tax"]["root_cause_ids"] == roots
    assert lines["subtotal::electricity"]["root_cause_ids"] == roots
    assert audit["review_requests"][0]["grounded_audit_line_ids"] == roots
