def test_strangler_contract_exposes_migration_ready_metadata(client):
    response = client.get("/internal/v1/strangler/contract")

    assert response.status_code == 200
    data = response.get_json()
    assert data["service"] == "service-extractor-notebookum"
    assert data["status"] == "ready"
    assert data["pattern"] == "strangler"
    assert data["contract_version"] == "v1"
    assert data["fallback_owner"] == "notebookum-monolith"
    assert data["recommended_client_id"] == "notebookum-monolith"
    assert data["error_content_type"] == "application/problem+json"


def test_strangler_contract_lists_required_extraction_endpoints(client):
    response = client.get("/internal/v1/strangler/contract")

    assert response.status_code == 200
    endpoints = response.get_json()["endpoints"]
    assert endpoints["create_extraction"]["method"] == "POST"
    assert endpoints["create_extraction"]["path"] == "/internal/v1/extractions"
    assert endpoints["create_extraction"]["success_status"] == 202
    assert endpoints["get_status"]["path"] == "/internal/v1/extractions/{job_id}"
    assert endpoints["get_result"]["path"] == "/internal/v1/extractions/{job_id}/result"


def test_strangler_contract_includes_limits_and_headers(client):
    response = client.get("/internal/v1/strangler/contract")

    assert response.status_code == 200
    data = response.get_json()
    assert "X-Correlation-ID" in data["required_headers"]
    assert "X-Client-ID" in data["required_headers"]
    assert data["job_statuses"] == ["accepted", "processing", "completed", "failed"]
    assert data["limits"]["max_upload_size"] == 26214400
    assert data["limits"]["rate_limit_requests"] == 60
