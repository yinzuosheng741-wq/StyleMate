"""Application context and validation tests, retained after web UI removal."""
import pytest

from stylemate.config.runtime import RuntimeSettings
from stylemate.demo.sample_data import sample_garments
from stylemate.services.context import build_context, load_sample_wardrobe, validated_garment_update


def settings(mode: str) -> RuntimeSettings:
    return RuntimeSettings(
        app_mode=mode,
        vision_model_name="vision-test",
        text_model_name="text-test",
    )


def test_demo_context_reuses_session_state():
    state = {}

    first = build_context(state, settings("demo"))
    second = build_context(state, settings("demo"))

    assert first.repository is second.repository
    assert first.image_store is second.image_store
    assert first.agent_repository is second.agent_repository
    assert first.conversation_id == second.conversation_id
    assert first.owner_id == "demo-user"


def test_sample_load_is_idempotent():
    context = build_context({}, settings("demo"))

    assert load_sample_wardrobe(context) == 6
    assert load_sample_wardrobe(context) == 0
    assert len(context.repository.list_garments(context.owner_id)) == 6


def test_invalid_edit_is_rejected_without_changing_saved_garment():
    context = build_context({}, settings("demo"))
    original = sample_garments()[0]
    context.repository.save_garment(context.owner_id, original)

    with pytest.raises(ValueError):
        validated_garment_update(
            original,
            name="   ",
            category=original.category,
            primary_color=original.primary_color,
            material=original.material,
            seasons="春，秋",
            styles="通勤，简约",
        )

    assert context.repository.get_garment(context.owner_id, original.id) == original
