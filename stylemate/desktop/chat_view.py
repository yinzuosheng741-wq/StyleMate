"""Safe, selectable conversation markup for the native Qt transcript."""

from __future__ import annotations

import re
from html import escape

from PySide6.QtCore import QUrl


def _text_html(text: str, *, assistant: bool) -> str:
    """Render common assistant formatting without accepting arbitrary HTML."""
    lines = []
    for raw_line in text.split("\n"):
        line = escape(raw_line)
        if assistant:
            line = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", line)
            line = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", line)
            line = re.sub(r"^#{1,4}\s+(.+)$", r"<b>\1</b>", line)
            line = re.sub(r"^\s*[-*]\s+", "&nbsp;&nbsp;• ", line)
        lines.append(line or "&nbsp;")
    return "<br>".join(lines)


def conversation_html(messages, garments) -> str:
    """Create clearly aligned roles while retaining citations and outfit names."""
    html = ['<html><body style="font-family:Microsoft YaHei UI;color:#273b35;">']
    if not messages:
        html.append('<p style="font-size:19px;color:#244d3e;"><b>你好，今天想聊什么？</b></p>')
        html.append('<p style="color:#75847a;">可以问我穿搭、衣物洗护，或者一起准备旅行行李。</p>')
    for message in messages:
        assistant = message.role == "assistant"
        content = _text_html(message.content, assistant=assistant)
        if assistant:
            html.append('<p style="color:#356b50;font-size:13px;"><b>●  衣橱助手</b></p>')
            html.append(f'<p style="line-height:145%;">{content}</p>')
            for outfit in message.outfits:
                names = "、".join(garments[g].name if g in garments else "已移除单品" for g in outfit.garment_ids)
                html.append('<p style="color:#526a5b;"><b>搭配：</b>' + escape(names) + '</p>')
            links = []
            for source in message.sources:
                if QUrl(source.url).scheme() in {"https", "http"}:
                    links.append(f'<a href="{escape(source.url, quote=True)}">{escape(source.title)}</a>')
            if links:
                html.append('<p style="color:#718078;"><b>参考来源</b><br>' + '<br>'.join(links) + '</p>')
        else:
            # QTextDocument supports tables and cell backgrounds, not browser CSS
            # flexbox or rounded divs. A spacer column keeps user messages right-aligned.
            longest_line = max((len(line) for line in message.content.splitlines()), default=0)
            width = min(76, max(28, 8 + 2 * longest_line))
            html.append('<p align="right" style="color:#718078;font-size:12px;"><b>你</b></p>')
            html.append('<table width="100%" cellspacing="0" cellpadding="0" border="0"><tr>'
                        f'<td width="{100 - width}%"></td><td width="{width}%" bgcolor="#e8f1e9">'
                        '<table width="100%" cellspacing="0" cellpadding="12" border="0"><tr><td>'
                        f'{content}</td></tr></table></td></tr></table>')
        html.append('<p style="font-size:5px;">&nbsp;</p>')
    html.append('</body></html>')
    return "".join(html)
