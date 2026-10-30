"""Read-only conversation export for the native client."""

import re
from html import escape

from stylemate.domain.models import ConversationState, Garment


def literal_text(value: str) -> str:
    """Keep exported transcript text literal even in a Markdown/HTML viewer."""
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", escape(value))


def conversation_export(state: ConversationState, garments: list[Garment]) -> str:
    by_id = {item.id: item for item in garments}
    parts = ["# 出行衣橱助手 对话", "", "导出当前可阅读历史；不包含内部记忆、工具执行数据或上传文件原文。", ""]
    for message in state.transcript or state.messages:
        parts.extend(["## " + ("你" if message.role == "user" else "出行衣橱助手"), "", literal_text(message.content), ""])
        if message.outfits:
            parts.extend(["### 搭配记录", "", "历史候选按当前衣橱解析，不代表此刻适合穿着；规则评分不是成功概率。", ""])
            for outfit in message.outfits:
                names = [literal_text(by_id[key].name) if key in by_id else "[单品已不在当前衣橱]"
                         for key in outfit.garment_ids]
                parts.extend(["- " + "、".join(names), ""])
        if message.sources:
            parts.extend(["### 来源记录", ""])
            for source in message.sources:
                parts.append("- " + literal_text(source.title) + " · " + literal_text(source.url))
            parts.append("")
    return "\n".join(parts)


