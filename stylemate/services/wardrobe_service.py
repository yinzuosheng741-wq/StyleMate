"""Validation and persistence for confirmed wardrobe garments."""

import hashlib
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from stylemate.domain.models import Garment
from stylemate.repositories.base import WardrobeRepository
from stylemate.storage.images import ImageStore

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MIME_FORMATS = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}


class UploadValidationError(ValueError):
    """Raised when a submitted garment image cannot be safely accepted."""


class ImageCleanupError(RuntimeError):
    """The garment record was removed, but its local image could not be purged."""


class WardrobeService:
    def __init__(
        self,
        repository: WardrobeRepository,
        image_store: ImageStore,
        max_upload_bytes: int,
    ):
        self.repository = repository
        self.image_store = image_store
        self.max_upload_bytes = max_upload_bytes

    def validate_upload(self, image_bytes: bytes, mime_type: str) -> None:
        if mime_type not in ALLOWED_MIME_TYPES:
            raise UploadValidationError("Only JPG, PNG, and WEBP images are supported")
        if not image_bytes:
            raise UploadValidationError("Image upload cannot be empty")
        if len(image_bytes) > self.max_upload_bytes:
            raise UploadValidationError("Image upload must be 8 MB or smaller")
        try:
            with Image.open(BytesIO(image_bytes)) as image:
                image.load()
                if image.format != _MIME_FORMATS[mime_type]:
                    raise UploadValidationError(
                        "Image MIME type does not match its content"
                    )
        except UploadValidationError:
            raise
        except (OSError, UnidentifiedImageError) as exc:
            raise UploadValidationError("Image bytes cannot be decoded") from exc

    @staticmethod
    def image_hash(image_bytes: bytes) -> str:
        return hashlib.sha256(image_bytes).hexdigest()

    def find_duplicate(self, owner_id: str, image_bytes: bytes) -> Garment | None:
        return self.repository.find_garment_by_hash(owner_id, self.image_hash(image_bytes))

    def save_confirmed(
        self,
        owner_id: str,
        garment: Garment,
        image_bytes: bytes,
        mime_type: str,
    ) -> Garment:
        self.validate_upload(image_bytes, mime_type)
        image_ref = self.image_store.save(owner_id, garment.id, image_bytes, mime_type)
        saved = garment.model_copy(
            update={"image_ref": image_ref, "image_hash": self.image_hash(image_bytes)}
        )
        try:
            self.repository.save_garment(owner_id, saved)
        except Exception:
            self.image_store.delete(owner_id, image_ref)
            raise
        return saved

    def save_manual(self, owner_id: str, garment: Garment) -> Garment:
        """Persist a manually entered garment without accepting image content."""
        if garment.source != "manual":
            raise ValueError("Manual garments must use the manual source")
        if garment.image_ref is not None or garment.image_hash is not None:
            raise ValueError("Manual garments cannot include an image")
        self.repository.save_garment(owner_id, garment)
        return garment

    def update_confirmed(
        self, owner_id: str, garment_id: str, changes: dict[str, object]
    ) -> Garment:
        """Update an already revalidated garment through the service boundary."""
        current = self.repository.get_garment(owner_id, garment_id)
        if current is None:
            raise ValueError("Garment no longer exists")
        candidate = current.model_dump(mode="python")
        candidate.update(changes)
        updated = Garment.model_validate(candidate)
        if updated == current:
            return current
        self.repository.save_garment(owner_id, updated)
        return updated

    def delete_confirmed(self, owner_id: str, garment_id: str) -> None:
        """Delete a garment record and then remove its owned local image.

        The database mutation is the authoritative business operation.  Image cleanup
        runs afterwards so a storage failure cannot leave a visible garment pointing
        at a missing image.  Callers receive ``ImageCleanupError`` when the record
        was deleted but the file needs explicit follow-up.
        """
        current = self.repository.get_garment(owner_id, garment_id)
        if current is None:
            raise ValueError("Garment no longer exists")
        self.repository.delete_garment(owner_id, garment_id)
        if not current.image_ref:
            return
        try:
            self.image_store.delete(owner_id, current.image_ref)
        except Exception as exc:
            raise ImageCleanupError(
                "Garment record deleted but image cleanup failed"
            ) from exc
