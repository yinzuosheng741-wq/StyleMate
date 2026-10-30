"""Selected-item advice must stay grounded in the current owner's inventory."""

from stylemate.agent.tools.location_weather import WeatherResult
from stylemate.demo.sample_data import sample_garments
from tests.agent.test_service import service


def populated():
    app = service()
    items = sample_garments()
    for item in items:
        app.wardrobe_repository.save_garment("owner-a", item)
    return app, items


def test_selected_item_outfits_must_include_exact_item_and_show_names():
    class Weather:
        def weather(self, _city):
            return WeatherResult(available=True, city="示例", summary="晴", temperature_c=20)

    app, items = populated()
    app.weather_client = Weather()
    target = items[0]
    reply = app.chat("owner-a", "thread-a", "如果今天穿这个，怎么搭配？", garment_id=target.id)
    assert target.name in reply.content
    assert reply.outfits and all(target.id in outfit.garment_ids for outfit in reply.outfits)
    assert [trace.name for trace in reply.traces] == ["get_garment", "get_weather", "recommend_inventory_outfit"]
    saved = app.repository.load_conversation("owner-a", "thread-a")
    assert "关联衣物" in saved.transcript[-2].content


def test_selected_shoe_is_not_lost_when_equivalent_shoes_are_deduplicated():
    app, items = populated()
    original = next(item for item in items if item.category == "鞋履")
    chosen = original.model_copy(update={"id": "zz-selected-shoe", "name": "我的第二双黑鞋"})
    app.wardrobe_repository.save_garment("owner-a", chosen)
    reply = app.chat("owner-a", "thread-a", "这双鞋怎么搭配", garment_id=chosen.id)
    assert reply.outfits and all(chosen.id in outfit.garment_ids for outfit in reply.outfits)


def test_selected_item_never_bypasses_explicit_exclusions():
    app, items = populated()
    target = next(item for item in items if item.category == "鞋履")
    reply = app.chat("owner-a", "thread-a", "这双鞋怎么搭配，不要黑色", garment_id=target.id)
    assert not reply.outfits and "没有符合条件" in reply.content


def test_explicitly_excluding_selected_item_never_recommends_it():
    app, items = populated()
    reply = app.chat("owner-a", "thread-a", "这件不穿，帮我搭配", garment_id=items[0].id)
    assert not reply.outfits and "不穿" in reply.content


def test_unknown_material_requests_label_and_named_wool_uses_cited_care():
    app, items = populated()
    unknown = items[0]
    reply = app.chat("owner-a", "thread-a", "这个怎么洗", garment_id=unknown.id)
    assert "材质" in reply.content and "标签" in reply.content and not reply.sources
    wool = unknown.model_copy(update={"id": "wool-item", "name": "羊毛上衣", "material": "羊毛"})
    app.wardrobe_repository.save_garment("owner-a", wool)
    reply = app.chat("owner-a", "thread-a", "羊毛上衣怎么洗")
    assert wool.name in reply.content and "洗护标签" in reply.content and reply.sources
    assert [trace.name for trace in reply.traces] == ["get_garment", "care_guide"]


def test_foreign_or_missing_item_never_uses_other_inventory():
    app, items = populated()
    reply = app.chat("owner-b", "thread-b", "这个怎么搭配", garment_id=items[0].id)
    assert "未找到" in reply.content and not reply.outfits
    reply = app.chat("owner-a", "thread-a", "这件怎么洗")
    assert "选择" in reply.content and not reply.sources


def test_duplicate_name_requires_user_selection():
    app, items = populated()
    app.wardrobe_repository.save_garment("owner-a", items[0].model_copy(update={"id": "duplicate"}))
    reply = app.chat("owner-a", "thread-a", items[0].name + "怎么搭配")
    assert "同名" in reply.content and not reply.outfits


def test_explicit_other_garment_name_takes_priority_over_selected_item():
    app, items = populated()
    reply = app.chat("owner-a", "thread-a", items[1].name + "怎么洗", garment_id=items[0].id)
    assert items[1].name in reply.content
    assert items[0].name not in reply.content
