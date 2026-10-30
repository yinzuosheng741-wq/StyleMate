"""Snapshot only the installed portable runtime dependency closure (including extras)."""
import argparse
import platform
import sys
from importlib.metadata import distribution
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]


def read_requirements(path):
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r "):
            yield from read_requirements(path.parent / line[3:].strip())
        else:
            yield Requirement(line)


def resolve_installed(requirements):
    pending = list(requirements)
    visited = set()
    locked = {}
    while pending:
        requirement = pending.pop()
        if requirement.marker and not requirement.marker.evaluate():
            continue
        name = canonicalize_name(requirement.name)
        installed = distribution(name)
        if requirement.specifier and installed.version not in requirement.specifier:
            raise ValueError(f"Installed {name}=={installed.version} does not satisfy {requirement.specifier}")
        locked[name] = installed.version
        extras = frozenset(requirement.extras)
        key = (name, extras)
        if key in visited:
            continue
        visited.add(key)
        for value in installed.requires or []:
            child = Requirement(value)
            if child.marker and not any(child.marker.evaluate({"extra": extra}) for extra in ("", *extras)):
                continue
            # Parent-extra markers have already been evaluated in their correct scope.
            child.marker = None
            pending.append(child)
    return locked


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="Replace the reviewed portable snapshot from this environment")
    mode.add_argument("--common", action="store_true", help="Check declared common requirements against the installed environment")
    args = parser.parse_args()
    locked = resolve_installed(read_requirements(ROOT / ("requirements-common.txt" if args.common else "requirements-portable.txt")))
    if args.common:
        print(f"Validated {len(locked)} installed common runtime distributions")
        return 0
    path = ROOT / "portable-lock.txt"
    if args.write:
        header = f"# Portable runtime snapshot: {sys.platform}, Python {platform.python_version()}.\n"
        path.write_text(header + "".join(f"{name}=={version}\n" for name, version in sorted(locked.items())), encoding="utf-8")
        print(f"Locked {len(locked)} runtime distributions")
        return 0
    saved = {canonicalize_name(req.name): str(req.specifier).removeprefix("==") for req in read_requirements(path)}
    matches = saved == locked
    print("Runtime lock matches installed portable closure" if matches else "Runtime lock differs; review before --write")
    return 0 if matches else 1


if __name__ == "__main__":
    raise SystemExit(main())
