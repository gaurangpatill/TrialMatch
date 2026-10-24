from __future__ import annotations

from argparse import Namespace

import pytest

from backend.app.clinical.cli import run_summarize
from backend.app.clinical.database import ClinicalRepository
from backend.app.clinical.summaries import StudySummaryService, SummaryError


class FakeProvider:
    name = "test-provider"
    model = "test-model"

    def __init__(self) -> None:
        self.calls = 0

    async def summarize(self, study):
        self.calls += 1
        return {
            "nct_id": study.nct_id,
            "source_hash": study.source_hash,
            "plain_language_summary": "A source-grounded plain-language purpose summary.",
        }


@pytest.mark.asyncio
async def test_summary_is_explicitly_generated_once_and_read_from_current_cache(
    study_factory, tmp_path
):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    study = study_factory()
    repository.upsert_studies([study])
    provider = FakeProvider()
    service = StudySummaryService(repository, provider)

    first, first_cached = await service.summarize(study)
    second, second_cached = await service.summarize(study)

    assert first == second
    assert first_cached is False
    assert second_cached is True
    assert provider.calls == 1
    assert repository.get_current_summary(study.nct_id, study.source_hash) == (
        "A source-grounded plain-language purpose summary."
    )


@pytest.mark.asyncio
async def test_summary_rejects_mismatched_source_identity_without_publishing(study_factory, tmp_path):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    study = study_factory()
    repository.upsert_studies([study])

    class WrongProvider(FakeProvider):
        async def summarize(self, current):
            return {
                "nct_id": "NCT99999999",
                "source_hash": current.source_hash,
                "plain_language_summary": "Wrong record.",
            }

    with pytest.raises(SummaryError, match="identifiers do not match"):
        await StudySummaryService(repository, WrongProvider()).summarize(study)
    assert repository.get_current_summary(study.nct_id, study.source_hash) is None


@pytest.mark.asyncio
async def test_summary_requires_official_source_description(study_factory, tmp_path):
    repository = ClinicalRepository(tmp_path / "clinical.sqlite3")
    study = study_factory(source_description=None)
    repository.upsert_studies([study])
    provider = FakeProvider()

    with pytest.raises(SummaryError, match="no official source description"):
        await StudySummaryService(repository, provider).summarize(study)
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_summary_cli_refuses_more_than_three_or_duplicate_ids(tmp_path, capsys):
    too_many = Namespace(
        database=str(tmp_path / "unused.sqlite3"),
        nct_ids=["NCT00000001", "NCT00000002", "NCT00000003", "NCT00000004"],
    )
    duplicate = Namespace(
        database=str(tmp_path / "unused.sqlite3"),
        nct_ids=["NCT00000001", "NCT00000001"],
    )

    assert await run_summarize(too_many) == 2
    assert await run_summarize(duplicate) == 2
    output = capsys.readouterr().out
    assert "one to three" in output
    assert "unique" in output
