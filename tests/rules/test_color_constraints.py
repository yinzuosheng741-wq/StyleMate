from stylemate.domain.models import Garment, OutfitRequest
from stylemate.rules.constraints import excludes_color, extract_color_exclusions
from stylemate.rules.outfit_rules import plan_outfits


def garment(key, category, color):
    return Garment(id=key, name=key, category=category, primary_color=color,
                   seasons=["春"], styles=["通勤"], source="manual")


def test_explicit_color_constraints_filter_before_ranking():
    garments = [garment("black-top", "上装", "黑色"), garment("white-top", "上装", "白色"),
                garment("blue-bottom", "下装", "蓝色")]
    result = plan_outfits(OutfitRequest(scene="通勤", extra_constraints=["不穿黑色"]), garments)
    assert result
    assert all("black-top" not in item.garment_ids for item in result)
    assert all(item.constraint_checks["exclusions"] for item in result)


def test_infeasible_color_constraint_returns_no_inventory_outfit():
    garments = [garment("top", "上装", "黑色"), garment("bottom", "下装", "蓝色")]
    assert plan_outfits(OutfitRequest(scene="通勤", extra_constraints=["不穿黑色"]), garments) == []


def test_category_specific_color_exclusion_does_not_exclude_other_categories():
    assert excludes_color("黑色", "上装", ["不穿黑色上衣"])
    assert not excludes_color("黑色", "下装", ["不穿黑色上衣"])
    assert not excludes_color("白色", "上装", ["不穿黑色上衣"])


def test_negation_and_soft_preferences_do_not_become_hard_exclusions():
    assert extract_color_exclusions("不是不穿黑色，只是今天喜欢白色") == []
    assert extract_color_exclusions("不要排除黑色") == []
    assert extract_color_exclusions("我不喜欢黑色") == []
