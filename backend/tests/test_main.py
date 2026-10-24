from fastapi.testclient import TestClient

from backend.app.main import app


def test_health_is_process_liveness_not_data_readiness() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "trialmatch-api",
        "version": "0.1.0",
    }


def test_cors_allows_local_frontend_and_rejects_unlisted_origins() -> None:
    headers = {
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "GET",
    }
    with TestClient(app) as client:
        allowed = client.options("/api/health", headers=headers)
        rejected = client.options(
            "/api/health",
            headers={**headers, "Origin": "https://untrusted.example"},
        )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers
