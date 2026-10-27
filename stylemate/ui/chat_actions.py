"""Read-only conversation export and explicit task drafts for the desktop UI."""

import re
from html import escape

from stylemate.domain.models import ConversationState, Garment


def literal_text(value: str) -> str:
    """Keep exported transcript text literal even in a Markdown/HTML viewer."""
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", escape(value))


def conversation_export(state: ConversationState, garments: list[Garment]) -> str:
    by_id = {item.id: item for item in garments}
    parts = ["# StyleMate 对话", "", "导出当前可阅读历史；不包含内部记忆、工具执行数据或上传文件原文。", ""]
    for message in state.transcript or state.messages:
        parts.extend(["## " + ("你" if message.role == "user" else "StyleMate"), "", literal_text(message.content), ""])
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


def clear_task_draft(state):
    for key in ("stylemate_task_draft", "stylemate_task_text"):
        state.pop(key, None)


def start_task_draft(state, text):
    state["stylemate_task_draft"] = True
    state["stylemate_task_text"] = text


def render_task_draft(st):
    if not st.session_state.get("stylemate_task_draft"):
        return None
    with st.container(key="workspace_draft"):
        st.caption("任务草稿 · 补充条件后再发送")
        with st.form("stylemate_task_form"):
            text = st.text_area("编辑你的问题", key="stylemate_task_text", height=140, max_chars=6000)
            submit, cancel = st.columns([1, 1])
            sent = submit.form_submit_button("发送这个问题", type="primary", use_container_width=True)
            cancelled = cancel.form_submit_button("取消", use_container_width=True)
        if cancelled:
            st.session_state.pop("stylemate_task_draft", None)
            st.rerun()
        if sent:
            if not text.strip():
                st.warning("请先填写问题。")
            else:
                return text.strip()
    return None
