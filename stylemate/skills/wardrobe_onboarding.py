"""Draft-first multimodal garment onboarding workflow."""

import uuid
from json import JSONDecodeError

from pydantic import BaseModel, ValidationError

from stylemate.domain.models import Garment, SkillOutcome, SkillSpec
from stylemate.gateways.vision import (
    VisionError,
    VisionGateway,
    VisionNotFashion,
    validate_vision_payload,
)
from stylemate.services.wardrobe_service import UploadValidationError, WardrobeService
from stylemate.skills.runtime import SkillRun


class WardrobeOnboardingInput(BaseModel):
    owner_id: str
    image_bytes: bytes
    mime_type: str
    filename: str
    user_note: str = ""


class WardrobeOnboardingSkill:
    spec = SkillSpec(
        name="wardrobe_onboarding",
        description="校验衣物图片、检测重复、生成识别草稿并等待人工确认。",
        input_model=WardrobeOnboardingInput,
        output_model=SkillOutcome,
        allowed_tools=(
            "validate_upload",
            "duplicate_check",
            "vision_analysis",
            "manual_fallback",
        ),
        max_steps=4,
        fallback_strategy="无效上传返回人工录入表；识别失败两次停止入库，保留重试入口。",
    )

    def __init__(self, service: WardrobeService, vision: VisionGateway):
        self.service = service
        self.vision = vision

    def run(
        self,
        owner_id: str,
        image_bytes: bytes,
        mime_type: str,
        filename: str,
        user_note: str,
    ) -> SkillOutcome:
        run = SkillRun(self.spec, WardrobeOnboardingInput(
            owner_id=owner_id, image_bytes=image_bytes, mime_type=mime_type,
            filename=filename, user_note=user_note,
        ), trace_name="WardrobeOnboardingSkill")
        accepted = True
        with run.step("validate_upload") as step:
            try:
                self.service.validate_upload(image_bytes, mime_type)
            except UploadValidationError:
                step.status = "fallback"
                accepted = False
        if not accepted:
            with run.step("manual_fallback") as step:
                step.status = "fallback"
                draft = self._blank_garment()
            return run.finish(status="needs_review",
                              data={"garment": draft, "manual_entry": True, "duplicate": False},
                              message="Upload could not be used; enter garment details manually.")
        with run.step("duplicate_check"):
            duplicate = self.service.find_duplicate(owner_id, image_bytes)
        if duplicate is not None:
            return run.finish(status="needs_review",
                              data={"garment": duplicate.model_dump(mode="json"), "duplicate": True},
                              message="This image already exists in your wardrobe. Review the existing garment.")

        for attempt in range(2):
            rejected = False
            garment = None
            with run.step("vision_analysis") as step:
                try:
                    payload = validate_vision_payload(self.vision.analyze(image_bytes, mime_type, user_note))
                    garment = Garment.model_validate({
                        **payload, "id": str(uuid.uuid4()),
                        "image_hash": self.service.image_hash(image_bytes),
                        "image_ref": None, "source": "ai",
                    })
                except VisionNotFashion:
                    rejected = True
                    step.status = "failed"
                except (TimeoutError, OSError, VisionError, JSONDecodeError, ValidationError, ValueError):
                    step.status = "fallback" if attempt else "failed"
            if rejected:
                return run.finish(status="failed", data={"rejected": True, "reason": "not_fashion"},
                                  message="这张图片未识别为服装、鞋履、包袋或配饰，未进入衣橱。请上传单件衣物的清晰照片。")
            if garment is not None:
                return run.finish(status="needs_review",
                                  data={"garment": garment.model_dump(mode="json"), "duplicate": False},
                                  message="Review and confirm the suggested garment details before saving.")
        return run.finish(status="failed", data={"vision_blocked": True, "reason": "vision_unavailable"},
                          message="多模态模型当前不可用或未返回有效结果，图片未进入衣橱。请稍后重试；如需手工录入，请不要上传图片。")

    @staticmethod
    def _blank_garment() -> dict:
        return {
            "id": str(uuid.uuid4()),
            "name": "",
            "category": "",
            "primary_color": "",
            "material": "",
            "seasons": [],
            "styles": [],
            "confidence": {},
            "image_ref": None,
            "image_hash": None,
            "source": "manual",
        }
