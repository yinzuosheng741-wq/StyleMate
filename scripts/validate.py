"""One local/CI command with bounded steps and revision-bound validation artifacts."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source_fingerprint():
    digest = hashlib.sha256()
    paths = set()
    for folder in ("stylemate", "evaluation", "scripts", "tests"):
        paths.update((ROOT / folder).rglob("*.py"))
    paths.update(ROOT.glob("requirements*.txt"))
    paths.update((ROOT / "stylemate/prompts").rglob("*.txt"))
    paths.update((ROOT / ".github/workflows").glob("*.yml"))
    paths.update(ROOT / name for name in (".github/dependabot.yml",))
    paths.update(ROOT / name for name in ("desktop.py", "pyproject.toml"))
    for path in sorted(paths):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_text("utf-8").encode())
        digest.update(b"\0")
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts/validation")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    fingerprint = source_fingerprint()
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True))
    except (OSError, subprocess.CalledProcessError):
        revision, dirty = "unavailable", None
    environment = dict(os.environ, PYTHONUTF8="1", QT_QPA_PLATFORM="offscreen", COVERAGE_FILE=str(output / ".coverage"))
    # Do not inherit paid-service credentials into repeatable validation runs.
    for key in list(environment):
        if key.endswith("API_KEY") or key in {"DASHSCOPE_API_KEY", "OPENAI_API_KEY"}:
            environment[key] = ""
    report = {"schema_version": 1, "revision": revision, "dirty": dirty, "source_fingerprint": fingerprint,
              "started_at": datetime.now(timezone.utc).isoformat(), "steps": [], "passed": False}
    # Keep temporary image paths below Windows' legacy path limit (owner hashes
    # and UUID filenames already take significant space).
    with tempfile.TemporaryDirectory(prefix=".pytest-tmp-v-", dir=ROOT) as temporary:
        environment.update(TEMP=temporary, TMP=temporary)
        checks = [
            ("dependencies", ["-m", "pip", "check"]),
            ("constraints", ["scripts/lock_runtime.py", "--common"]),
            ("health", ["scripts/healthcheck.py"]),
            ("assets", ["scripts/audit_demo_sources.py"]),
            ("docs", ["scripts/check_docs.py"]),
            ("lint", ["-m", "ruff", "check", "."]),
            ("compile", ["-m", "compileall", "-q", "stylemate", "evaluation", "scripts", "desktop.py"]),
            ("tests", ["-m", "pytest", "-q", "--junitxml=" + str(output / "junit.xml"),
                       "--cov=stylemate.agent", "--cov-report=json:" + str(output / "coverage.json"),
                       "--cov-report=term-missing",
                       "--basetemp=" + str(Path(temporary) / "pytest")]),
            ("evaluation", ["-m", "evaluation.quality_gate", "--output-dir", str(output)]),
        ]
        for name, arguments in checks:
            started = time.monotonic()
            with (output / (name + ".log")).open("w", encoding="utf-8") as log:
                try:
                    result = subprocess.run([sys.executable, *arguments], cwd=ROOT, env=environment,
                                            stdout=log, stderr=subprocess.STDOUT, timeout=300)
                    code = result.returncode
                except subprocess.TimeoutExpired:
                    code = 124
            report["steps"].append({"name": name, "exit_code": code,
                                    "duration_seconds": round(time.monotonic() - started, 3)})
            print(f"{name}: {'passed' if code == 0 else 'FAILED'}", flush=True)
            if code:
                break
        report["source_unchanged"] = fingerprint == source_fingerprint()
        report["passed"] = (len(report["steps"]) == len(checks) and all(s["exit_code"] == 0 for s in report["steps"])
                            and report["source_unchanged"])
        (output / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
