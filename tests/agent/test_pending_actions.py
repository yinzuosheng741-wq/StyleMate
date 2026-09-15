from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from stylemate.agent.tools.write_actions import (
    ActionPreparationError,
    cancel_action,
    confirm_action,
    prepare_add_garment,
    prepare_delete_garment,
    prepare_update_garment,
)
from stylemate.domain.models import Garment
from stylemate.repositories.agent_session import SessionAgentRepository
from stylemate.repositories.session import SessionWardrobeRepository
from stylemate.services.wardrobe_service import WardrobeService
from stylemate.storage.images import SessionImageStore

OWNER = "owner-a"
CONVERSATION = "thread-1"


class Harness:
    def __init__(self):
        self.wardrobe = SessionWardrobeRepository({})
        self.agent = SessionAgentRepository({})
        self.service = WardrobeService(
            self.wardrobe, SessionImageStore({}), max_upload_bytes=8 * 1024 * 1024
        )
        self.wardrobe.save_garment(OWNER, garment("g-1"))

    def prepare_add(self, metadata: dict | None = None):
        return prepare_add_garment(
            owner_id=OWNER,
            conversation_id=CONVERSATION,
            metadata=metadata or add_metadata(),
            agent_repository=self.agent,
        )

    def prepare_update(self, garment_id: str = "g-1", changes: dict | None = None):
        return prepare_update_garment(
            owner_id=OWNER,
            conversation_id=CONVERSATION,
            garment_id=garment_id,
            changes=changes or {"styles": ["通勤", "简约"]},
            agent_repository=self.agent,
            wardrobe_repository=self.wardrobe,
        )

    def prepare_delete(self, garment_id: str = "g-1"):
        return prepare_delete_garment(
            owner_id=OWNER,
            conversation_id=CONVERSATION,
            garment_id=garment_id,
            agent_repository=self.agent,
            wardrobe_repository=self.wardrobe,
        )

    def confirm(self, action_id: str, *, owner_id: str = OWNER, conversation_id: str = CONVERSATION):
        return confirm_action(
            action_id=action_id,
            owner_id=owner_id,
            conversation_id=conversation_id,
            agent_repository=self.agent,
            wardrobe_repository=self.wardrobe,
            wardrobe_service=self.service,
        )

    def cancel(self, action_id: str, *, owner_id: str = OWNER, conversation_id: str = CONVERSATION):
        return cancel_action(
            action_id=action_id,
            owner_id=owner_id,
            conversation_id=conversation_id,
            agent_repository=self.agent,
        )


@pytest.fixture
def harness():
    return Harness()


def garment(garment_id: str) -> Garment:
    return Garment(
        id=garment_id,
        name="米色风衣",
        category="外套",
        primary_color="米色",
        material="棉",
        seasons=["春", "秋"],
        styles=["通勤"],
        source="manual",
    )


def add_metadata() -> dict:
    return {
        "id": "g-new",
        "name": "白衬衫",
        "category": "上装",
        "primary_color": "白色",
        "material": "棉",
        "seasons": ["春", "夏"],
        "styles": ["通勤"],
    }


def test_prepare_actions_persist_one_ten_minute_snapshot_without_mutating_wardrobe(harness):
    initial = harness.wardrobe.get_garment(OWNER, "g-1")

    add = harness.prepare_add()
    assert add.operation == "add"
    assert add.before is None
    assert add.target_garment_id == "g-new"
    assert timedelta(minutes=9, seconds=59) <= add.expires_at - add.created_at <= timedelta(minutes=10)
    assert harness.wardrobe.get_garment(OWNER, "g-new") is None
    assert harness.agent.get_pending(OWNER, CONVERSATION) == add

    update = harness.prepare_update()
    assert update.operation == "update"
    assert update.before == initial.model_dump(mode="json")
    assert harness.wardrobe.get_garment(OWNER, "g-1") == initial
    assert harness.agent.get_pending(OWNER, CONVERSATION) == update

    delete = harness.prepare_delete()
    assert delete.operation == "delete"
    assert delete.before == initial.model_dump(mode="json")
    assert harness.wardrobe.get_garment(OWNER, "g-1") == initial
    assert harness.agent.get_pending(OWNER, CONVERSATION) == delete


def test_confirm_successfully_adds_manual_metadata_only_and_clears_pending(harness):
    action = harness.prepare_add()

    result = harness.confirm(action.id)

    saved = harness.wardrobe.get_garment(OWNER, "g-new")
    assert result.status == "confirmed"
    assert saved is not None
    assert saved.source == "manual"
    assert saved.image_ref is None
    assert harness.agent.get_pending(OWNER, CONVERSATION) is None


def test_confirm_successfully_updates_whitelisted_fields_and_clears_pending(harness):
    action = harness.prepare_update(changes={"name": "新名称", "styles": ["通勤", "简约"]})

    result = harness.confirm(action.id)

    saved = harness.wardrobe.get_garment(OWNER, "g-1")
    assert result.status == "confirmed"
    assert saved.name == "新名称"
    assert saved.styles == ["通勤", "简约"]
    assert harness.agent.get_pending(OWNER, CONVERSATION) is None


def test_confirm_successfully_deletes_exact_existing_garment_and_clears_pending(harness):
    action = harness.prepare_delete()

    result = harness.confirm(action.id)

    assert result.status == "confirmed"
    assert harness.wardrobe.get_garment(OWNER, "g-1") is None
    assert harness.agent.get_pending(OWNER, CONVERSATION) is None


@pytest.mark.parametrize(
    ("owner_id", "conversation_id", "action_id"),
    [("owner-b", CONVERSATION, None), (OWNER, "thread-b", None), (OWNER, CONVERSATION, "wrong-action")],
)
def test_confirm_rejects_identity_or_action_mismatch_without_mutation(
    harness, owner_id, conversation_id, action_id
):
    action = harness.prepare_delete()

    result = harness.confirm(action_id or action.id, owner_id=owner_id, conversation_id=conversation_id)

    assert result.status == "rejected"
    assert harness.wardrobe.get_garment(OWNER, "g-1") is not None
    assert harness.agent.get_pending(OWNER, CONVERSATION) == action


def test_confirm_revalidates_expiry_target_existence_and_before_snapshot(harness):
    action = harness.prepare_update()
    expired = action.model_copy(update={"expires_at": datetime.now() - timedelta(seconds=1)})
    harness.agent.save_pending(expired)

    assert harness.confirm(action.id).status == "rejected"
    assert harness.wardrobe.get_garment(OWNER, "g-1").styles == ["通勤"]

    action = harness.prepare_update()
    harness.wardrobe.delete_garment(OWNER, "g-1")
    assert harness.confirm(action.id).status == "rejected"
    assert harness.wardrobe.get_garment(OWNER, "g-1") is None

    harness.wardrobe.save_garment(OWNER, garment("g-1").model_copy(update={"name": "并发修改"}))
    action = harness.prepare_update()
    harness.wardrobe.save_garment(OWNER, garment("g-1").model_copy(update={"name": "再次并发修改"}))
    assert harness.confirm(action.id).status == "rejected"
    assert harness.wardrobe.get_garment(OWNER, "g-1").name == "再次并发修改"


def test_confirm_revalidates_add_target_and_after_payload_without_mutation(harness):
    action = harness.prepare_add()
    harness.wardrobe.save_garment(OWNER, garment("g-new"))

    assert harness.confirm(action.id).status == "rejected"
    assert harness.wardrobe.get_garment(OWNER, "g-new").name == "米色风衣"

    action = harness.prepare_update()
    harness.agent.save_pending(action.model_copy(update={"after": {"image_ref": "forbidden"}}))
    assert harness.confirm(action.id).status == "rejected"
    assert harness.wardrobe.get_garment(OWNER, "g-1").name == "米色风衣"


def test_prepare_rejects_images_nonwhitelisted_updates_and_unknown_delete_target(harness):
    with pytest.raises(ActionPreparationError, match="我的衣橱"):
        harness.prepare_add({**add_metadata(), "image_bytes": b"not allowed"})
    with pytest.raises(ActionPreparationError):
        harness.prepare_update(changes={"source": "ai"})
    with pytest.raises(ActionPreparationError):
        harness.prepare_delete("not-found")
    assert harness.wardrobe.get_garment(OWNER, "g-1") is not None
    assert harness.agent.get_pending(OWNER, CONVERSATION) is None


def test_cancel_discards_only_matching_action_without_mutating_or_calling_service(harness, monkeypatch):
    action = harness.prepare_delete()
    service_call = Mock(wraps=harness.service.delete_confirmed)
    monkeypatch.setattr(harness.service, "delete_confirmed", service_call)

    rejected = harness.cancel(action.id, owner_id="owner-b")
    assert rejected.status == "rejected"
    assert harness.agent.get_pending(OWNER, CONVERSATION) == action

    result = harness.cancel(action.id)
    assert result.status == "cancelled"
    assert harness.agent.get_pending(OWNER, CONVERSATION) is None
    assert harness.wardrobe.get_garment(OWNER, "g-1") is not None
    service_call.assert_not_called()


def test_service_failure_rejects_without_clearing_pending_or_mutating(harness, monkeypatch):
    action = harness.prepare_delete()

    def fail_delete(*_args):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(harness.service, "delete_confirmed", fail_delete)

    assert harness.confirm(action.id).status == "rejected"
    assert harness.agent.get_pending(OWNER, CONVERSATION) == action
    assert harness.wardrobe.get_garment(OWNER, "g-1") is not None


def test_material_can_be_explicitly_cleared_on_confirm(harness):
    action = harness.prepare_update(changes={"material": None})

    assert action.after == {"material": None}
    assert harness.confirm(action.id).status == "confirmed"
    assert harness.wardrobe.get_garment(OWNER, "g-1").material is None


def test_cleanup_failure_after_add_reports_confirmed_and_prevents_second_write(harness, monkeypatch):
    action = harness.prepare_add()
    save_call = Mock(wraps=harness.service.save_manual)
    monkeypatch.setattr(harness.service, "save_manual", save_call)

    def fail_clear(*_args):
        raise RuntimeError("pending database unavailable")

    monkeypatch.setattr(harness.agent, "clear_pending", fail_clear)

    result = harness.confirm(action.id)

    assert result.status == "confirmed"
    assert "\u8863\u6a71\u5df2\u66f4\u65b0\uff0c\u4f46\u786e\u8ba4\u8bb0\u5f55\u6e05\u7406\u5931\u8d25" in result.user_message
    assert "\u8bf7\u52ff\u91cd\u590d" in result.user_message
    assert harness.wardrobe.get_garment(OWNER, "g-new") is not None
    assert harness.agent.get_pending(OWNER, CONVERSATION) == action
    assert save_call.call_count == 1

    retry = harness.confirm(action.id)
    assert retry.status == "rejected"
    assert save_call.call_count == 1


def test_cleanup_failure_after_noop_update_keeps_pending_without_repeat_write(harness, monkeypatch):
    action = harness.prepare_update(changes={"name": harness.wardrobe.get_garment(OWNER, "g-1").name})
    save_call = Mock(wraps=harness.wardrobe.save_garment)
    monkeypatch.setattr(harness.wardrobe, "save_garment", save_call)

    def fail_clear(*_args):
        raise RuntimeError("pending database unavailable")

    monkeypatch.setattr(harness.agent, "clear_pending", fail_clear)

    first = harness.confirm(action.id)
    retry = harness.confirm(action.id)

    assert first.status == retry.status == "confirmed"
    assert "\u786e\u8ba4\u8bb0\u5f55\u6e05\u7406\u5931\u8d25" in first.user_message
    assert harness.agent.get_pending(OWNER, CONVERSATION) == action
    save_call.assert_not_called()


def test_image_cleanup_failure_after_delete_is_confirmed_and_consumes_pending(harness, monkeypatch):
    action = harness.prepare_delete()

    def fail_after_delete(owner_id, garment_id):
        harness.wardrobe.delete_garment(owner_id, garment_id)
        from stylemate.services.wardrobe_service import ImageCleanupError

        raise ImageCleanupError("image cleanup failed")

    monkeypatch.setattr(harness.service, "delete_confirmed", fail_after_delete)

    result = harness.confirm(action.id)

    assert result.status == "confirmed"
    assert "图片清理失败" in result.user_message
    assert harness.wardrobe.get_garment(OWNER, "g-1") is None
    assert harness.agent.get_pending(OWNER, CONVERSATION) is None
