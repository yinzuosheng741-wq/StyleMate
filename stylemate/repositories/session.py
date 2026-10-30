from stylemate.domain.models import FavoriteOutfit, Garment, OutfitFeedback


class SessionWardrobeRepository:
    def __init__(self, state: dict):
        owners = state.setdefault("owners", {})
        # Keep tool-worker reads away from Streamlit's thread-bound state proxy.
        self.state = {"owners": owners}

    def _owner(self, owner_id: str) -> dict:
        owners = self.state["owners"]
        owner = owners.setdefault(owner_id, {})
        owner.setdefault("garments", {})
        owner.setdefault("profile", {})
        owner.setdefault("favorites", {})
        owner.setdefault("feedback", {})
        return owner

    def list_garments(self, owner_id: str) -> list[Garment]:
        return [
            Garment.model_validate(payload)
            for payload in self._owner(owner_id)["garments"].values()
        ]

    def get_garment(self, owner_id: str, garment_id: str) -> Garment | None:
        payload = self._owner(owner_id)["garments"].get(garment_id)
        return Garment.model_validate(payload) if payload else None

    def save_garment(self, owner_id: str, garment: Garment) -> None:
        self._owner(owner_id)["garments"][garment.id] = garment.model_dump(mode="json")

    def delete_garment(self, owner_id: str, garment_id: str) -> None:
        self._owner(owner_id)["garments"].pop(garment_id, None)

    def find_garment_by_hash(self, owner_id: str, image_hash: str) -> Garment | None:
        for garment in self.list_garments(owner_id):
            if garment.image_hash == image_hash:
                return garment
        return None

    def get_profile(self, owner_id: str) -> dict[str, str]:
        return dict(self._owner(owner_id)["profile"])

    def save_profile(self, owner_id: str, profile: dict[str, str]) -> None:
        self._owner(owner_id)["profile"] = dict(profile)

    def save_favorite(self, favorite: FavoriteOutfit) -> None:
        owner = self._owner(favorite.owner_id)
        owner["favorites"][favorite.recommendation.id] = favorite.model_dump(mode="json")

    def list_favorites(self, owner_id: str) -> list[FavoriteOutfit]:
        return [
            FavoriteOutfit.model_validate(payload)
            for payload in self._owner(owner_id)["favorites"].values()
        ]

    def delete_favorite(self, owner_id: str, outfit_id: str) -> None:
        self._owner(owner_id)["favorites"].pop(outfit_id, None)

    def save_feedback(self, feedback: OutfitFeedback) -> None:
        owner = self._owner(feedback.owner_id)
        owner["feedback"][feedback.outfit_id] = feedback.model_dump(mode="json")
