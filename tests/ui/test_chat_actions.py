from pathlib import Path

from streamlit.testing.v1 import AppTest

from stylemate.domain.models import (
    ConversationMessage,
    ConversationState,
    Garment,
    KnowledgeSource,
    OutfitRecommendation,
)
from stylemate.ui.chat_actions import conversation_export
from tests.test_app_smoke import _disable_model_providers


def desktop(monkeypatch):
    monkeypatch.setenv("APP_MODE", "demo")
    monkeypatch.setenv("STYLEMATE_DESKTOP", "1")
    _disable_model_providers(monkeypatch)
    return AppTest.from_file(str(Path(__file__).parents[2] / "app.py")).run(timeout=20)


def test_task_draft_is_editable_and_sends_only_after_submit(monkeypatch):
    app = desktop(monkeypatch)
    app.button(key="assistant_preset_care").click().run(timeout=20)
    assert not app.exception
    assert not app.chat_message
    assert app.chat_input(key="desktop_chat_input").disabled
    app.text_area(key="stylemate_task_text").set_value("羊毛围巾可以机洗吗？")
    app.button(key="FormSubmitter:stylemate_task_form-发送这个问题").click().run(timeout=20)
    assert not app.exception
    assert len(app.chat_message) == 2
    assert not app.chat_input(key="desktop_chat_input").disabled
    user = [message for message in app.chat_message if message.name == "user"]
    assert user[0].markdown[0].value == "羊毛围巾可以机洗吗？"


def test_empty_task_and_cancel_do_not_execute_and_new_chat_clears_draft(monkeypatch):
    app = desktop(monkeypatch)
    app.button(key="assistant_preset_care").click().run(timeout=20)
    app.text_area(key="stylemate_task_text").set_value("   ")
    app.button(key="FormSubmitter:stylemate_task_form-发送这个问题").click().run(timeout=20)
    assert not app.chat_message
    assert any("请先填写" in item.value for item in app.warning)
    app.button(key="FormSubmitter:stylemate_task_form-取消").click().run(timeout=20)
    assert not app.chat_message
    app.button(key="assistant_preset_travel").click().run(timeout=20)
    app.button(key="desktop_new_chat").click().run(timeout=20)
    assert not app.exception
    assert not app.text_area
    assert not app.chat_input(key="desktop_chat_input").disabled


def test_export_keeps_archive_after_context_forgetting_and_resolves_current_inventory():
    message = ConversationMessage(role="assistant", content="<script>ignore</script>", sources=[
        KnowledgeSource(id="s", title="护理说明", url="https://example.com/care")], outfits=[
        OutfitRecommendation(id="outfit", garment_ids=["owned", "removed"], score=70,
                             reason="ok", constraint_checks={})])
    state = ConversationState(owner_id="alice", conversation_id="one", transcript=[
        ConversationMessage(role="user", content="帮我搭配"), message], summary="INTERNAL_SUMMARY")
    garment = Garment(id="owned", name="当前衬衫", category="上装", primary_color="白色",
                      seasons=["春"], styles=["通勤"], source="manual")
    text = conversation_export(state, [garment])
    assert "帮我搭配" in text and "当前衬衫" in text
    assert "单品已不在当前衣橱" in text and "护理说明" in text
    assert "INTERNAL_SUMMARY" not in text and "<script>" not in text
    assert "成功概率" in text
