from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit


SAFE_UI_TERMS = (
    "查询", "搜索", "下载", "导出", "刷新", "关闭", "取消", "确定", "确认", "我知道了",
    "申报结果", "综合所得", "分类所得", "限售股", "扣缴申报", "税款所属月份",
    "申报成功", "未申报", "申报失败", "处理中", "安全验证", "拖动滑块",
    "查看导出记录", "立即进入", "个人所得税扣缴申报表", "返回", "下一步",
)

SENSITIVE_ATTRS = {"value", "data-value", "data-token", "data-session", "data-user", "srcdoc"}
DYNAMIC_ATTR_PREFIXES = ("data-v-", "data-react", "ng-")
DYNAMIC_ID = re.compile(
    r"(?:^|[-_])(?:\d{6,}|[0-9a-f]{8,}|[A-Za-z0-9_-]{20,})(?:$|[-_])",
    re.IGNORECASE,
)
DYNAMIC_CLASS = re.compile(r"(?:css|sc|jsx|jss|emotion|ant)-?[0-9a-z]{6,}$", re.IGNORECASE)

REDACTIONS = (
    (re.compile(r"\b\d{17}[0-9Xx]\b|\b\d{15}\b"), "<ID_NUMBER>"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "<PHONE>"),
    (re.compile(r"(?i)(token|session(?:id)?|trace(?:id)?|nonce|authorization)\s*[:=]\s*[^\s&]+"), r"\1=<REDACTED>"),
    (re.compile(r"(?:￥|¥|人民币)\s*-?\d[\d,]*(?:\.\d{1,2})?"), "<AMOUNT>"),
    (re.compile(r"(?<!\d)\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?(?!\d)"), "<DATE_VALUE>"),
    (re.compile(r"(?<!\d)\d{4}年\d{1,2}月(?!\d)"), "<DATE_VALUE>"),
    (re.compile(r"((?:姓名|人员姓名|纳税人姓名)\s*[：:]?\s*)[\u4e00-\u9fff·]{2,12}"), r"\1<PERSON>"),
    (re.compile(r"((?:身份证号|证件号码|手机号|手机号码)\s*[：:]?\s*)[^\s，,；;]+"), r"\1<REDACTED>"),
    (re.compile(r"((?:收入|税额|金额|所得额)\s*[：:]?\s*)-?\d[\d,.]*"), r"\1<AMOUNT>"),
)


def sanitize_url(value: str) -> str:
    """Keep only the stable origin, path, and hash route."""
    try:
        parsed = urlsplit(str(value or ""))
    except ValueError:
        return "<INVALID_URL>"
    fragment = parsed.fragment.split("?", 1)[0]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", fragment))


def sanitize_text(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)
    text = re.sub(r"\b[0-9a-f]{24,}\b", "<DYNAMIC_ID>", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<!\d)\d{12,}(?!\d)", "<IDENTIFIER>", text)
    return text


def stable_ui_text(value: str) -> str:
    normalized = re.sub(r"\s+", "", str(value or ""))
    matched = [term for term in SAFE_UI_TERMS if term in normalized]
    return " / ".join(dict.fromkeys(matched)) if matched else ("<TEXT>" if normalized else "")


def is_dynamic_identifier(value: str) -> bool:
    candidate = str(value or "").strip()
    return not candidate or bool(DYNAMIC_ID.search(candidate))


def stable_classes(value: str) -> list[str]:
    result = []
    for item in str(value or "").split():
        if len(item) > 64 or DYNAMIC_CLASS.search(item) or DYNAMIC_ID.search(item):
            continue
        result.append(item)
    return result[:4]


def sanitize_attribute(name: str, value: str) -> str | None:
    key = name.lower()
    if key in SENSITIVE_ATTRS or key.startswith(DYNAMIC_ATTR_PREFIXES):
        return None
    if key in {"href", "src", "action"}:
        return sanitize_url(value)
    if key == "id" and is_dynamic_identifier(value):
        return None
    if key == "class":
        classes = stable_classes(value)
        return " ".join(classes) if classes else None
    if key.startswith("on"):
        return None
    return sanitize_text(value)[:300]


def recommended_selector(element: dict) -> str:
    tag = str(element.get("tag") or "*").lower()
    element_id = str(element.get("id") or "")
    if element_id and not is_dynamic_identifier(element_id):
        return f"#{css_escape(element_id)}"
    for attr in ("name", "aria_label", "placeholder"):
        value = str(element.get(attr) or "")
        if value:
            html_attr = attr.replace("_", "-")
            return f'{tag}[{html_attr}="{css_string(value)}"]'
    role = str(element.get("role") or "")
    if role:
        return f'{tag}[role="{css_string(role)}"]'
    classes = stable_classes(str(element.get("class") or ""))
    if classes:
        return tag + "".join(f".{css_escape(item)}" for item in classes[:2])
    return tag


def css_escape(value: str) -> str:
    return re.sub(r"([^A-Za-z0-9_-])", lambda match: "\\" + match.group(1), value)


def css_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


class SanitizingHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_decl(self, decl: str) -> None:
        self.parts.append(f"<!{sanitize_text(decl)}>")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        rendered = []
        for name, raw in attrs:
            value = sanitize_attribute(name, raw or "")
            if value is not None:
                rendered.append(f' {name}="{html.escape(value, quote=True)}"')
        self.parts.append(f"<{tag}{''.join(rendered)}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self.parts:
            self.parts[-1] = self.parts[-1][:-1] + " />"

    def handle_endtag(self, tag: str) -> None:
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        value = stable_ui_text(data)
        if value:
            self.parts.append(html.escape(value))

    def handle_comment(self, _data: str) -> None:
        return


def sanitize_html(value: str) -> str:
    parser = SanitizingHTMLParser()
    parser.feed(value)
    parser.close()
    return "".join(parser.parts)
