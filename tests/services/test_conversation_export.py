"""Conversation archive export, independent of any web interface."""
from stylemate.domain.models import (
    ConversationMessage,
    ConversationState,
    Garment,
    KnowledgeSource,
    OutfitRecommendation,
)
from stylemate.services.conversation_export import conversation_export


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
