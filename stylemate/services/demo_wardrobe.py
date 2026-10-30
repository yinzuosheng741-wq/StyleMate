"""Persistent, resumable demo wardrobe seeding and version migration."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Protocol

from stylemate.domain.models import Garment
from stylemate.repositories.base import WardrobeRepository
from stylemate.storage.images import ImageStore

DEMO_SEED_KEY = "demo_wardrobe_v1"
LEGACY_DEMO_SEED_KEY = DEMO_SEED_KEY
_SEED_IDS_SUFFIX = ":ids"
_SEED_OWNER_ID = "local-user"
_SEED_CREATED_AT = datetime(2024, 1, 1)


class DemoSeedRepository(WardrobeRepository, Protocol):
    def get_metadata(self, key: str) -> str | None: ...

    def set_metadata(self, key: str, value: str) -> None: ...


def seed_local_demo_wardrobe(
    repository: DemoSeedRepository,
    image_store: ImageStore,
    manifest_path: Path,
    owner_id: str = _SEED_OWNER_ID,
) -> int:
    """Seed a manifest exactly once, or migrate it additively to v2.

    v1 seeded IDs are persisted separately from the completion marker. During
    a v1-to-v2 migration, an absent legacy ID is treated as a deliberate user
    deletion and is never recreated. Progress IDs make an interrupted v2 run
    resumable without losing the same deletion guarantee.
    """
    version, records, manifest_legacy_ids = _load_manifest(manifest_path)
    marker = repository.get_metadata(DEMO_SEED_KEY)
    if marker == version == "demo_wardrobe_v2":
        return 0
    if marker == "demo_wardrobe_v1" and version == "demo_wardrobe_v1":
        return 0

    legacy_ids = _read_ids(repository, f"{LEGACY_DEMO_SEED_KEY}{_SEED_IDS_SUFFIX}")
    # Manifest IDs describe a previous release, not deletions in a brand-new database.
    if marker == "demo_wardrobe_v1":
        legacy_ids |= manifest_legacy_ids
    progress_key = f"{DEMO_SEED_KEY}{_SEED_IDS_SUFFIX}"
    progress_ids = _read_ids(repository, progress_key)
    inserted = 0
    for record in records:
        garment_id = record["id"]
        existing = repository.get_garment(owner_id, garment_id)
        if existing is None and version == "demo_wardrobe_v2" and garment_id in legacy_ids:
            continue
        if existing is not None and version == "demo_wardrobe_v2":
            _refresh_existing(repository, image_store, owner_id, existing, record, manifest_path)
            progress_ids.add(garment_id)
            repository.set_metadata(progress_key, _dump_ids(progress_ids))
            continue
        if existing is not None:
            progress_ids.add(garment_id)
            continue

        image_path = _asset_path(manifest_path, record["image"])
        image_bytes = image_path.read_bytes()
        image_ref = image_store.save(owner_id, garment_id, image_bytes, "image/webp")
        try:
            repository.save_garment(owner_id, _to_garment(record, image_ref, image_bytes))
        except Exception:
            image_store.delete(owner_id, image_ref)
            raise
        progress_ids.add(garment_id)
        repository.set_metadata(progress_key, _dump_ids(progress_ids))
        inserted += 1

    missing = [
        record["id"]
        for record in records
        if repository.get_garment(owner_id, record["id"]) is None
        and not (version == "demo_wardrobe_v2" and record["id"] in legacy_ids)
    ]
    if missing:
        raise RuntimeError(f"Demo wardrobe seed incomplete: {missing}")
    repository.set_metadata(DEMO_SEED_KEY, version)
    return inserted


def _refresh_existing(
    repository: DemoSeedRepository,
    image_store: ImageStore,
    owner_id: str,
    existing: Garment,
    record: dict,
    manifest_path: Path,
) -> None:
    image_path = _asset_path(manifest_path, record["image"])
    image_bytes = image_path.read_bytes()
    old_ref = existing.image_ref
    image_ref = image_store.save(owner_id, existing.id, image_bytes, "image/webp")
    try:
        repository.save_garment(owner_id, _to_garment(record, image_ref, image_bytes))
    except Exception:
        image_store.delete(owner_id, image_ref)
        raise
    if old_ref and old_ref != image_ref:
        image_store.delete(owner_id, old_ref)


def _to_garment(record: dict, image_ref: str, image_bytes: bytes) -> Garment:
    return Garment(
        id=record["id"],
        name=record["name"],
        category=record["category"],
        primary_color=record["primary_color"],
        material=record["material"],
        seasons=record["seasons"],
        styles=record["styles"],
        image_ref=image_ref,
        image_hash=hashlib.sha256(image_bytes).hexdigest(),
        source="sample",
        created_at=_SEED_CREATED_AT,
    )


def _read_ids(repository: DemoSeedRepository, key: str) -> set[str]:
    raw = repository.get_metadata(key)
    if not raw:
        return set()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return set()
    return {item for item in value if isinstance(item, str)} if isinstance(value, list) else set()


def _dump_ids(ids: set[str]) -> str:
    return json.dumps(sorted(ids), ensure_ascii=False)


def _load_manifest(manifest_path: Path) -> tuple[str, list[dict], set[str]]:
    path = manifest_path.resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read demo wardrobe manifest: {path}") from exc
    version = payload.get("version")
    records = payload.get("garments")
    raw_legacy_ids = payload.get("legacy_ids", [])
    if version not in {"demo_wardrobe_v1", "demo_wardrobe_v2"} or not isinstance(records, list) or not records:
        raise ValueError("Demo wardrobe manifest has an invalid version or garment list")

    seen_ids: set[str] = set()
    validated: list[dict] = []
    for record in records:
        if not isinstance(record, dict) or record.get("id") in seen_ids:
            raise ValueError("Demo wardrobe manifest contains duplicate or invalid IDs")
        seen_ids.add(record.get("id"))
        try:
            Garment(
                id=record["id"],
                name=record["name"],
                category=record["category"],
                primary_color=record["primary_color"],
                material=record["material"],
                seasons=record["seasons"],
                styles=record["styles"],
                source="sample",
            )
            _asset_path(path, record["image"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid demo wardrobe record: {record!r}") from exc
        validated.append(record)
    legacy_ids = {item for item in raw_legacy_ids if isinstance(item, str)} if isinstance(raw_legacy_ids, list) else set()
    return version, validated, legacy_ids


def _asset_path(manifest_path: Path, filename: str) -> Path:
    if not isinstance(filename, str) or not filename.endswith(".webp"):
        raise ValueError("Demo wardrobe assets must be WebP files")
    asset_root = (manifest_path.parent / "garments").resolve()
    candidate = (asset_root / filename).resolve()
    try:
        candidate.relative_to(asset_root)
    except ValueError as exc:
        raise ValueError("Demo wardrobe asset escapes the configured directory") from exc
    if not candidate.is_file():
        raise ValueError(f"Demo wardrobe asset does not exist: {candidate}")
    return candidate
