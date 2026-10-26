from pathlib import Path

from streamlit.testing.v1 import AppTest

from stylemate.demo.sample_data import sample_garments


def _disable_model_providers(monkeypatch):
    for name in (
        "LLM_API_KEY",
        "OPENAI_API_KEY",
        "DASHSCOPE_API_KEY",
        "VISION_API_KEY",
        "EMBEDDING_API_KEY",
        "AMAP_API_KEY",
        "GAODE_API_KEY",
    ):
        monkeypatch.setenv(name, "")


def test_streamlit_app_starts_in_demo_mode(monkeypatch):
    monkeypatch.setenv("APP_MODE", "demo")
    _disable_model_providers(monkeypatch)
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"))

    app.run(timeout=20)

    assert not app.exception
    assert "StyleMate" in app.title[0].value
    assert [tab.label for tab in app.tabs] == ["今日搭配", "我的衣橱", "关于项目"]
    rendered = "\n".join(item.value for item in app.markdown)
    assert "位置服务尚未配置" in rendered
    assert app.button(key="assistant_preset_weather")
    assert app.button(key="assistant_preset_care")
    assert app.button(key="assistant_preset_purchase")
    assert app.button(key="assistant_preset_travel")
    assert all(button.key != "assistant_preset_tops" for button in app.button)
    metrics = {metric.label: metric.value for metric in app.metric}
    assert [metrics[label] for label in ("Recall@5", "MRR@5", "nDCG@5")] == ["95.00%", "98.06%", "94.98%"]
    assert "固定离线回归集包含 60 条文档级用例" in rendered


def test_sample_wardrobe_renders_all_cards_without_exception(monkeypatch):
    monkeypatch.setenv("APP_MODE", "demo")
    _disable_model_providers(monkeypatch)
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"))

    app.run(timeout=20)
    app.button(key="load_samples_today").click()
    app.run(timeout=20)

    assert not app.exception
    rendered = "\n".join(item.value for item in app.markdown)
    assert all(garment.name in rendered for garment in sample_garments())


def test_invalid_wardrobe_edit_is_shown_without_saving_or_crashing(monkeypatch):
    monkeypatch.setenv("APP_MODE", "demo")
    _disable_model_providers(monkeypatch)
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"))

    app.run(timeout=20)
    app.button(key="load_samples_today").click()
    app.run(timeout=20)
    app.text_input(key="name_sample-shirt-white").set_value("   ")
    app.button(key="FormSubmitter:edit_sample-shirt-white-保存修改").click()
    app.run(timeout=20)

    assert not app.exception
    assert any("无法保存" in item.value for item in app.error)
    saved = app.session_state["owners"]["demo-user"]["garments"]["sample-shirt-white"]
    assert saved["name"] == "白色衬衫"


def test_activity_selection_recomputes_the_outfit(monkeypatch):
    monkeypatch.setenv("APP_MODE", "demo")
    _disable_model_providers(monkeypatch)
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"))

    app.run(timeout=20)
    app.button(key="load_samples_today").click()
    app.run(timeout=20)
    app.radio(key="stylemate_activity").set_value("约会")
    app.run(timeout=20)

    assert not app.exception
    rendered = "\n".join(item.value for item in app.markdown)
    assert "已按“约会”重新推荐" in rendered
    assert "符合约会场景" in rendered


def test_new_chat_creates_a_fresh_conversation_instead_of_erasing_history(monkeypatch):
    monkeypatch.setenv("APP_MODE", "demo")
    _disable_model_providers(monkeypatch)
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"))

    app.run(timeout=20)
    original_id = app.session_state["stylemate_conversation_id"]
    app.button(key="assistant_preset_purchase").click()
    app.run(timeout=20)
    app.button(key="clear_agent_conversation").click()
    app.run(timeout=20)

    assert app.session_state["stylemate_conversation_id"] != original_id
    conversations = app.session_state["stylemate_agent"]["demo-user"]["conversations"]
    assert original_id in conversations


def test_desktop_opens_conversation_workspace_and_can_switch_to_wardrobe(monkeypatch):
    monkeypatch.setenv("APP_MODE", "demo")
    monkeypatch.setenv("STYLEMATE_DESKTOP", "1")
    _disable_model_providers(monkeypatch)
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py")).run(timeout=20)
    assert not app.exception
    assert app.radio(key="desktop_page").value == "AI 对话"
    assert app.button(key="assistant_preset_care")
    app.radio(key="desktop_page").set_value("衣橱工作台").run(timeout=20)
    assert not app.exception
    assert [tab.label for tab in app.tabs] == ["今日搭配", "我的衣橱", "关于项目"]
    app.button(key="desktop_new_chat").click().run(timeout=20)
    assert app.radio(key="desktop_page").value == "AI 对话"
    assert not app.exception


def test_desktop_history_and_memory_reset_keep_archive(monkeypatch):
    monkeypatch.setenv("APP_MODE", "demo")
    monkeypatch.setenv("STYLEMATE_DESKTOP", "1")
    _disable_model_providers(monkeypatch)
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py")).run(timeout=20)
    first_id = app.session_state["stylemate_conversation_id"]
    app.chat_input(key="desktop_chat_input").set_value("羊毛怎么洗").run(timeout=20)
    assert not app.exception
    app.button(key="desktop_new_chat").click().run(timeout=20)
    assert app.session_state["stylemate_conversation_id"] != first_id
    app.button(key=f"desktop_history_{first_id}").click().run(timeout=20)
    app.button(key="stylemate_forget_context").click().run(timeout=20)
    state = app.session_state["stylemate_agent"]["demo-user"]["conversations"][first_id]
    assert state["messages"] == [] and len(state["transcript"]) == 2
    assert len(app.chat_message) == 2
    assert not app.exception
