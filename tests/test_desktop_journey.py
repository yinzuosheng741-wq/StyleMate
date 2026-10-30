"""User journeys against real SQLite and photo storage in an isolated app folder."""
import hashlib
import json
import os
import shutil
import time
import zipfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QListWidget, QPushButton  # noqa: E402

from stylemate.config.portable import DEFAULTS, FIELDS, ServiceConfigStore  # noqa: E402
from stylemate.config.runtime import RuntimeSettings  # noqa: E402
from stylemate.desktop import application  # noqa: E402
from stylemate.desktop.application import GarmentDialog, MainWindow  # noqa: E402
from stylemate.desktop.service_settings import ServiceSettingsDialog  # noqa: E402
from stylemate.repositories.agent_sqlite import SQLiteAgentRepository  # noqa: E402
from stylemate.repositories.sqlite import SQLiteWardrobeRepository  # noqa: E402
from stylemate.services.context import build_context  # noqa: E402


@pytest.fixture
def app_root(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    shutil.copytree(root / "assets/demo", tmp_path / "assets/demo")
    shutil.copytree(root / "data/knowledge", tmp_path / "data/knowledge")
    monkeypatch.setattr(application, "ROOT", tmp_path)
    monkeypatch.setattr("stylemate.services.context.application_root", lambda: tmp_path)
    for key in (*FIELDS, "OPENAI_API_KEY", "DASHSCOPE_API_KEY", "GAODE_API_KEY", "OPENAI_BASE_URL", "DASHSCOPE_BASE_URL"):
        monkeypatch.setenv(key, "")
    QApplication.instance() or QApplication([])
    return tmp_path


def wait_idle(window):
    deadline = time.monotonic() + 10
    while window.busy and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    assert not window.busy


def test_first_start_offline(app_root):
    observed = {"wizard": False, "main": False, "timed_out": False}
    app = QApplication.instance()
    timer = QTimer()
    def navigate():
        for widget in app.topLevelWidgets():
            if isinstance(widget, ServiceSettingsDialog) and widget.isVisible():
                observed["wizard"] = True
                # The real rejection path is the user's "暂不配置" choice.
                widget.reject()
            elif isinstance(widget, MainWindow) and widget.isVisible() and not observed["main"]:
                observed["main"] = True
                QTimer.singleShot(100, widget.close)
    timer.timeout.connect(navigate)
    timer.start(30)
    watchdog = QTimer()
    watchdog.setSingleShot(True)
    def timeout():
        observed["timed_out"] = True
        app.quit()
    watchdog.timeout.connect(timeout)
    watchdog.start(30000)
    try:
        assert application.run() == 0
    finally:
        timer.stop()
        watchdog.stop()
    assert observed == {"wizard": True, "main": True, "timed_out": False}
    assert ServiceConfigStore(app_root).load() == DEFAULTS
    assert (app_root / "data/desktop/ui.ini").is_file()
    assert not (app_root / "data/desktop/instance.lock").exists()
    assert len(SQLiteWardrobeRepository(app_root / "data/stylemate.db").list_garments("local-user")) == 128


def test_daily_journey(app_root, monkeypatch):
    settings = RuntimeSettings(app_mode="local", text_model_name="offline", vision_model_name="offline", weather_provider="disabled")
    context = build_context({}, settings)
    window = MainWindow(context, ServiceConfigStore(app_root))
    errors = []
    monkeypatch.setattr(window, "error", errors.append)
    window.show()
    QTest.qWait(100)
    try:
        def add(dialog):
            for key, value in {"name": "旅行雨披", "category": "雨具", "primary_color": "蓝色", "seasons": "四季"}.items():
                dialog.fields[key].setText(value)
            dialog.validate()
            return dialog.result()
        monkeypatch.setattr(GarmentDialog, "exec", add)
        manual = next(action for action in window.add_garment_button.menu().actions() if action.text() == "手动录入")
        manual.trigger()
        garment = next(g for g in window.garments() if g.name == "旅行雨披")
        window.search.setText("旅行雨披")
        assert "找到 1 件" in window.result_count.text()
        window.profile_fields["style_preference"].setText("轻便、简约")
        window.save_profile()

        def edit(dialog):
            dialog.fields["name"].setText("轻便旅行雨披")
            dialog.validate()
            return dialog.result()
        monkeypatch.setattr(GarmentDialog, "exec", edit)
        window.edit_garment(garment)
        assert context.repository.get_garment(context.owner_id, garment.id).name == "轻便旅行雨披"

        destinations = {"JSON (*.json)": app_root / "wardrobe.json", "Markdown (*.md)": app_root / "chat.md", "ZIP (*.zip)": app_root / "backup.zip"}
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(destinations[args[-1]]), ""))
        window.export_wardrobe()
        assert any(g["name"] == "轻便旅行雨披" for g in json.loads((app_root / "wardrobe.json").read_text("utf-8")))
        window.navigate(1)
        window.generate_outfits()
        wait_idle(window)
        assert window.outfits
        window.save_favorite(window.outfits[0])

        window.navigate(2)
        window.new_conversation()
        conversation = context.conversation_id
        window.input.setPlainText("查看衣橱")
        window.send_chat()
        wait_idle(window)
        window.export_chat()
        assert "查看衣橱" in (app_root / "chat.md").read_text("utf-8")

        document = app_root / "trip.txt"
        document.write_text("旅行准备：雨天携带轻便雨披。", "utf-8")
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(document), ""))
        def upload(dialog):
            next(b for b in dialog.findChildren(QPushButton) if b.text() == "添加资料").click()
            return 1
        monkeypatch.setattr(QDialog, "exec", upload)
        window.manage_documents()
        wait_idle(window)
        assert len(context.agent_service.list_documents(context.owner_id, conversation)) == 1

        monkeypatch.setattr(window, "ask", lambda *args: True)
        def remove(dialog):
            dialog.findChild(QListWidget).setCurrentRow(0)
            next(b for b in dialog.findChildren(QPushButton) if b.text() == "移除选中资料").click()
            return 1
        monkeypatch.setattr(QDialog, "exec", remove)
        window.manage_documents()
        assert not context.agent_service.list_documents(context.owner_id, conversation)

        window.backup_data()
        wait_idle(window)
        with zipfile.ZipFile(app_root / "backup.zip") as archive:
            assert archive.testzip() is None
            manifest = json.loads(archive.read("backup-manifest.json"))
            for name, digest in manifest["files"].items():
                assert hashlib.sha256(archive.read(name)).hexdigest() == digest
            snapshot = app_root / "restored.db"
            snapshot.write_bytes(archive.read("data/stylemate.db"))
        restored = SQLiteWardrobeRepository(snapshot)
        assert restored.get_garment(context.owner_id, garment.id).name == "轻便旅行雨披"
        assert len(restored.list_favorites(context.owner_id)) == 1
        history = SQLiteAgentRepository(snapshot).load_conversation(context.owner_id, conversation)
        assert len(history.transcript or history.messages) >= 2

        monkeypatch.setattr(window, "ask", lambda *args: False)
        window.clear_conversation()
        assert context.agent_repository.load_conversation(context.owner_id, conversation).messages
        monkeypatch.setattr(window, "ask", lambda *args: True)
        window.clear_conversation()
        cleared = context.agent_repository.load_conversation(context.owner_id, conversation)
        assert not (cleared.transcript or cleared.messages)
        window.new_conversation()
        window.input.setPlainText("尚未发送的旅行草稿")
        window.close()

        reopened = MainWindow(build_context({}, settings), ServiceConfigStore(app_root))
        try:
            assert reopened.input.toPlainText() == "尚未发送的旅行草稿"
            assert reopened.context.profile_service.get(context.owner_id)["style_preference"] == "轻便、简约"
            assert len(reopened.context.repository.list_favorites(context.owner_id)) == 1
            assert reopened.context.repository.get_garment(context.owner_id, garment.id).name == "轻便旅行雨披"
            monkeypatch.setattr(reopened, "ask", lambda *args: True)
            reopened.delete_garment(garment)
            assert reopened.context.repository.get_garment(context.owner_id, garment.id) is None
        finally:
            reopened.close()
        assert not errors
    finally:
        wait_idle(window)
        window.close()
        window.deleteLater()
        QApplication.processEvents()
