import hashlib
from io import BytesIO
from unittest.mock import Mock

import pytest
from PIL import Image

from stylemate.domain.models import Garment
from stylemate.services.wardrobe_service import (
    ImageCleanupError,
    UploadValidationError,
    WardrobeService,
)
from stylemate.storage.images import SessionImageStore


def make_service(repo):
    return WardrobeService(repo, SessionImageStore({}), max_upload_bytes=8 * 1024 * 1024)


def confirmed_garment(image_hash: str) -> Garment:
    return Garment(
        id="g-1",
        name="Beige coat",
        category="outerwear",
        primary_color="beige",
        seasons=["spring"],
        styles=["minimal"],
        image_hash=image_hash,
        source="ai",
    )


def test_upload_rejects_unknown_mime(repo):
    with pytest.raises(UploadValidationError, match="JPG"):
        make_service(repo).validate_upload(b"abc", "application/pdf")


def test_upload_rejects_empty_bytes(repo):
    with pytest.raises(UploadValidationError, match="empty"):
        make_service(repo).validate_upload(b"", "image/jpeg")


def test_upload_rejects_more_than_eight_mb(repo):
    with pytest.raises(UploadValidationError, match="8 MB"):
        make_service(repo).validate_upload(b"x" * (8 * 1024 * 1024 + 1), "image/jpeg")


def test_upload_rejects_undecodable_image_bytes(repo):
    with pytest.raises(UploadValidationError, match="decoded"):
        make_service(repo).validate_upload(b"not-an-image", "image/jpeg")


def test_upload_rejects_mime_that_disagrees_with_image_content(repo):
    image = BytesIO()
    Image.new("RGB", (32, 32), "white").save(image, format="PNG")

    with pytest.raises(UploadValidationError, match="content"):
        make_service(repo).validate_upload(image.getvalue(), "image/jpeg")


def test_find_duplicate_is_scoped_to_owner_and_hashes_bytes(repo):
    image_bytes = b"same image"
    repo.save_garment("owner-1", confirmed_garment(hashlib.sha256(image_bytes).hexdigest()))

    service = make_service(repo)

    assert service.find_duplicate("owner-1", image_bytes).id == "g-1"
    assert service.find_duplicate("owner-2", image_bytes) is None
    assert service.image_hash(image_bytes) == hashlib.sha256(image_bytes).hexdigest()


def test_save_confirmed_stores_image_before_persisting_garment(repo, jpeg_bytes):
    store = SessionImageStore({})
    service = WardrobeService(repo, store, max_upload_bytes=8 * 1024 * 1024)
    garment = confirmed_garment(service.image_hash(jpeg_bytes))

    saved = service.save_confirmed("owner-1", garment, jpeg_bytes, "image/jpeg")

    assert saved.image_ref is not None
    assert store.read("owner-1", saved.image_ref) == jpeg_bytes
    assert repo.get_garment("owner-1", garment.id) == saved


class FailingRepository:
    def save_garment(self, owner_id, garment):
        raise RuntimeError("database unavailable")


def test_save_confirmed_deletes_image_when_persistence_fails(jpeg_bytes):
    store = SessionImageStore({})
    service = WardrobeService(FailingRepository(), store, max_upload_bytes=8 * 1024 * 1024)
    garment = confirmed_garment(service.image_hash(jpeg_bytes))

    with pytest.raises(RuntimeError, match="database unavailable"):
        service.save_confirmed("owner-1", garment, jpeg_bytes, "image/jpeg")

    assert store.state["images"]["owner-1"] == {}


def test_update_confirmed_revalidates_and_preserves_explicit_material_clear(repo):
    garment = confirmed_garment("hash").model_copy(update={"material": "wool"})
    repo.save_garment("owner-1", garment)
    service = make_service(repo)

    updated = service.update_confirmed("owner-1", "g-1", {"material": None})

    assert updated.material is None
    assert repo.get_garment("owner-1", "g-1").material is None
    with pytest.raises(ValueError):
        service.update_confirmed("owner-1", "g-1", {"seasons": []})


def test_update_confirmed_does_not_save_a_noop(repo, monkeypatch):
    garment = confirmed_garment("hash")
    repo.save_garment("owner-1", garment)
    service = make_service(repo)
    save_call = Mock(wraps=repo.save_garment)
    monkeypatch.setattr(repo, "save_garment", save_call)

    updated = service.update_confirmed("owner-1", "g-1", {"name": garment.name})

    assert updated == garment
    save_call.assert_not_called()


def test_delete_confirmed_removes_owned_image_after_deleting_record(repo, jpeg_bytes):
    store = SessionImageStore({})
    service = WardrobeService(repo, store, max_upload_bytes=8 * 1024 * 1024)
    garment = confirmed_garment(service.image_hash(jpeg_bytes))
    saved = service.save_confirmed("owner-1", garment, jpeg_bytes, "image/jpeg")

    service.delete_confirmed("owner-1", saved.id)

    assert repo.get_garment("owner-1", saved.id) is None
    assert saved.image_ref is not None
    assert store.read("owner-1", saved.image_ref) is None


def test_delete_confirmed_reports_image_cleanup_failure_after_record_delete(repo, jpeg_bytes):
    class FailingImageStore(SessionImageStore):
        def delete(self, owner_id, image_ref):
            raise OSError("storage unavailable")

    store = FailingImageStore({})
    service = WardrobeService(repo, store, max_upload_bytes=8 * 1024 * 1024)
    garment = confirmed_garment(service.image_hash(jpeg_bytes))
    saved = service.save_confirmed("owner-1", garment, jpeg_bytes, "image/jpeg")

    with pytest.raises(ImageCleanupError, match="record deleted"):
        service.delete_confirmed("owner-1", saved.id)

    assert repo.get_garment("owner-1", saved.id) is None
