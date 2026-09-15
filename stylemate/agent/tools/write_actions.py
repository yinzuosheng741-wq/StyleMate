"""Prepare, confirm, and cancel owner-scoped wardrobe write actions."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from stylemate.domain.models import Garment, PendingAction
from stylemate.repositories.agent_base import AgentRepository
from stylemate.repositories.base import WardrobeRepository
from stylemate.services.wardrobe_service import ImageCleanupError, WardrobeService

PENDING_ACTION_TTL = timedelta(minutes=10)
UPDATE_FIELDS = frozenset({"name", "category", "primary_color", "material", "seasons", "styles"})


class ActionPreparationError(ValueError):
    """Raised when an action cannot safely be prepared for user confirmation."""


class ActionResult(BaseModel):
    status: Literal["confirmed", "cancelled", "rejected"]
    user_message: str
    action: PendingAction | None = None


class _ManualGarmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    primary_color: str = Field(min_length=1, max_length=80)
    material: str | None = Field(default=None, max_length=80)
    seasons: list[str] = Field(min_length=1, max_length=12)
    styles: list[str] = Field(min_length=1, max_length=12)
    source: Literal["manual"] = "manual"


class _UpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    primary_color: str | None = Field(default=None, min_length=1, max_length=80)
    material: str | None = Field(default=None, max_length=80)
    seasons: list[str] | None = Field(default=None, min_length=1, max_length=12)
    styles: list[str] | None = Field(default=None, min_length=1, max_length=12)

    @model_validator(mode="after")
    def has_a_change(self) -> "_UpdatePayload":
        if not self.model_fields_set:
            raise ValueError("at least one editable field is required")
        return self


def prepare_add_garment(*, owner_id: str, conversation_id: str, metadata: dict[str, Any], agent_repository: AgentRepository, now: datetime | None = None) -> PendingAction:
    """Store a manual-add snapshot only; image recognition stays in the wardrobe UI."""
    _require_identity(owner_id, conversation_id)
    if not isinstance(metadata, dict):
        raise ActionPreparationError("衣物信息格式无效，请重新填写。")
    if any(key in metadata for key in ("image_bytes", "image", "image_ref", "image_hash")):
        raise ActionPreparationError("图片识别请使用“我的衣橱”上传入口，本操作只支持手工填写衣物信息。")
    try:
        payload = _ManualGarmentPayload.model_validate(metadata)
    except ValidationError as exc:
        raise ActionPreparationError("手工衣物信息无效，请检查必填字段。") from exc
    return _save_pending(owner_id=owner_id, conversation_id=conversation_id, operation="add", target_garment_id=payload.id, before=None, after=payload.model_dump(), agent_repository=agent_repository, now=now)


def prepare_update_garment(*, owner_id: str, conversation_id: str, garment_id: str, changes: dict[str, Any], agent_repository: AgentRepository, wardrobe_repository: WardrobeRepository, now: datetime | None = None) -> PendingAction:
    """Snapshot an exact owned garment and an allowlisted change set without writing it."""
    _require_identity(owner_id, conversation_id)
    current = _require_existing_garment(wardrobe_repository, owner_id, garment_id)
    if not isinstance(changes, dict) or set(changes) - UPDATE_FIELDS:
        raise ActionPreparationError("只能修改名称、品类、主色、材质、季节或风格。")
    try:
        payload = _UpdatePayload.model_validate(changes)
    except ValidationError as exc:
        raise ActionPreparationError("修改内容无效，请检查后重试。") from exc
    return _save_pending(owner_id=owner_id, conversation_id=conversation_id, operation="update", target_garment_id=current.id, before=_snapshot(current), after=payload.model_dump(exclude_unset=True), agent_repository=agent_repository, now=now)


def prepare_delete_garment(*, owner_id: str, conversation_id: str, garment_id: str, agent_repository: AgentRepository, wardrobe_repository: WardrobeRepository, now: datetime | None = None) -> PendingAction:
    """Snapshot one exact existing garment for deletion; no repository mutation occurs."""
    _require_identity(owner_id, conversation_id)
    current = _require_existing_garment(wardrobe_repository, owner_id, garment_id)
    return _save_pending(owner_id=owner_id, conversation_id=conversation_id, operation="delete", target_garment_id=current.id, before=_snapshot(current), after=None, agent_repository=agent_repository, now=now)


def confirm_action(*, action_id: str, owner_id: str, conversation_id: str, agent_repository: AgentRepository, wardrobe_repository: WardrobeRepository, wardrobe_service: WardrobeService, now: datetime | None = None) -> ActionResult:
    """Revalidate, apply once, and report cleanup failures without misstating writes."""
    try:
        _require_identity(owner_id, conversation_id)
        action = agent_repository.get_pending(owner_id, conversation_id)
        if action is None or action.id != action_id:
            raise ActionPreparationError("未找到匹配的待确认操作，请重新发起请求。")
        current_time = now or datetime.now(action.expires_at.tzinfo)
        if action.owner_id != owner_id or action.conversation_id != conversation_id:
            raise ActionPreparationError("确认身份或会话不匹配，操作已拒绝。")
        if action.expires_at <= current_time:
            raise ActionPreparationError("该确认操作已过期，请重新发起请求。")
        current = wardrobe_repository.get_garment(owner_id, action.target_garment_id) if action.target_garment_id else None
        _validate_current_snapshot_and_after_payload(action, current)
    except (ActionPreparationError, ValidationError, ValueError, TypeError):
        return ActionResult(status="rejected", user_message="确认条件未通过，尚未执行衣橱更新。")
    except Exception:
        return ActionResult(status="rejected", user_message="确认记录读取失败，尚未执行衣橱更新。")

    try:
        _apply_through_wardrobe_service(action, wardrobe_service)
    except ImageCleanupError:
        # The authoritative garment write already succeeded.  Clearing the snapshot
        # prevents a stale confirmation from being retried as though it had failed.
        try:
            agent_repository.clear_pending(owner_id, conversation_id)
        except Exception:
            return ActionResult(
                status="confirmed",
                user_message="衣物记录已删除，但图片清理和确认记录清理都失败；请不要重复确认。",
                action=action,
            )
        return ActionResult(
            status="confirmed",
            user_message="衣物记录已删除，但关联图片清理失败；请在本地检查后再清理该图片。",
            action=action,
        )
    except Exception:
        return ActionResult(status="rejected", user_message="执行失败，请检查衣橱状态后重试。", action=action)

    try:
        agent_repository.clear_pending(owner_id, conversation_id)
    except Exception:
        return ActionResult(status="confirmed", user_message="衣橱已更新，但确认记录清理失败；操作将过期，请勿重复确认。", action=action)
    return ActionResult(status="confirmed", user_message="已确认并更新衣橱。", action=action)


def cancel_action(*, action_id: str, owner_id: str, conversation_id: str, agent_repository: AgentRepository) -> ActionResult:
    """Cancel only the matching owner and conversation pending snapshot."""
    try:
        _require_identity(owner_id, conversation_id)
        action = agent_repository.get_pending(owner_id, conversation_id)
        if action is None or action.id != action_id or action.owner_id != owner_id or action.conversation_id != conversation_id:
            raise ActionPreparationError("未找到匹配的待确认操作，无法取消。")
        agent_repository.clear_pending(owner_id, conversation_id)
        return ActionResult(status="cancelled", user_message="已取消待确认操作。", action=action)
    except (ActionPreparationError, ValueError, TypeError):
        return ActionResult(status="rejected", user_message="取消条件未通过，衣橱未发生变更。")


def _save_pending(*, owner_id: str, conversation_id: str, operation: Literal["add", "update", "delete"], target_garment_id: str | None, before: dict[str, Any] | None, after: dict[str, Any] | None, agent_repository: AgentRepository, now: datetime | None) -> PendingAction:
    created_at = now or datetime.now()
    action = PendingAction(id=str(uuid4()), owner_id=owner_id, conversation_id=conversation_id, operation=operation, target_garment_id=target_garment_id, before=before, after=after, created_at=created_at, expires_at=created_at + PENDING_ACTION_TTL)
    agent_repository.save_pending(action)
    return action


def _validate_current_snapshot_and_after_payload(action: PendingAction, current: Garment | None) -> None:
    if action.operation == "add":
        if action.before is not None or current is not None or not action.target_garment_id:
            raise ActionPreparationError("新增目标已发生变化。")
        payload = _manual_payload_from_action(action)
        if payload.id != action.target_garment_id:
            raise ActionPreparationError("新增衣物标识不匹配。")
        return
    if current is None or action.before is None or _snapshot(current) != action.before:
        raise ActionPreparationError("衣物已变更或不存在，请重新发起操作。")
    if action.operation == "update":
        _update_payload_from_action(action)
        return
    if action.operation == "delete" and action.after is None:
        return
    raise ActionPreparationError("待确认操作内容无效。")


def _apply_through_wardrobe_service(action: PendingAction, service: WardrobeService) -> None:
    if action.operation == "add":
        service.save_manual(action.owner_id, Garment.model_validate(_manual_payload_from_action(action).model_dump()))
    elif action.operation == "update":
        service.update_confirmed(action.owner_id, _target_id(action), _update_payload_from_action(action).model_dump(exclude_unset=True))
    elif action.operation == "delete":
        service.delete_confirmed(action.owner_id, _target_id(action))
    else:
        raise ActionPreparationError("待确认操作类型无效。")


def _manual_payload_from_action(action: PendingAction) -> _ManualGarmentPayload:
    if action.after is None:
        raise ActionPreparationError("新增衣物信息缺失。")
    try:
        return _ManualGarmentPayload.model_validate(action.after)
    except ValidationError as exc:
        raise ActionPreparationError("新增衣物信息无效。") from exc


def _update_payload_from_action(action: PendingAction) -> _UpdatePayload:
    if action.after is None or set(action.after) - UPDATE_FIELDS:
        raise ActionPreparationError("修改字段无效。")
    try:
        return _UpdatePayload.model_validate(action.after)
    except ValidationError as exc:
        raise ActionPreparationError("修改内容无效。") from exc


def _require_existing_garment(wardrobe_repository: WardrobeRepository, owner_id: str, garment_id: str) -> Garment:
    if not isinstance(garment_id, str) or not garment_id.strip():
        raise ActionPreparationError("请选择衣橱搜索结果中的准确衣物编号。")
    garment = wardrobe_repository.get_garment(owner_id, garment_id)
    if garment is None:
        raise ActionPreparationError("未找到该衣物，请先通过衣橱搜索选择准确编号。")
    return garment


def _require_identity(owner_id: str, conversation_id: str) -> None:
    if not isinstance(owner_id, str) or not owner_id.strip() or not isinstance(conversation_id, str) or not conversation_id.strip():
        raise ActionPreparationError("用户或会话信息无效。")


def _target_id(action: PendingAction) -> str:
    if not action.target_garment_id:
        raise ActionPreparationError("衣物编号缺失。")
    return action.target_garment_id


def _snapshot(garment: Garment) -> dict[str, Any]:
    return garment.model_dump(mode="json")
