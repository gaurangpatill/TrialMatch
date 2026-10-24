"""Finite Clinical Intelligence maintenance commands."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .client import ClinicalTrialsClient
from .database import ClinicalRepository
from .extraction import EligibilityExtractor, ExtractionError, provider_from_environment
from .ingestion import ClinicalIngestionService, update_manifest, write_report


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="TrialMatch Clinical Intelligence commands")
    commands = root.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="ingest recruiting Massachusetts trials")
    ingest.add_argument("--database", default="backend/data/trialmatch.sqlite3")
    ingest.add_argument("--cache-dir", default="backend/data/cache/clinicaltrials")
    ingest.add_argument("--page-size", type=int, default=1000)
    ingest.add_argument("--detail-limit", type=int, default=20)
    ingest.add_argument("--detail-id", action="append", dest="detail_ids")
    ingest.add_argument(
        "--report", default="backend/data/cache/clinicaltrials/latest_ingestion_report.json"
    )
    ingest.add_argument("--update-manifest", default=None)

    extract = commands.add_parser("extract", help="extract criteria for detailed cached studies")
    extract.add_argument("--database", default="backend/data/trialmatch.sqlite3")
    extract.add_argument("--limit", type=int, default=20)
    return root


async def run_ingest(args: argparse.Namespace) -> int:
    repository = ClinicalRepository(args.database)
    async with ClinicalTrialsClient(cache_dir=args.cache_dir) as client:
        report = await ClinicalIngestionService(client, repository).ingest(
            page_size=args.page_size,
            detail_limit=args.detail_limit,
            detail_ids=args.detail_ids,
        )
    write_report(report, args.report)
    if args.update_manifest:
        update_manifest(report, args.update_manifest)
    print(report.model_dump_json(indent=2))
    return 0 if report.status.value == "complete" else 1


async def run_extract(args: argparse.Namespace) -> int:
    repository = ClinicalRepository(args.database)
    provider = provider_from_environment()
    extractor = EligibilityExtractor(repository, provider)
    studies = [study for study in repository.get_studies(limit=10000) if study.eligibility_criteria][
        : args.limit
    ]
    results: list[dict[str, object]] = []
    failed = False
    for study in studies:
        try:
            criteria, from_cache = await extractor.extract(study)
            results.append(
                {
                    "nct_id": study.nct_id,
                    "criteria": len(criteria),
                    "from_cache": from_cache,
                    "provider": provider.name,
                    "model": provider.model,
                }
            )
        except ExtractionError as exc:
            failed = True
            results.append({"nct_id": study.nct_id, "error": str(exc)})
    print(json.dumps({"studies": results}, indent=2))
    return 1 if failed else 0


async def async_main() -> int:
    args = parser().parse_args()
    if args.command == "ingest":
        return await run_ingest(args)
    if args.command == "extract":
        return await run_extract(args)
    raise AssertionError(f"unhandled command {args.command}")


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
