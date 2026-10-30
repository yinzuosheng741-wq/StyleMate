"""Collect licenses from the actual runtime dependency closure."""
import json
import shutil
import sys
from importlib.metadata import distribution
from pathlib import Path

from scripts.lock_runtime import read_requirements, resolve_installed

ROOT = Path(__file__).resolve().parents[1]


def copy_notices(output):
    target = output / "licenses"
    target.mkdir(exist_ok=True)
    for source in (ROOT / "licenses").glob("*.txt"):
        shutil.copyfile(source, target / source.name)
    metadata = []
    for name, version in sorted(resolve_installed(read_requirements(ROOT / "requirements.txt")).items()):
        package = distribution(name)
        record = {"name": name, "version": version,
                  "license": package.metadata.get("License-Expression") or package.metadata.get("License") or "See upstream metadata"}
        metadata.append(record)
        for file in package.files or []:
            if not file.name.lower().startswith(("license", "copying", "notice")):
                continue
            source = Path(package.locate_file(file))
            if source.is_file():
                folder = target / name
                folder.mkdir(exist_ok=True)
                destination = folder.joinpath(*(part for part in file.parts if part not in {".", ".."}))
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
    (target / "runtime-dependencies.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), "utf-8")
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copyfile(python_license, target / "Python-LICENSE.txt")
    shutil.copyfile(ROOT / "THIRD_PARTY_NOTICES.md", output / "THIRD_PARTY_NOTICES.md")
    # Keep the material referenced by the third-party notice available locally.
    (output / "assets/demo").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "assets/demo/SOURCE.md", output / "assets/demo/SOURCE.md")
