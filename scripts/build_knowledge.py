"""Audit the checked-in wardrobe corpus; it never downloads sources at runtime."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stylemate.rag.corpus import load_builtin_records  # noqa: E402 - direct script execution needs ROOT on sys.path

REQUIRED_TOPICS = {"fabric", "care", "size", "color", "weather", "scenario", "wardrobe", "style", "storage"}
FORBIDDEN_COPIED_PARAGRAPHS = (
    "The Federal Trade Commission (FTC) enforces the Care Labeling Rule",
    "The combination of the five basic care symbols",
    "To get started doing your laundry, follow these steps",
)


def _load_sources(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def audit(records_path: Path, sources_path: Path) -> list[str]:
    errors: list[str] = []
    sources = _load_sources(sources_path)
    source_ids = [source.get("id") for source in sources]
    source_urls = [source.get("url") for source in sources]
    if len(source_ids) != len(set(source_ids)) or any(not value for value in source_ids):
        errors.append("sources.json duplicate or missing source id")
    if len(source_urls) != len(set(source_urls)) or any(not str(value).startswith("https://") for value in source_urls):
        errors.append("sources.json duplicate or non-HTTPS URL")
    source_by_url = {source.get("url"): source for source in sources}
    for source in sources:
        try:
            retrieved_at = date.fromisoformat(str(source.get("retrieved_at", "")))
        except ValueError:
            errors.append(f"{source.get('id')} has an invalid retrieved_at date")
            continue
        if retrieved_at > date.today():
            errors.append(f"{source.get('id')} has a future retrieved_at date")
    try:
        records = load_builtin_records(records_path)
    except (OSError, ValueError) as exc:
        return [str(exc)]
    if not records:
        errors.append("corpus must not be empty")
    ids = [record.id for record in records]
    if len(ids) != len(set(ids)):
        errors.append("records.jsonl has duplicate record ID")
    missing_topics = REQUIRED_TOPICS - {record.topic for record in records}
    if missing_topics:
        errors.append("missing topics: " + ", ".join(sorted(missing_topics)))
    for record in records:
        if record.content_kind == "heuristic":
            if record.source_url is not None:
                errors.append(f"{record.id} project heuristic must not carry an authority citation")
            continue
        source = source_by_url.get(str(record.source_url))
        if source is None:
            errors.append(f"{record.id} uses a URL absent from sources.json")
        else:
            if record.retrieved_at.isoformat() != source.get("retrieved_at"):
                errors.append(f"{record.id} retrieved_at differs from its source")
            if record.source_name != source.get("source_name"):
                errors.append(f"{record.id} source_name differs from its source")
        if len(record.content) < 40:
            errors.append(f"{record.id} summary is shorter than 40 characters")
        if not any("\u4e00" <= char <= "\u9fff" for char in record.content):
            errors.append(f"{record.id} does not contain an original Chinese summary")
        if any(paragraph in record.content for paragraph in FORBIDDEN_COPIED_PARAGRAPHS):
            errors.append(f"{record.id} appears to copy a source paragraph")
        if record.reviewed_at and record.reviewed_at > date.today():
            errors.append(f"{record.id} has a future review date")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate the checked-in corpus")
    parser.add_argument("--report", type=Path, help="write a new structural/provenance report, without live verification")
    args = parser.parse_args()
    errors = audit(ROOT / "data/knowledge/records.jsonl", ROOT / "data/knowledge/sources.json")
    if errors:
        print("knowledge audit FAILED")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    records = load_builtin_records(ROOT / "data/knowledge/records.jsonl")
    if args.report:
        if args.report.exists():
            parser.error("report already exists; use a new path")
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as handle:
            json.dump({
                "scope": "structural_and_recorded_provenance_not_live_source_verification",
                "records": len(records),
                "published_evidence": sum(r.is_published_evidence for r in records),
                "review_status_counts": dict(Counter(r.review_status for r in records)),
                "published_topic_counts": dict(Counter(r.topic for r in records if r.is_published_evidence)),
                "missing_published_topics": sorted(REQUIRED_TOPICS - {r.topic for r in records if r.is_published_evidence}),
                "items": [{"id": r.id, "topic": r.topic, "review_status": r.review_status,
                           "content_kind": r.content_kind, "source_locator": r.source_locator,
                           "review_note": r.review_note} for r in records],
            }, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    if args.check:
        print(
            f"knowledge structure PASS: {len(records)} records, "
            f"{sum(r.is_published_evidence for r in records)} published evidence; "
            "this command does not verify source semantics"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
