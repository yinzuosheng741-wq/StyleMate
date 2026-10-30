"""Native, selectable conversation rows with safe source links."""

from __future__ import annotations

import math
import re
from html import escape

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QTextBrowser, QVBoxLayout, QWidget


def _text_html(text: str) -> str:
    """Support common assistant formatting without accepting arbitrary HTML."""
    lines = []
    for raw_line in text.split("\n"):
        line = escape(raw_line)
        line = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", line)
        line = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", line)
        line = re.sub(r"^#{1,4}\s+(.+)$", r"<b>\1</b>", line)
        line = re.sub(r"^\s*[-*]\s+", "&nbsp;&nbsp;• ", line)
        lines.append(line or "&nbsp;")
    return "<br>".join(lines)


def assistant_html(message, garments) -> str:
    html = [f'<p style="margin:0;line-height:145%;">{_text_html(message.content)}</p>']
    for outfit in message.outfits:
        names = "、".join(garments[g].name if g in garments else "已移除单品" for g in outfit.garment_ids)
        html.append('<p style="color:#555d67;"><b>搭配：</b>' + escape(names) + '</p>')
    links = []
    for source in message.sources:
        if QUrl(source.url).scheme() in {"https", "http"}:
            links.append(f'<a style="color:#526b83;" href="{escape(source.url, quote=True)}">{escape(source.title)}</a>')
    if links:
        html.append('<p style="color:#717780;"><b>参考来源</b><br>' + '<br>'.join(links) + '</p>')
    return "".join(html)


class MessageBrowser(QTextBrowser):
    """A selectable rich-text reply that grows inside the outer scroll area."""

    def __init__(self, source_handler):
        super().__init__()
        self.setObjectName("assistantMessage")
        self.setOpenLinks(False)
        self.anchorClicked.connect(source_handler)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(0)
        self.document().documentLayout().documentSizeChanged.connect(self._adjust_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.document().setTextWidth(max(1, self.viewport().width()))
        self._adjust_height()

    def _adjust_height(self, *_args):
        height = max(22, math.ceil(self.document().size().height()) + 3)
        if self.height() != height:
            self.setFixedHeight(height)


class ChatTranscript(QScrollArea):
    def __init__(self, source_handler):
        super().__init__()
        self.source_handler = source_handler
        self.setObjectName("chatTranscript")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.outer = QWidget()
        self.outer.setObjectName("chatCanvas")
        self.setWidget(self.outer)
        center = QHBoxLayout(self.outer)
        center.setContentsMargins(20, 8, 20, 18)
        center.addStretch(1)
        self.column = QWidget()
        self.column.setMaximumWidth(780)
        self.column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        center.addWidget(self.column, 10, Qt.AlignmentFlag.AlignTop)
        center.addStretch(1)
        self.rows = QVBoxLayout(self.column)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(22)
        self.rows.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.user_bubbles = []
        self.message_widgets = []

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_bubbles()

    def _resize_bubbles(self):
        width = max(160, int(self.viewport().width() * 0.66))
        for bubble, desired in getattr(self, "user_bubbles", []):
            bubble.setFixedWidth(min(desired, width))

    def set_messages(self, messages, garments, *, waiting=False):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.user_bubbles = []
        self.message_widgets = []
        if not messages:
            welcome = QWidget()
            box = QVBoxLayout(welcome)
            box.setContentsMargins(0, 54, 0, 24)
            box.setSpacing(10)
            title = QLabel("今天想聊什么？")
            title.setObjectName("chatWelcome")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            detail = QLabel("穿搭灵感、衣物洗护，或一次轻松的出行准备。")
            detail.setObjectName("subtitle")
            detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
            detail.setWordWrap(True)
            box.addWidget(title)
            box.addWidget(detail)
            self.rows.addWidget(welcome)
        for message in messages:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)
            layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            if message.role == "user":
                layout.addStretch(1)
                user_column = QWidget()
                user_layout = QVBoxLayout(user_column)
                user_layout.setContentsMargins(0, 0, 0, 0)
                user_layout.setSpacing(4)
                author = QLabel("你")
                author.setObjectName("messageMeta")
                author.setAlignment(Qt.AlignmentFlag.AlignRight)
                user_layout.addWidget(author)
                bubble = QFrame()
                bubble.setObjectName("userBubble")
                bubble.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
                bubble_box = QVBoxLayout(bubble)
                bubble_box.setContentsMargins(16, 12, 16, 12)
                text = QLabel(message.content)
                text.setObjectName("userMessage")
                text.setTextFormat(Qt.TextFormat.PlainText)
                text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                text.setWordWrap(True)
                bubble_box.addWidget(text)
                user_layout.addWidget(bubble, 0, Qt.AlignmentFlag.AlignRight)
                layout.addWidget(user_column, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
                metrics = QFontMetrics(text.font())
                desired = max(100, min(560, max((metrics.horizontalAdvance(line)
                                                 for line in message.content.splitlines()), default=0) + 32))
                self.user_bubbles.append((bubble, desired))
                self.message_widgets.append(text)
            else:
                avatar = QLabel("衣")
                avatar.setObjectName("assistantAvatar")
                avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
                avatar.setFixedSize(30, 30)
                layout.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
                content = QWidget()
                box = QVBoxLayout(content)
                box.setContentsMargins(0, 2, 0, 0)
                box.setSpacing(8)
                title = QLabel("衣橱助手")
                title.setObjectName("messageAuthor")
                box.addWidget(title)
                browser = MessageBrowser(self.source_handler)
                browser.setHtml(assistant_html(message, garments))
                box.addWidget(browser)
                layout.addWidget(content, 1)
                self.message_widgets.append(browser)
            self.rows.addWidget(row)
        if waiting:
            working = QLabel("衣橱助手正在整理…")
            working.setObjectName("messageMeta")
            self.rows.addWidget(working)
        self._resize_bubbles()
        QTimer.singleShot(50, lambda: self.verticalScrollBar().setValue(self.verticalScrollBar().maximum()))

    def plain_text(self):
        return "\n".join(widget.toPlainText() if isinstance(widget, QTextBrowser) else widget.text()
                         for widget in self.message_widgets)
