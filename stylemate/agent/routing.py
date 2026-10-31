"""Multi-label skill routing with an execution-time write capability boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass

from stylemate.rag.query_planning import care_clarification

WRITE_TOOLS = frozenset({"add_garment", "update_garment", "delete_garment"})
MEASUREMENT_KNOWLEDGE_TERMS = ("尺码表", "商品尺寸", "成衣尺寸", "人体尺寸", "平铺", "胸宽", "测量方法")
CONCEPT_KNOWLEDGE_TERMS = ("色轮", "配色原理", "同类色", "类似色", "邻近色", "互补色", "叠穿原理", "分层原理")
OUTFIT_INTENT_TERMS = ("搭配", "穿什么", "怎么穿", "搭一套", "搭一身", "配一套", "上班穿", "穿一套", "穿搭", "怎么配")
CARE_INTENT_TERMS = ("洗", "清洁", "护理", "保养", "柔顺剂", "漂白", "去渍", "烘干", "晾晒", "熨烫", "洗标", "洗涤剂")
KNOWLEDGE_INTENT_TERMS = CARE_INTENT_TERMS + MEASUREMENT_KNOWLEDGE_TERMS + (
    "知识库", "羊毛", "材质", "面料", "gore-tex", "功能外套", "拒水", "防水", "紫外线",
    "防晒", "高温", "寒冷", "温差", "分层", "色轮", "配色", "收纳", "污渍",
)
_COLLOQUIAL_OUTFIT = re.compile(r"(?:给我|帮我|替我|想|要).{0,8}(?:搭|配)(?:一)?(?:身|套)(?:衣服|穿搭|上班|通勤|日常|出游|约会)")
SKILL_TOOLS = {
    "knowledge_qa": frozenset({"care_guide", "rag_search", "get_garment"}),
    "outfit_planning": frozenset({"get_user_location", "get_weather", "search_wardrobe",
                                  "recommend_inventory_outfit", "recommend_open_outfit", "recommend_size",
                                  "wardrobe_gap_check", "item_style_analysis", "get_garment"}),
    "travel_planning": frozenset({"get_user_location", "get_weather", "travel_packing",
                                  "search_wardrobe", "recommend_inventory_outfit", "rag_search"}),
    "wardrobe_management": frozenset({"search_wardrobe", "item_style_analysis", "wardrobe_gap_check", "get_garment"}),
    "purchase_planning": frozenset({"recommend_purchases", "wardrobe_gap_check", "search_wardrobe",
                                    "get_weather", "get_user_location", "rag_search"}),
}
_TERMS = {
    "knowledge_qa": KNOWLEDGE_INTENT_TERMS + CONCEPT_KNOWLEDGE_TERMS + ("知识", "care", "wash"),
    "outfit_planning": ("穿", "通勤", "天气", "尺码", "outfit", "weather", "size") + OUTFIT_INTENT_TERMS,
    "travel_planning": ("旅行", "旅游", "出差", "行李", "travel", "packing", "trip"),
    "wardrobe_management": ("衣橱", "衣柜", "库存", "查询", "找", "wardrobe", "search"),
    "purchase_planning": ("购买", "买", "缺少", "添置", "purchase", "buy"),
}
_WRITE_TERMS = {
    "add_garment": ("新增", "添加", "录入", "入库", "add "),
    "update_garment": ("修改", "更新", "编辑", "改成", "改为", "改名", "重命名", "update ", "edit "),
    "delete_garment": ("删除", "移除", "删掉", "delete ", "remove "),
}

_QUOTED = re.compile(r'“[^”]*”|「[^」]*」|"[^"]*"|`[^`]*`')
_NON_ACTION = re.compile(
    r"不要|别|不想|不能|不用|无需|不需要|不允许|不可以|先不|暂不|"
    r"如何|怎么|能否|是否|能不能|假如|如果|要是|假设|"
    r"意味着|是什么意思|功能|按钮|说明|教程|示例|撤销|恢复|后果|会怎样|会怎么样|"
    r"\b(?:don't|do not|never|how|what|whether|if|undo|restore|example|explain)\b",
    re.I,
)
_REQUEST_PREFIX = re.compile(
    r"^(?:(?:请|麻烦|帮我|替我|帮忙|现在|立即|直接|我想|我要|我需要|我希望)\s*)*"
    r"(?:新增|添加|录入|入库|修改|更新|编辑|改名|重命名|删除|移除|删掉|把|将|"
    r"(?:please\s+)?(?:add|update|edit|delete|remove)\b)", re.I,
)


def explicit_write_tools(text: str) -> set[str]:
    """Conservatively recognize a proposal request, never an authorization.

    Quoted examples, questions, negation and conditional clauses remain read-only.
    This small grammar deliberately prefers clarification over guessing intent.
    The subsequent PendingAction confirmation is still mandatory.
    """
    text = _QUOTED.sub("", text)
    # A comma does not end a conditional: "如果...，请删除..." is still hypothetical.
    sentences = re.split(r"[。；;！!\n]", text)
    writes = set()
    for sentence in sentences:
        if re.search(r"如果|假如|要是|假设|\bif\b", sentence, re.I):
            continue
        for clause in re.split(r"[，,]|(?:但是|但|然后)", sentence):
            clause = clause.strip().casefold()
            if not clause or _NON_ACTION.search(clause) or re.search(r"[?？]|吗|么|呢", clause):
                continue
            if re.search(r"(?:删除|移除|修改|更新|添加|改成|改为|改名|重命名)(?:为)?(?:前|后|过|了)", clause):
                continue
            if not _REQUEST_PREFIX.search(clause):
                continue
            writes.update(name for name, terms in _WRITE_TERMS.items() if any(term in clause for term in terms))
    return writes


@dataclass(frozen=True)
class SkillRoute:
    skills: tuple[str, ...]
    allowed_tools: frozenset[str]
    reason: str
    intent: str = "auto"
    deterministic: bool = False
    clarification: str = ""


def is_outfit_intent(text: str) -> bool:
    return any(term in text for term in OUTFIT_INTENT_TERMS) or bool(_COLLOQUIAL_OUTFIT.search(text))


def task_intent(text: str) -> str:
    """One ordered decision for service fallbacks and graph diagnostics.

    Resolving owned objects, travel follow-ups and user authorization remains at
    their trusted boundaries; a text label cannot grant any of those privileges.
    """
    lower = text.casefold()
    if re.search(r"删除|移除|删掉|\bdelete\b|\bremove\b", text, re.I) and "delete_garment" not in explicit_write_tools(text):
        return "delete_explanation"
    if any(term in text for term in ("推荐购买", "买什么", "购买建议")):
        return "purchase"
    if ("知识库" in text or any(term in text for term in CONCEPT_KNOWLEDGE_TERMS)) and not any(term in lower for term in CARE_INTENT_TERMS):
        return "knowledge"
    if any(term in text for term in ("旅行", "旅游", "行李")):
        return "travel"
    if any(term in lower for term in CARE_INTENT_TERMS):
        return "care"
    if is_outfit_intent(text):
        return "outfit"
    if any(term in text for term in ("天气", "定位", "城市")):
        return "weather"
    if any(term in lower for term in KNOWLEDGE_INTENT_TERMS):
        return "knowledge"
    if any(term in text for term in ("缺", "补齐", "补充")):
        return "wardrobe_gap"
    if "delete_garment" in explicit_write_tools(text):
        return "delete"
    if any(term in text for term in ("衣橱", "衣柜", "搜索")):
        return "wardrobe_search"
    if any(term in text for term in ("风格", "分析")):
        return "item_style"
    return "auto"


def route_skills(text: str, available: set[str], *, travel_follow_up: bool = False) -> SkillRoute:
    """Union applicable read skills; write proposals require current-turn intent.

    This is a routing policy, not user authentication. Bound tool closures still
    enforce owner/conversation, and PendingAction still requires confirmation.
    """
    normalized = text.casefold()
    skills = tuple(name for name, terms in _TERMS.items() if any(term in normalized for term in terms))
    intent = task_intent(text)
    if travel_follow_up and intent not in {"delete_explanation", "purchase", "knowledge"}:
        intent = "travel"
    intent_skill = {"knowledge": "knowledge_qa", "care": "knowledge_qa", "outfit": "outfit_planning",
                    "travel": "travel_planning", "purchase": "purchase_planning", "weather": "outfit_planning",
                    "wardrobe_gap": "wardrobe_management", "wardrobe_search": "wardrobe_management",
                    "item_style": "wardrobe_management"}.get(intent)
    if intent_skill:
        skills = tuple(dict.fromkeys((*skills, intent_skill)))
    allowed: set[str] = set()
    for skill in skills:
        allowed.update(SKILL_TOOLS[skill])
    if re.search(r"配色|色轮|互补色|邻近色|类似色", text) and not re.search(r"洗|护理|保养|烘|熨|漂白|柔顺剂", text):
        allowed.discard("care_guide")
    writes = explicit_write_tools(text)
    if writes:
        allowed.update(SKILL_TOOLS["wardrobe_management"])
        allowed.update(writes)
        skills = tuple(dict.fromkeys([*skills, "wardrobe_management"]))
    if not skills:
        # Ambiguous requests retain read recall without silently granting writes.
        allowed = available - WRITE_TOOLS
    deterministic = intent in {"delete_explanation", "delete", "purchase", "travel", "care", "outfit"} or any(
        term in text for term in MEASUREMENT_KNOWLEDGE_TERMS
    )
    return SkillRoute(skills or ("read_fallback",), frozenset(allowed & available),
                      "explicit_write_proposal" if writes else "bounded_read_route", intent, deterministic,
                      care_clarification(text) or "")
