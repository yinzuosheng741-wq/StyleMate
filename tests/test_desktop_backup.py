import hashlib
import json
import sqlite3
import zipfile

import pytest

from stylemate.desktop.backup import create_backup
from stylemate.domain.models import ConversationMessage, ConversationState
from stylemate.repositories.agent_sqlite import SQLiteAgentRepository
from stylemate.repositories.sqlite import SQLiteWardrobeRepository
from stylemate.services.wardrobe_service import WardrobeService
from stylemate.storage.images import LocalImageStore


@pytest.fixture
def backup_data(tmp_path, sample_garments, jpeg_bytes):
    database = tmp_path / "data/stylemate.db"
    repository = SQLiteWardrobeRepository(database)
    images = LocalImageStore(tmp_path / "data/uploads")
    service = WardrobeService(repository, images, 8 * 1024 * 1024)
    saved = service.save_confirmed("local-user", sample_garments[0], jpeg_bytes, "image/jpeg")
    agent = SQLiteAgentRepository(database)
    agent.save_conversation(ConversationState(owner_id="local-user", conversation_id="test",
                                             messages=[ConversationMessage(role="user", content="备份测试")]))
    (tmp_path / ".env").write_text("LLM_API_KEY=private", encoding="utf-8")
    return database, images.root, saved


def test_backup_contains_consistent_database_images_and_hashes(backup_data, tmp_path):
    database, uploads, garment = backup_data
    output = tmp_path / "backup.zip"
    report = create_backup(database, uploads, output)
    assert report["garments"] == report["images"] == 1
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert "data/uploads/" + garment.image_ref in archive.namelist()
        assert not any(name.endswith(".env") for name in archive.namelist())
        manifest = json.loads(archive.read("backup-manifest.json"))
        for name, digest in manifest["files"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
        snapshot = tmp_path / "restored.db"
        snapshot.write_bytes(archive.read("data/stylemate.db"))
    restored = SQLiteWardrobeRepository(snapshot)
    assert restored.get_garment("local-user", garment.id) == garment
    messages = SQLiteAgentRepository(snapshot).load_conversation("local-user", "test").messages
    assert messages[0].content == "备份测试"


def test_backup_failure_keeps_existing_archive_and_removes_temporary_files(backup_data, tmp_path):
    database, uploads, garment = backup_data
    (uploads / garment.image_ref).unlink()
    output = tmp_path / "backup.zip"
    output.write_bytes(b"previous-backup")
    with pytest.raises(ValueError, match="image_missing"):
        create_backup(database, uploads, output)
    assert output.read_bytes() == b"previous-backup"
    assert not list(tmp_path.glob("stylemate-backup-*"))


def test_backup_rejects_overwriting_source_or_storing_archive_in_images(backup_data):
    database, uploads, _ = backup_data
    for output in (database, uploads / "backup.zip"):
        with pytest.raises(ValueError):
            create_backup(database, uploads, output)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_backup_rejects_image_reference_outside_upload_root(backup_data, tmp_path):
    database, uploads, garment = backup_data
    repo = SQLiteWardrobeRepository(database)
    repo.save_garment("local-user", garment.model_copy(update={"image_ref": "../../.env"}))
    with pytest.raises(ValueError, match="image_missing_or_invalid"):
        create_backup(database, uploads, tmp_path / "backup.zip")
