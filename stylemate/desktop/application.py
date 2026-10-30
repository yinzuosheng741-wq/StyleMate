"""Native desktop workbench. All mutations go through the existing services."""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import uuid
from datetime import date
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QRunnable, QSettings, QSize, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from stylemate.branding import REPOSITORY_URL
from stylemate.config.portable import DEFAULTS, ServiceConfigStore, application_root, apply_environment
from stylemate.config.runtime import RuntimeSettings
from stylemate.desktop.backup import create_backup
from stylemate.desktop.chat_view import conversation_html
from stylemate.desktop.icons import navigation_icon
from stylemate.desktop.instance import acquire_instance_lock
from stylemate.desktop.service_settings import ServiceSettingsDialog
from stylemate.desktop.theme import STYLE
from stylemate.diagnostics import runtime_diagnostics
from stylemate.domain.models import FavoriteOutfit, Garment, OutfitRecommendation, OutfitRequest
from stylemate.services.context import build_context, validated_garment_update
from stylemate.services.conversation_export import conversation_export

ROOT = application_root()


def label(text, name="", wrap=False):
    result = QLabel(str(text))
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setObjectName(name)
    result.setWordWrap(wrap)
    return result


def button(text, action, primary=False):
    result = QPushButton(text)
    result.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        result.setObjectName("primary")
    result.clicked.connect(action)
    return result


def combo(items):
    result = QComboBox()
    result.addItems(items)
    return result


def panel(name="card"):
    widget = QFrame()
    widget.setObjectName(name)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)
    return widget, layout


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


def scroll_content():
    area = QScrollArea()
    area.setWidgetResizable(True)
    content = QWidget()
    area.setWidget(content)
    return area, content


def app_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor("#203d35"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#e1e7cb"), 3))
    painter.drawArc(26, 11, 14, 14, 0, 270 * 16)
    painter.drawPolyline([QPoint(x, y)
                          for x, y in [(32, 25), (12, 43), (52, 43), (32, 25)]])
    painter.end()
    return QIcon(pixmap)


class TaskSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Task(QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.signals = TaskSignals()

    def run(self):
        try:
            result = self.operation()
        except Exception:
            # Avoid displaying provider exceptions that may contain credentials or request bodies.
            self.signals.failed.emit("操作未完成，请检查输入、文件权限或外部服务配置后重试。")
        else:
            self.signals.done.emit(result)


class GarmentDialog(QDialog):
    def __init__(self, parent, garment=None, draft=None):
        super().__init__(parent)
        self.setWindowTitle("编辑单品" if garment else "添加到衣橱")
        self.setMinimumWidth(480)
        self.garment = garment
        self.value = None
        self.draft = draft or {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(label("编辑衣物" if garment else "添加衣物", "cardTitle"))
        layout.addWidget(label("确认信息后保存，季节和风格可用逗号分隔。", "subtitle"))
        form = QFormLayout()
        self.fields = {}
        values = garment.model_dump() if garment else self.draft
        for key, title, default in [
            ("name", "衣物名称 *", ""), ("category", "类别 *", "上装"),
            ("primary_color", "颜色 *", ""), ("material", "材质", ""),
            ("seasons", "季节 *", "春,秋"), ("styles", "风格 *", "简约"),
        ]:
            value = values.get(key, default) or ""
            if isinstance(value, list):
                value = ",".join(value)
            field = QLineEdit(str(value))
            self.fields[key] = field
            form.addRow(title, field)
        layout.addLayout(form)
        self.error = label("", "subtitle", True)
        layout.addWidget(self.error)
        actions = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        actions.button(QDialogButtonBox.StandardButton.Save).setText("确认保存")
        actions.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        actions.accepted.connect(self.validate)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)

    def validate(self):
        try:
            base = self.garment or Garment(
                id=self.draft.get("id") or str(uuid.uuid4()), name="新单品", category="上装",
                primary_color="未设置", seasons=["春"], styles=["简约"],
                source="ai" if self.draft.get("source") == "ai" else "manual",
            )
            self.value = validated_garment_update(base, **{key: field.text() for key, field in self.fields.items()})
        except ValueError:
            self.error.setText("请填写名称、类别、颜色，以及至少一个季节和风格。")
            return
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, context, config_store=None):
        super().__init__()
        self.context = context
        self.config_store = config_store or ServiceConfigStore()
        self.busy = False
        self.active_task = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.preferences = QSettings(str(self.config_store.root / "data/desktop/ui.ini"), QSettings.Format.IniFormat)
        last_conversation = self.preferences.value("conversation", "")
        if last_conversation:
            self.context.conversation_id = str(last_conversation)
        self.page_size = 12
        self.page_number = 0
        self.outfits = []
        self.setWindowTitle("出行衣橱助手 · 个人衣橱")
        configure_fonts()
        self.setWindowIcon(app_icon())
        self.resize(1240, 860)
        self.setMinimumSize(960, 680)
        root = QWidget()
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        sidebar, side = panel("sidebar")
        sidebar.setFixedWidth(190)
        side.setContentsMargins(16, 30, 16, 20)
        side.addWidget(label("出行衣橱助手", "brand"))
        side.addWidget(label("你的日常衣橱", "eyebrow"))
        side.addSpacing(28)
        self.navigation = []
        for index, (title, icon) in enumerate([
            ("我的衣橱", "wardrobe"), ("今日搭配", "outfits"), ("衣橱助手", "chat"),
            ("搭配收藏", "favorites"), ("设置", "settings"),
        ]):
            if index == 4:
                side.addStretch()
            nav = button(title, lambda checked=False, i=index: self.navigate(i))
            nav.setIcon(navigation_icon(icon))
            nav.setIconSize(QSize(20, 20))
            nav.setObjectName("nav")
            nav.setCheckable(True)
            self.navigation.append(nav)
            side.addWidget(nav)
        side.addSpacing(8)
        side.addWidget(label("衣橱保存在本机", "eyebrow"))
        shell.addWidget(sidebar)
        body = QVBoxLayout()
        body.setContentsMargins(28, 28, 28, 10)
        body.setSpacing(18)
        self.pages = QStackedWidget()
        self.build_wardrobe()
        self.build_outfits()
        self.build_chat()
        self.build_favorites()
        self.build_settings()
        self.install_shortcuts()
        self.restore_draft()
        body.addWidget(self.pages)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        body.addWidget(self.progress)
        shell.addLayout(body, 1)
        self.statusBar().showMessage("本地数据已就绪 · 图片与衣橱保存在本机")
        self.navigate(0)
        geometry = self.preferences.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def page(self, title, subtitle):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        heading = QVBoxLayout()
        heading.setSpacing(6)
        heading.addWidget(label(title, "title"))
        heading.addWidget(label(subtitle, "subtitle", True))
        layout.addLayout(heading)
        self.pages.addWidget(widget)
        return layout

    def notify(self, text):
        self.statusBar().showMessage(text, 12000)

    def error(self, text):
        QMessageBox.warning(self, "出行衣橱助手", text)

    def ask(self, title, text):
        return QMessageBox.question(self, title, text,
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def background(self, operation, callback, message):
        if self.busy:
            return
        self.busy = True
        self.pages.setEnabled(False)
        for nav in self.navigation:
            nav.setEnabled(False)
        self.progress.show()
        self.statusBar().showMessage(message)
        task = Task(operation)
        self.active_task = task
        task.signals.done.connect(lambda value: self.task_done(value, callback))
        task.signals.failed.connect(self.task_failed)
        self.pool.start(task)

    def finish_task(self):
        self.busy = False
        self.pages.setEnabled(True)
        for nav in self.navigation:
            nav.setEnabled(True)
        self.progress.hide()
        self.active_task = None

    def task_done(self, value, callback):
        self.finish_task()
        try:
            callback(value)
        except Exception:
            self.error("结果处理失败，请重新打开该页面后重试。")

    def task_failed(self, message):
        self.finish_task()
        self.error(message)
        self.notify("操作未完成，可重试")

    def navigate(self, index):
        if self.busy:
            return
        self.pages.setCurrentIndex(index)
        for i, nav in enumerate(self.navigation):
            nav.setChecked(i == index)
        if index == 0:
            self.refresh_wardrobe()
        elif index == 2:
            self.refresh_sessions()
            self.refresh_chat()
        elif index == 3:
            self.refresh_favorites()

    def garments(self):
        return self.context.repository.list_garments(self.context.owner_id)

    def image(self, garment, width=190, height=150):
        result = label(garment.category)
        result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        result.setFixedHeight(height)
        result.setMinimumWidth(0)
        result.setStyleSheet("background: #f4f5f0; border-radius: 8px; color: #95a08d; font-size: 20px;")
        pixmap = QPixmap()
        if garment.image_ref:
            try:
                if garment.image_ref.startswith("assets/demo/") or Path(garment.image_ref).is_absolute():
                    path = (ROOT / garment.image_ref).resolve()
                    path.relative_to(ROOT / "assets" / "demo")
                    pixmap.load(str(path))
                else:
                    payload = self.context.image_store.read(self.context.owner_id, garment.image_ref)
                    if payload:
                        pixmap.loadFromData(payload)
            except (ValueError, OSError):
                pass
        if not pixmap.isNull():
            result.setPixmap(pixmap.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
        return result

    def build_wardrobe(self):
        layout = self.page("我的衣橱", "整理衣物，发现适合自己的搭配。")
        line = QHBoxLayout()
        self.wardrobe_summary = label("", "subtitle")
        line.addWidget(self.wardrobe_summary, 1)
        self.add_garment_button = button("添加衣物", lambda: None, True)
        menu = QMenu(self.add_garment_button)
        menu.addAction("上传照片识别", self.import_image)
        menu.addAction("手动录入", self.add_manual)
        self.add_garment_button.setMenu(menu)
        line.addWidget(self.add_garment_button)
        layout.addLayout(line)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索名称、颜色、材质或风格…")
        self.search.setClearButtonEnabled(True)
        self.category = combo(["全部类别", "上装", "下装", "外套", "连衣裙", "鞋履", "包袋", "配饰"])
        self.season = combo(["全部季节", "春", "夏", "秋", "冬"])
        self.sort = combo(["最新添加", "名称排序"])
        for widget in [self.search, self.category, self.season, self.sort]:
            filters.addWidget(widget, 2 if widget == self.search else 0)
        self.search.textChanged.connect(self.reset_filter)
        for widget in [self.category, self.season, self.sort]:
            widget.currentTextChanged.connect(self.reset_filter)
        layout.addLayout(filters)
        area, content = scroll_content()
        self.garment_area = area
        self.grid_columns = 3
        self.grid_resize_timer = QTimer(self)
        self.grid_resize_timer.setSingleShot(True)
        self.grid_resize_timer.timeout.connect(self.reflow_wardrobe)
        area.viewport().installEventFilter(self)
        self.garment_content = content
        self.garment_grid = QGridLayout(content)
        self.garment_grid.setContentsMargins(0, 0, 6, 0)
        self.garment_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.garment_grid.setSpacing(14)
        layout.addWidget(area, 1)
        paging = QHBoxLayout()
        self.result_count = label("", "subtitle")
        paging.addWidget(self.result_count, 1)
        self.previous = button("上一页", lambda: self.change_page(-1))
        self.next = button("下一页", lambda: self.change_page(1))
        paging.addWidget(self.previous)
        paging.addWidget(self.next)
        layout.addLayout(paging)

    def reset_filter(self, *args):
        self.page_number = 0
        self.refresh_wardrobe()
        self.garment_area.verticalScrollBar().setValue(0)

    def change_page(self, delta):
        self.page_number += delta
        self.refresh_wardrobe()
        self.garment_area.verticalScrollBar().setValue(0)

    def refresh_wardrobe(self):
        garments = self.garments()
        # Keep custom categories accessible without losing the active selection.
        categories = ["全部类别", "上装", "下装", "外套", "连衣裙", "鞋履", "包袋", "配饰"]
        categories.extend(sorted({g.category for g in garments} - set(categories)))
        current = self.category.currentText()
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItems(categories)
        self.category.setCurrentText(current if current in categories else "全部类别")
        self.category.blockSignals(False)
        self.wardrobe_summary.setText(f"{len(garments)} 件衣物  ·  {len({g.category for g in garments})} 种类别")
        query = self.search.text().strip().casefold()
        filtered = [g for g in garments
                    if (self.category.currentIndex() == 0 or g.category == self.category.currentText())
                    and (self.season.currentIndex() == 0 or self.season.currentText() in g.seasons or "四季" in g.seasons)
                    and (not query or query in " ".join([g.name, g.category, g.primary_color,
                                                         g.material or "", *g.styles]).casefold())]
        filtered.sort(key=(lambda g: g.name) if self.sort.currentIndex() else (lambda g: g.created_at),
                      reverse=not self.sort.currentIndex())
        max_page = max(0, (len(filtered) - 1) // self.page_size)
        self.page_number = max(0, min(self.page_number, max_page))
        start = self.page_number * self.page_size
        self.grid_columns = self.wardrobe_columns()
        columns = self.grid_columns
        clear_layout(self.garment_grid)
        for i, garment in enumerate(filtered[start:start + self.page_size]):
            card, box = panel("garmentCard")
            card.setFixedHeight(310)
            box.setContentsMargins(12, 12, 12, 12)
            box.setSpacing(8)
            box.addWidget(self.image(garment, 200, 160))
            title = label(garment.name, "cardTitle", True)
            title.setFixedHeight(40)
            title.setToolTip(garment.name)
            box.addWidget(title)
            meta = label(f"{garment.category} · {garment.primary_color}", "subtitle")
            meta.setToolTip(" / ".join(garment.seasons) + " · " + " / ".join(garment.styles))
            box.addWidget(meta)
            box.addWidget(button("查看详情", lambda checked=False, g=garment: self.show_garment(g)))
            self.garment_grid.addWidget(card, i // columns, i % columns)
        for column in range(4):
            self.garment_grid.setColumnStretch(column, 1 if column < columns else 0)
        rows = (len(filtered[start:start + self.page_size]) + columns - 1) // columns
        self.garment_content.setMinimumHeight(rows * 324 if rows else 120)
        if not filtered:
            self.garment_grid.addWidget(label("没有找到衣物\n试试清除筛选，或添加第一件衣物。", "subtitle", True), 0, 0, 1, columns)
        self.result_count.setText(f"找到 {len(filtered)} 件单品  ·  第 {self.page_number + 1} / {max_page + 1} 页")
        self.previous.setEnabled(self.page_number > 0)
        self.next.setEnabled(self.page_number < max_page)
        self.garment_grid.activate()

    def wardrobe_columns(self):
        return max(2, min(4, (self.garment_area.viewport().width() + 14) // 244))

    def eventFilter(self, watched, event):
        if hasattr(self, "garment_area") and watched is self.garment_area.viewport() and event.type() == QEvent.Type.Resize:
            self.grid_resize_timer.start(80)
        return super().eventFilter(watched, event)

    def reflow_wardrobe(self):
        if self.pages.currentIndex() == 0 and not self.busy and self.wardrobe_columns() != self.grid_columns:
            self.refresh_wardrobe()

    def show_garment(self, garment):
        dialog = QDialog(self)
        dialog.setWindowTitle("衣物详情")
        dialog.setMinimumWidth(420)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(self.image(garment, 360, 250))
        layout.addWidget(label(garment.name, "cardTitle", True))
        layout.addWidget(label(f"{garment.category} · {garment.primary_color} · {garment.material or '未填写材质'}", wrap=True))
        layout.addWidget(label("季节：" + " / ".join(garment.seasons), "subtitle", True))
        layout.addWidget(label("风格：" + " / ".join(garment.styles), "subtitle", True))
        row = QHBoxLayout()
        def edit():
            dialog.accept()
            self.edit_garment(garment)
        def remove():
            self.delete_garment(garment)
            if not self.context.repository.get_garment(self.context.owner_id, garment.id):
                dialog.accept()
        delete = button("删除衣物", remove)
        delete.setObjectName("danger")
        row.addWidget(delete)
        row.addStretch()
        row.addWidget(button("关闭", dialog.reject))
        row.addWidget(button("编辑", edit, True))
        layout.addLayout(row)
        dialog.exec()

    def add_manual(self):
        dialog = GarmentDialog(self)
        if dialog.exec():
            try:
                self.context.wardrobe_service.save_manual(self.context.owner_id, dialog.value)
                self.refresh_wardrobe()
                self.notify("新单品已保存")
            except (ValueError, OSError):
                self.error("保存失败，请检查信息和数据目录权限。")

    def edit_garment(self, garment):
        dialog = GarmentDialog(self, garment)
        if dialog.exec():
            try:
                self.context.wardrobe_service.update_confirmed(
                    self.context.owner_id, garment.id, dialog.value.model_dump(mode="python"))
                self.refresh_wardrobe()
                self.notify("单品信息已更新")
            except (ValueError, OSError):
                self.error("保存失败，该单品可能已被删除。")

    def delete_garment(self, garment):
        if self.ask("删除衣物", f"确定删除“{garment.name}”？该操作会同时清理关联图片，无法撤销。"):
            try:
                self.context.wardrobe_service.delete_confirmed(self.context.owner_id, garment.id)
            except Exception:
                self.error("删除或图片清理未能全部完成，请刷新检查衣橱。")
            self.refresh_wardrobe()

    def import_image(self):
        filename, _ = QFileDialog.getOpenFileName(self, "选择单件衣物照片", "", "衣物照片 (*.jpg *.jpeg *.png *.webp)")
        if not filename:
            return
        path = Path(filename)
        try:
            if path.stat().st_size > self.context.settings.max_upload_bytes:
                self.error("照片不能超过 8 MB。")
                return
            payload = path.read_bytes()
            mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            self.context.wardrobe_service.validate_upload(payload, mime)
        except (ValueError, OSError):
            self.error("照片无法读取，请选择有效的 JPG、PNG 或 WEBP 文件。")
            return
        def reviewed(outcome):
            if outcome.data.get("duplicate"):
                self.error("这张照片已在衣橱中，无需重复添加。")
            elif outcome.status == "failed" or outcome.data.get("manual_entry"):
                self.error(outcome.user_message)
            else:
                dialog = GarmentDialog(self, draft=outcome.data["garment"])
                if dialog.exec():
                    self.context.wardrobe_service.save_confirmed(self.context.owner_id, dialog.value, payload, mime)
                    self.refresh_wardrobe()
                    self.notify("照片和单品信息已保存")
        self.background(lambda: self.context.onboarding_skill.run(self.context.owner_id, payload, mime, path.name, ""),
                        reviewed, "正在识别衣物，完成后可编辑并确认…")

    def build_outfits(self):
        layout = self.page("今日搭配", f"{date.today():%Y.%m.%d}  ·  根据场景、天气和衣橱挑选组合。")
        card, box = panel("hero")
        form = QHBoxLayout()
        self.scene = combo(["日常", "通勤", "约会", "运动", "聚会", "户外", "旅行"])
        self.outfit_season = combo(["不限季节", "春", "夏", "秋", "冬"])
        self.city = QLineEdit()
        self.city.setText(self.context.settings.weather_city)
        self.city.setPlaceholderText("城市（可选，查询天气）")
        form.addWidget(self.scene)
        form.addWidget(self.outfit_season)
        form.addWidget(self.city, 1)
        form.addWidget(button("生成今日搭配", self.generate_outfits, True))
        box.addLayout(form)
        self.constraints = QLineEdit()
        self.constraints.setPlaceholderText("补充限制，例如：不要裙子，排除红色（逗号分隔）")
        box.addWidget(self.constraints)
        layout.addWidget(card)
        self.outfit_message = label("选择场景后生成搭配；天气不可用时会使用衣橱规则。", "subtitle", True)
        layout.addWidget(self.outfit_message)
        area, content = scroll_content()
        self.outfit_results = QVBoxLayout(content)
        self.outfit_results.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(area, 1)

    def generate_outfits(self):
        request = OutfitRequest(scene=self.scene.currentText(), city=self.city.text().strip() or None,
                                target_season=self.outfit_season.currentText() if self.outfit_season.currentIndex() else None,
                                extra_constraints=[v.strip() for v in self.constraints.text().replace("，", ",").split(",") if v.strip()])
        def completed(outcome):
            self.outfit_message.setText(outcome.user_message + " 规则分数仅用于候选排序。")
            self.outfits = [OutfitRecommendation.model_validate(item) for item in outcome.data["recommendations"]]
            clear_layout(self.outfit_results)
            for outfit in self.outfits:
                self.outfit_results.addWidget(self.outfit_card(outfit))
            self.notify("搭配已生成")
        self.background(lambda: self.context.outfit_skill.run(self.context.owner_id, request), completed, "正在匹配天气与衣橱…")

    def outfit_card(self, outfit, saved=False):
        card, box = panel()
        heading = QHBoxLayout()
        heading.addWidget(label("已收藏的搭配" if saved else "为你挑选", "cardTitle"), 1)
        score = label(f"匹配分 {outfit.score}", "subtitle")
        score.setToolTip("规则评分仅用于搭配排序，不代表穿搭成功率。")
        heading.addWidget(score)
        box.addLayout(heading)
        row = QHBoxLayout()
        by_id = {g.id: g for g in self.garments()}
        for garment_id in outfit.garment_ids:
            item = QVBoxLayout()
            garment = by_id.get(garment_id)
            if garment:
                item.addWidget(self.image(garment, 135, 110))
                item.addWidget(label(garment.name, wrap=True))
            else:
                item.addWidget(label("单品已从衣橱移除", "subtitle"))
            row.addLayout(item, 1)
        box.addLayout(row)
        box.addWidget(label(outfit.reason, wrap=True))
        if outfit.weather_note:
            box.addWidget(label(outfit.weather_note, "subtitle", True))
        if not saved:
            box.addWidget(button("收藏搭配", lambda: self.save_favorite(outfit)), 0, Qt.AlignmentFlag.AlignRight)
        else:
            box.addWidget(button("取消收藏", lambda: self.remove_favorite(outfit)), 0, Qt.AlignmentFlag.AlignRight)
        return card

    def remove_favorite(self, outfit):
        self.context.repository.delete_favorite(self.context.owner_id, outfit.id)
        self.refresh_favorites()
        self.notify("已取消收藏")

    def save_favorite(self, outfit):
        self.context.repository.save_favorite(FavoriteOutfit(owner_id=self.context.owner_id, recommendation=outfit))
        self.notify("已保存到搭配收藏")

    def build_favorites(self):
        layout = self.page("搭配收藏", "保存喜欢的组合，随时查看。")
        area, content = scroll_content()
        self.favorite_results = QVBoxLayout(content)
        self.favorite_results.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(area)

    def refresh_favorites(self):
        clear_layout(self.favorite_results)
        favorites = self.context.repository.list_favorites(self.context.owner_id)
        for favorite in favorites:
            self.favorite_results.addWidget(self.outfit_card(favorite.recommendation, True))
        if not favorites:
            self.favorite_results.addWidget(label("还没有收藏。去「今日搭配」保存第一套喜欢的组合吧。", "subtitle", True))

    def build_chat(self):
        layout = self.page("衣橱助手", "穿搭、洗护与旅行建议。修改衣橱前，会先请你确认。")
        split = QSplitter()
        session_panel = QWidget()
        sessions = QVBoxLayout(session_panel)
        sessions.setContentsMargins(0, 0, 10, 0)
        sessions.addWidget(button("新建对话", self.new_conversation))
        self.sessions = QListWidget()
        self.sessions.itemClicked.connect(self.select_conversation)
        sessions.addWidget(self.sessions)
        more = button("对话管理", lambda: None)
        menu = QMenu(more)
        menu.addAction("会话资料", self.manage_documents)
        menu.addAction("导出当前对话", self.export_chat)
        menu.addSeparator()
        menu.addAction("清空当前会话", self.clear_conversation)
        more.setMenu(menu)
        sessions.addWidget(more)
        session_panel.setMinimumWidth(155)
        session_panel.setMaximumWidth(240)
        split.addWidget(session_panel)
        conversation = QWidget()
        chat = QVBoxLayout(conversation)
        chat.setContentsMargins(10, 0, 0, 0)
        self.transcript = QTextBrowser()
        self.transcript.setObjectName("chatTranscript")
        self.transcript.document().setDocumentMargin(22)
        self.transcript.setOpenLinks(False)
        self.transcript.anchorClicked.connect(self.open_source)
        chat.addWidget(self.transcript, 1)
        self.pending = QPlainTextEdit()
        self.pending.setReadOnly(True)
        self.pending.setMaximumHeight(140)
        chat.addWidget(self.pending)
        actions = QHBoxLayout()
        self.confirm_action = button("确认执行修改", lambda: self.resolve_action(True), True)
        self.cancel_action = button("取消修改", lambda: self.resolve_action(False))
        actions.addWidget(self.confirm_action)
        actions.addWidget(self.cancel_action)
        actions.addStretch()
        chat.addLayout(actions)
        shortcuts = QHBoxLayout()
        for title, prompt in [("洗护帮助", "洗护帮助"), ("旅行行李", "我想规划旅行行李"), ("购买建议", "推荐购买")]:
            shortcuts.addWidget(button(title, lambda checked=False, p=prompt: self.input.setPlainText(p)))
        chat.addLayout(shortcuts)
        composer = QFrame()
        composer.setObjectName("chatComposer")
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(12, 8, 12, 10)
        composer_layout.setSpacing(4)
        self.input = QPlainTextEdit()
        self.input.setObjectName("chatInput")
        self.input.setPlaceholderText("描述你的需求，例如：去杭州旅行三天…（Ctrl+Enter 发送）")
        self.input.textChanged.connect(self.save_draft)
        self.input.setMaximumHeight(90)
        composer_layout.addWidget(self.input)
        send = QHBoxLayout()
        send.addWidget(label("Ctrl+Enter 发送 · 草稿自动保存", "subtitle"), 1)
        send.addWidget(button("发送", self.send_chat, True))
        composer_layout.addLayout(send)
        chat.addWidget(composer)
        split.addWidget(conversation)
        split.setSizes([200, 700])
        layout.addWidget(split, 1)

    def open_source(self, url):
        if url.scheme() in {"http", "https"}:
            QDesktopServices.openUrl(url)

    def refresh_sessions(self):
        self.sessions.clear()
        sessions = self.context.agent_service.list_conversations(self.context.owner_id)
        known = {s["conversation_id"] for s in sessions}
        for key in self.preferences.allKeys():
            if key.startswith("drafts/"):
                conversation_id = key.removeprefix("drafts/")
                if conversation_id not in known:
                    text = str(self.preferences.value(key, "")).strip()
                    if text:
                        sessions.insert(0, {"conversation_id": conversation_id, "title": "草稿 · " + text[:24]})
        for session in sessions:
            item = QListWidgetItem(session.get("title", "历史会话"))
            item.setData(Qt.ItemDataRole.UserRole, session["conversation_id"])
            self.sessions.addItem(item)
            if session["conversation_id"] == self.context.conversation_id:
                self.sessions.setCurrentItem(item)

    def new_conversation(self):
        if self.busy:
            return
        self.save_draft()
        self.context.conversation_id = "desktop-" + uuid.uuid4().hex
        self.restore_draft()
        self.refresh_sessions()
        self.refresh_chat()
        self.notify("已创建新会话，发送消息后自动保存")

    def select_conversation(self, item):
        self.save_draft()
        self.context.conversation_id = item.data(Qt.ItemDataRole.UserRole)
        self.restore_draft()
        self.refresh_chat()

    def draft_key(self):
        return "drafts/" + self.context.conversation_id

    def save_draft(self):
        text = self.input.toPlainText()
        if text:
            self.preferences.setValue(self.draft_key(), text)
        else:
            self.preferences.remove(self.draft_key())
        self.preferences.setValue("conversation", self.context.conversation_id)

    def restore_draft(self):
        self.input.blockSignals(True)
        self.input.setPlainText(str(self.preferences.value(self.draft_key(), "")))
        self.input.blockSignals(False)
        self.preferences.setValue("conversation", self.context.conversation_id)

    def install_shortcuts(self):
        self.shortcuts = []
        for sequence, action in [("Ctrl+Return", self.send_chat), ("Ctrl+Enter", self.send_chat),
                                 ("Ctrl+N", self.shortcut_new_chat), ("Ctrl+F", self.focus_search)]:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(action)
            self.shortcuts.append(shortcut)

    def shortcut_new_chat(self):
        if not self.busy:
            self.navigate(2)
            self.new_conversation()
            self.input.setFocus()

    def focus_search(self):
        if not self.busy:
            self.navigate(0)
            self.search.setFocus()
            self.search.selectAll()

    def refresh_chat(self):
        state = self.context.agent_repository.load_conversation(self.context.owner_id, self.context.conversation_id)
        messages = state.transcript or state.messages
        by_id = {g.id: g for g in self.garments()}
        self.transcript.setHtml(conversation_html(messages, by_id))
        self.transcript.verticalScrollBar().setValue(self.transcript.verticalScrollBar().maximum())
        action = self.context.agent_repository.get_pending(self.context.owner_id, self.context.conversation_id)
        self.pending.setVisible(action is not None)
        self.confirm_action.setVisible(action is not None)
        self.cancel_action.setVisible(action is not None)
        if action:
            fields = {"name": "名称", "category": "类别", "primary_color": "颜色", "material": "材质",
                      "seasons": "季节", "styles": "风格"}
            lines = [{"add": "确认添加衣物", "update": "确认修改衣物", "delete": "确认删除衣物"}[action.operation]]
            for title, values in [("修改前", action.before), ("修改后", action.after)]:
                if values:
                    lines.append("\n" + title)
                    for key, name in fields.items():
                        if key in values:
                            value = values[key]
                            lines.append(name + "：" + (" / ".join(map(str, value)) if isinstance(value, list) else str(value or "未填写")))
            self.pending.setPlainText("\n".join(lines))

    def send_chat(self):
        if self.busy or self.pages.currentIndex() != 2:
            return
        text = self.input.toPlainText().strip()
        if not text:
            return
        if len(text) > 4000:
            self.error("请将单条消息控制在 4000 字以内。")
            return
        conversation_id = self.context.conversation_id
        def completed(reply):
            self.input.clear()
            self.refresh_sessions()
            self.refresh_chat()
            self.notify("回复已保存")
        self.background(lambda: self.context.agent_service.chat(self.context.owner_id, conversation_id, text),
                        completed, "助手正在整理衣橱与知识来源…")

    def resolve_action(self, confirmed):
        action = self.context.agent_repository.get_pending(self.context.owner_id, self.context.conversation_id)
        if action:
            method = self.context.agent_service.confirm if confirmed else self.context.agent_service.cancel
            try:
                result = method(self.context.owner_id, self.context.conversation_id, action.id)
                self.notify(result.user_message)
            except (ValueError, RuntimeError):
                self.error("操作已过期或衣橱已变化，请重新提出修改。")
            self.refresh_chat()

    def clear_conversation(self):
        if self.ask("清空会话", "确定删除当前会话的消息、临时资料和待确认操作？"):
            self.context.agent_service.clear(self.context.owner_id, self.context.conversation_id)
            self.input.clear()
            self.refresh_sessions()
            self.refresh_chat()

    def export_chat(self):
        filename, _ = QFileDialog.getSaveFileName(self, "导出当前对话", "出行衣橱助手-对话.md", "Markdown (*.md)")
        if filename:
            state = self.context.agent_repository.load_conversation(self.context.owner_id, self.context.conversation_id)
            self.write_export(filename, conversation_export(state, self.garments()))

    def write_export(self, filename, content):
        try:
            Path(filename).write_text(content, encoding="utf-8")
            self.notify("已导出到所选位置")
        except OSError:
            self.error("无法写入所选位置，请选择可写目录。")

    def manage_documents(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("当前会话资料")
        dialog.resize(540, 380)
        box = QVBoxLayout(dialog)
        box.addWidget(label("资料仅用于当前会话。支持 PDF、TXT、Markdown，单个不超过 4 MB。", wrap=True))
        files = QListWidget()
        box.addWidget(files)
        def refresh():
            files.clear()
            for document in self.context.agent_service.list_documents(self.context.owner_id, self.context.conversation_id):
                item = QListWidgetItem(document.filename)
                item.setData(Qt.ItemDataRole.UserRole, document.document_id)
                files.addItem(item)
        def remove():
            item = files.currentItem()
            if item and self.ask("移除资料", "确定从当前会话移除该资料？"):
                self.context.agent_service.delete_document(self.context.owner_id, self.context.conversation_id,
                                                           item.data(Qt.ItemDataRole.UserRole))
                refresh()
        def upload():
            filename, _ = QFileDialog.getOpenFileName(dialog, "选择资料", "", "会话资料 (*.pdf *.txt *.md)")
            if not filename:
                return
            path = Path(filename)
            try:
                if path.stat().st_size > self.context.settings.max_document_bytes:
                    self.error("资料超过 4 MB。")
                    return
                payload = path.read_bytes()
            except OSError:
                self.error("无法读取所选资料。")
                return
            dialog.accept()
            mime = "application/pdf" if path.suffix.lower() == ".pdf" else "text/plain"
            self.background(lambda: self.context.agent_service.ingest_document(
                self.context.owner_id, self.context.conversation_id, path.name, mime, payload),
                lambda _: self.notify("资料已添加，可在对话中提问"), "正在读取并索引资料…")
        actions = QHBoxLayout()
        actions.addWidget(button("添加资料", upload, True))
        actions.addWidget(button("移除选中资料", remove))
        actions.addWidget(button("关闭", dialog.accept))
        box.addLayout(actions)
        refresh()
        dialog.exec()

    def build_settings(self):
        layout = self.page("设置", "穿衣偏好、服务状态与本地数据。")
        self.settings_tabs = QTabWidget()
        layout.addWidget(self.settings_tabs, 1)
        def section(title):
            area, content = scroll_content()
            body = QVBoxLayout(content)
            body.setContentsMargins(0, 18, 8, 0)
            body.setAlignment(Qt.AlignmentFlag.AlignTop)
            self.settings_tabs.addTab(area, title)
            return body
        body = section("穿衣偏好")
        card, box = panel()
        box.addWidget(label("我的穿衣偏好", "cardTitle"))
        box.addWidget(label("这些信息可帮助助手给出更贴合你的建议，均为选填。", "subtitle", True))
        form = QFormLayout()
        form.setVerticalSpacing(14)
        self.profile_fields = {}
        profile = self.context.profile_service.get(self.context.owner_id)
        for key, title in [("height", "身高（cm）"), ("weight", "体重（kg）"), ("fit_preference", "版型偏好"),
                           ("style_preference", "风格偏好"), ("color_preference", "颜色偏好"),
                           ("scene_preference", "常见场景"), ("body_features", "补充说明")]:
            field = QLineEdit(profile.get(key, ""))
            self.profile_fields[key] = field
            form.addRow(title, field)
        box.addLayout(form)
        box.addWidget(button("保存偏好", self.save_profile, True), 0, Qt.AlignmentFlag.AlignRight)
        body.addWidget(card)
        body = section("服务状态")
        card, box = panel()
        box.addWidget(label("已连接的服务", "cardTitle"))
        box.addWidget(button("配置模型、天气与定位", self.configure_services, True), 0, Qt.AlignmentFlag.AlignLeft)
        diagnostics = runtime_diagnostics(self.context.settings, self.context.agent_service.retriever)
        self.service_status = {}
        for key, title in [("text_model_configured", "AI 对话"), ("vision_configured", "图片识别"),
                           ("weather_configured", "实时天气"), ("embedding_configured", "语义检索")]:
            row = QHBoxLayout()
            row.addWidget(label(title), 1)
            status = label("已配置" if diagnostics[key] else "未配置", "subtitle")
            self.service_status[key] = status
            row.addWidget(status)
            box.addLayout(row)
        box.addWidget(label("未配置时仍可管理衣橱、使用规则搭配和关键词检索。配置在本机保存并即时应用；状态表示已填写，实际可用性请使用设置窗口的连接测试。", "subtitle", True))
        body.addWidget(card)

        body = section("数据与关于")
        card, box = panel()
        box.addWidget(label("本地数据", "cardTitle"))
        box.addWidget(label("衣物、照片与会话保存在本机。更换电脑或升级前，可以先创建完整备份。", "subtitle", True))
        row = QHBoxLayout()
        row.addWidget(button("打开数据目录", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(ROOT / "data")))))
        row.addWidget(button("导出衣橱清单", self.export_wardrobe))
        box.addLayout(row)
        box.addWidget(button("创建完整备份", self.backup_data, True), 0, Qt.AlignmentFlag.AlignLeft)
        box.addWidget(label("完整备份包含 SQLite 数据、衣物照片、会话与资料；密钥不进入备份。", "subtitle", True))
        body.addWidget(card)
        card, box = panel()
        box.addWidget(label("出行衣橱助手", "cardTitle"))
        box.addWidget(button("GitHub 项目与源码", lambda: QDesktopServices.openUrl(
            QUrl(REPOSITORY_URL))))
        box.addWidget(label("快捷键：Ctrl+F 搜索衣橱 · Ctrl+N 新建对话 · Ctrl+Enter 发送", "subtitle", True))
        body.addWidget(card)

    def configure_services(self):
        if self.busy:
            return
        dialog = ServiceSettingsDialog(self, self.config_store)
        if dialog.exec():
            try:
                self.config_store.save(dialog.value)
                apply_environment(dialog.value)
                from dataclasses import replace
                settings = replace(RuntimeSettings.from_env(), app_mode=self.context.settings.app_mode)
                state = {"stylemate_conversation_id": self.context.conversation_id}
                if settings.app_mode == "demo":
                    state.update(stylemate_repository=self.context.repository,
                                 stylemate_image_store=self.context.image_store,
                                 stylemate_agent_repository=self.context.agent_repository)
                def completed(context):
                    self.context = context
                    self.city.setText(settings.weather_city)
                    diagnostics = runtime_diagnostics(settings, context.agent_service.retriever)
                    for key, status in self.service_status.items():
                        status.setText("已配置" if diagnostics[key] else "未配置")
                    self.notify("服务配置已保存并应用")
                self.background(lambda: build_context(state, settings), completed, "正在应用服务配置…")
            except Exception:
                self.error("配置未能完成应用，请检查文件权限并重新打开客户端。")

    def save_profile(self):
        self.context.profile_service.replace(self.context.owner_id,
                                             {k: v.text().strip() for k, v in self.profile_fields.items()})
        self.notify("穿衣偏好已保存")

    def export_wardrobe(self):
        filename, _ = QFileDialog.getSaveFileName(self, "导出衣橱清单", "出行衣橱助手-衣橱.json", "JSON (*.json)")
        if filename:
            self.write_export(filename, json.dumps([g.model_dump(mode="json") for g in self.garments()],
                                                   ensure_ascii=False, indent=2))

    def backup_data(self):
        database = getattr(self.context.repository, "path", None)
        uploads = getattr(self.context.image_store, "root", None)
        if database is None or uploads is None:
            self.error("完整备份需要本地持久化模式。")
            return
        filename, _ = QFileDialog.getSaveFileName(self, "备份本地数据", f"出行衣橱助手-备份-{date.today():%Y%m%d}.zip", "ZIP (*.zip)")
        if filename:
            self.background(lambda: create_backup(database, uploads, Path(filename)),
                            lambda report: self.notify(f"备份完成：{report['garments']} 件衣物、{report['images']} 张照片"),
                            "正在生成数据库快照并备份照片…")

    def closeEvent(self, event):
        if self.busy:
            self.notify("后台任务正在执行，请等待完成后关闭窗口。")
            event.ignore()
            return
        self.preferences.setValue("geometry", self.saveGeometry())
        self.save_draft()
        self.preferences.sync()
        event.accept()


def run(shutdown_after=0, no_ui=False):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("出行衣橱助手")
    configure_fonts()
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    instance_lock = acquire_instance_lock(ROOT)
    if instance_lock is None:
        if not (no_ui or shutdown_after):
            QMessageBox.information(None, "出行衣橱助手", "此目录的客户端已在运行，请切换到已打开的窗口。")
        return 2
    store = ServiceConfigStore(ROOT)
    values = store.load()
    if not store.path.exists() and not no_ui and not shutdown_after:
        dialog = ServiceSettingsDialog(None, store, first_run=True)
        values = dialog.value if dialog.exec() else dict(DEFAULTS)
        store.save(values)
    apply_environment(values)
    # The native client always persists data; in-memory mode is reserved for tests.
    settings = RuntimeSettings.from_env()
    from dataclasses import replace
    settings = replace(settings, app_mode="local")
    context = build_context({}, settings)
    if no_ui:
        report = {"application": "出行衣橱助手", "storage": "sqlite", "interface": "native-qt",
                  "garments": len(context.repository.list_garments(context.owner_id))}
        report_path = ROOT / "data/desktop/native-check.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report), encoding="utf-8")
        print(json.dumps(report))
        return 0
    window = MainWindow(context, store)
    window.show()
    app.setQuitOnLastWindowClosed(True)
    if shutdown_after:
        QTimer.singleShot(int(shutdown_after * 1000), window.close)
    result = app.exec()
    instance_lock.unlock()
    return result


def configure_fonts():
    """Offscreen Windows Qt cannot enumerate system fonts; register a local fallback."""
    if sys.platform == "win32" and not QFontDatabase.families():
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
            if (fonts / name).is_file():
                QFontDatabase.addApplicationFont(str(fonts / name))
    QApplication.instance().setFont(QFont("Microsoft YaHei UI", 10))
