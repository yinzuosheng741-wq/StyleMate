from datetime import datetime, timedelta

from langchain_core.messages import HumanMessage, SystemMessage

from stylemate.agent.memory import prune_expired_facts, update_conversation_facts
from stylemate.agent.state import initial_state, model_messages
from stylemate.domain.models import ConversationFacts, ConversationMessage


def test_model_context_renders_structured_facts_instead_of_free_text_summary():
    state = initial_state(
        "接着推荐",
        facts=ConversationFacts(
            topics=["outfit"],
            scenes=["面试"],
            locations=["上海"],
            constraints=["不紧身"],
        ),
    )

    messages = model_messages(state, "system")

    system_text = "\n".join(
        message.content for message in messages if isinstance(message, HumanMessage)
    )
    assert '"scenes":["面试"]' in system_text
    assert '"constraints":["不紧身"]' in system_text
    assert "对话摘要" not in system_text
    assert [m.content for m in messages if isinstance(m, SystemMessage)] == ["system"]


def test_initial_state_accepts_legacy_summary_for_rolling_migration():
    state = initial_state("继续", summary="旧摘要")

    assert state["conversation_facts"]["legacy_notes"] == ["旧摘要"]


def test_memory_extracts_id_after_garment_label():
    facts = update_conversation_facts(
        ConversationFacts(),
        ConversationMessage(
            role="user", content="分析衣物 ID: sample-shirt-white"
        ),
    )

    assert facts.garment_ids == ["sample-shirt-white"]


def test_memory_records_fact_provenance_and_expires_temporary_constraints():
    created_at = datetime(2026, 8, 17, 9, 0, 0)
    message = ConversationMessage(
        role="user",
        content="明天去上海面试，需要正式但不紧身",
        created_at=created_at,
    )

    facts = update_conversation_facts(
        ConversationFacts(), message, now=created_at
    )

    formal = next(
        item
        for item in facts.provenance
        if item.field == "constraints" and item.value == "正式"
    )
    assert formal.source_message_id == message.id
    assert formal.updated_at == created_at
    assert formal.expires_at == created_at + timedelta(hours=24)

    expired = prune_expired_facts(facts, created_at + timedelta(hours=25))
    assert expired.constraints == []
    assert expired.scenes == ["面试"]
    assert expired.locations == ["上海"]


def test_explicit_correction_replaces_active_scene_and_location():
    facts = update_conversation_facts(
        ConversationFacts(),
        ConversationMessage(role="user", content="明天去上海面试"),
    )

    corrected = update_conversation_facts(
        facts,
        ConversationMessage(role="user", content="更正，改成杭州通勤"),
    )

    assert corrected.scenes == ["通勤"]
    assert corrected.locations == ["杭州"]
    assert {
        item.value for item in corrected.provenance if item.field == "locations"
    } == {"杭州"}
