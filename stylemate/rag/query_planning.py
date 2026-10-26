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


def knowledge_compatible(query: str, *, title: str, content: str, topic: str) -> bool:
    """Reject explicit subject/topic mismatches; this is not entailment scoring."""
    requested = {key for key, pattern in SUBJECTS.items() if re.search(pattern, query, re.I)}
    available = {key for key, pattern in SUBJECTS.items()
                 if re.search(pattern, f"{title} {content}", re.I)}
    if requested and not requested.intersection(available):
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
