"""Attach only known URLs explicitly cited by the final model answer."""

import html
import re
from urllib.parse import urlsplit, urlunsplit

from stylemate.domain.models import KnowledgeSource


def _without_fragment(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def cited_sources(answer: str, candidates: list[KnowledgeSource]) -> list[KnowledgeSource]:
    links = re.findall(r"(?:https?://|user-document://)[^\s<>\[\]()\"']+", html.unescape(answer))
    explicit = {_without_fragment(link.rstrip(".,;:!?，。；：！？")) for link in links}
    seen = set()
    selected = []
    for source in candidates:
        key = _without_fragment(source.url)
        if key in explicit and key not in seen:
            selected.append(source)
            seen.add(key)
    return selected
