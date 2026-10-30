"""Native UI integration tests with isolated local data and no remote services."""
import json
import os
import threading
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PIL import Image  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QPushButton, QTextBrowser  # noqa: E402

from stylemate.config.portable import ServiceConfigStore  # noqa: E402
from stylemate.config.runtime import RuntimeSettings  # noqa: E402
from stylemate.desktop.application import GarmentDialog, MainWindow  # noqa: E402
from stylemate.desktop.service_settings import ServiceSettingsDialog  # noqa: E402
from stylemate.desktop.theme import STYLE  # noqa: E402
from stylemate.domain.models import ConversationMessage, Garment, KnowledgeSource  # noqa: E402
from stylemate.services.context import build_context  # noqa: E402


@pytest.fixture
def window(monkeypatch, tmp_path):
    for name in ("LLM_API_KEY", "DASHSCOPE_API_KEY", "VISION_API_KEY", "EMBEDDING_API_KEY", "AMAP_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLE)
    settings = RuntimeSettings(app_mode="demo", vision_model_name="offline", text_model_name="offline")
    context = build_context({}, settings)
    root = Path(__file__).resolve().parents[1]
    records = json.loads((root / "assets/demo/wardrobe.json").read_text("utf-8"))["garments"]
    for record in records:
        garment = Garment.model_validate({**record, "source": "sample",
                                         "image_ref": "assets/demo/garments/" + record["image"]})
        context.repository.save_garment(context.owner_id, garment)
    result = MainWindow(context, ServiceConfigStore(tmp_path))
    result.preferences.clear()
    yield result
    deadline = time.monotonic() + 5
    while result.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    result.close()
    result.deleteLater()
    app.processEvents()


def wait_idle(window):
    deadline = time.monotonic() + 10
    while window.busy and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    assert not window.busy, "Background task did not finish"


def test_filter_pagination_and_all_pages(window):
    assert "128" in window.wardrobe_summary.text()
    assert window.next.isEnabled()
    window.change_page(1)
    assert window.page_number == 1
    window.search.setText("不存在的衣物xyz")
    assert "找到 0 件" in window.result_count.text()
    assert window.page_number == 0
    for index in range(5):
        window.navigate(index)
        assert window.pages.currentIndex() == index


def test_manual_add_edit_delete_use_services(window, monkeypatch):
    before = len(window.garments())
    def add(dialog):
        for key, value in {"name": "测试衬衫", "primary_color": "白色"}.items():
            dialog.fields[key].setText(value)
        dialog.validate()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(GarmentDialog, "exec", add)
    window.add_manual()
    assert len(window.garments()) == before + 1
    garment = next(g for g in window.garments() if g.name == "测试衬衫")
    def edit(dialog):
        dialog.fields["name"].setText("已编辑衬衫")
        dialog.validate()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(GarmentDialog, "exec", edit)
    window.edit_garment(garment)
    assert window.context.repository.get_garment(window.context.owner_id, garment.id).name == "已编辑衬衫"
    monkeypatch.setattr(window, "ask", lambda *args: True)
    window.delete_garment(garment)
    assert len(window.garments()) == before


def test_dialog_rejects_empty_required_fields(window):
    dialog = GarmentDialog(window)
    dialog.validate()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.error.text()


def test_background_recommendation_and_favorite(window):
    window.generate_outfits()
    assert window.busy
    wait_idle(window)
    assert window.outfits
    outfit = window.outfits[0]
    ids = {g.id for g in window.garments()}
    assert set(outfit.garment_ids) <= ids
    window.save_favorite(outfit)
    window.refresh_favorites()
    assert window.favorite_results.count() == 1
    window.remove_favorite(outfit)
    assert not window.context.repository.list_favorites(window.context.owner_id)


def test_chat_history_export_and_documents(window, tmp_path):
    window.navigate(2)
    window.new_conversation()
    window.input.setPlainText("查看衣橱")
    window.send_chat()
    wait_idle(window)
    state = window.context.agent_repository.load_conversation(window.context.owner_id, window.context.conversation_id)
    assert len(state.transcript or state.messages) >= 2
    assert "查看衣橱" in window.transcript.plain_text()
    assert len(window.transcript.user_bubbles) == 1
    document = window.context.agent_service.ingest_document(window.context.owner_id, window.context.conversation_id,
                                                            "test.txt", "text/plain", "我的风格偏好是简约".encode())
    assert document.filename == "test.txt"
    filename = tmp_path / "export.json"
    window.write_export(str(filename), "{}")
    assert json.loads(filename.read_text("utf-8")) == {}


def test_chat_distinguishes_roles_and_keeps_sources_safe_and_selectable(window):
    conversation = window.context.conversation_id
    state = window.context.agent_repository.load_conversation(window.context.owner_id, conversation)
    state.transcript = [
        ConversationMessage(role="user", content="明天穿什么？"),
        ConversationMessage(role="assistant", content="**搭配建议**\n- 衬衫\n<script>不执行</script>", sources=[
            KnowledgeSource(id="source", title="天气来源", url="https://example.com/weather"),
            KnowledgeSource(id="unsafe", title="不安全链接", url="javascript:alert(1)"),
        ]),
    ]
    window.context.agent_repository.save_conversation(state)
    window.navigate(2)
    rendered = window.transcript.plain_text()
    assistant = window.transcript.findChild(QTextBrowser, "assistantMessage")
    html = assistant.toHtml()
    assert len(window.transcript.user_bubbles) == 1
    assert window.transcript.findChild(QTextBrowser, "assistantMessage") is not None
    assert "明天穿什么？" in rendered and "搭配建议" in rendered
    assert "<script>不执行</script>" in rendered
    assert "天气来源" in rendered and "不安全链接" not in rendered
    assert "https://example.com/weather" in html and "javascript:alert" not in html
    assert "**搭配建议**" not in rendered
    assert assistant.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse


def test_chat_long_messages_wrap_at_compact_window_width(window):
    state = window.context.agent_repository.load_conversation(window.context.owner_id, window.context.conversation_id)
    state.transcript = [ConversationMessage(role="user", content="很长的出行需求" * 100),
                        ConversationMessage(role="assistant", content="详细的搭配建议" * 100)]
    window.context.agent_repository.save_conversation(state)
    window.resize(960, 680)
    window.show()
    window.navigate(2)
    QTest.qWait(100)
    assert window.transcript.horizontalScrollBar().maximum() == 0
    assistant = window.transcript.findChild(QTextBrowser, "assistantMessage")
    assert assistant.height() >= assistant.document().size().height()
    assert window.transcript.verticalScrollBar().maximum() > 0
    assert window.transcript.verticalScrollBar().value() == window.transcript.verticalScrollBar().maximum()


def test_chat_user_and_assistant_rows_have_distinct_alignment(window):
    state = window.context.agent_repository.load_conversation(window.context.owner_id, window.context.conversation_id)
    state.transcript = [ConversationMessage(role="user", content="今天穿什么？"),
                        ConversationMessage(role="assistant", content="根据天气选择轻薄外套。")]
    window.context.agent_repository.save_conversation(state)
    window.resize(960, 680)
    window.show()
    window.navigate(2)
    QTest.qWait(120)
    user = window.transcript.user_bubbles[0][0]
    assistant = window.transcript.findChild(QTextBrowser, "assistantMessage")
    user_x = user.mapTo(window.transcript.viewport(), user.rect().center()).x()
    assistant_x = assistant.mapTo(window.transcript.viewport(), assistant.rect().topLeft()).x()
    assert user_x > assistant_x


def test_chat_shows_sent_message_immediately_and_retains_draft_on_failure(window, monkeypatch):
    window.navigate(2)
    release = threading.Event()
    def fail(*_args):
        release.wait(5)
        raise RuntimeError("offline test failure")
    monkeypatch.setattr(window.context.agent_service, "chat", fail)
    monkeypatch.setattr(window, "error", lambda _message: None)
    window.input.setPlainText("旅行应该带什么")
    window.send_chat()
    assert window.busy and "旅行应该带什么" in window.transcript.plain_text()
    state = window.context.agent_repository.load_conversation(window.context.owner_id, window.context.conversation_id)
    assert not (state.transcript or state.messages)
    release.set()
    wait_idle(window)
    assert "旅行应该带什么" not in window.transcript.plain_text()
    assert window.input.toPlainText() == "旅行应该带什么"


def test_background_failure_restores_interaction(window, monkeypatch):
    errors = []
    monkeypatch.setattr(window, "error", errors.append)
    def fail():
        raise ValueError("secret-provider-key")
    window.background(fail, lambda _: None, "测试")
    wait_idle(window)
    assert window.pages.isEnabled()
    assert len(errors) == 1
    assert "secret-provider-key" not in errors[0]


def test_drafts_survive_switches_and_are_listed_without_sending(window):
    window.navigate(2)
    first = window.context.conversation_id
    window.input.setPlainText("还没发出的旅行计划")
    window.new_conversation()
    second = window.context.conversation_id
    window.input.setPlainText("第二个草稿")
    index = window.sessions.findData(first)
    assert index >= 0
    window.sessions.setCurrentIndex(index)
    window.select_conversation(index)
    assert window.input.toPlainText() == "还没发出的旅行计划"
    assert window.preferences.value("drafts/" + second) == "第二个草稿"
    # A new window reads the same isolated settings and resumes the active draft.
    reopened = MainWindow(window.context, window.config_store)
    assert reopened.input.toPlainText() == "还没发出的旅行计划"
    reopened.close()


def test_custom_categories_and_all_season_garments_can_be_filtered(window):
    garment = Garment(id="custom", name="测试雨披", category="雨具", primary_color="蓝色",
                      seasons=["四季"], styles=["简约"], source="manual")
    window.context.wardrobe_service.save_manual(window.context.owner_id, garment)
    window.refresh_wardrobe()
    window.category.setCurrentText("雨具")
    window.season.setCurrentText("冬")
    assert "找到 1 件" in window.result_count.text()


def test_keyboard_actions_respect_busy_state(window):
    window.focus_search()
    assert window.pages.currentIndex() == 0
    window.shortcut_new_chat()
    assert window.pages.currentIndex() == 2
    conversation = window.context.conversation_id
    window.busy = True
    window.shortcut_new_chat()
    window.navigate(0)
    assert window.context.conversation_id == conversation
    assert window.pages.currentIndex() == 2
    window.busy = False


def test_preview(window):
    output = os.getenv("STYLEMATE_PREVIEW_DIR")
    if output:
        window.show()
        QApplication.processEvents()
        QTest.qWait(120)
        window.generate_outfits()
        wait_idle(window)
        if window.outfits:
            window.save_favorite(window.outfits[0])
        for width, height, suffix in [(1240, 860, ""), (960, 680, "-compact")]:
            window.resize(width, height)
            for index, name in [(0, "wardrobe"), (1, "outfits"), (2, "assistant"), (3, "favorites"), (4, "settings")]:
                window.navigate(index)
                QTest.qWait(120)
                window.grab().save(str(Path(output) / (name + suffix + ".png")))


@pytest.mark.parametrize("width,height,columns", [(960, 680, 2), (1240, 860, 4), (1600, 900, 4)])
def test_grid_reflows_without_clipping_or_overlap(window, width, height, columns):
    window.resize(width, height)
    window.show()
    # Reflow is debounced and Qt posts child visibility/layout events separately.
    # Wait for rendered geometry, rather than assuming a fixed machine speed.
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        QTest.qWait(20)
        cards = [window.garment_grid.itemAt(i).widget() for i in range(window.garment_grid.count())]
        if window.grid_columns == columns and len(cards) == 12 and all(
            not card.geometry().intersects(other.geometry())
            for index, card in enumerate(cards) for other in cards[index + 1:]
        ):
            break
    assert window.grid_columns == columns
    assert window.garment_area.horizontalScrollBar().maximum() == 0
    cards = [window.garment_grid.itemAt(i).widget() for i in range(window.garment_grid.count())]
    assert len(cards) == 12
    for index, card in enumerate(cards):
        assert card.width() >= 220
        assert card.geometry().right() <= window.garment_area.viewport().width()
        assert all(not card.geometry().intersects(other.geometry()) for other in cards[index + 1:]), [
            (widget.geometry().getRect(), widget.isVisible()) for widget in cards]
    window.garment_area.verticalScrollBar().setValue(window.garment_area.verticalScrollBar().maximum())
    window.change_page(1)
    assert window.garment_area.verticalScrollBar().value() == 0
    window.resize(1100, 760)
    QTest.qWait(160)
    assert window.grid_columns == 3
    assert window.page_number == 1


def test_detail_edit_and_cancelled_delete_remain_available(window, monkeypatch):
    garment = window.garments()[0]
    opened = []
    monkeypatch.setattr(window, "ask", lambda *args: False)
    monkeypatch.setattr(window, "edit_garment", opened.append)
    def inspect(dialog):
        controls = {item.text(): item for item in dialog.findChildren(QPushButton)}
        controls["删除衣物"].click()
        assert window.context.repository.get_garment(window.context.owner_id, garment.id) is not None
        controls["编辑"].click()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(QDialog, "exec", inspect)
    window.show_garment(garment)
    assert opened == [garment]


@pytest.mark.parametrize("confirmed", [False, True])
def test_photo_import_requires_review_before_saving(window, monkeypatch, tmp_path, confirmed):
    payload = BytesIO()
    Image.new("RGB", (20, 20), "blue").save(payload, "PNG")
    image = tmp_path / "photo.png"
    image.write_bytes(payload.getvalue())
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(image), ""))
    garment = Garment(id="native-photo", name="照片衬衫", category="上装", primary_color="蓝色",
                      seasons=["春"], styles=["简约"], source="ai")
    monkeypatch.setattr(window.context.onboarding_skill, "run", lambda *args: SimpleNamespace(
        status="success", data={"garment": garment.model_dump()}, user_message="识别完成"))
    def review(dialog):
        assert window.context.repository.get_garment(window.context.owner_id, garment.id) is None
        dialog.fields["name"].setText("确认后的衬衫")
        if confirmed:
            dialog.validate()
        return int(confirmed)
    monkeypatch.setattr(GarmentDialog, "exec", review)
    window.import_image()
    wait_idle(window)
    saved = window.context.repository.get_garment(window.context.owner_id, garment.id)
    assert bool(saved) == confirmed
    if confirmed:
        assert saved.name == "确认后的衬衫"
        assert window.context.image_store.read(window.context.owner_id, saved.image_ref)


def test_preset_and_empty_input_never_send_automatically(window, monkeypatch):
    window.navigate(2)
    calls = []
    monkeypatch.setattr(window.context.agent_service, "chat", lambda *args: calls.append(args))
    preset = next(control for control in window.pages.widget(2).findChildren(QPushButton) if control.text() == "洗护帮助")
    preset.click()
    assert window.input.toPlainText() == "洗护帮助"
    assert not calls
    window.input.setPlainText("   ")
    window.send_chat()
    assert not calls
    window.new_conversation()
    assert not window.input.toPlainText()


def test_settings_tabs_preserve_profile_and_data_actions(window):
    window.navigate(4)
    assert window.settings_tabs.count() == 3
    window.profile_fields["style_preference"].setText("简约、通勤")
    window.save_profile()
    assert window.context.profile_service.get(window.context.owner_id)["style_preference"] == "简约、通勤"
    window.settings_tabs.setCurrentIndex(2)
    actions = {item.text() for item in window.settings_tabs.currentWidget().findChildren(QPushButton)}
    assert {"创建完整备份", "导出衣橱清单", "打开数据目录"} <= actions


def test_service_wizard_copies_connection_and_tests_without_saving(window, monkeypatch):
    from stylemate.config.portable import DEFAULTS
    window.config_store.save(DEFAULTS)
    dialog = ServiceSettingsDialog(window, window.config_store, first_run=True)
    dialog.fields["LLM_BASE_URL"].setText("https://example.test/v1")
    dialog.fields["LLM_API_KEY"].setText("private-key")
    dialog.fields["TEXT_MODEL_NAME"].setText("text-model")
    dialog.copy_connection("VISION")
    dialog.fields["VISION_MODEL_NAME"].setText("vision-model")
    assert dialog.fields["VISION_API_KEY"].echoMode().name == "Password"
    monkeypatch.setattr("stylemate.desktop.service_settings.check_service", lambda *args: {"ok": True, "message": "测试通过"})
    dialog.test_service("vision")
    deadline = time.monotonic() + 5
    while dialog.testing and time.monotonic() < deadline:
        QTest.qWait(20)
    assert not dialog.testing
    assert dialog.results["vision"].text() == "测试通过"
    assert window.config_store.load()["LLM_API_KEY"] == ""
    dialog.accept_values()
    assert dialog.value["VISION_API_KEY"] == "private-key"


def test_saved_weather_settings_apply_without_losing_conversation(window, monkeypatch):
    from stylemate.config.portable import DEFAULTS, FIELDS
    for key in (*FIELDS, "OPENAI_API_KEY", "DASHSCOPE_API_KEY", "GAODE_API_KEY", "OPENAI_BASE_URL", "DASHSCOPE_BASE_URL"):
        monkeypatch.setenv(key, os.environ.get(key, ""))
    window.navigate(2)
    window.input.setPlainText("未发送的草稿")
    conversation = window.context.conversation_id
    def accept(dialog):
        dialog.value = dict(DEFAULTS) | {"WEATHER_PROVIDER": "open-meteo", "WEATHER_CITY": "杭州"}
        return 1
    monkeypatch.setattr(ServiceSettingsDialog, "exec", accept)
    window.configure_services()
    assert window.busy
    wait_idle(window)
    assert window.context.settings.weather_provider == "open-meteo"
    assert window.context.conversation_id == conversation
    assert window.input.toPlainText() == "未发送的草稿"
    assert window.city.text() == "杭州"
    assert window.config_store.load()["WEATHER_CITY"] == "杭州"


def test_legacy_env_import_preserves_explicit_key_and_imports_aliases(window, monkeypatch, tmp_path):
    from stylemate.config.portable import DEFAULTS
    window.config_store.save(DEFAULTS)
    path = tmp_path / "legacy.env"
    path.write_text("OPENAI_API_KEY=legacy-private\nOPENAI_BASE_URL=https://example.test/v1\n"
                    "DASHSCOPE_API_KEY=shared-private\nGAODE_API_KEY=weather-private\n"
                    "VISION_API_KEY=explicit-private\nTEXT_MODEL_NAME=text-model\n", "utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    dialog = ServiceSettingsDialog(window, window.config_store)
    dialog.import_file()
    assert dialog.fields["LLM_API_KEY"].text() == "legacy-private"
    assert dialog.fields["VISION_API_KEY"].text() == "explicit-private"
    assert dialog.fields["EMBEDDING_API_KEY"].text() == "shared-private"
    assert dialog.fields["AMAP_API_KEY"].text() == "weather-private"
    assert window.config_store.load()["LLM_API_KEY"] == ""
from stylemate.agent.tools.write_actions import prepare_update_garment  # noqa: E402


@pytest.mark.parametrize("confirmed", [False, True])
def test_plain_language_preview_still_requires_explicit_confirmation(window, confirmed):
    context = window.context
    garment = window.garments()[0]
    prepare_update_garment(owner_id=context.owner_id, conversation_id=context.conversation_id,
                           garment_id=garment.id, changes={"name": "确认修改的衣物"},
                           agent_repository=context.agent_repository, wardrobe_repository=context.repository)
    window.navigate(2)
    preview = window.pending.toPlainText()
    assert "确认修改衣物" in preview and "修改前" in preview and "修改后" in preview
    assert "名称：确认修改的衣物" in preview
    assert context.repository.get_garment(context.owner_id, garment.id).name == garment.name
    window.resolve_action(confirmed)
    actual = context.repository.get_garment(context.owner_id, garment.id)
    assert actual.name == ("确认修改的衣物" if confirmed else garment.name)
    assert context.agent_repository.get_pending(context.owner_id, context.conversation_id) is None
    assert "status=" not in window.statusBar().currentMessage()
    assert "action=" not in window.statusBar().currentMessage()
