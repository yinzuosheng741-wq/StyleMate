"""CI/deployment health check with a machine-readable JSON result."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def run(root: Path) -> dict[str, object]:
    checks = {
        "knowledge_records": (root / "data" / "knowledge" / "records.jsonl").is_file(),
        "demo_manifest": (root / "assets" / "demo" / "wardrobe.json").is_file(),
        "evaluation_artifact": (root / "artifacts" / "agent_evaluation.json").is_file(),
    }
    return {"ok": all(checks.values()), "checks": checks}


if __name__ == "__main__":
    payload = run(Path(__file__).resolve().parents[1])
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.exit(0 if payload["ok"] else 1)
