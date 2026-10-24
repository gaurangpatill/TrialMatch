from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.clinical.database import ClinicalRepository
from backend.app.clinical.dependencies import get_repository
from backend.app.clinical.normalize import source_structured_criteria
from backend.app.main import app


def client_with_repository(repository):
    app.dependency_overrides[get_repository] = lambda: repository
    return TestClient(app)


def test_trial_search_contract(study_factory, tmp_path):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    study = study_factory(conditions=["Cancer"])
    repository.upsert_studies([study])
    with client_with_repository(repository) as client:
        response = client.get("/api/trials", params={"query": "cancer", "page_size": 10})
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["nct_id"] == study.nct_id
    assert body["pagination"] == {"page": 1, "page_size": 10, "total_items": 1, "total_pages": 1}
    assert body["data_freshness"]["source"] == "ClinicalTrials.gov"


def test_empty_trial_search_contract(study_factory, tmp_path):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    repository.upsert_studies([study_factory()])
    with client_with_repository(repository) as client:
        response = client.get("/api/trials", params={"query": "does-not-exist"})
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["pagination"]["total_items"] == 0
    assert response.json()["items"] == []


def test_match_contract_and_evidence(study_factory, tmp_path):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    study = study_factory()
    repository.upsert_studies([study])
    repository.replace_criteria(
        study.nct_id, "source_structured", source_structured_criteria(study)
    )
    payload = {
        "patient": {
            "profile_id": "synthetic-api",
            "synthetic": True,
            "age_years": 40,
            "conditions": [],
            "medications": [],
            "procedures": [],
            "laboratory_values": {},
            "attributes": {},
        },
        "trial_ids": [study.nct_id],
        "limit": 20,
    }
    with client_with_repository(repository) as client:
        response = client.post("/api/match", json=payload)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["nct_id"] == study.nct_id
    assert result["screening_status"] == "potential_match"
    criterion_texts = {item["original_text"] for item in result["criteria"]}
    assert "Minimum Age: 18 Years" in criterion_texts
    assert "Maximum Age: 65 Years" in criterion_texts
    assert result["source_url"] == study.source_url


def test_non_synthetic_profile_is_rejected_with_contract_error(tmp_path):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    payload = {
        "patient": {"profile_id": "real-profile", "synthetic": False},
        "limit": 20,
    }
    with client_with_repository(repository) as client:
        response = client.post("/api/match", json=payload)
    app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SYNTHETIC_PROFILE_REQUIRED"
    assert response.json()["error"]["retryable"] is False


def test_validation_error_uses_shared_envelope(tmp_path):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    with client_with_repository(repository) as client:
        response = client.get("/api/trials", params={"page_size": 101})
    app.dependency_overrides.clear()

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "VALIDATION_ERROR"
    assert body["details"][0]["field"] == "page_size"
    assert body["request_id"]
