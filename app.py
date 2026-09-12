"""StyleMate: a demo-first, inventory-grounded wardrobe workbench."""

import json
import uuid
from datetime import date
from html import escape
from pathlib import Path
from urllib.parse import quote

import streamlit as st
from dotenv import load_dotenv
from pydantic import ValidationError

from stylemate.agent.tools.location_weather import WeatherResult
from stylemate.config.runtime import RuntimeSettings
from stylemate.diagnostics import runtime_diagnostics
from stylemate.domain.models import ConversationMessage, Garment, OutfitRecommendation, OutfitRequest
from stylemate.ui.components import (
    inject_style,
    render_empty_state,
    render_garment_card,
    render_outfit_card,
    render_trace,
)
from stylemate.ui.state import (
    AppContext,
    build_context,
    delete_garment,
    load_sample_wardrobe,
    validated_garment_update,
)
from stylemate.ui.today import build_packing_plan, open_outfit_guidance, weather_guidance

load_dotenv()
st.set_page_config(page_title="StyleMate 衣橱管家", page_icon="👔", layout="wide")
inject_style()


_ACTIVITIES = ("在家", "通勤", "约会", "运动", "聚会", "户外")
_TRAVEL_SCENES = {
    "城市观光": "旅行",
    "商务出差": "通勤",
    "户外活动": "户外",
    "探亲聚会": "聚会",
    "约会行程": "约会",
}
_WEATHER_FAILURE_TEXT = {
    "missing_key": "位置服务尚未配置；输入城市后仍可使用衣橱规则生成搭配。",
    "timeout": "天气服务响应超时，请稍后刷新或手动输入城市。",
    "upstream_error": "天气服务暂时不可用，请手动输入城市继续。",
    "invalid_response": "未能识别当前位置，请手动输入城市继续。",
}


def _labels(value: str) -> list[str]:
    return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]


def _image_value(context: AppContext, garment: Garment):
    if not garment.image_ref:
        return None
    if garment.image_ref.startswith("assets/demo/"):
        project_root = Path(__file__).resolve().parent
        sample_path = (project_root / garment.image_ref).resolve()
        try:
            sample_path.relative_to(project_root)
        except ValueError:
            return None
        if sample_path.suffix.lower() == ".svg" and sample_path.is_file():
            svg_text = sample_path.read_text(encoding="utf-8")
            return f"data:image/svg+xml;utf8,{quote(svg_text)}"
        return sample_path
    return context.image_store.read(context.owner_id, garment.image_ref)


def _draft_form(context: AppContext) -> None:
    draft = st.session_state.get("stylemate_draft")
    upload = st.session_state.get("stylemate_upload")
    if not draft or not upload:
        return

    st.subheader("确认衣物信息")
    with st.form("stylemate_confirm_garment"):
        name = st.text_input("名称", value=draft.get("name", ""))
        category = st.text_input("类别", value=draft.get("category", ""), placeholder="上装、下装、外套或鞋履")
        color = st.text_input("颜色", value=draft.get("primary_color", ""))
        material = st.text_input("材质", value=draft.get("material") or "")
        seasons = st.text_input("适用季节（逗号分隔）", value="，".join(draft.get("seasons", [])), placeholder="春、秋")
        styles = st.text_input("风格（逗号分隔）", value="，".join(draft.get("styles", [])), placeholder="通勤、简约")
        confirmed = st.form_submit_button("确认入库", type="primary")
    if not confirmed:
        return
    try:
        garment = Garment.model_validate(
            {
                **draft,
                "id": draft.get("id") or str(uuid.uuid4()),
                "name": name.strip(),
                "category": category.strip(),
                "primary_color": color.strip(),
                "material": material.strip() or None,
                "seasons": _labels(seasons),
                "styles": _labels(styles),
                "source": "manual" if draft.get("source") == "manual" else "ai",
            }
        )
        context.wardrobe_service.save_confirmed(context.owner_id, garment, upload["bytes"], upload["mime_type"])
    except (ValidationError, ValueError) as exc:
        st.error(f"请补全有效的衣物信息：{exc}")
        return
    st.session_state.pop("stylemate_draft", None)
    st.session_state.pop("stylemate_upload", None)
    st.success("已保存到你的衣橱。")
    st.rerun()


def _local_weather(context: AppContext) -> tuple[str, WeatherResult]:
    cached = st.session_state.get("stylemate_local_weather")
    if isinstance(cached, dict):
        return str(cached.get("city", "")), WeatherResult.model_validate(
            cached.get("weather", {"available": False, "reason": "invalid_response"})
        )

    location = context.weather_client.locate()
    if location.available:
        city = location.city or location.province
        weather = context.weather_client.weather(location.adcode or city)
        if weather.available:
            city = weather.city or city
    else:
        city = ""
        weather = WeatherResult(available=False, reason=location.reason)
    st.session_state["stylemate_local_weather"] = {
        "city": city,
        "weather": weather.model_dump(mode="json"),
        "source": "auto",
    }
    return city, weather


def _weather_panel(context: AppContext) -> tuple[str, WeatherResult]:
    city, weather = _local_weather(context)
    with st.container(key="stylemate_weather_panel"):
        header, action = st.columns([5, 1])
        header.markdown("#### 今天的天气")
        if action.button("刷新", key="refresh_local_weather", use_container_width=True):
            st.session_state.pop("stylemate_local_weather", None)
            st.session_state.pop("stylemate_base_outfit", None)
            st.rerun()

        if weather.available:
            metric_columns = st.columns(3)
            metric_columns[0].metric("位置", city or weather.city or "已定位")
            metric_columns[1].metric("当前天气", weather.summary)
            temperature = f"{weather.temperature_c:g}°C" if weather.temperature_c is not None else "暂无"
            metric_columns[2].metric("当前温度", temperature)
        else:
            reason = _WEATHER_FAILURE_TEXT.get(weather.reason, "暂时无法获取天气，请输入城市继续。")
            st.markdown(f"**{reason}**")

    with st.expander("手动设置所在城市", expanded=not weather.available):
        with st.form("manual_city_form"):
            manual_city = st.text_input(
                "城市",
                value=city,
                placeholder="例如：杭州",
                help="用于查询该城市的当前天气；天气不可用时仍会生成基础搭配。",
            )
            submitted = st.form_submit_button("使用这个城市", type="primary")
        if submitted:
            normalized_city = manual_city.strip()
            if not normalized_city:
                st.error("请输入城市名称。")
            else:
                manual_weather = context.weather_client.weather(normalized_city)
                st.session_state["stylemate_local_weather"] = {
                    "city": manual_weather.city or normalized_city,
                    "weather": manual_weather.model_dump(mode="json"),
                    "source": "manual",
                }
                st.session_state.pop("stylemate_base_outfit", None)
                st.rerun()
    return city, weather


def _cached_outfit(
    context: AppContext,
    garments: list[Garment],
    *,
    cache_key: str,
    scene: str,
    weather: WeatherResult,
    style: str | None = None,
    constraints: list[str] | None = None,
):
    signature = (
        tuple(item.id for item in garments),
        scene,
        weather.summary,
        weather.temperature_c,
        style,
        tuple(constraints or []),
    )
    cached = st.session_state.get(cache_key)
    if not isinstance(cached, dict) or cached.get("signature") != signature:
        outcome = context.outfit_skill.run(
            context.owner_id,
            OutfitRequest(
                scene=scene,
                temperature_c=weather.temperature_c if weather.available else None,
                weather_condition=weather.summary if weather.available else None,
                style_preference=style,
                extra_constraints=constraints or [],
            ),
        )
        cached = {"signature": signature, "outcome": outcome}
        st.session_state[cache_key] = cached
    return cached["outcome"]


def _render_recommendations(context: AppContext, outcome, garments: list[Garment], *, limit: int = 3) -> None:
    st.caption(outcome.user_message)
    by_id = {garment.id: garment for garment in garments}
    image_values = {garment.id: _image_value(context, garment) for garment in garments}
    recommendations = outcome.data.get("recommendations", [])[:limit]
    if not recommendations:
        render_empty_state(
            "暂时无法组成完整搭配",
            "衣橱至少需要一件上装和一件下装；天气较冷时还需要外套。",
        )
        return
    for payload in recommendations:
        render_outfit_card(OutfitRecommendation.model_validate(payload), by_id, image_values)


def _today_tab(context: AppContext, garments: list[Garment]) -> None:
    st.markdown(
        f"<div class='stylemate-kicker'>TODAY / {date.today():%Y.%m.%d}</div>"
        "<h2>今天穿什么</h2>"
        "<div class='stylemate-muted'>根据当地天气和你的安排，选一套今天穿得舒服的衣服。</div>",
        unsafe_allow_html=True,
    )
    _city, weather = _weather_panel(context)
    guidance = weather_guidance(weather)
    st.markdown(
        f"<div class='stylemate-weather'><strong>{escape(guidance.headline)}</strong>"
        f"<span>{escape(guidance.detail)}</span></div>",
        unsafe_allow_html=True,
    )

    if not garments:
        open_guidance = open_outfit_guidance(weather)
        st.markdown(
            "#### 先给你一套基础选择"
            f"<div class='stylemate-open-recommendation'>"
            f"<strong>上装</strong><span>{escape(open_guidance.top)}</span>"
            f"<strong>下装</strong><span>{escape(open_guidance.bottom)}</span>"
            f"<strong>鞋履</strong><span>{escape(open_guidance.shoes)}</span>"
            f"<strong>配色</strong><span>{escape(open_guidance.color)}</span>"
            f"<strong>避免</strong><span>{escape(open_guidance.avoid)}</span>"
            "</div>",
            unsafe_allow_html=True,
        )
        render_empty_state(
            "还没有添加衣物",
            "添加衣物后，我会结合你的单品调整建议；现在也可以直接参考上面的基础选择。",
        )
        if st.button("加载样例衣橱", type="primary", key="load_samples_today"):
            count = load_sample_wardrobe(context)
            st.success(f"已添加 {count} 件样例衣物。")
            st.rerun()
        return

    st.markdown("#### 先给你一个基础组合")
    base_outcome = _cached_outfit(
        context,
        garments,
        cache_key="stylemate_base_outfit",
        scene="日常",
        weather=weather,
    )
    _render_recommendations(context, base_outcome, garments, limit=1)

    st.divider()
    st.markdown("#### 今天主要去做什么？")
    st.caption("选择场景后，会重新计算正式度、活动量和穿着风格。")
    activity = st.radio(
        "今日场景",
        _ACTIVITIES,
        index=None,
        horizontal=True,
        key="stylemate_activity",
        label_visibility="collapsed",
    )
    with st.expander("补充偏好和限制"):
        style = st.selectbox(
            "偏好风格",
            ["不限定", "简约", "通勤", "休闲", "温柔", "优雅", "运动"],
            key="stylemate_today_style",
        )
        constraints = st.multiselect(
            "今天不想穿",
            ["不穿裙子", "不穿高跟鞋"],
            key="stylemate_today_constraints",
        )
    if activity:
        st.markdown(f"##### 已按“{activity}”重新推荐")
        activity_outcome = _cached_outfit(
            context,
            garments,
            cache_key="stylemate_activity_outfit",
            scene=activity,
            weather=weather,
            style=None if style == "不限定" else style,
            constraints=constraints,
        )
        _render_recommendations(context, activity_outcome, garments)
        render_trace(activity_outcome.trace)
    else:
        st.markdown(
            "<div class='stylemate-section-note'>告诉我今天的活动，搭配会从“日常可穿”进一步调整到具体场景。</div>",
            unsafe_allow_html=True,
        )

    _travel_planner(context, garments)


def _travel_planner(context: AppContext, garments: list[Garment]) -> None:
    with st.container(key="stylemate_travel_panel"):
        st.subheader("旅行行李助手")
        st.caption("目的地天气仅作为当前情况参考，不代表行程日期的未来预报。")
        with st.form("travel_planner_form"):
            fields = st.columns([1.35, 1, 1])
            destination = fields[0].text_input("目的地", placeholder="例如：成都")
            duration = int(fields[1].number_input("行程天数", min_value=1, max_value=30, value=3))
            trip_type = fields[2].selectbox("行程重点", list(_TRAVEL_SCENES))
            travel_style = st.selectbox(
                "旅行风格",
                ["不限定", "休闲", "简约", "通勤", "优雅", "运动"],
            )
            submitted = st.form_submit_button("生成行李建议", type="primary")

    if submitted:
        normalized_destination = destination.strip()
        if not normalized_destination:
            st.error("请输入旅行目的地。")
        else:
            destination_weather = context.weather_client.weather(normalized_destination)
            outcome = context.outfit_skill.run(
                context.owner_id,
                OutfitRequest(
                    scene=_TRAVEL_SCENES[trip_type],
                    temperature_c=(destination_weather.temperature_c if destination_weather.available else None),
                    weather_condition=(destination_weather.summary if destination_weather.available else None),
                    style_preference=(None if travel_style == "不限定" else travel_style),
                ),
            )
            recommendation_payloads = outcome.data.get("recommendations", [])
            recommendation_ids = recommendation_payloads[0].get("garment_ids", []) if recommendation_payloads else []
            plan = build_packing_plan(
                garments,
                recommendation_ids,
                duration,
                destination_weather,
            )
            st.session_state["stylemate_travel_plan"] = {
                "destination": destination_weather.city or normalized_destination,
                "duration": duration,
                "trip_type": trip_type,
                "weather": destination_weather.model_dump(mode="json"),
                "outcome": outcome,
                "plan": plan,
            }

    payload = st.session_state.get("stylemate_travel_plan")
    if not isinstance(payload, dict):
        return
    destination_weather = WeatherResult.model_validate(payload["weather"])
    if destination_weather.available:
        temperature = (
            f"，{destination_weather.temperature_c:g}°C" if destination_weather.temperature_c is not None else ""
        )
        st.info(
            f"{payload['destination']}当前天气：{destination_weather.summary}{temperature}。"
            "以下建议按当前天气生成，请在出发前再次确认预报。"
        )
    else:
        st.warning(f"暂未取得{payload['destination']}的当前天气，已按行程类型和衣橱库存给出基础清单。")

    result_columns = st.columns([1.2, 1])
    plan = payload["plan"]
    with result_columns[0]:
        st.markdown("##### 从我的衣橱带上")
        if plan.garments:
            st.markdown(
                "<div class='stylemate-item-list'>"
                + "".join(f"<span>{escape(item.name)} · {escape(item.category)}</span>" for item in plan.garments)
                + "</div>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("衣橱中暂时没有适合加入清单的单品。")
    with result_columns[1]:
        st.markdown("##### 还要记得")
        st.write("、".join(plan.essentials))
        for gap in plan.gaps:
            st.warning(gap)
    st.markdown("##### 目的地参考搭配")
    _render_recommendations(context, payload["outcome"], garments, limit=1)


def _wardrobe_tab(context: AppContext, garments: list[Garment]) -> None:
    st.subheader("我的衣橱")
    st.caption(f"{len(garments)} 件单品 · {len({item.category for item in garments})} 个类别")
    if not garments:
        render_empty_state("还没有衣物", "上传一张清晰的衣物照片，识别后确认入库。")
        if st.button("加载样例衣橱", type="primary", key="load_samples_wardrobe"):
            load_sample_wardrobe(context)
            st.rerun()
    else:
        categories = sorted({garment.category for garment in garments})
        styles = sorted({style for garment in garments for style in garment.styles})
        filters = st.columns(2)
        selected_category = filters[0].selectbox("按类别筛选", ["全部", *categories])
        selected_style = filters[1].selectbox("按风格筛选", ["全部", *styles])
        visible = [
            garment
            for garment in garments
            if (selected_category == "全部" or garment.category == selected_category)
            and (selected_style == "全部" or selected_style in garment.styles)
        ]
        grid_columns = st.columns(3)
        for index, garment in enumerate(visible):
            with grid_columns[index % 3]:
                with st.container(key=f"garment_card_{garment.id}"):
                    render_garment_card(garment, _image_value(context, garment))
                    with st.expander("编辑或删除"):
                        with st.form(f"edit_{garment.id}"):
                            name = st.text_input("名称", garment.name, key=f"name_{garment.id}")
                            category = st.text_input("类别", garment.category, key=f"category_{garment.id}")
                            color = st.text_input("颜色", garment.primary_color, key=f"color_{garment.id}")
                            material = st.text_input("材质", garment.material or "", key=f"material_{garment.id}")
                            seasons = st.text_input("适用季节", "，".join(garment.seasons), key=f"seasons_{garment.id}")
                            styles_value = st.text_input("风格", "，".join(garment.styles), key=f"styles_{garment.id}")
                            save = st.form_submit_button("保存修改")
                        if save:
                            try:
                                updated = validated_garment_update(
                                    garment,
                                    name=name,
                                    category=category,
                                    primary_color=color,
                                    material=material,
                                    seasons=seasons,
                                    styles=styles_value,
                                )
                                context.repository.save_garment(context.owner_id, updated)
                                st.rerun()
                            except (ValidationError, ValueError) as exc:
                                st.error(f"无法保存：{exc}")
                        if st.button("删除这件衣物", key=f"delete_{garment.id}"):
                            delete_garment(context, garment.id)
                            st.rerun()

    st.divider()
    st.subheader("新增衣物")
    uploaded = st.file_uploader("上传衣物照片", type=["jpg", "jpeg", "png", "webp"])
    note = st.text_input("补充说明（可选）", placeholder="例如：偏宽松的米色风衣")
    if uploaded and st.button("识别衣物", type="primary"):
        image_bytes = uploaded.getvalue()
        outcome = context.onboarding_skill.run(context.owner_id, image_bytes, uploaded.type, uploaded.name, note)
        if outcome.status == "failed" or "garment" not in outcome.data:
            st.session_state.pop("stylemate_draft", None)
            st.session_state.pop("stylemate_upload", None)
            st.session_state["stylemate_onboarding_trace"] = outcome.trace
            st.warning(outcome.user_message)
            return
        st.session_state["stylemate_draft"] = outcome.data["garment"]
        st.session_state["stylemate_upload"] = {"bytes": image_bytes, "mime_type": uploaded.type}
        st.session_state["stylemate_onboarding_trace"] = outcome.trace
        st.info(outcome.user_message)
    _draft_form(context)
    if trace := st.session_state.get("stylemate_onboarding_trace"):
        render_trace(trace)


def _assistant_rail(context: AppContext, garments: list[Garment]) -> None:
    with st.container(key="stylemate_assistant_rail"):
        st.markdown(
            "<div class='stylemate-assistant-head'>"
            "<div class='status'>STYLEMATE AGENT · ONLINE</div>"
            "<h3>AI 衣橱助手</h3>"
            f"<p>已接入 {len(garments)} 件衣物 · 可结合你的衣橱推荐</p>"
            "</div>",
            unsafe_allow_html=True,
        )
        top_actions = st.columns([1, 1.4, 1.35], gap="small")
        if top_actions[0].button(
            "新建",
            key="clear_agent_conversation",
            icon=":material/add_comment:",
            help="新建独立对话，保留已有历史",
            use_container_width=True,
        ):
            st.session_state["stylemate_conversation_id"] = f"conversation-{uuid.uuid4().hex[:10]}"
            st.session_state["stylemate_show_history"] = False
            st.session_state.pop("stylemate_profile_proposal", None)
            st.rerun()
        if top_actions[1].button(
            "历史对话",
            key="open_agent_history",
            icon=":material/history:",
            help="查看并切换已保存的对话",
            use_container_width=True,
        ):
            st.session_state["stylemate_show_history"] = not st.session_state.get("stylemate_show_history", False)
            st.rerun()
        with top_actions[2].popover(
            "资料",
            icon=":material/library_books:",
            help="管理当前会话可检索的资料",
            use_container_width=True,
        ):
            _assistant_documents(context)

        presets = (
            ("weather", "天气穿搭", "根据今天的天气推荐穿搭"),
            ("care", "洗护帮助", "洗护帮助"),
            ("purchase", "推荐购买", "推荐购买"),
            ("travel", "旅游出行", "旅游出行"),
        )
        selected_prompt = ""
        conversation = context.agent_repository.load_conversation(context.owner_id, context.conversation_id)
        chat_history = st.container(
            height=430,
            border=False,
            key="stylemate_chat_history",
        )
        with chat_history:
            if st.session_state.get("stylemate_show_history"):
                st.markdown(
                    "<div class='stylemate-kicker'>历史对话</div>",
                    unsafe_allow_html=True,
                )
                sessions = context.agent_service.list_conversations(context.owner_id)
                if not sessions:
                    st.caption("还没有已保存的对话")
                for session in sessions[:12]:
                    session_id = session["conversation_id"]
                    label = session["title"]
                    if session_id == context.conversation_id:
                        label = f"当前 · {label}"
                    if (
                        st.button(
                            label,
                            key=f"switch_agent_conversation_{session_id}",
                            use_container_width=True,
                        )
                        and session_id != context.conversation_id
                    ):
                        st.session_state["stylemate_conversation_id"] = session_id
                        st.session_state["stylemate_show_history"] = False
                        st.session_state.pop("stylemate_profile_proposal", None)
                        st.rerun()
            if not conversation.messages:
                st.markdown(
                    "<div class='stylemate-kicker'>试试这些功能</div>",
                    unsafe_allow_html=True,
                )
                preset_columns = st.columns(2, gap="small")
                for index, (key, label, prompt_value) in enumerate(presets):
                    if preset_columns[index % 2].button(
                        label,
                        key=f"assistant_preset_{key}",
                        use_container_width=True,
                    ):
                        selected_prompt = prompt_value
                st.caption("告诉我场景、目的地，或你想解决的衣物问题。")
            else:
                for message in conversation.messages[-8:]:
                    _render_agent_message(message)
            _render_profile_proposal(context)
            _render_pending_action(context)

        with st.form("assistant_prompt_form", clear_on_submit=True):
            prompt = st.text_area(
                "消息",
                placeholder="例如：周五要面试，帮我搭一套不紧身的衣服",
                height=76,
                label_visibility="collapsed",
            )
            submitted = st.form_submit_button("发送", type="primary", use_container_width=True)
        if submitted:
            selected_prompt = prompt.strip()
        if not selected_prompt:
            return
        try:
            with chat_history:
                with st.chat_message("user"):
                    st.markdown(selected_prompt)
                with st.chat_message("assistant"):
                    with st.spinner("正在为你整理一套方案..."):
                        context.agent_service.chat(
                            context.owner_id,
                            context.conversation_id,
                            selected_prompt,
                        )
            proposal = context.agent_service.propose_profile_updates(context.owner_id, selected_prompt)
            if proposal:
                st.session_state["stylemate_profile_proposal"] = proposal
        except ValueError as exc:
            with chat_history:
                st.error(str(exc))
            return
        except Exception:
            with chat_history:
                st.error("助手暂时不可用，请稍后重试。")
            return
        st.rerun()


def _assistant_documents(context: AppContext) -> None:
    documents = context.agent_service.list_documents(context.owner_id, context.conversation_id)
    for saved_document in documents:
        st.caption(f"{saved_document.filename} · {len(saved_document.text)} 字符")
        if st.button(
            "删除",
            key=f"delete_agent_document_{saved_document.document_id}",
        ):
            context.agent_service.delete_document(
                context.owner_id,
                context.conversation_id,
                saved_document.document_id,
            )
            st.rerun()
    document = st.file_uploader(
        "上传 TXT、Markdown 或 PDF",
        type=["txt", "md", "pdf"],
        key="stylemate_agent_document",
    )
    if document and st.button("加入本次会话", key="ingest_agent_document"):
        try:
            context.agent_service.ingest_document(
                context.owner_id,
                context.conversation_id,
                document.name,
                document.type or "application/octet-stream",
                document.getvalue(),
            )
            st.success("资料已加入这次对话，可以继续提问。")
        except ValueError as exc:
            st.error(f"文档无法加入：{exc}")


def _render_agent_message(message: ConversationMessage) -> None:
    with st.chat_message(message.role):
        st.markdown(message.content)
        if message.sources:
            with st.expander("引用来源"):
                for source in message.sources:
                    st.markdown(f"- [{source.title}]({source.url})")
        if message.traces:
            with st.expander("处理详情"):
                for step in message.traces:
                    st.write(f"{step.name} · {step.status} · {step.summary}")


def _render_profile_proposal(context: AppContext) -> None:
    proposal = st.session_state.get("stylemate_profile_proposal")
    if not isinstance(proposal, dict) or not proposal:
        return
    labels = {
        "height": "身高",
        "weight": "体重",
        "fit_preference": "版型偏好",
        "style_preference": "风格偏好",
        "color_preference": "颜色偏好",
        "scene_preference": "常用场景",
        "body_features": "体型特征",
    }
    with st.container(border=True):
        st.markdown("**检测到新的长期偏好**")
        for key, value in proposal.items():
            st.write(f"{labels.get(key, key)}：{value}")
        confirm, dismiss = st.columns(2)
        if confirm.button("确认保存", key="confirm_profile_memory", type="primary"):
            context.agent_service.confirm_profile_updates(context.owner_id, proposal)
            st.session_state.pop("stylemate_profile_proposal", None)
            st.success("偏好已保存，后续对话会自动带入。")
            st.rerun()
        if dismiss.button("忽略", key="dismiss_profile_memory"):
            st.session_state.pop("stylemate_profile_proposal", None)
            st.rerun()


def _render_pending_action(context: AppContext) -> None:
    action = context.agent_repository.get_pending(context.owner_id, context.conversation_id)
    if action is None:
        return
    operation_labels = {"add": "新增衣物", "update": "修改衣物", "delete": "删除衣物"}
    with st.container(border=True):
        st.markdown(f"**待确认：{operation_labels[action.operation]}**")
        if action.target_garment_id:
            st.caption(f"衣物编号：{action.target_garment_id}")
        preview = action.after if action.operation != "delete" else action.before
        if preview:
            allowed = {
                key: preview[key]
                for key in ("name", "category", "primary_color", "material", "seasons", "styles")
                if key in preview
            }
            st.json(allowed)
        confirm, cancel = st.columns(2)
        if confirm.button("确认执行", key=f"confirm_action_{action.id}", type="primary"):
            result = context.agent_service.confirm(context.owner_id, context.conversation_id, action.id)
            (st.success if result.status == "confirmed" else st.warning)(result.user_message)
            st.rerun()
        if cancel.button("取消", key=f"cancel_action_{action.id}"):
            result = context.agent_service.cancel(context.owner_id, context.conversation_id, action.id)
            (st.info if result.status == "cancelled" else st.warning)(result.user_message)
            st.rerun()


def _about_tab(context: AppContext) -> None:
    st.markdown(
        "<div class='stylemate-kicker'>PROJECT NOTES</div>"
        "<h2>关于项目</h2>"
        "<div class='stylemate-muted'>面向个人衣橱场景的有边界 Agent 应用</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div class='stylemate-techline'><strong>技术栈</strong> &nbsp; "
        "Streamlit · LangGraph · Pydantic · Chroma · SQLite · OpenAI 兼容模型服务</div>",
        unsafe_allow_html=True,
    )
    feature_columns = st.columns(3, gap="medium")
    features = (
        (
            "01 / AGENT",
            "有边界的工具编排",
            "穿搭、天气、衣橱查询与写操作均使用结构化工具；写操作必须经过用户确认。",
        ),
        (
            "02 / RETRIEVAL",
            "混合知识检索",
            "知识问答采用 BM25 + 向量召回 + RRF 融合，并返回可追溯的知识来源。",
        ),
        (
            "03 / MEMORY",
            "结构化会话记忆",
            "长期偏好保存为带来源的会话事实，临时约束设有有效期，避免上下文无限膨胀。",
        ),
    )
    for column, (number, title, body) in zip(feature_columns, features):
        column.markdown(
            f"<div class='stylemate-feature'><div class='number'>{number}</div>" f"<h4>{title}</h4><p>{body}</p></div>",
            unsafe_allow_html=True,
        )

    st.markdown("#### 质量验证")
    mode_text = (
        "演示模式仅在当前浏览器会话保存数据。"
        if context.settings.app_mode == "demo"
        else "本地模式将衣物元数据保存在本机 SQLite，图片保存在本地目录。"
    )
    artifact = Path("artifacts/agent_evaluation.json")
    if not artifact.is_file():
        st.caption("评测将在发布前生成。")
        return
    try:
        metrics = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        st.caption("评测将在发布前生成。")
        return
    retrieval_case_count = int(metrics.get("retrieval_case_count", 0))
    st.markdown(
        "<div class='stylemate-eval-summary'>"
        "<strong>BM25 + Embedding + Chroma + RRF</strong> 当前混合检索链路"
        f"<span>固定离线回归集包含 {retrieval_case_count} 条文档级用例，"
        "评估召回、排序质量与首个相关结果位置；离线结果使用可复现 Embedding 配置。</span></div>",
        unsafe_allow_html=True,
    )
    metric_columns = st.columns(3)
    metric_labels = (
        ("rag_recall_at_5", "Recall@5"),
        ("rag_mrr_at_5", "MRR@5"),
        ("rag_ndcg_at_5", "nDCG@5"),
    )
    for column, (key, label) in zip(metric_columns, metric_labels):
        value = metrics.get(key)
        column.metric(label, f"{float(value) * 100:.2f}%" if value is not None else "--")
    st.markdown(
        f"<div class='stylemate-privacy'>{mode_text}<br>上传图片仅用于识别与衣橱保存；"
        "页面不会展示图片字节或 API 密钥。</div>",
        unsafe_allow_html=True,
    )
    st.markdown("#### 运行时诊断")
    diagnostics = runtime_diagnostics(context.settings, context.agent_service.retriever)
    readiness = (
        ("文本模型", diagnostics["text_model_configured"]),
        ("视觉识别", diagnostics["vision_configured"]),
        ("向量检索", diagnostics["embedding_configured"]),
        ("天气服务", diagnostics["weather_configured"]),
    )
    cols = st.columns(4)
    for col, (label, configured) in zip(cols, readiness):
        col.metric(label, "已配置" if configured else "规则降级")
    st.caption(
        f"当前 RAG 路径：{diagnostics['rag_mode']}；诊断信息只显示能力状态和计数，不包含密钥、原文或向量。"
    )


def main() -> None:
    settings = RuntimeSettings.from_env()
    context = build_context(st.session_state, settings)
    garments = context.repository.list_garments(context.owner_id)
    st.markdown(
        "<div class='stylemate-brand-kicker'>PERSONAL WARDROBE AGENT</div>",
        unsafe_allow_html=True,
    )
    st.title("StyleMate 衣橱管家")
    st.caption("结合当地天气和你的行程，推荐今天适合穿的衣服。")
    st.markdown("<div class='stylemate-brand-rule'></div>", unsafe_allow_html=True)
    main_column, assistant_column = st.columns([2, 1], gap="large")
    with main_column:
        today, wardrobe, about = st.tabs(["今日搭配", "我的衣橱", "关于项目"])
        with today:
            _today_tab(context, garments)
        with wardrobe:
            _wardrobe_tab(context, garments)
        with about:
            _about_tab(context)
    with assistant_column:
        _assistant_rail(context, garments)


main()
