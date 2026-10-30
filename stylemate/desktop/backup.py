"""Consistent SQLite and image backups, written atomically to a user-selected ZIP."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def create_backup(database: Path, uploads: Path, destination: Path) -> dict:
    database, uploads, destination = database.resolve(), uploads.resolve(), destination.resolve()
    if not database.is_file():
        raise ValueError("database_missing")
    if destination.suffix.lower() != ".zip":
        raise ValueError("backup_requires_zip_extension")
    if destination == database or destination == uploads or uploads in destination.parents:
        raise ValueError("backup_destination_overlaps_data")
    if destination.exists() and os.path.samefile(database, destination):
        raise ValueError("backup_destination_overlaps_data")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="stylemate-backup-", dir=destination.parent) as temporary:
        staging = Path(temporary)
        snapshot = staging / "stylemate.db"
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(snapshot)) as target:
                source.backup(target)
                rows = target.execute("SELECT payload FROM garments").fetchall()
        images = set()
        for (payload,) in rows:
            reference = json.loads(payload).get("image_ref")
            if not reference or reference.startswith("assets/demo/"):
                continue
            image = (uploads / reference).resolve()
            if uploads not in image.parents or not image.is_file():
                raise ValueError("backup_image_missing_or_invalid")
            images.add(image)
        manifest = {"application": "StyleMate", "format": 1,
                    "created_at": datetime.now(timezone.utc).isoformat(), "files": {}}
        archive_path = staging / "backup.zip"
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            files = [(snapshot, "data/stylemate.db")]
            files.extend((image, "data/uploads/" + image.relative_to(uploads).as_posix()) for image in sorted(images))
            for source_path, archive_name in files:
                payload = source_path.read_bytes()
                archive.writestr(archive_name, payload)
                manifest["files"][archive_name] = hashlib.sha256(payload).hexdigest()
            archive.writestr("backup-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive_path.replace(destination)
    return {"images": len(images), "garments": len(rows), "path": str(destination)}
