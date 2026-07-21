from wattproof.app import create_app


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
