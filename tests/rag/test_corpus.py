import json
from datetime import date
from pathlib import Path

from stylemate.rag.corpus import load_builtin_records


def test_builtin_corpus_retains_reviews_and_separates_authority_from_heuristics():
    records = load_builtin_records(Path("data/knowledge/records.jsonl"))
    sources = json.loads(
        Path("data/knowledge/sources.json").read_text(encoding="utf-8")
    )
    source_dates = {
        source["url"]: date.fromisoformat(source["retrieved_at"])
        for source in sources
    }

    assert records
    assert {"fabric", "care", "size", "color", "weather", "scenario", "wardrobe", "style", "storage"} <= {
        record.topic for record in records
    }
    assert all(record.source_url is None for record in records if record.content_kind == "heuristic")
    facts = [record for record in records if record.content_kind == "source_summary"]
    assert all(str(record.source_url).startswith("https://") for record in facts)
    assert all(
        record.retrieved_at == source_dates[str(record.source_url)]
        for record in facts
    )
    assert all(len(record.content) <= 900 for record in records)
    assert all(record.source_locator and record.reviewer for record in records if record.is_published_evidence)
