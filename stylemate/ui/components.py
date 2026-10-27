"""Focused Streamlit renderers for the StyleMate workbench."""

from html import escape

import streamlit as st

from stylemate.domain.models import AgentTrace, Garment, OutfitRecommendation


def inject_style() -> None:
    st.markdown(
        """
        <style>
        :root {
            --sm-ink: #1d2823;
            --sm-muted: #66736d;
            --sm-line: #d9e1dc;
            --sm-surface: #ffffff;
            --sm-green: #176b4d;
            --sm-green-dark: #173c31;
            --sm-mint: #e7f2ec;
            --sm-coral: #d9684e;
            --sm-coral-soft: #faeee9;
        }
        html, body, [class*="css"] {font-family: Inter, "PingFang SC", "Microsoft YaHei", sans-serif;}
        .stApp {background: #f4f6f3; color: var(--sm-ink);}
        [data-testid="stHeader"] {background: transparent;}
        .block-container {max-width: 1480px; padding-top: 1.2rem; padding-bottom: 3rem;}
        h1, h2, h3, h4, h5 {letter-spacing: 0; color: var(--sm-ink);}
        h1 {font-size: 2.15rem !important; line-height: 1.15 !important; margin: .15rem 0 .25rem !important;}
        h2 {font-size: 1.65rem !important;}
        h3 {font-size: 1.35rem !important;}
        [data-testid="stCaptionContainer"] {color: var(--sm-muted);}
        .stylemate-brand-kicker {font-size: .7rem; font-weight: 800; color: var(--sm-green); letter-spacing: .12rem; margin-top: .35rem;}
        .stylemate-brand-rule {height: 1px; background: var(--sm-line); margin: .8rem 0 1rem;}
        [data-testid="stTabs"] [data-baseweb="tab-list"] {display: inline-flex; width: auto; gap: 0; padding: .25rem; background: #e7ece9; border-radius: 8px; border: 0;}
        [data-testid="stTabs"] [data-baseweb="tab"] {height: 2.65rem; padding: 0 1.15rem; border-radius: 6px; color: #53615a;}
        [data-testid="stTabs"] [aria-selected="true"] {color: var(--sm-ink); background: white; box-shadow: 0 1px 5px rgba(29, 40, 35, .1);}
        [data-testid="stTabs"] [data-baseweb="tab-highlight"] {display: none;}
        [data-testid="stTabs"] [data-baseweb="tab-border"] {display: none;}
        .stylemate-card {border: 1px solid var(--sm-line); border-radius: 8px; padding: 1rem; margin-bottom: .75rem; background: var(--sm-surface);}
        .stylemate-card h4 {margin: 0 0 .3rem 0; color: var(--sm-ink); font-size: 1rem;}
        .stylemate-muted {color: var(--sm-muted); font-size: .88rem; line-height: 1.55;}
        .stylemate-kicker {color: var(--sm-green); font-size: .72rem; font-weight: 800; text-transform: uppercase; margin-bottom: .3rem;}
        .stylemate-weather {border-left: 4px solid var(--sm-coral); padding: .85rem 1rem; background: var(--sm-mint); margin: 0 0 1.2rem;}
        .stylemate-weather strong {display: block; color: var(--sm-ink); margin-bottom: .2rem;}
        .stylemate-weather span {color: var(--sm-muted); font-size: .9rem;}
        .stylemate-section-note {border-left: 3px solid var(--sm-coral); padding: .65rem .8rem; background: var(--sm-coral-soft); color: var(--sm-muted); font-size: .9rem;}
        .stylemate-item-list {margin: .35rem 0 .75rem; color: var(--sm-ink);}
        .stylemate-item-list span {display: block; padding: .18rem 0;}
        .stylemate-empty {border: 1px dashed #b9c7bf; background: #fbfcfb; padding: 1.35rem; margin: .6rem 0 .8rem; border-radius: 8px;}
        .stylemate-empty strong {display: block; font-size: 1rem; margin-bottom: .25rem;}
        .stylemate-empty span {color: var(--sm-muted); font-size: .9rem;}
        .stylemate-garment-meta {padding: .7rem .15rem .15rem;}
        .stylemate-garment-meta h4 {font-size: 1rem; margin: 0 0 .3rem;}
        .stylemate-outfit-title {font-size: 1.05rem; font-weight: 750; line-height: 1.45; margin-bottom: .2rem;}
        .stylemate-score {text-align: right; color: var(--sm-green); font-size: 1.45rem; font-weight: 800; white-space: nowrap;}
        .stylemate-piece-name {font-size: .78rem; color: #53615a; text-align: center; margin-top: .15rem; line-height: 1.3;}
        .stylemate-reason {background: #f2f6f3; color: #4f5d56; font-size: .88rem; line-height: 1.55; padding: .7rem .8rem; border-radius: 6px; margin-top: .55rem;}
        .stylemate-open-recommendation {display: grid; grid-template-columns: 3.2rem 1fr; gap: .35rem .7rem; background: #f8fbf9; border: 1px solid #dce9e1; border-left: 3px solid var(--sm-green); border-radius: 8px; padding: .85rem 1rem; margin: .6rem 0 .85rem; font-size: .88rem; line-height: 1.5;}
        .stylemate-open-recommendation strong {color: var(--sm-green-dark);}
        .stylemate-open-recommendation span {color: #4f5d56;}
        .stylemate-feature {background: white; border: 1px solid var(--sm-line); border-top: 3px solid var(--sm-green); border-radius: 8px; padding: 1rem; min-height: 10.5rem;}
        .stylemate-feature .number {font-size: .7rem; color: var(--sm-coral); font-weight: 800; margin-bottom: .6rem;}
        .stylemate-feature h4 {font-size: 1rem; margin: 0 0 .45rem;}
        .stylemate-feature p {font-size: .84rem; color: var(--sm-muted); line-height: 1.6; margin: 0;}
        .stylemate-techline {background: #eaf1f4; color: #52666e; border: 1px solid #d7e3e7; padding: .9rem 1rem; border-radius: 6px; font-size: .84rem; line-height: 1.6; margin: .8rem 0 1.25rem;}
        .stylemate-techline strong {color: var(--sm-ink);}
        .stylemate-eval-summary {background: white; border: 1px solid var(--sm-line); border-left: 3px solid var(--sm-coral); padding: .8rem 1rem; color: var(--sm-ink); font-size: .9rem; line-height: 1.55; margin: .4rem 0 .8rem;}
        .stylemate-eval-summary span {display: block; color: var(--sm-muted); font-size: .8rem; margin-top: .15rem;}
        .stylemate-privacy {background: var(--sm-mint); border-left: 3px solid var(--sm-green); padding: .8rem 1rem; color: #4f5d56; font-size: .84rem; line-height: 1.55; margin-top: 1rem;}
        [data-testid="stMetricValue"] {font-size: 1.35rem; font-weight: 700;}
        .stButton > button {border-radius: 6px; min-height: 2.45rem; font-weight: 600;}
        .stButton > button[kind="primary"] {background: var(--sm-green); border-color: var(--sm-green);}
        .stButton > button[kind="primary"]:hover {background: #125b41; border-color: #125b41;}
        .stTextInput input, .stTextArea textarea, [data-baseweb="select"] > div {background: white; border-color: var(--sm-line);}

        .st-key-stylemate_weather_panel {background: #e8f1f4; border: 1px solid #cfdee3; border-radius: 8px; padding: 1.05rem 1.2rem .95rem; margin-top: .25rem;}
        .st-key-stylemate_weather_panel h4,
        .st-key-stylemate_weather_panel p,
        .st-key-stylemate_weather_panel [data-testid="stMetricValue"],
        .st-key-stylemate_weather_panel [data-testid="stMetricLabel"] {color: var(--sm-ink) !important;}
        .st-key-stylemate_weather_panel [data-testid="stMetricLabel"] {opacity: .62;}
        .st-key-stylemate_weather_panel .stButton > button {background: rgba(255,255,255,.8); color: #385d68; border-color: #bfd1d7;}
        .st-key-stylemate_weather_panel .stButton > button:hover {border-color: #779ba6; background: white;}

        [class*="st-key-stylemate_outfit_"] {background: white; border: 1px solid var(--sm-line); border-top: 3px solid var(--sm-green); border-radius: 8px; padding: 1rem; margin: .55rem 0 .85rem; box-shadow: 0 5px 18px rgba(29, 40, 35, .05);}
        [class*="st-key-stylemate_outfit_"] [data-testid="stImage"] img {aspect-ratio: 1; object-fit: cover; border-radius: 6px; background: #eef2ef;}
        [class*="st-key-garment_card_"] {background: white; border: 1px solid var(--sm-line); border-radius: 8px; padding: .65rem; margin-bottom: .9rem; box-shadow: 0 4px 14px rgba(29, 40, 35, .04);}
        [class*="st-key-garment_card_"] [data-testid="stImage"] img {aspect-ratio: 1; object-fit: cover; border-radius: 6px;}

        div[data-testid="stColumn"]:has(.st-key-stylemate_assistant_rail) {position: sticky; top: 1rem; align-self: flex-start;}
        .st-key-stylemate_assistant_rail {background: white; border: 1px solid var(--sm-line); border-radius: 8px; padding: 1rem; box-shadow: 0 10px 28px rgba(29,40,35,.07); height: calc(100vh - 2rem); min-height: 700px; overflow: hidden;}
        .stylemate-assistant-head {background: var(--sm-mint); border-bottom: 1px solid #cfe1d7; margin: -1rem -1rem .8rem; padding: 1rem; border-radius: 7px 7px 0 0;}
        .stylemate-assistant-head .status {font-size: .68rem; color: var(--sm-green); font-weight: 800; margin-bottom: .3rem;}
        .stylemate-assistant-head h3 {color: var(--sm-ink); font-size: 1.2rem !important; margin: 0 0 .2rem;}
        .stylemate-assistant-head p {color: #5c7167; font-size: .78rem; margin: 0;}
        .st-key-stylemate_assistant_rail .stButton > button {font-size: .78rem; background: #f4f7f5; border-color: #dce5e0; min-height: 2.8rem; padding: .3rem .2rem !important; white-space: nowrap;}
        .st-key-stylemate_assistant_rail .stButton > button p {white-space: nowrap;}
        .st-key-stylemate_assistant_rail .stButton > button:hover {color: var(--sm-green); border-color: #92b6a5; background: #edf5f0;}
        .st-key-stylemate_assistant_rail .stFormSubmitButton > button[kind="primary"] {background: var(--sm-green); border-color: var(--sm-green); color: white; min-height: 2.55rem;}
        .st-key-stylemate_chat_history {background: #fbfcfb; border-top: 1px solid #edf1ef; border-bottom: 1px solid #edf1ef; padding: .5rem .25rem; margin: .5rem -0.25rem .7rem;}
        .st-key-stylemate_assistant_rail [data-testid="stChatMessage"] {background: transparent; padding: .4rem .2rem; margin-bottom: .35rem;}
        .st-key-stylemate_assistant_rail [data-testid="stChatMessage"][aria-label="Chat message from user"] {background: #e6f2ec; border-radius: 8px; margin-left: 15%; padding: .55rem .7rem;}
        .st-key-stylemate_assistant_rail [data-testid="stChatMessage"][aria-label="Chat message from assistant"] {background: white; border: 1px solid #e7ece9; border-radius: 8px; padding: .55rem .7rem;}
        .st-key-stylemate_assistant_rail [data-testid="stChatMessage"] p,
        .st-key-stylemate_assistant_rail [data-testid="stChatMessage"] li {font-size: .84rem; line-height: 1.5;}
        .st-key-stylemate_assistant_rail [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {min-width: 0; overflow-wrap: anywhere;}
        .st-key-stylemate_assistant_rail [data-testid="stChatMessage"] table {display: block; width: 100%; overflow-x: auto; white-space: nowrap; font-size: .78rem;}
        .st-key-stylemate_assistant_rail [data-testid="stChatMessage"] th,
        .st-key-stylemate_assistant_rail [data-testid="stChatMessage"] td {padding: .35rem .45rem;}
        @media (min-width: 1100px) {
            div[data-testid="stColumn"]:has(.st-key-stylemate_assistant_rail) {
                position: sticky;
                top: 1rem;
                align-self: flex-start;
                width: clamp(430px, 34vw, 620px) !important;
                z-index: 10;
            }
            .st-key-stylemate_assistant_rail {
                position: fixed;
                top: 3rem;
                right: max(1.5rem, calc((100vw - 1700px) * .5));
                width: clamp(430px, 34vw, 620px);
                height: calc(100vh - 4rem);
                min-height: 0;
                max-height: calc(100vh - 4rem);
                flex: none;
                z-index: 10;
            }
            .st-key-stylemate_assistant_rail > [data-testid="stElementContainer"]:first-child,
            .st-key-stylemate_assistant_rail > [data-testid="stElementContainer"]:first-child > div {
                width: 100% !important;
                max-width: none !important;
                align-self: stretch;
            }
            .st-key-stylemate_assistant_rail > [data-testid="stVerticalBlockBorderWrapper"]:has(.st-key-stylemate_chat_history) {
                display: flex;
                flex: 1 1 0;
                height: auto !important;
                min-height: 0;
                overflow: hidden;
            }
            .st-key-stylemate_assistant_rail > [data-testid="stVerticalBlockBorderWrapper"]:has(.st-key-stylemate_chat_history) > div {
                display: flex;
                flex: 1 1 0;
                height: 100%;
                min-height: 0;
            }
            .st-key-stylemate_chat_history {
                flex: 1 1 0;
                height: 100% !important;
                min-height: 0;
                overflow-y: auto;
            }
            .st-key-stylemate_assistant_rail [data-testid="stForm"] {padding: .65rem;}
            .st-key-stylemate_assistant_rail > [data-testid="stHorizontalBlock"] {
                flex: 0 0 40px;
                height: 40px !important;
                min-height: 40px;
            }
        }
        [data-testid="stRadio"] [role="radiogroup"] {gap: .5rem;}
        [data-testid="stRadio"] [role="radiogroup"] label {background: white; border: 1px solid var(--sm-line); border-radius: 6px; padding: .48rem .75rem; min-width: 4.25rem; justify-content: center; transition: border-color .15s ease, background-color .15s ease;}
        [data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) {background: var(--sm-green); border-color: var(--sm-green); color: white;}
        [data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) p {color: white;}
        [data-testid="stRadio"] [role="radiogroup"] label > div:first-child {display: none;}
        .st-key-stylemate_travel_panel {border-top: 2px solid var(--sm-coral); padding-top: 1.2rem; margin-top: 1.5rem;}
        hr {border-color: var(--sm-line) !important;}
        @media (max-width: 900px) {
            .block-container {padding: 1rem .8rem 1.5rem;}
            h1 {font-size: 1.65rem !important;}
            [data-testid="stTabs"] [data-baseweb="tab-list"] {width: 100%; overflow-x: auto;}
            [data-testid="stTabs"] [data-baseweb="tab"] {font-size: .85rem; white-space: nowrap; padding: 0 .75rem; flex: 1;}
            div[data-testid="stColumn"]:has(.st-key-stylemate_assistant_rail) {position: static;}
            .st-key-stylemate_assistant_rail {height: auto; min-height: 680px; max-height: none; margin-top: 1rem; overflow: visible;}
            .st-key-stylemate_weather_panel {padding: .9rem;}
            [data-testid="stRadio"] [role="radiogroup"] label {min-width: calc(33.333% - .4rem);}
            .stylemate-feature {min-height: auto; margin-bottom: .55rem;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_garment_card(garment: Garment, image_value=None) -> None:
    if image_value:
        st.image(image_value, use_container_width=True)
    st.markdown(
        f"<div class='stylemate-garment-meta'><h4>{escape(garment.name)}</h4>"
        f"<div class='stylemate-muted'>{escape(garment.category)} · {escape(garment.primary_color)}</div>"
        f"<div class='stylemate-muted'>{escape('、'.join(garment.styles))}</div></div>",
        unsafe_allow_html=True,
    )


def render_outfit_card(
    recommendation: OutfitRecommendation,
    garments: dict[str, Garment],
    image_values: dict[str, object] | None = None,
    *, key_prefix: str = "",
) -> None:
    selected = [
        garments[item_id]
        for item_id in recommendation.garment_ids
        if item_id in garments
    ]
    with st.container(key=f"stylemate_outfit_{key_prefix}{recommendation.id}"):
        title, score = st.columns([5, 1])
        title.markdown(
            "<div class='stylemate-kicker'>WARDROBE MATCH</div>"
            f"<div class='stylemate-outfit-title'>{escape(' + '.join(item.name for item in selected))}</div>",
            unsafe_allow_html=True,
        )
        score.markdown(
            f"<div class='stylemate-score'>{recommendation.score}</div>",
            unsafe_allow_html=True,
        )
        if selected:
            piece_columns = st.columns(len(selected), gap="small")
            for column, garment in zip(piece_columns, selected):
                with column:
                    image_value = (image_values or {}).get(garment.id)
                    if image_value:
                        st.image(image_value, use_container_width=True)
                    else:
                        st.markdown(
                            f"<div style='background:#f4f4f5;border-radius:10px;padding:1.75rem .5rem;text-align:center;color:#71717a'>{escape(garment.category)}</div>",
                            unsafe_allow_html=True,
                        )
                    st.markdown(
                        f"<div class='stylemate-piece-name'>{escape(garment.name)}</div>",
                        unsafe_allow_html=True,
                    )
        weather = (
            f"天气参考：{recommendation.weather_note}。"
            if recommendation.weather_note
            else ""
        )
        st.markdown(
            f"<div class='stylemate-reason'>{escape(weather + recommendation.reason)}</div>",
            unsafe_allow_html=True,
        )
        if recommendation.score_breakdown:
            with st.expander("查看评分依据"):
                st.json(recommendation.score_breakdown)


def render_trace(trace: AgentTrace) -> None:
    with st.expander("生成过程"):
        for step in trace.steps:
            st.write(f"{step.name} · {step.status} · {step.summary}")


def render_empty_state(title: str, body: str) -> None:
    st.markdown(
        f"<div class='stylemate-empty'><strong>{escape(title)}</strong>"
        f"<span>{escape(body)}</span></div>",
        unsafe_allow_html=True,
    )
