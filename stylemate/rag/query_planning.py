"""Bounded lexical expansion preserving the original query and its constraints."""

from __future__ import annotations

ALIASES = {
    "冲锋衣": "GORE-TEX 功能外套",
    "防泼水": "耐久拒水",
    "洗护": "洗涤 护理",
    "清洗": "洗涤",
    "羽绒服": "羽绒 down",
    "尺码号": "品牌尺码表",
}


def lexical_queries(query: str) -> tuple[str, ...]:
    normalized = " ".join(query.split())
    expanded = normalized
    for alias, replacement in ALIASES.items():
        expanded = expanded.replace(alias, replacement)
    return tuple(dict.fromkeys([normalized, expanded]))
