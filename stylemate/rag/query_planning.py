"""Bounded lexical expansion preserving the original query and its constraints."""

from __future__ import annotations

import re

ALIASES = {
    "冲锋衣": "功能外套",
    "防泼水": "耐久拒水",
    "洗护": "洗涤 护理",
    "清洗": "洗涤",
    "羽绒服": "羽绒 down",
    "尺码号": "品牌尺码表",
    "内层": "内层 贴身层",
    "保暖层": "保暖层 中间层",
}

SUBJECTS = {
    "wool": r"羊毛|\bwool\b",
    "cashmere": r"羊绒|\bcashmere\b",
    "cotton": r"棉|\bcotton\b",
    "silk": r"真丝|蚕丝|\bsilk\b",
    "leather": r"皮革|真皮|\bleather\b",
    "down": r"羽绒|\bdown\b",
    "linen": r"亚麻|麻质|\blinen\b",
    "polyester": r"涤纶|聚酯|\bpolyester\b",
    "nylon": r"尼龙|锦纶|\bnylon\b",
    "viscose": r"粘纤|粘胶|人造丝|\bviscose\b|\brayon\b",
    "goretex": r"gore[ -]?tex|shakedry",
}

_UNCONFIRMED_CATEGORY = re.compile(r"毛衣|针织|冲锋衣|功能外套|夹克|衬衫|外套|大衣|风衣|连衣裙|"
                                   r"(?<![A-Za-z])(?:sweater|knit[a-z]*|shell|jacket|shirt|coat)(?![A-Za-z])", re.I)
_GARMENT_ONLY = re.compile(_UNCONFIRMED_CATEGORY.pattern + r"|衣物|衣服", re.I)
_GENERAL_CARE_FACT = re.compile(r"符号|洗标|分类|污渍|收纳|折叠|用量|洗涤剂|烘干前", re.I)
_OTHER_DOMAIN_SUBJECT = re.compile(
    r"股票|证券|基金|股价|期货|外汇|变速箱|发动机|汽车|轮胎|电脑|数据库|服务器|程序代码|"
    r"血压|糖尿病|药物剂量|抗生素|食谱|炒菜|烹饪|\b(?:stock|investment|engine|database|antibiotic)\b", re.I,
)
_CLOTHING_SUBJECT = re.compile(
    r"衣|裤|衫|裙|鞋|袜|帽|围巾|穿|搭配|面料|洗标|尺码|胸围|羊毛|羊绒|真丝|亚麻|"
    r"\b(?:garment|clothing|outfit|shirt|trouser|jacket|wool|silk|linen)\b", re.I,
)


def is_outside_builtin_scope(query: str) -> bool:
    """Finite explicit-subject boundary, not a general intent classifier.

    A travel or care question can mention a car/computer while still asking
    about clothing. Uploaded user documents retain their own scoped channel.
    """
    return bool(_OTHER_DOMAIN_SUBJECT.search(query) and not _CLOTHING_SUBJECT.search(query))


def care_clarification(query: str) -> str | None:
    if re.search(r"洗|清洁|护理|保养|烘|漂白|柔顺剂|熨|\bwash|\bcare\b", query, re.I):
        return material_clarification(query)
    return None


def requests_exact_product_measurement(query: str) -> bool:
    """Conceptual measuring guidance cannot establish a product's exact dimensions."""
    dimensions = r"胸围|腰围|肩宽|衣长|袖长|裤长|胸宽|尺寸"
    return bool(re.search(rf"(?:{dimensions}).{{0,12}}(?:多少|几厘米|几公分|具体数值)|"
                          rf"(?:多少|几厘米|几公分).{{0,12}}(?:{dimensions})", query))


def material_clarification(query: str) -> str | None:
    """A garment category does not establish its fibre or product care label."""
    if any(re.search(pattern, query, re.I) for pattern in SUBJECTS.values()):
        return None
    if _GARMENT_ONLY.search(query) and not _GENERAL_CARE_FACT.search(query):
        return "请先提供这件衣物的材质成分或洗护标签；仅凭衣物类别还不能确定洗涤、烘干等处理方法。"
    return None


def knowledge_compatible(query: str, *, title: str, content: str, topic: str) -> bool:
    """Reject explicit subject/topic mismatches; this is not entailment scoring."""
    if is_outside_builtin_scope(query):
        return False
    requested = {key for key, pattern in SUBJECTS.items() if re.search(pattern, query, re.I)}
    available = {key for key, pattern in SUBJECTS.items()
                 if re.search(pattern, f"{title} {content}", re.I)}
    if requested and not requested.intersection(available):
        return False
    if not requested and _UNCONFIRMED_CATEGORY.search(query) and available:
        # Generic clothing/sweater/shell questions may receive general care
        # evidence, but cannot silently acquire wool or a brand technology.
        return False
    if not requested and _UNCONFIRMED_CATEGORY.search(query) and re.search(r"拒水|防水|水珠|\bdwr\b", query, re.I):
        if not re.search(r"拒水|防水|水珠|\bdwr\b", f"{title} {content}", re.I):
            return False
        # Choosing a rain layer is not evidence about restoring an existing
        # garment's failing finish; require a care/technology source instead.
        if re.search(r"下降|失效|变差|恢复|消失|不再|不起", query) and topic not in {"care", "fabric", "wardrobe"}:
            return False
    # Use narrow question markers, so a care question mentioning clothing color
    # is not incorrectly routed to aesthetic color theory.
    care_context = re.search(r"洗|护理|烘|熨|缩水|变形|\bwash|\bcare\b|\bshrink", query, re.I)
    if not care_context and re.search(r"尺码|尺寸|\bsize\b|\bsizing\b", query, re.I):
        return topic == "size"
    if not care_context and re.search(r"色轮|配色|\bcolor wheel\b", query, re.I):
        return topic in {"color", "style"}
    return True


def lexical_queries(query: str) -> tuple[str, ...]:
    normalized = " ".join(query.split())
    expanded = normalized
    for alias, replacement in ALIASES.items():
        expanded = expanded.replace(alias, replacement)
    return tuple(dict.fromkeys([normalized, expanded]))
