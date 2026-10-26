from __future__ import annotations

from langchain_core.messages import AIMessage

from stylemate.agent.service import AgentService
from stylemate.agent.tools.location_weather import WeatherResult
from stylemate.config.runtime import RuntimeSettings
from stylemate.demo.sample_data import sample_garments
from stylemate.domain.models import ConversationState
from stylemate.rag.corpus import load_builtin_records
from stylemate.rag.retriever import HybridRetriever, create_chroma_client
from stylemate.repositories.agent_session import SessionAgentRepository
from stylemate.repositories.session import SessionWardrobeRepository
from stylemate.services.wardrobe_service import WardrobeService
from stylemate.storage.images import SessionImageStore


def service() -> AgentService:
    agent_repo, wardrobe = SessionAgentRepository({}), SessionWardrobeRepository({})
    settings = RuntimeSettings(app_mode="demo", vision_model_name="vision", text_model_name="text")
    retriever = HybridRetriever(load_builtin_records(__import__("pathlib").Path("data/knowledge/records.jsonl")), agent_repo, None, create_chroma_client("demo"))
    return AgentService(settings=settings, agent_repository=agent_repo, wardrobe_repository=wardrobe, wardrobe_service=WardrobeService(wardrobe, SessionImageStore({}), 1024), retriever=retriever, model=None)


def test_chat_persists_recent_messages_and_compacts_older_turns():
    app = service()
    for index in range(12):
        text = "明天去上海面试，想穿得正式但不紧身" if index == 0 else f"第 {index} 轮"
        app.chat("owner-a", "thread-a", text)
    saved = app.repository.load_conversation("owner-a", "thread-a")
    assert len(saved.messages) <= 8
    assert saved.summary == ""
    assert saved.facts.scenes == ["面试"]
    assert saved.facts.locations == ["上海"]
    assert saved.facts.constraints == ["不紧身", "正式"]


def test_old_string_summary_is_migrated_into_structured_facts():
    app = service()
    app.repository.save_conversation(
        ConversationState(
            owner_id="owner-a",
            conversation_id="thread-a",
            summary="旧版本摘要：用户曾咨询羊毛洗护。",
        )
    )

    app.chat("owner-a", "thread-a", "继续")

    saved = app.repository.load_conversation("owner-a", "thread-a")
    assert saved.summary == ""
    assert saved.facts.legacy_notes == ["旧版本摘要：用户曾咨询羊毛洗护。"]


def test_no_key_router_can_use_size_and_rag_tools():
    app = service()
    size_reply = app.chat("owner-a", "thread-a", "165cm 52kg 穿什么尺码")
    rag_reply = app.chat("owner-a", "thread-a", "知识库里羊毛怎么洗")
    assert "参考尺码" in size_reply.content
    assert rag_reply.sources


def test_no_key_router_recognizes_specific_outerwear_care_terms():
    app = service()

    reply = app.chat(
        "owner-a", "thread-a", "GORE-TEX 外套可以使用柔顺剂吗"
    )

    assert "柔顺剂" in reply.content
    assert reply.sources
    assert reply.traces[0].name == "care_guide"


def test_model_network_failure_falls_back_to_deterministic_tools():
    class UnavailableModel:
        def bind_tools(self, _tools):
            return self

        def invoke(self, _messages):
            raise ConnectionError("model unavailable")

    app = service()
    app.model = UnavailableModel()

    reply = app.chat("owner-a", "thread-a", "帮我讲讲我的穿衣偏好")

    assert "模型服务当前不可用" in reply.content
    assert reply.traces[0].name == "model_fallback"
    assert reply.traces[0].status == "fallback"


def test_model_failure_keeps_explicit_wardrobe_search_filters():
    class UnavailableModel:
        def bind_tools(self, _tools):
            return self

        def invoke(self, _messages):
            raise ConnectionError("model unavailable")

    app = service()
    app.model = UnavailableModel()
    for garment in sample_garments():
        app.wardrobe_repository.save_garment("owner-a", garment)

    reply = app.chat(
        "owner-a", "thread-a", "请查看衣橱，告诉我有哪些上装"
    )

    assert "sample-shirt-white" in reply.content
    assert "sample-cardigan-cream" in reply.content
    assert "sample-jeans-blue" not in reply.content


def test_deterministic_outfit_route_preserves_scene_and_exclusions():
    app = service()
    for garment in sample_garments():
        app.wardrobe_repository.save_garment("owner-a", garment)

    reply = app.chat("owner-a", "thread-a", "推荐不穿裙子的通勤搭配")

    assert "符合通勤场景" in reply.content
    assert "sample-skirt-gray" not in reply.content


def test_weather_outfit_shortcut_avoids_model_tool_loop():
    class MarkerModel:
        def bind_tools(self, _tools):
            return self

        def invoke(self, _messages):
            return AIMessage(content="model path")

    app = service()
    app.model = MarkerModel()

    reply = app.chat("owner-a", "thread-a", "根据今天的天气推荐穿搭")

    assert "通用穿搭建议" in reply.content
    assert "当前衣橱还无法组成完整搭配" not in reply.content
    assert all(trace.name != "model_fallback" for trace in reply.traces)


def test_empty_wardrobe_outfit_still_returns_general_knowledge_guidance():
    app = service()

    reply = app.chat("owner-a", "thread-a", "推荐通勤搭配")

    assert "通用穿搭建议" in reply.content
    assert "当前衣橱还无法组成完整搭配" not in reply.content
    assert "搭配规则启发" in reply.content
    assert not reply.sources


def test_purchase_shortcut_collects_missing_conditions():
    app = service()

    purchase = app.chat("owner-a", "thread-a", "推荐购买")

    assert "补充季节或实际温度" in purchase.content
    assert not purchase.sources


def test_travel_shortcut_collects_destination_before_using_tools():
    app = service()

    reply = app.chat("owner-a", "thread-a", "旅游出行")

    assert "目的地" in reply.content
    assert "行程天数" in reply.content
    assert reply.traces == []


def test_travel_follow_up_uses_destination_weather_and_builds_packing_plan():
    class ChengduWeatherClient:
        def weather(self, city):
            assert city == "成都"
            return WeatherResult(
                available=True,
                city="成都市",
                summary="小雨",
                temperature_c=18,
            )

    app = service()
    app.weather_client = ChengduWeatherClient()
    app.chat("owner-a", "thread-a", "旅游出行")

    reply = app.chat("owner-a", "thread-a", "成都，4天，城市观光")

    assert "成都市天气" in reply.content
    assert "18" in reply.content
    assert "行李清单" in reply.content
    assert "雨具" in reply.content
    assert [trace.name for trace in reply.traces] == [
        "get_weather",
        "travel_packing",
    ]


def test_direct_travel_request_extracts_destination_and_days():
    class ChengduWeatherClient:
        def weather(self, city):
            return WeatherResult(
                available=True,
                city=city,
                summary="晴",
                temperature_c=30,
            )

    app = service()
    app.weather_client = ChengduWeatherClient()

    reply = app.chat("owner-a", "thread-a", "去成都旅游4天，主要城市观光")

    assert "成都天气" in reply.content
    assert "4天行程行李清单" in reply.content
    assert "透气" in reply.content


def test_weather_shortcut_passes_live_temperature_into_general_outfit():
    class HotWeatherClient:
        def weather(self, _city):
            return WeatherResult(
                available=True,
                city="武汉市",
                summary="晴",
                temperature_c=34,
            )

    app = service()
    app.weather_client = HotWeatherClient()

    reply = app.chat("owner-a", "thread-a", "天气穿搭")

    assert "透气短袖或亚麻衬衫" in reply.content


def test_model_configured_outfit_intent_keeps_general_guidance_layer():
    class MarkerModel:
        def bind_tools(self, _tools):
            return self

        def invoke(self, _messages):
            return AIMessage(content="inventory only")

    app = service()
    app.model = MarkerModel()

    reply = app.chat("owner-a", "thread-a", "推荐通勤搭配")

    assert "通用穿搭建议" in reply.content
    assert "inventory only" not in reply.content


def test_explicit_preferences_are_proposed_before_they_are_persisted():
    app = service()

    proposed = app.propose_profile_updates(
        "owner-a", "我身高165cm，52kg，不喜欢紧身，偏好简约风格"
    )

    assert proposed == {
        "height": "165cm",
        "weight": "52kg",
        "fit_preference": "宽松",
        "style_preference": "简约",
    }
    assert app.profile_service.get("owner-a") == {}

    saved = app.confirm_profile_updates("owner-a", proposed)
    assert saved["fit_preference"] == "宽松"
    assert saved["style_preference"] == "简约"


def test_clear_removes_messages_and_session_documents_together():
    app = service()
    app.chat("owner-a", "thread-a", "知识库里羊毛怎么洗")
    document = app.ingest_document(
        "owner-a",
        "thread-a",
        "notes.md",
        "text/markdown",
        "羊毛需要低温清洗。".encode("utf-8"),
    )
    assert app.list_documents("owner-a", "thread-a") == [document]

    app.clear("owner-a", "thread-a")

    assert app.repository.load_conversation("owner-a", "thread-a").messages == []
    assert app.list_documents("owner-a", "thread-a") == []
