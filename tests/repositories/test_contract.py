import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from stylemate.domain.models import FavoriteOutfit, Garment, OutfitFeedback, OutfitRecommendation
from stylemate.repositories.session import SessionWardrobeRepository
from stylemate.repositories.sqlite import SQLiteWardrobeRepository


@pytest.fixture(params=["session", "sqlite"])
def repo(request, tmp_path: Path):
    if request.param == "session":
        return SessionWardrobeRepository({})
    return SQLiteWardrobeRepository(tmp_path / "stylemate.db")


def garment(garment_id: str, image_hash: str) -> Garment:
    return Garment(
        id=garment_id,
        name="白色衬衫",
        category="上装",
        primary_color="白色",
        seasons=["春", "秋"],
        styles=["通勤"],
        image_hash=image_hash,
        source="manual",
    )


def favorite(owner_id: str, outfit_id: str, reason: str) -> FavoriteOutfit:
    return FavoriteOutfit(
        owner_id=owner_id,
        recommendation=OutfitRecommendation(
            id=outfit_id,
            garment_ids=["g-1"],
            score=90,
            reason=reason,
            constraint_checks={"inventory": True},
        ),
    )


def feedback(owner_id: str, outfit_id: str, note: str) -> OutfitFeedback:
    return OutfitFeedback(
        owner_id=owner_id,
        outfit_id=outfit_id,
        reasons=["颜色不喜欢"],
        note=note,
    )


def stored_feedback(repo, owner_id: str, outfit_id: str) -> OutfitFeedback:
    if isinstance(repo, SessionWardrobeRepository):
        payload = repo.state["owners"][owner_id]["feedback"][outfit_id]
        return OutfitFeedback.model_validate(payload)
    with closing(sqlite3.connect(repo.path)) as connection:
        row = connection.execute(
            "SELECT payload FROM feedback WHERE owner_id = ? AND outfit_id = ?",
            (owner_id, outfit_id),
        ).fetchone()
    return OutfitFeedback.model_validate_json(row[0])


def test_repository_garment_crud_and_owner_isolation(repo):
    first = garment("g-1", "hash-1")
    second = garment("g-2", "hash-2")
    repo.save_garment("owner-1", first)
    repo.save_garment("owner-2", second)

    assert repo.get_garment("owner-1", "g-1") == first
    assert repo.get_garment("owner-1", "g-2") is None
    assert repo.find_garment_by_hash("owner-1", "hash-1") == first
    assert repo.find_garment_by_hash("owner-2", "hash-1") is None
    assert repo.list_garments("owner-1") == [first]
    assert repo.list_garments("owner-2") == [second]

    replacement = first.model_copy(update={"name": "更新后的衬衫"})
    repo.save_garment("owner-1", replacement)

    assert repo.get_garment("owner-1", "g-1") == replacement
    assert repo.list_garments("owner-1") == [replacement]

    repo.delete_garment("owner-1", "g-1")

    assert repo.get_garment("owner-1", "g-1") is None
    assert repo.list_garments("owner-1") == []
    assert repo.get_garment("owner-2", "g-2") == second


def test_repository_profile_favorite_and_feedback_round_trips_are_isolated(repo):
    repo.save_profile("owner-1", {"style_preference": "简约"})
    repo.save_profile("owner-1", {"style_preference": "街头", "height": "171cm"})
    repo.save_profile("owner-2", {"style_preference": "通勤"})

    first_favorite = favorite("owner-1", "outfit-1", "初版理由")
    replacement_favorite = favorite("owner-1", "outfit-1", "更新后的理由")
    other_favorite = favorite("owner-2", "outfit-2", "另一位用户")
    repo.save_favorite(first_favorite)
    repo.save_favorite(replacement_favorite)
    repo.save_favorite(other_favorite)

    repo.save_feedback(feedback("owner-1", "outfit-1", "初始反馈"))
    replacement_feedback = feedback("owner-1", "outfit-1", "更新后的反馈")
    repo.save_feedback(replacement_feedback)
    repo.save_feedback(feedback("owner-2", "outfit-2", "另一位用户的反馈"))

    assert repo.get_profile("owner-1") == {"style_preference": "街头", "height": "171cm"}
    assert repo.get_profile("owner-2") == {"style_preference": "通勤"}
    assert repo.list_favorites("owner-1") == [replacement_favorite]
    assert repo.list_favorites("owner-2") == [other_favorite]
    assert stored_feedback(repo, "owner-1", "outfit-1") == replacement_feedback
    assert stored_feedback(repo, "owner-2", "outfit-2").note == "另一位用户的反馈"


def test_delete_favorite_preserves_other_owner_and_survives_reload(repo):
    repo.save_favorite(favorite("owner-1", "same-id", "自己的收藏"))
    repo.save_favorite(favorite("owner-2", "same-id", "他人的收藏"))
    repo.delete_favorite("owner-1", "same-id")
    repo.delete_favorite("owner-1", "missing")
    if isinstance(repo, SQLiteWardrobeRepository):
        repo = SQLiteWardrobeRepository(repo.path)
    assert repo.list_favorites("owner-1") == []
    assert len(repo.list_favorites("owner-2")) == 1


def test_sqlite_repository_round_trips_through_a_fresh_instance(tmp_path: Path):
    database_path = tmp_path / "stylemate.db"
    original = SQLiteWardrobeRepository(database_path)
    saved_garment = garment("g-1", "hash-1")
    saved_favorite = favorite("owner-1", "outfit-1", "持久化理由")
    saved_feedback = feedback("owner-1", "outfit-1", "持久化反馈")
    original.save_garment("owner-1", saved_garment)
    original.save_profile("owner-1", {"style_preference": "简约"})
    original.save_favorite(saved_favorite)
    original.save_feedback(saved_feedback)

    restored = SQLiteWardrobeRepository(database_path)

    assert restored.list_garments("owner-1") == [saved_garment]
    assert restored.get_profile("owner-1") == {"style_preference": "简约"}
    assert restored.list_favorites("owner-1") == [saved_favorite]
    assert stored_feedback(restored, "owner-1", "outfit-1") == saved_feedback
