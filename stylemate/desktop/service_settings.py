"""First-run and in-app service configuration, shared by both distributions."""
from dotenv import dotenv_values
from PySide6.QtCore import QThreadPool, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from stylemate.config.portable import DEFAULTS, FIELDS, validate_config
from stylemate.services.connection_check import check_service


class ServiceSettingsDialog(QDialog):
    def __init__(self, parent, store, first_run=False):
        super().__init__(parent)
        self.store = store
        self.value = None
        self.testing = False
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.setWindowTitle("欢迎使用 出行衣橱助手" if first_run else "模型、天气与定位")
        self.resize(690, 650)
        self.setMinimumSize(600, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        heading = QLabel("快速配置你的客户端" if first_run else "服务设置")
        heading.setObjectName("title")
        layout.addWidget(heading)
        note = QLabel("模型按需配置，也可先使用离线衣橱。密钥仅保存在本机；连接测试会发送少量测试请求。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.fields = {}
        self.results = {}
        for kind, title, prefix, model in [
            ("text", "对话", "LLM", "TEXT_MODEL_NAME"), ("vision", "图片识别", "VISION", "VISION_MODEL_NAME"),
            ("embedding", "知识检索", "EMBEDDING", "EMBEDDING_MODEL_NAME"),
        ]:
            body = self.section(title)
            if kind != "text":
                copy = QPushButton("沿用对话的地址和密钥")
                copy.clicked.connect(lambda checked=False, p=prefix: self.copy_connection(p))
                body.addWidget(copy)
            form = QFormLayout()
            for key, caption in [(prefix + "_BASE_URL", "接口地址"), (prefix + "_API_KEY", "API Key"), (model, "模型名称")]:
                field = QLineEdit()
                if key.endswith("API_KEY"):
                    field.setEchoMode(QLineEdit.EchoMode.Password)
                field.setPlaceholderText("https://你的服务地址/v1" if key.endswith("BASE_URL") else "选填，使用此能力时填写")
                self.fields[key] = field
                form.addRow(caption, field)
            body.addLayout(form)
            if kind == "text":
                presets = QHBoxLayout()
                for name, url in [("阿里云兼容地址", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                                  ("本机 Ollama", "http://localhost:11434/v1")]:
                    preset = QPushButton(name)
                    preset.clicked.connect(lambda checked=False, u=url: self.use_preset(u))
                    presets.addWidget(preset)
                body.addLayout(presets)
            self.probe_button(body, kind)
            help_text = {"text": "用于衣橱对话。模型应支持工具调用；测试通过只验证基础响应。",
                         "vision": "需要支持图片输入的模型。测试只发送程序生成的色块，不上传衣橱照片。",
                         "embedding": "用于语义检索，填写向量模型名称。留空时仍可使用本地关键词检索。"}[kind]
            explanation = QLabel(help_text)
            explanation.setWordWrap(True)
            body.addWidget(explanation)
            body.addStretch()
        body = self.section("天气与定位")
        form = QFormLayout()
        self.weather_provider = QComboBox()
        for title, value in [("高德（自己的 Web 服务 Key）", "amap"), ("Open-Meteo（免 Key，限非商业使用）", "open-meteo"), ("关闭在线天气", "disabled")]:
            self.weather_provider.addItem(title, value)
        form.addRow("天气服务", self.weather_provider)
        for key, title in [("AMAP_API_KEY", "高德 Key"), ("WEATHER_CITY", "默认城市")]:
            field = QLineEdit()
            if key.endswith("API_KEY"):
                field.setEchoMode(QLineEdit.EchoMode.Password)
            else:
                field.setPlaceholderText("例如：浙江省杭州市；尽量包含省份")
            self.fields[key] = field
            form.addRow(title, field)
        body.addLayout(form)
        self.allow_location = QCheckBox("没有指定城市时，允许高德通过 IP 推测所在城市")
        body.addWidget(self.allow_location)
        location_note = QLabel("IP 定位只到城市，可能受 VPN 或网络出口影响。默认关闭；不需要 GPS，也不自动请求定位。")
        location_note.setWordWrap(True)
        body.addWidget(location_note)
        self.probe_button(body, "weather")
        for title, url in [("申请高德 Web 服务 Key", "https://lbs.amap.com/api/webservice/gettingstarted"),
                           ("Open-Meteo 使用限制与数据来源", "https://open-meteo.com/en/pricing")]:
            link = QPushButton(title)
            link.clicked.connect(lambda checked=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            body.addWidget(link)
        credit = QLabel("Weather data: Open-Meteo.com (CC BY 4.0) · City data: GeoNames。免费接口有限额，无可用性保证；商业使用需另行授权。")
        credit.setWordWrap(True)
        body.addWidget(credit)
        body.addStretch()
        self.message = QLabel("")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        controls = QHBoxLayout()
        self.import_button = QPushButton("导入已有 .env")
        self.import_button.clicked.connect(self.import_file)
        controls.addWidget(self.import_button)
        show = QCheckBox("显示密钥")
        show.toggled.connect(self.show_keys)
        controls.addWidget(show)
        controls.addStretch()
        self.cancel_button = QPushButton("暂不配置" if first_run else "取消")
        self.cancel_button.clicked.connect(self.reject)
        controls.addWidget(self.cancel_button)
        self.save_button = QPushButton("保存并应用")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.accept_values)
        controls.addWidget(self.save_button)
        layout.addLayout(controls)
        self.populate(store.load())
        for field in self.fields.values():
            field.textChanged.connect(self.invalidate_tests)
        self.weather_provider.currentIndexChanged.connect(self.invalidate_tests)
        self.allow_location.toggled.connect(self.invalidate_tests)

    def invalidate_tests(self, *args):
        for result in self.results.values():
            result.setText("配置已修改，尚未测试")

    def use_preset(self, url):
        self.fields["LLM_BASE_URL"].setText(url)
        if url.startswith("http://localhost") and not self.fields["LLM_API_KEY"].text():
            self.fields["LLM_API_KEY"].setText("ollama")

    def section(self, title):
        area = QScrollArea()
        area.setWidgetResizable(True)
        content = QWidget()
        area.setWidget(content)
        body = QVBoxLayout(content)
        body.setSpacing(16)
        body.setContentsMargins(12, 20, 12, 16)
        self.tabs.addTab(area, title)
        return body

    def probe_button(self, body, kind):
        test = QPushButton("测试连接" if kind != "weather" else "测试天气 / 定位")
        test.clicked.connect(lambda: self.test_service(kind))
        body.addWidget(test)
        result = QLabel("尚未测试")
        result.setWordWrap(True)
        self.results[kind] = result
        body.addWidget(result)

    def populate(self, values):
        for key, field in self.fields.items():
            field.setText(values.get(key, ""))
        self.weather_provider.setCurrentIndex(max(0, self.weather_provider.findData(values.get("WEATHER_PROVIDER", "amap"))))
        self.allow_location.setChecked(values.get("ALLOW_IP_LOCATION") == "1")

    def values(self):
        return validate_config(dict(DEFAULTS) | {key: field.text() for key, field in self.fields.items()} |
                               {"WEATHER_PROVIDER": self.weather_provider.currentData(),
                                "ALLOW_IP_LOCATION": "1" if self.allow_location.isChecked() else "0"})

    def copy_connection(self, prefix):
        for suffix in ("BASE_URL", "API_KEY"):
            self.fields[prefix + "_" + suffix].setText(self.fields["LLM_" + suffix].text())

    def show_keys(self, visible):
        for key, field in self.fields.items():
            if key.endswith("API_KEY"):
                field.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)

    def import_file(self):
        filename, _ = QFileDialog.getOpenFileName(self, "导入服务配置", "", "配置文件 (*.env);;所有文件 (*)")
        if filename:
            try:
                raw = dotenv_values(filename, interpolate=False)
                imported = {key: raw[key] or "" for key in FIELDS if key in raw}
                aliases = {"LLM_API_KEY": ("OPENAI_API_KEY", "DASHSCOPE_API_KEY"),
                           "LLM_BASE_URL": ("OPENAI_BASE_URL", "DASHSCOPE_BASE_URL"),
                           "VISION_API_KEY": ("DASHSCOPE_API_KEY",),
                           "EMBEDDING_API_KEY": ("DASHSCOPE_API_KEY",), "AMAP_API_KEY": ("GAODE_API_KEY",)}
                for key, names in aliases.items():
                    if key not in imported:
                        for name in names:
                            if raw.get(name):
                                imported[key] = raw[name]
                                break
                current = dict(DEFAULTS) | {key: field.text() for key, field in self.fields.items()}
                self.populate(current | imported)
                self.message.setText("已导入到表单，检查后点击保存。")
            except Exception:
                self.message.setText("无法导入，请检查配置文件格式。")

    def accept_values(self):
        try:
            self.value = self.values()
        except ValueError as error:
            self.message.setText(str(error))
            return
        self.accept()

    def test_service(self, kind):
        if self.testing:
            return
        try:
            values = self.values()
        except ValueError as error:
            self.message.setText(str(error))
            return
        from stylemate.desktop.application import Task
        self.testing = True
        for widget in (self.tabs, self.save_button, self.import_button, self.cancel_button):
            widget.setEnabled(False)
        self.results[kind].setText("正在测试…")
        task = Task(lambda: check_service(kind, values))
        self.task = task
        task.signals.done.connect(lambda result: self.test_done(kind, result))
        task.signals.failed.connect(lambda _: self.test_done(kind, {"ok": False, "message": "测试未完成，请重试。"}))
        self.pool.start(task)

    def test_done(self, kind, result):
        self.testing = False
        for widget in (self.tabs, self.save_button, self.import_button, self.cancel_button):
            widget.setEnabled(True)
        self.results[kind].setText(result["message"])

    def reject(self):
        if not self.testing:
            super().reject()

    def closeEvent(self, event):
        if self.testing:
            event.ignore()
        else:
            super().closeEvent(event)
