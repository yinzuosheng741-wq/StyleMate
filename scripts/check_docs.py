"""Check repository-relative Markdown file links without accessing external URLs."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"!?\[[^\]]*\]\((?:<([^>]+)>|([^\s)]+))(?:\s+\"[^\"]*\")?\)")


def public_markdown(root: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root,
    )
    return sorted({root / name.decode("utf-8") for name in output.split(b"\0")
                   if name and name.endswith(b".md") and (root / name.decode("utf-8")).is_file()})


def broken_links(root: Path, documents: list[Path]) -> list[str]:
    root = root.resolve()
    failures = []
    for document in documents:
        text = re.sub(r"```.*?```", "", document.read_text(encoding="utf-8"), flags=re.S)
        for match in LINK.finditer(text):
            target = match[1] or match[2]
            parts = urlsplit(target)
            if parts.scheme or parts.netloc or not parts.path:
                continue
            destination = (document.parent / unquote(parts.path)).resolve()
            if not destination.is_relative_to(root) or not destination.exists():
                failures.append(f"{document.relative_to(root).as_posix()}: {target}")
    return failures


def main():
    documents = public_markdown(ROOT)
    failures = broken_links(ROOT, documents)
    for failure in failures:
        print(f"Broken local link: {failure}")
    print(f"Markdown documents: {len(documents)}; broken local file links: {len(failures)}")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
