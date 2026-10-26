from stylemate.agent.middleware import ToolContext
from stylemate.agent.tools.styling import (
    care_guide,
    get_user_location,
    get_weather,
    rag_search,
    recommend_open_outfit,
    recommend_purchases,
    recommend_size,
    travel_packing,
)
from stylemate.rag.models import RetrievalHit
from stylemate.repositories.session import SessionWardrobeRepository


class FakeAmap:
    def __init__(self):
        self.weather_city = None

    def locate(self):
        return type("Location", (), {"available": True, "city": "杭州", "province": "浙江", "adcode": "330100", "reason": ""})()

    def weather(self, city):
        self.weather_city = city
        return type("Weather", (), {"available": True, "city": city, "summary": "晴", "temperature_c": 28.0, "humidity": 50, "reason": ""})()


class FakeRetriever:
    def __init__(self):
        self.calls = []

    def search(self, query, owner_id, conversation_id, top_k=4):
        self.calls.append((query, owner_id, conversation_id, top_k))
        return [
            RetrievalHit(
                title="棉质衣物护理",
                snippet="低温轻柔洗涤。",
                source_name="care.md",
                source_url="https://example.test/care",
                topic="care",
                score=0.9,
            )
        ]


def _context():
    return ToolContext(
        owner_id="owner-a",
        app_mode="demo",
        wardrobe_repository=SessionWardrobeRepository({}),
        retriever=FakeRetriever(),
        amap_client=FakeAmap(),
        settings=None,
        conversation_id="conversation-a",
    )


def test_location_and_weather_delegate_only_to_typed_amap_client():
    context = _context()

    location = get_user_location({}, context)
    weather = get_weather({"city": "杭州"}, context)

    assert location["city"] == "杭州"
    assert weather["summary"] == "晴"
    assert context.amap_client.weather_city == "杭州"


def test_size_recommendation_is_bounded_and_explicitly_a_reference():
    result = recommend_size({"height_cm": 165, "weight_kg": 52, "fit_preference": "标准"}, _context())

    assert result["recommended_size"]
    assert "参考" in result["reference_note"]
    assert "通用" not in result["reference_note"]


def test_rag_backed_tools_preserve_citations_and_owner_context():
    context = _context()

    care = care_guide({"material": "棉"}, context)
    search = rag_search({"query": "棉质衣物如何清洗"}, context)

    assert care["sources"][0]["url"] == "https://example.test/care"
    assert search["sources"][0]["title"] == "棉质衣物护理"
    assert all(call[1:3] == ("owner-a", "conversation-a") for call in context.retriever.calls)


def test_travel_packing_adapts_to_weather_and_activity():
    result = travel_packing(
        {
            "destination": "成都",
            "days": 4,
            "activities": ["城市观光"],
            "temperature_c": 18,
            "weather_condition": "小雨",
        },
        _context(),
    )

    assert result["destination"] == "成都"
    assert result["days"] == 4
    assert any("雨具" in item for item in result["packing_list"])
    assert any("外套" in item for item in result["packing_list"])
    assert result["weather_summary"] == "小雨，18°C"


def test_heuristic_outfit_does_not_attach_unrelated_retrieval_sources():
    context = _context()
    result = recommend_open_outfit({"scene": "通勤", "temperature_c": 30}, context)
    assert result["sources"] == []
    assert result["recommendation_basis"] == "project_heuristic"
    assert context.retriever.calls == []
    assert "透气短袖" in result["recommendation"]


def test_unknown_temperature_does_not_become_a_silent_mild_weather_assumption():
    result = recommend_open_outfit({"scene": "通勤"}, _context())
    assert result["conditions"]["temperature_c"] is None
    assert result["missing_conditions"] == ["temperature_c"]
    assert "温度未知" in result["recommendation"]
    assert "长袖衬衫或薄针织" not in result["recommendation"]


def test_purchase_requires_season_or_temperature_and_has_no_authority_citation():
    context = _context()
    missing = recommend_purchases({}, context)
    seasonal = recommend_purchases({"season": "夏"}, context)
    assert missing["priorities"] == []
    assert missing["missing_conditions"] == ["season_or_temperature"]
    assert seasonal["temperature_c"] is None
    assert seasonal["priorities"]
    assert seasonal["sources"] == []
    assert context.retriever.calls == []


def test_complete_inventory_does_not_trigger_arbitrary_purchase_suggestions():
    from stylemate.demo.sample_data import sample_garments

    context = _context()
    for garment in sample_garments():
        context.wardrobe_repository.save_garment(context.owner_id, garment)
    result = recommend_purchases({"season": "夏"}, context)
    assert result["priorities"] == []
    assert "无需" in result["message"]


def test_weather_typed_timeout_is_retried_by_executor_without_trace_leak():
    from dataclasses import replace

    from stylemate.agent.middleware import ToolExecutor
    from stylemate.domain.models import ToolSpec

    class FlakyAmap:
        def __init__(self):
            self.calls = 0

        def weather(self, _city):
            self.calls += 1
            if self.calls == 1:
                return type("Weather", (), {"available": False, "city": "", "summary": "", "temperature_c": None, "humidity": None, "reason": "timeout"})()
            return type("Weather", (), {"available": True, "city": "hangzhou", "summary": "sunny", "temperature_c": 28.0, "humidity": 50, "reason": ""})()

    context = replace(_context(), amap_client=FlakyAmap())
    result = ToolExecutor().execute(
        ToolSpec(name="get_weather", permission="read", timeout_seconds=2, retry_once=True),
        {"city": "hangzhou"},
        context,
        get_weather,
    )

    assert context.amap_client.calls == 2
    assert result.status == "success"
    assert "sk-test" not in result.trace.summary


def test_location_typed_upstream_error_is_retried_by_executor_without_trace_leak():
    from dataclasses import replace

    from stylemate.agent.middleware import ToolExecutor
    from stylemate.domain.models import ToolSpec

    class FlakyAmap:
        def __init__(self):
            self.calls = 0

        def locate(self):
            self.calls += 1
            if self.calls == 1:
                return type("Location", (), {"available": False, "city": "", "province": "", "adcode": "", "reason": "upstream_error"})()
            return type("Location", (), {"available": True, "city": "hangzhou", "province": "zhejiang", "adcode": "330100", "reason": ""})()

    context = replace(_context(), amap_client=FlakyAmap())
    result = ToolExecutor().execute(
        ToolSpec(name="get_user_location", permission="read", timeout_seconds=2, retry_once=True),
        {},
        context,
        get_user_location,
    )

    assert context.amap_client.calls == 2
    assert result.status == "success"
    assert "sk-test" not in result.trace.summary


def test_weather_missing_key_is_not_retried():
    from dataclasses import replace

    from stylemate.agent.middleware import ToolExecutor
    from stylemate.domain.models import ToolSpec

    class MissingKeyAmap:
        def __init__(self):
            self.calls = 0

        def weather(self, _city):
            self.calls += 1
            return type("Weather", (), {"available": False, "city": "", "summary": "", "temperature_c": None, "humidity": None, "reason": "missing_key"})()

    context = replace(_context(), amap_client=MissingKeyAmap())
    result = ToolExecutor().execute(
        ToolSpec(name="get_weather", permission="read", timeout_seconds=2, retry_once=True),
        {"city": "hangzhou"},
        context,
        get_weather,
    )

    assert context.amap_client.calls == 1
    assert result.status == "success"
