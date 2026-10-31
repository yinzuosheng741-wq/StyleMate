"""The benchmark must expose denominators and distinguish contracts from tool hits."""

from types import SimpleNamespace

from evaluation.benchmark import assess, distribution, proportion, summarize_tasks


def test_empty_measurements_are_unknown_and_small_success_sample_has_uncertainty():
    assert proportion(0, 0)["rate"] is None
    assert distribution([])["p95_ms"] is None
    result = proportion(3, 3)
    assert result["rate"] == 1 and result["wilson_95"][0] < 0.5


def test_tool_hit_alone_does_not_pass_a_task_requiring_inventory_result():
    reply = SimpleNamespace(traces=[SimpleNamespace(name="recommend_inventory_outfit")],
                            content="没有完整搭配", outfits=[], sources=[])
    checks, _ = assess({"tools": ["recommend_inventory_outfit"], "outfits": True}, reply, None)
    assert checks["expected_tool_hit"] and not checks["outfits"]
    assert not all(checks.values())


def test_additional_tool_is_reported_even_if_expected_tool_was_hit():
    reply = SimpleNamespace(traces=[SimpleNamespace(name="get_weather"), SimpleNamespace(name="search_wardrobe")],
                            content="22℃", outfits=[], sources=[])
    checks, _ = assess({"tools": ["get_weather"]}, reply, None)
    assert checks["expected_tool_hit"] and not checks["exact_tool_set"]
    row = {"id": "extra-read", "expected_tools": ["get_weather"], "actual_tools": ["get_weather", "search_wardrobe"],
           "checks": dict(checks, inventory_unchanged=True), "passed": False, "duration_ms": 1}
    summary = summarize_tasks([row])
    assert summary["functional_task_success"]["rate"] == 1
    assert summary["contract_task_success"]["rate"] == 0
