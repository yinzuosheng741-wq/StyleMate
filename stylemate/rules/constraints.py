"""Small explicit color-exclusion grammar shared by chat and rule execution."""

import re

_COLOR = r"(?:黑色|白色|灰色|米色|蓝色|红色|绿色|黄色|紫色|棕色|粉色|橙色|卡其色)"
_PATTERN = re.compile(
    rf"(?:不穿|不要|排除|避开)\s*(?P<colors>{_COLOR}(?:[、和或及与\s]+{_COLOR})*)"
    r"(?P<category>上衣|上装|裤子|下装|外套|裙子|鞋子|鞋履)?"
)
_CATEGORIES = {"上衣": "上装", "裤子": "下装", "裙子": "裙", "鞋子": "鞋履"}


def extract_color_exclusions(text: str) -> list[str]:
    result = []
    for match in _PATTERN.finditer(text):
        # Do not turn "不要排除黑色" or "不是不穿黑色" into an exclusion.
        if re.search(r"(?:不要|不用|无需|不是|并非)\s*$", text[:match.start()]):
            continue
        category = match.group("category") or ""
        for color in re.findall(_COLOR, match.group("colors")):
            result.append(f"不穿{color}{category}")
    return list(dict.fromkeys(result))


def excludes_color(primary_color: str, category: str, constraints: list[str]) -> bool:
    for constraint in constraints:
        for normalized in extract_color_exclusions(constraint):
            match = _PATTERN.fullmatch(normalized)
            if match is None:
                continue
            color = match.group("colors")
            target = _CATEGORIES.get(match.group("category"), match.group("category"))
            # Chinese color names may be stored with or without the 色 suffix.
            if color.removesuffix("色") in primary_color and (not target or target in category):
                return True
    return False
