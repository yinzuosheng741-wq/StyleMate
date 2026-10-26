from stylemate.domain.models import Garment, OutfitRequest
from stylemate.rules.outfit_rules import plan_outfits


def _garment(garment_id: str, category: str) -> Garment:
    return Garment(
        id=garment_id,
        name=garment_id,
        category=category,
        primary_color="black",
        seasons=["spring"],
        styles=["commute"],
        source="manual",
    )


def test_plan_uses_only_candidate_inventory(sample_garments):
    candidates = sample_garments[:4]
    request = OutfitRequest(
        scene="\u901a\u52e4",
        style_preference="\u7b80\u7ea6",
        candidate_garment_ids=[item.id for item in candidates],
    )

    results = plan_outfits(request, sample_garments)

    allowed = {item.id for item in candidates}
    assert 1 <= len(results) <= 3
    assert all(set(item.garment_ids) <= allowed for item in results)
    assert all(item.constraint_checks["inventory"] for item in results)


def test_plan_is_deterministic(sample_garments):
    request = OutfitRequest(scene="\u901a\u52e4")

    first = [
        item.model_dump(mode="json", exclude={"created_at"})
        for item in plan_outfits(request, sample_garments)
    ]
    second = [
        item.model_dump(mode="json", exclude={"created_at"})
        for item in plan_outfits(request, sample_garments)
    ]

    assert first == second


def test_plan_never_returns_more_than_three_outfits(sample_garments):
    results = plan_outfits(OutfitRequest(scene="\u901a\u52e4"), sample_garments, limit=10)

    assert len(results) == 3


def test_plan_rejects_single_garment_matching_both_mandatory_roles():
    all_in_one = _garment(
        "all-in-one",
        "\u4e0a\u88c5 \u4e0b\u88c5 \u978b\u5c65 \u5916\u5957",
    )

    results = plan_outfits(OutfitRequest(scene="\u901a\u52e4"), [all_in_one])

    assert results == []


def test_plan_outputs_keep_grounded_recommendation_invariants(sample_garments):
    results = plan_outfits(OutfitRequest(scene="\u901a\u52e4"), sample_garments)

    inventory_ids = {garment.id for garment in sample_garments}
    combinations = [tuple(sorted(item.garment_ids)) for item in results]
    assert all(
        set(item.constraint_checks)
        == {"inventory", "top_bottom", "season", "weather", "exclusions"}
        for item in results
    )
    assert all(0 <= item.score <= 100 for item in results)
    assert len(combinations) == len(set(combinations))
    assert all(set(item.garment_ids) <= inventory_ids for item in results)


def test_cold_weather_requires_outerwear_and_hot_weather_excludes_it(sample_garments):
    cold = plan_outfits(
        OutfitRequest(scene="通勤", temperature_c=8), sample_garments
    )
    hot = plan_outfits(
        OutfitRequest(scene="通勤", temperature_c=28), sample_garments
    )

    assert cold and all("sample-trench-beige" in item.garment_ids for item in cold)
    assert hot and all("sample-trench-beige" not in item.garment_ids for item in hot)
    assert all("sample-cardigan-cream" not in item.garment_ids for item in hot)
    assert all(item.constraint_checks["weather"] for item in [*cold, *hot])


def test_season_and_explicit_exclusions_are_hard_constraints(sample_garments):
    winter = plan_outfits(
        OutfitRequest(scene="通勤", target_season="冬"), sample_garments
    )
    no_skirts = plan_outfits(
        OutfitRequest(scene="通勤", extra_constraints=["不穿裙子"]), sample_garments
    )

    assert winter == []
    assert no_skirts
    assert all("sample-skirt-gray" not in item.garment_ids for item in no_skirts)


def test_results_use_distinct_top_bottom_pairs_and_expose_score_breakdown(sample_garments):
    results = plan_outfits(OutfitRequest(scene="通勤"), sample_garments)

    core_pairs = [
        tuple(
            garment_id
            for garment_id in item.garment_ids
            if garment_id in {"sample-shirt-white", "sample-cardigan-cream", "sample-jeans-blue", "sample-skirt-gray"}
        )
        for item in results
    ]
    assert len(core_pairs) == len(set(core_pairs))
    assert all(sum(item.score_breakdown.values()) >= item.score for item in results)


def test_dress_is_a_complete_alternative_and_still_obeys_weather_and_exclusions():
    garments = [_garment("dress", "连衣裙"), _garment("shoe", "鞋履"), _garment("coat", "外套")]
    warm = plan_outfits(OutfitRequest(scene="通勤", temperature_c=28), garments)
    cold = plan_outfits(OutfitRequest(scene="通勤", temperature_c=8), garments)
    assert warm and all("dress" in item.garment_ids and "coat" not in item.garment_ids for item in warm)
    assert cold and all("coat" in item.garment_ids for item in cold)
    assert plan_outfits(OutfitRequest(scene="通勤", extra_constraints=["不穿裙子"]), garments) == []


def test_accessory_pruning_preserves_explicit_color_preference():
    clothes = [_garment("top", "上装"), _garment("bottom", "下装"),
               _garment("a-black", "鞋履"),
               _garment("z-white", "鞋履").model_copy(update={"primary_color": "white"})]
    plain = plan_outfits(OutfitRequest(scene="通勤"), clothes)
    preferred = plan_outfits(OutfitRequest(scene="通勤", color_preference="white"), clothes)
    assert "a-black" in plain[0].garment_ids
    assert "z-white" in preferred[0].garment_ids
