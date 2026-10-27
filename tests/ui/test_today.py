from stylemate.agent.tools.location_weather import WeatherResult
from stylemate.demo.sample_data import sample_garments
from stylemate.ui.today import build_packing_plan, open_outfit_guidance, weather_guidance


def test_weather_guidance_adds_rain_specific_advice():
    guidance = weather_guidance(
        WeatherResult(
            available=True,
            city="杭州",
            summary="小雨",
            temperature_c=18,
        )
    )

    assert "轻外套" in guidance.headline
    assert "带伞" in guidance.detail


def test_packing_plan_only_selects_owned_garments_and_surfaces_essentials():
    garments = sample_garments()
    plan = build_packing_plan(
        garments,
        ["sample-cardigan-cream", "sample-skirt-gray"],
        5,
        WeatherResult(
            available=True,
            city="成都",
            summary="小雨",
            temperature_c=20,
        ),
    )

    assert {item.id for item in plan.garments} <= {item.id for item in garments}
    assert plan.garments[0].id == "sample-cardigan-cream"
    assert "折叠伞" in plan.essentials
    assert any("上装数量不足" in gap for gap in plan.gaps)


def test_packing_plan_reports_missing_categories():
    garments = [item for item in sample_garments() if "鞋履" not in item.category]

    plan = build_packing_plan(
        garments,
        [],
        2,
        WeatherResult(available=False, reason="missing_key"),
    )

    assert any("鞋履" in gap for gap in plan.gaps)


def test_open_outfit_guidance_is_available_without_owned_garments():
    guidance = open_outfit_guidance(
        WeatherResult(available=True, summary="晴", temperature_c=32)
    )

    assert "透气短袖" in guidance.top
    assert "轻薄下装" in guidance.bottom
    assert guidance.avoid


def test_workbench_unknown_weather_uses_the_same_category_boundary_as_chat():
    guidance = open_outfit_guidance(WeatherResult(available=False, reason="missing_key"))
    assert "薄针织" not in guidance.top
    assert "温度未知" in guidance.avoid
    assert "未知" in weather_guidance(None).headline
