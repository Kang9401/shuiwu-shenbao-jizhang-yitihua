from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

try:
    from .sanitize import is_dynamic_identifier, recommended_selector, sanitize_text, sanitize_url
except ImportError:  # pragma: no cover - direct script execution
    from sanitize import is_dynamic_identifier, recommended_selector, sanitize_text, sanitize_url


@dataclass(frozen=True)
class SelectorSource:
    source_file: str
    line: int
    function: str
    report_type: str
    method: str
    selector: str
    name: str = ""
    exact: bool = False
    expected_frame: str = "top"


def report_type_for(path: Path, function: str) -> str:
    combined = f"{path.name}:{function}".lower()
    if "restricted" in combined or "限售" in combined:
        return "restricted_stock_result"
    if "classified" in combined or "extra_income" in combined or "分类" in combined:
        return "classified_result"
    if "comprehensive" in combined or "income_report" in combined or "综合" in combined:
        return "comprehensive_result"
    if "slider" in combined or "security" in combined or "滑块" in combined:
        return "slider_dialog"
    return "shared"


class SelectorVisitor(ast.NodeVisitor):
    def __init__(self, path: Path):
        self.path = path
        self.functions: list[str] = []
        self.items: list[SelectorSource] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"locator", "get_by_text", "get_by_role"}:
            method = node.func.attr
            selector = literal_string(node.args[0]) if node.args else ""
            name = keyword_string(node, "name")
            exact = keyword_bool(node, "exact")
            if selector:
                function = self.functions[-1] if self.functions else "<module>"
                self.items.append(
                    SelectorSource(
                        source_file=str(self.path),
                        line=node.lineno,
                        function=function,
                        report_type=report_type_for(self.path, function),
                        method=method,
                        selector=selector,
                        name=name,
                        exact=exact,
                    )
                )
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        target_names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if "SITE_CONFIG_DEFAULTS" in target_names and isinstance(node.value, ast.Dict):
            for key, value in zip(node.value.keys, node.value.values):
                selector = literal_string(value)
                config_key = literal_string(key)
                if selector and config_key and selector[:1] in {".", "#", "["}:
                    self.items.append(
                        SelectorSource(
                            source_file=str(self.path),
                            line=getattr(value, "lineno", node.lineno),
                            function=f"SITE_CONFIG_DEFAULTS.{config_key}",
                            report_type="classified_result/restricted_stock_result",
                            method="locator",
                            selector=selector,
                        )
                    )
        self.generic_visit(node)


def literal_string(node: ast.AST | None) -> str:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else ""


def keyword_string(node: ast.Call, key: str) -> str:
    return next((literal_string(item.value) for item in node.keywords if item.arg == key), "")


def keyword_bool(node: ast.Call, key: str) -> bool:
    value = next((item.value for item in node.keywords if item.arg == key), None)
    return bool(value.value) if isinstance(value, ast.Constant) and isinstance(value.value, bool) else False


def extract_selectors(paths: Iterable[Path]) -> list[SelectorSource]:
    result: list[SelectorSource] = []
    seen: set[tuple] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = SelectorVisitor(path)
        visitor.visit(tree)
        for item in visitor.items:
            key = (item.source_file, item.line, item.method, item.selector, item.name)
            if key not in seen:
                seen.add(key)
                result.append(item)
    return result


def frame_paths(page: Any) -> dict[Any, str]:
    paths: dict[Any, str] = {}
    for frame in page.frames:
        if frame.parent_frame is None:
            paths[frame] = "top"
            continue
        parent = paths.get(frame.parent_frame, "top")
        try:
            element = frame.frame_element()
            frame_id = stable_frame_identifier(element.get_attribute("id") or "")
            frame_name = stable_frame_identifier(element.get_attribute("name") or frame.name or "")
        except Exception:
            frame_id, frame_name = "", stable_frame_identifier(frame.name or "")
        label = f"iframe#{frame_id}" if frame_id else (f"iframe[name={frame_name}]" if frame_name else "iframe")
        paths[frame] = f"{parent} > {label}"
    return paths


def stable_frame_identifier(value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate or len(candidate) > 64 or is_dynamic_identifier(candidate):
        return ""
    return sanitize_text(candidate)


def locator_for(frame: Any, source: SelectorSource) -> Any:
    if source.method == "get_by_text":
        return frame.get_by_text(source.selector, exact=source.exact)
    if source.method == "get_by_role":
        options = {"name": source.name} if source.name else {}
        return frame.get_by_role(source.selector, **options)
    return frame.locator(source.selector)


def element_facts(locator: Any) -> dict[str, Any]:
    return locator.evaluate(
        """el => {
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            const center = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
            return {
                tag: el.tagName.toLowerCase(), id: el.id || '', name: el.getAttribute('name') || '',
                class: el.getAttribute('class') || '', role: el.getAttribute('role') || '',
                aria_label: el.getAttribute('aria-label') || '', placeholder: el.getAttribute('placeholder') || '',
                enabled: !el.disabled && el.getAttribute('aria-disabled') !== 'true',
                width: rect.width, height: rect.height,
                covered: !!center && center !== el && !el.contains(center),
                pointer_events: style.pointerEvents
            };
        }"""
    )


def audit_selectors(page: Any, sources: Iterable[SelectorSource]) -> list[dict[str, Any]]:
    paths = frame_paths(page)
    output: list[dict[str, Any]] = []
    for source in sources:
        total = visible = 0
        matched_frames: list[str] = []
        first_facts: dict[str, Any] | None = None
        for frame, frame_path in paths.items():
            try:
                locator = locator_for(frame, source)
                count = locator.count()
            except Exception:
                continue
            if count:
                matched_frames.append(frame_path)
            total += count
            for index in range(count):
                try:
                    item = locator.nth(index)
                    if item.is_visible():
                        visible += 1
                        if first_facts is None:
                            first_facts = element_facts(item)
                except Exception:
                    continue
        if total == 0:
            status = "missing"
        elif len(matched_frames) > 1 and source.expected_frame not in matched_frames:
            status = "wrong_frame"
        elif total > 1:
            status = "multiple"
        elif visible == 0:
            status = "hidden"
        elif first_facts and first_facts.get("covered"):
            status = "covered"
        else:
            status = "ok"
        clickable = bool(
            first_facts
            and first_facts.get("enabled")
            and first_facts.get("width", 0) > 0
            and first_facts.get("height", 0) > 0
            and first_facts.get("pointer_events") != "none"
            and not first_facts.get("covered")
        )
        output.append(
            {
                **asdict(source),
                "actual_frame": " | ".join(matched_frames),
                "match_count": total,
                "visible_match_count": visible,
                "clickable": clickable,
                "status": status,
                "suggested_selector": recommended_selector(first_facts or {}) if first_facts else "",
                "evidence": f"url={sanitize_url(page.url)}; frames={len(paths)}",
            }
        )
    return output


def write_static_manifest(paths: Iterable[Path], output: Path) -> list[SelectorSource]:
    sources = extract_selectors(paths)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps([asdict(item) for item in sources], ensure_ascii=False, indent=2), encoding="utf-8")
    return sources


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract and optionally audit e-tax RPA selectors")
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cdp")
    args = parser.parse_args()
    paths = [Path(item).resolve() for item in args.source]
    sources = extract_selectors(paths)
    result: Any = [
        {
            **asdict(item),
            "actual_frame": "",
            "match_count": 0,
            "visible_match_count": 0,
            "clickable": False,
            "status": "stale",
            "suggested_selector": "",
            "evidence": "静态提取完成；尚未连接真实 Chrome 页面验证",
        }
        for item in sources
    ]
    if args.cdp:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(args.cdp)
            context = browser.contexts[0]
            page = next((item for item in context.pages if "withholding/index.html" in item.url), context.pages[-1])
            result = audit_selectors(page, sources)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
