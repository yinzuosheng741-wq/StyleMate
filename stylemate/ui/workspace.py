"""Conversation-first desktop shell and inspectable memory."""

from uuid import uuid4

import streamlit as st

from stylemate.agent.memory import prune_expired_facts


def render_desktop_sidebar(context):
    target = st.session_state.pop("stylemate_navigation_target", None)
    if target:
        st.session_state["desktop_page"] = target
    with st.sidebar:
        st.markdown("### StyleMate")
        page = st.radio("工作区", ["AI 对话", "衣橱工作台"], key="desktop_page")
        if st.button("＋ 新对话", key="desktop_new_chat", use_container_width=True):
            st.session_state["stylemate_conversation_id"] = f"conversation-{uuid4().hex}"
            st.session_state["stylemate_navigation_target"] = "AI 对话"
            st.session_state.pop("stylemate_profile_proposal", None)
            st.rerun()
        query = st.text_input("搜索历史对话", placeholder="按标题查找", key="desktop_history_query")
        st.caption("历史对话")
        matches = 0
        for session in context.agent_service.list_conversations(context.owner_id):
            if query.casefold() not in session["title"].casefold():
                continue
            matches += 1
            session_id = session["conversation_id"]
            if st.button(session["title"], key=f"desktop_history_{session_id}",
                         type="primary" if session_id == context.conversation_id else "secondary",
                         use_container_width=True):
                st.session_state["stylemate_conversation_id"] = session_id
                st.session_state["stylemate_navigation_target"] = "AI 对话"
                st.session_state.pop("stylemate_profile_proposal", None)
                st.rerun()
        if not matches:
            st.caption("还没有对话，或没有匹配的结果")
        st.divider()
        st.caption("本机保存" if context.settings.app_mode == "local" else "演示模式 · 当前窗口内保存")
        st.caption(f"衣橱中有 {len(context.repository.list_garments(context.owner_id))} 件衣物")
        render_memory_controls(context)
    return page


def render_memory_controls(context):
    with st.expander("记忆与权限"):
        state = context.agent_repository.load_conversation(context.owner_id, context.conversation_id)
        facts = prune_expired_facts(state.facts)
        st.markdown("**本次会话记忆**")
        st.json(facts.model_dump(mode="json", exclude_defaults=True, exclude={"provenance"}))
        if facts.provenance:
            st.caption("来源与有效期")
            st.dataframe([{"字段": item.field, "内容": item.value,
                           "来源消息": item.source_message_id,
                           "有效期": str(item.expires_at or "会话内")}
                          for item in facts.provenance], hide_index=True)
        if st.button("忘记本次对话上下文", key="stylemate_forget_context"):
            context.agent_service.forget_context(context.owner_id, context.conversation_id)
            st.session_state.pop("stylemate_profile_proposal", None)
            st.rerun()
        st.caption("保留可阅读的历史，重置模型上下文和待执行操作；已上传资料及长期偏好单独管理。")
        st.markdown("**已确认的长期偏好**")
        profile = context.agent_service.profile_service.get(context.owner_id)
        for field, value in profile.items():
            st.write(f"{field}：{value}")
            if st.button("遗忘", key=f"forget_profile_{field}"):
                context.agent_service.forget_profile_field(context.owner_id, field)
                st.rerun()
        if not profile:
            st.caption("尚未保存长期偏好")
        st.markdown("**工具边界**")
        st.caption("仅访问当前用户的衣橱和本会话资料。新增、修改、删除先生成预览，确认后执行。记忆和文档不能授予工具权限。")


def inject_desktop_style():
    st.markdown("""<style>
    .stApp {background:#ffffff;}
    [data-testid="stSidebar"] {background:#f7f7f8;border-right:1px solid #ececec;}
    .block-container {max-width:960px;padding-top:2rem;padding-bottom:4rem;}
    .st-key-stylemate_desktop_chat {width:100%;border:0;background:transparent;padding:0;}
    .st-key-stylemate_desktop_history {background:transparent;border:0;padding:.75rem 0;min-height:240px;}
    .st-key-stylemate_desktop_chat [data-testid="stChatMessage"] {padding:1.25rem .75rem;border-radius:18px;background:transparent;}
    .st-key-stylemate_desktop_chat [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {background:#f4f4f5;margin-left:8%;}
    .st-key-stylemate_desktop_chat [data-testid="stChatMessage"] p,
    .st-key-stylemate_desktop_chat [data-testid="stChatMessage"] li {font-size:1rem;line-height:1.8;}
    .st-key-stylemate_desktop_chat [data-testid="stChatMessage"] > div {min-width:0;}
    .st-key-stylemate_desktop_chat [data-testid="stMarkdownContainer"] {overflow-wrap:anywhere;}
    .st-key-stylemate_desktop_chat table {display:block;max-width:100%;overflow-x:auto;}
    [data-testid="stChatInput"] {border-radius:24px;border:1px solid #dedede;}
    [data-testid="stSidebar"] button {border:0;border-radius:10px;text-align:left;}
    [data-testid="stSidebar"] [data-testid="stTextInput"] input {border-radius:10px;}
    [data-testid="stExpander"] {border-radius:12px;border-color:#e9e9ec;}
    .st-key-stylemate_desktop_chat h2 {font-size:2.2rem;font-weight:650;letter-spacing:-.04em;color:#18181b;}
    [class*="st-key-assistant_preset_"] button {min-height:72px;border:1px solid #e7e7eb;background:#fff;border-radius:14px;box-shadow:none;font-weight:500;}
    [class*="st-key-assistant_preset_"] button:hover {background:#f7f7f8;border-color:#d4d4d8;}
    [class*="st-key-stylemate_outfit_"] {border-radius:14px!important;border-top:1px solid #e7e7eb!important;box-shadow:none!important;}
    .stylemate-assistant-head {background:transparent;border:0!important;margin:0!important;padding:.5rem 0 1.5rem!important;}
    .stylemate-assistant-head .status {display:none;}
    .stylemate-assistant-head h3 {display:none;}
    .st-key-stylemate_desktop_history h2 {text-align:center;margin-top:2rem;}
    [data-testid="stToolbar"] {display:none;}
    [data-testid="stDecoration"] {display:none;}
    @media(max-width:700px){.block-container{padding-left:1rem;padding-right:1rem;}}
    </style>""", unsafe_allow_html=True)
