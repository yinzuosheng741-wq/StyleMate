import json
from pathlib import Path

import pytest
from PIL import Image

from stylemate.repositories.sqlite import SQLiteWardrobeRepository
from stylemate.services.demo_wardrobe import DEMO_SEED_KEY, seed_local_demo_wardrobe
from stylemate.storage.images import LocalImageStore


def _write_manifest(root: Path, item_count: int = 2, *, version: str = "demo_wardrobe_v1") -> Path:
    asset_root = root / "assets" / "demo"
    image_root = asset_root / "garments"
    image_root.mkdir(parents=True)
    garments = []
    for index in range(item_count):
        filename = f"item-{index}.webp"
        Image.new("RGB", (32, 32), "white").save(
            image_root / filename, format="WEBP"
        )
        garments.append(
            {
                "id": f"demo-item-{index}",
                "name": f"演示衣物 {index}",
                "category": "上装" if index == 0 else "下装",
                "primary_color": "白色",
                "material": "棉",
                "seasons": ["四季"],
                "styles": ["简约"],
                "image": filename,
            }
        )
    manifest_path = asset_root / "wardrobe.json"
    manifest_path.write_text(
        json.dumps({"version": version, "garments": garments}, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest_path


def test_local_demo_wardrobe_seeds_once(tmp_path: Path):
    manifest_path = _write_manifest(tmp_path)
    repository = SQLiteWardrobeRepository(tmp_path / "stylemate.db")
    image_store = LocalImageStore(tmp_path / "uploads")

    assert seed_local_demo_wardrobe(repository, image_store, manifest_path) == 2
    assert seed_local_demo_wardrobe(repository, image_store, manifest_path) == 0
    assert len(repository.list_garments("local-user")) == 2
    assert repository.get_metadata(DEMO_SEED_KEY) == "demo_wardrobe_v1"


def test_fresh_v2_install_includes_items_that_also_have_legacy_ids(tmp_path: Path):
    manifest_path = _write_manifest(tmp_path, version="demo_wardrobe_v2")
    payload = json.loads(manifest_path.read_text("utf-8"))
    payload["legacy_ids"] = ["demo-item-0"]
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    repository = SQLiteWardrobeRepository(tmp_path / "stylemate.db")
    assert seed_local_demo_wardrobe(repository, LocalImageStore(tmp_path / "uploads"), manifest_path) == 2
    assert len(repository.list_garments("local-user")) == 2


def test_deleted_demo_item_stays_deleted_after_restart(tmp_path: Path):
    manifest_path = _write_manifest(tmp_path)
    database_path = tmp_path / "stylemate.db"
    upload_path = tmp_path / "uploads"
    repository = SQLiteWardrobeRepository(database_path)
    image_store = LocalImageStore(upload_path)
    seed_local_demo_wardrobe(repository, image_store, manifest_path)
    deleted = repository.get_garment("local-user", "demo-item-0")
    assert deleted is not None and deleted.image_ref is not None

    image_store.delete("local-user", deleted.image_ref)
    repository.delete_garment("local-user", deleted.id)

    fresh_repository = SQLiteWardrobeRepository(database_path)
    assert (
        seed_local_demo_wardrobe(
            fresh_repository, LocalImageStore(upload_path), manifest_path
        )
        == 0
    )
    assert fresh_repository.get_garment("local-user", deleted.id) is None
    assert len(fresh_repository.list_garments("local-user")) == 1


def test_interrupted_seed_resumes_missing_items_without_duplicates(tmp_path: Path):
    manifest_path = _write_manifest(tmp_path)
    repository = SQLiteWardrobeRepository(tmp_path / "stylemate.db")
    delegate = LocalImageStore(tmp_path / "uploads")

    class FailOnSecondSave:
        def __init__(self):
            self.calls = 0

        def save(self, owner_id, garment_id, image_bytes, mime_type):
            self.calls += 1
            if self.calls == 2:
                raise OSError("simulated interruption")
            return delegate.save(owner_id, garment_id, image_bytes, mime_type)

        def read(self, owner_id, image_ref):
            return delegate.read(owner_id, image_ref)

        def delete(self, owner_id, image_ref):
            delegate.delete(owner_id, image_ref)

    with pytest.raises(OSError, match="simulated interruption"):
        seed_local_demo_wardrobe(repository, FailOnSecondSave(), manifest_path)

    assert repository.get_metadata(DEMO_SEED_KEY) is None
    assert len(repository.list_garments("local-user")) == 1
    assert seed_local_demo_wardrobe(repository, delegate, manifest_path) == 1
    assert len(repository.list_garments("local-user")) == 2
    assert repository.get_metadata(DEMO_SEED_KEY) == "demo_wardrobe_v1"


def test_v2_migration_inserts_new_records_without_recreating_deleted_legacy_items(tmp_path: Path):
    manifest_path = _write_manifest(tmp_path, item_count=2, version="demo_wardrobe_v1")
    repository = SQLiteWardrobeRepository(tmp_path / "stylemate.db")
    image_store = LocalImageStore(tmp_path / "uploads")
    seed_local_demo_wardrobe(repository, image_store, manifest_path)
    deleted = repository.get_garment("local-user", "demo-item-0")
    assert deleted is not None
    image_store.delete("local-user", deleted.image_ref)
    repository.delete_garment("local-user", deleted.id)

    v2_root = tmp_path / "v2" / "assets" / "demo"
    v2_image_root = v2_root / "garments"
    v2_image_root.mkdir(parents=True)
    (v2_image_root / "new-item.webp").write_bytes((tmp_path / "assets" / "demo" / "garments" / "item-1.webp").read_bytes())
    v2_manifest = v2_root / "wardrobe.json"
    v2_manifest.write_text(
        json.dumps(
            {
                "version": "demo_wardrobe_v2",
                "legacy_ids": ["demo-item-0"],
                "garments": [
                    {
                        "id": "demo-item-0",
                        "name": "旧项目 0",
                        "category": "上装",
                        "primary_color": "白色",
                        "material": "棉",
                        "seasons": ["四季"],
                        "styles": ["简约"],
                        "image": "new-item.webp",
                    },
                    {
                        "id": "demo-new-item",
                        "name": "新项目",
                        "category": "上装",
                        "primary_color": "蓝色",
                        "material": "棉",
                        "seasons": ["春"],
                        "styles": ["休闲"],
                        "image": "new-item.webp",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert seed_local_demo_wardrobe(repository, image_store, v2_manifest) == 1
    assert repository.get_garment("local-user", "demo-item-0") is None
    assert repository.get_garment("local-user", "demo-new-item") is not None
    assert repository.get_metadata(DEMO_SEED_KEY) == "demo_wardrobe_v2"


def test_v2_manifest_legacy_ids_protect_deletions_from_old_databases_without_progress_metadata(tmp_path: Path):
    manifest_path = _write_manifest(tmp_path, item_count=1, version="demo_wardrobe_v2")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["legacy_ids"] = ["demo-item-0"]
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    repository = SQLiteWardrobeRepository(tmp_path / "stylemate.db")
    repository.set_metadata(DEMO_SEED_KEY, "demo_wardrobe_v1")

    assert seed_local_demo_wardrobe(repository, LocalImageStore(tmp_path / "uploads"), manifest_path) == 0
    assert repository.get_garment("local-user", "demo-item-0") is None
    assert repository.get_metadata(DEMO_SEED_KEY) == "demo_wardrobe_v2"


def test_v2_migration_resumes_after_interruption_and_is_idempotent(tmp_path: Path):
    manifest_path = _write_manifest(tmp_path, item_count=3, version="demo_wardrobe_v2")
    repository = SQLiteWardrobeRepository(tmp_path / "stylemate.db")
    delegate = LocalImageStore(tmp_path / "uploads")

    class FailOnSecondSave:
        def __init__(self):
            self.calls = 0

        def save(self, owner_id, garment_id, image_bytes, mime_type):
            self.calls += 1
            if self.calls == 2:
                raise OSError("simulated interruption")
            return delegate.save(owner_id, garment_id, image_bytes, mime_type)

        def read(self, owner_id, image_ref):
            return delegate.read(owner_id, image_ref)

        def delete(self, owner_id, image_ref):
            delegate.delete(owner_id, image_ref)

    with pytest.raises(OSError, match="simulated interruption"):
        seed_local_demo_wardrobe(repository, FailOnSecondSave(), manifest_path)
    assert repository.get_metadata(DEMO_SEED_KEY) is None
    assert seed_local_demo_wardrobe(repository, delegate, manifest_path) == 2
    assert seed_local_demo_wardrobe(repository, delegate, manifest_path) == 0
    assert len(repository.list_garments("local-user")) == 3
    assert repository.get_metadata(DEMO_SEED_KEY) == "demo_wardrobe_v2"
