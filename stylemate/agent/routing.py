"""Multi-label skill routing with an execution-time write capability boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass

WRITE_TOOLS = frozenset({"add_garment", "update_garment", "delete_garment"})
SKILL_TOOLS = {
    "knowledge_qa": frozenset({"care_guide", "rag_search"}),
    "outfit_planning": frozenset({"get_user_location", "get_weather", "search_wardrobe",
                                  "recommend_inventory_outfit", "recommend_open_outfit", "recommend_size",
                                  "wardrobe_gap_check", "item_style_analysis"}),
    "travel_planning": frozenset({"get_user_location", "get_weather", "travel_packing",
                                  "search_wardrobe", "recommend_inventory_outfit", "rag_search"}),
    "wardrobe_management": frozenset({"search_wardrobe", "item_style_analysis", "wardrobe_gap_check"}),
    "purchase_planning": frozenset({"recommend_purchases", "wardrobe_gap_check", "search_wardrobe",
                                    "get_weather", "get_user_location", "rag_search"}),
}
_TERMS = {
    "knowledge_qa": ("洗", "护理", "面料", "材质", "知识", "保养", "柔顺剂", "分层", "care", "wash"),
    "outfit_planning": ("穿", "搭配", "搭一套", "通勤", "天气", "尺码", "outfit", "weather", "size"),
    "travel_planning": ("旅行", "旅游", "出差", "行李", "travel", "packing", "trip"),
    "wardrobe_management": ("衣橱", "衣柜", "库存", "查询", "找", "wardrobe", "search"),
    "purchase_planning": ("购买", "买", "缺少", "添置", "purchase", "buy"),
}
_WRITE_TERMS = {
    "add_garment": ("新增", "添加", "录入", "入库", "add "),
    "update_garment": ("修改", "更新", "编辑", "改成", "update ", "edit "),
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
    r"(?:新增|添加|录入|入库|修改|更新|编辑|删除|移除|删掉|把|将|"
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
            if re.search(r"(?:删除|移除|修改|更新|添加)(?:前|后|过|了)", clause):
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


def route_skills(text: str, available: set[str]) -> SkillRoute:
    """Union applicable read skills; write proposals require current-turn intent.

    This is a routing policy, not user authentication. Bound tool closures still
    enforce owner/conversation, and PendingAction still requires confirmation.
    """
    normalized = text.casefold()
    skills = tuple(name for name, terms in _TERMS.items() if any(term in normalized for term in terms))
    allowed: set[str] = set()
    for skill in skills:
        allowed.update(SKILL_TOOLS[skill])
    writes = explicit_write_tools(text)
    if writes:
        allowed.update(SKILL_TOOLS["wardrobe_management"])
        allowed.update(writes)
        skills = tuple(dict.fromkeys([*skills, "wardrobe_management"]))
    if not skills:
        # Ambiguous requests retain read recall without silently granting writes.
        allowed = available - WRITE_TOOLS
    return SkillRoute(skills or ("read_fallback",), frozenset(allowed & available),
                      "explicit_write_proposal" if writes else "bounded_read_route")
