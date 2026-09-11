from __future__ import annotations

import argparse
import datetime as dt
import importlib.metadata
import json
import re
from pathlib import Path
from typing import Any

try:
    from .sanitize import (
        is_dynamic_identifier,
        recommended_selector,
        sanitize_attribute,
        sanitize_text,
        sanitize_url,
        stable_ui_text,
    )
    from .selector_audit import audit_selectors, extract_selectors, frame_paths
except ImportError:  # pragma: no cover - direct script execution
    from sanitize import (
        is_dynamic_identifier,
        recommended_selector,
        sanitize_attribute,
        sanitize_text,
        sanitize_url,
        stable_ui_text,
    )
    from selector_audit import audit_selectors, extract_selectors, frame_paths


PAGE_TYPES = (
    "comprehensive_result",
    "classified_result",
    "restricted_stock_result",
    "slider_dialog",
    "unknown_popup",
)
STAGES = (
    "entered",
    "queried",
    "before_download",
    "security_visible",
    "security_finished",
    "download_started",
)
INTERACTIVE_SELECTOR = (
    "button, a, input, select, textarea, table, thead, th, dialog, [role='dialog'], "
    "[role='button'], [role='alert'], iframe, canvas, svg, [class*='slider'], [class*='slide'], "
    "[class*='captcha'], [class*='mask'], [class*='overlay']"
)
MASK_SELECTOR = (
    "tbody, input, textarea, [contenteditable='true'], [class*='company-name'], "
    "[class*='taxpayer'], [class*='user-name'], [class*='person-name'], [class*='amount']"
)
DIALOG_SELECTOR = ".el-dialog:visible, .ant-modal:visible, [role='dialog']:visible, dialog[open]"
SLIDER_HANDLE_SELECTOR = (
    "#aliyunCaptcha-sliding-slider, .slider-handle, .handler, .verify-move-block, "
    ".nc_iconfont.btn_slide, [role='slider']"
)


def now_stamp() -> str:
    return dt.datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")


def safe_segment(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", value.strip())
    return cleaned.strip("._") or "unknown"


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def select_page(context: Any) -> Any:
    pages = [page for page in context.pages if "etax.chinatax.gov.cn" in page.url]
    if not pages:
        raise RuntimeError("没有找到税务局页面")
    return next((page for page in reversed(pages) if "withholding/index.html" in page.url), pages[-1])


def collect_frame_tree(page: Any) -> list[dict[str, Any]]:
    paths = frame_paths(page)
    origin = url_origin(page.url)
    result = []
    for frame, path in paths.items():
        item: dict[str, Any] = {
            "path": path,
            "name": stable_identifier(frame.name),
            "url": sanitize_url(frame.url),
            "same_origin": url_origin(frame.url) == origin,
            "readable": False,
            "visible": True if frame.parent_frame is None else False,
            "box": None,
            "main_titles": [],
            "interactive_count": 0,
            "error": None,
        }
        if frame.parent_frame is not None:
            try:
                element = frame.frame_element()
                item.update(
                    id=stable_identifier(element.get_attribute("id") or ""),
                    name=stable_identifier(element.get_attribute("name") or frame.name or ""),
                    src=sanitize_url(element.get_attribute("src") or ""),
                    visible=element.is_visible(),
                    box=element.bounding_box(),
                )
            except Exception as exc:
                item["error"] = sanitize_text(str(exc))[:300]
        try:
            facts = frame.evaluate(
                r"""selector => {
                    const safe = ['综合所得','分类所得','限售股','申报结果','安全验证'];
                    const titles = [...document.querySelectorAll('h1,h2,h3,[role=heading]')]
                      .map(el => safe.filter(term => (el.textContent || '').includes(term)).join(' / '))
                      .filter(Boolean).slice(0, 10);
                    return {titles, interactiveCount: document.querySelectorAll(selector).length};
                }""",
                INTERACTIVE_SELECTOR,
            )
            item["readable"] = True
            item["main_titles"] = facts["titles"]
            item["interactive_count"] = facts["interactiveCount"]
        except Exception as exc:
            item["error"] = sanitize_text(str(exc))[:300]
        result.append(item)
    return result


def url_origin(value: str) -> str:
    match = re.match(r"^(https?://[^/]+)", value or "")
    return match.group(1).lower() if match else ""


def stable_identifier(value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate or len(candidate) > 64 or is_dynamic_identifier(candidate):
        return ""
    return sanitize_text(candidate)


def collect_structure(frame: Any, frame_path: str) -> dict[str, Any]:
    raw = frame.evaluate(
        r"""() => {
            const visible = el => {
                const s = getComputedStyle(el), r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity || 1) > 0 && r.width > 0 && r.height > 0;
            };
            const tables = [...document.querySelectorAll('table')].map(table => ({
                headers: [...table.querySelectorAll('thead th, tr:first-child th')].map(th => (th.textContent || '').trim().slice(0, 80)),
                columns: Math.max(0, ...[...table.rows].map(row => row.cells.length)),
                rows: table.tBodies ? [...table.tBodies].reduce((sum, body) => sum + body.rows.length, 0) : 0,
                visible: visible(table)
            }));
            const counts = {};
            for (const selector of ['button','a','input','select','textarea','table','dialog','[role=dialog]','iframe','canvas','svg']) {
                counts[selector] = document.querySelectorAll(selector).length;
            }
            return {counts, tables};
        }"""
    )
    for table in raw["tables"]:
        table["headers"] = [sanitize_text(value) for value in table["headers"]]
    return {"frame": frame_path, **raw}


def collect_interactive(frame: Any, frame_path: str) -> list[dict[str, Any]]:
    elements = frame.evaluate(
        r"""selector => {
            const terms = ['查询','搜索','下载','导出','刷新','关闭','取消','确定','确认','我知道了','申报结果',
                '综合所得','分类所得','限售股','安全验证','拖动滑块','查看导出记录','立即进入','返回','下一步'];
            return [...document.querySelectorAll(selector)].slice(0, 1000).map(el => {
                const r = el.getBoundingClientRect(), s = getComputedStyle(el);
                const raw = (el.textContent || '').replace(/\s+/g, '');
                return {
                    tag: el.tagName.toLowerCase(), id: el.id || '', name: el.getAttribute('name') || '',
                    class: el.getAttribute('class') || '', role: el.getAttribute('role') || '',
                    aria_label: el.getAttribute('aria-label') || '', placeholder: el.getAttribute('placeholder') || '',
                    text: terms.filter(term => raw.includes(term)).join(' / '),
                    visible: s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity || 1) > 0 && r.width > 0 && r.height > 0,
                    enabled: !el.disabled && el.getAttribute('aria-disabled') !== 'true',
                    box: {x:r.x,y:r.y,width:r.width,height:r.height},
                    display:s.display, visibility:s.visibility, opacity:s.opacity, pointer_events:s.pointerEvents,
                    position:s.position, z_index:s.zIndex, transform:s.transform, touch_action:s.touchAction
                };
            });
        }""",
        INTERACTIVE_SELECTOR,
    )
    output = []
    for element in elements:
        element["frame"] = frame_path
        element["id"] = sanitize_attribute("id", element.get("id", "")) or ""
        element["name"] = stable_identifier(element.get("name", ""))
        element["class"] = sanitize_attribute("class", element.get("class", "")) or ""
        element["aria_label"] = stable_ui_text(element.get("aria_label", ""))
        element["placeholder"] = stable_ui_text(element.get("placeholder", ""))
        element["recommended_selector"] = recommended_selector(element)
        element.pop("name", None) if element.get("tag") == "input" else None
        output.append(element)
    return output


def collect_dialogs(frame: Any, frame_path: str) -> list[dict[str, Any]]:
    dialogs = frame.evaluate(
        r"""selector => {
            const redact = value => String(value || '')
              .replace(/\b\d{17}[0-9Xx]\b|\b\d{15}\b/g, '<ID_NUMBER>')
              .replace(/(?<!\d)1[3-9]\d{9}(?!\d)/g, '<PHONE>')
              .replace(/(?:￥|¥|人民币)\s*-?\d[\d,]*(?:\.\d{1,2})?/g, '<AMOUNT>')
              .replace(/(?<!\d)\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?(?!\d)/g, '<DATE_VALUE>')
              .replace(/\b[0-9a-f]{24,}\b/gi, '<DYNAMIC_ID>')
              .replace(/(?<!\d)\d{12,}(?!\d)/g, '<IDENTIFIER>')
              .replace(/((?:姓名|人员姓名|纳税人姓名)\s*[：:]?\s*)[\u4e00-\u9fff·]{2,12}/g, '$1<PERSON>');
            return [...document.querySelectorAll(selector)].map(dialog => {
                const r = dialog.getBoundingClientRect();
                const title = dialog.querySelector('.el-dialog__title,.ant-modal-title,[role=heading],h1,h2,h3');
                const buttons = [...dialog.querySelectorAll('button,[role=button]')].map(el => redact(el.textContent).trim()).filter(Boolean);
                return {title:redact(title?.textContent).trim(), body:redact(dialog.textContent).trim().slice(0, 1500), buttons,
                    box:{x:r.x,y:r.y,width:r.width,height:r.height}};
            });
        }""",
        DIALOG_SELECTOR,
    )
    for dialog in dialogs:
        dialog["frame"] = frame_path
        dialog["title"] = stable_ui_text(dialog["title"])
        dialog["body"] = stable_ui_text(dialog["body"])
        dialog["buttons"] = [stable_ui_text(value) for value in dialog["buttons"]]
    return dialogs


def sanitized_frame_html(frame: Any) -> str:
    return frame.evaluate(
        r"""() => {
            const terms = ['查询','搜索','下载','导出','刷新','关闭','取消','确定','确认','我知道了','申报结果',
                '综合所得','分类所得','限售股','扣缴申报','税款所属月份','申报成功','未申报','申报失败',
                '处理中','安全验证','拖动滑块','查看导出记录','立即进入','个人所得税扣缴申报表','返回','下一步'];
            const clone = document.documentElement.cloneNode(true);
            clone.querySelectorAll('script,style,noscript').forEach(el => el.remove());
            clone.querySelectorAll('input,textarea').forEach(el => { el.removeAttribute('value'); el.textContent = ''; });
            clone.querySelectorAll('*').forEach(el => {
                [...el.attributes].forEach(attr => {
                    const key = attr.name.toLowerCase();
                    if (key.startsWith('on') || key.startsWith('data-v-') || key.startsWith('data-react') ||
                        ['value','data-value','srcdoc','data-token','data-session','data-user'].includes(key)) el.removeAttribute(attr.name);
                    if ((key === 'href' || key === 'src') && attr.value.includes('?')) el.setAttribute(attr.name, attr.value.split('?')[0]);
                    if (key === 'id' && /[0-9a-f]{12,}|\d{8,}/i.test(attr.value)) el.removeAttribute('id');
                });
            });
            const walker = document.createTreeWalker(clone, NodeFilter.SHOW_TEXT);
            const nodes = [];
            while (walker.nextNode()) nodes.push(walker.currentNode);
            for (const node of nodes) {
                const raw = (node.nodeValue || '').replace(/\s+/g, '');
                if (!raw) continue;
                const kept = terms.filter(term => raw.includes(term));
                node.nodeValue = kept.length ? kept.join(' / ') : '<TEXT>';
            }
            return '<!doctype html>\n' + clone.outerHTML;
        }"""
    )


def screenshot_with_masks(page: Any, frames: list[Any], output: Path) -> None:
    masks = []
    for frame in frames:
        try:
            masks.append(frame.locator(MASK_SELECTOR))
        except Exception:
            continue
    page.screenshot(path=str(output), full_page=True, mask=masks, mask_color="#111827")


def collect_slider_event_types(context: Any, page: Any) -> dict[str, Any]:
    """Use the DevTools DOMDebugger domain to inspect listeners on the real handle."""
    result = {"frame": "top", "selector": SLIDER_HANDLE_SELECTOR, "event_types": [], "status": "missing"}
    session = context.new_cdp_session(page)
    try:
        remote = session.send(
            "Runtime.evaluate",
            {"expression": f"document.querySelector({json.dumps(SLIDER_HANDLE_SELECTOR)})", "returnByValue": False},
        ).get("result", {})
        object_id = remote.get("objectId")
        if not object_id or remote.get("subtype") == "null":
            return result
        listeners = session.send("DOMDebugger.getEventListeners", {"objectId": object_id}).get("listeners", [])
        result["event_types"] = sorted({str(item.get("type") or "") for item in listeners if item.get("type")})
        result["status"] = "ok"
        return result
    except Exception as exc:
        result["status"] = "unavailable"
        result["error"] = sanitize_text(str(exc))[:300]
        return result
    finally:
        session.detach()


def capture(args: argparse.Namespace) -> tuple[Path, bool]:
    from playwright.sync_api import sync_playwright

    target = Path(args.output_root).resolve() / safe_segment(args.org) / args.page_type / now_stamp()
    target.mkdir(parents=True, exist_ok=False)
    logs = [f"capture_started={dt.datetime.now().astimezone().isoformat()}", f"page_type={args.page_type}", f"stage={args.stage}"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(args.cdp)
        context = browser.contexts[0]
        page = select_page(context)
        paths = frame_paths(page)
        frames = list(paths)
        viewport = page.evaluate(
            """() => ({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,scrollX,scrollY,zoom:getComputedStyle(document.documentElement).zoom || '1'})"""
        )
        metadata = {
            "page_type": args.page_type,
            "stage": args.stage,
            "organization": safe_segment(args.org),
            "url": sanitize_url(page.url),
            "title": stable_ui_text(page.title()),
            "chrome_version": browser.version,
            "automation_framework": f"playwright {importlib.metadata.version('playwright')}",
            "viewport": {"width": viewport["width"], "height": viewport["height"]},
            "page_zoom": viewport["zoom"],
            "device_pixel_ratio": viewport["dpr"],
            "scroll": {"x": viewport["scrollX"], "y": viewport["scrollY"]},
            "captured_at": dt.datetime.now().astimezone().isoformat(),
            "open_page_count": len(context.pages),
        }
        write_json(target / "metadata.json", metadata)
        write_json(target / "frame_tree.json", collect_frame_tree(page))
        structures, interactive, dialogs, html_parts = [], [], [], []
        for frame, path in paths.items():
            try:
                structures.append(collect_structure(frame, path))
                interactive.extend(collect_interactive(frame, path))
                dialogs.extend(collect_dialogs(frame, path))
                html_parts.append(f"<!-- frame: {path} -->\n{sanitized_frame_html(frame)}")
            except Exception as exc:
                logs.append(f"frame_error={path}:{sanitize_text(str(exc))[:300]}")
        structures.append({"slider_event_listeners": collect_slider_event_types(context, page)})
        write_json(target / "structure.json", structures)
        write_json(target / "interactive_elements.json", interactive)
        write_json(target / "dialogs.json", dialogs)
        (target / "sanitized_dom.html").write_text("\n\n".join(html_parts), encoding="utf-8")
        screenshot_with_masks(page, frames, target / "screenshot.png")
        if dialogs:
            try:
                dialog = page.locator(DIALOG_SELECTOR).first
                dialog.screenshot(path=str(target / "dialog.png"), mask=[dialog.locator(".el-dialog__body, .ant-modal-body, input, textarea, tbody")])
            except Exception as exc:
                logs.append(f"dialog_screenshot_error={sanitize_text(str(exc))[:300]}")
        sources = extract_selectors(Path(item).resolve() for item in args.audit_source)
        selector_results = audit_selectors(page, sources) if sources else []
        write_json(target / "selector_audit.json", selector_results)
        known = set(args.known_dialog_title)
        unknown = [dialog for dialog in dialogs if dialog.get("title") not in known]
        if unknown:
            logs.append(f"unknown_dialogs={len(unknown)}; automatic actions paused")
        (target / "capture.log").write_text("\n".join(logs) + "\n", encoding="utf-8")
        return target, bool(unknown)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture a privacy-safe e-tax page structure snapshot")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--org", required=True, help="Non-sensitive organization/region label used only as a directory name")
    parser.add_argument("--page-type", choices=PAGE_TYPES, required=True)
    parser.add_argument("--stage", choices=STAGES, default="entered")
    parser.add_argument("--output-root", default="artifacts/etax_page_snapshots")
    parser.add_argument("--audit-source", action="append", default=[])
    parser.add_argument("--known-dialog-title", action="append", default=[])
    return parser


def main() -> int:
    args = build_parser().parse_args()
    target, unknown = capture(args)
    print(target)
    if unknown:
        print("检测到未知弹窗：已保存脱敏证据并暂停，未点击任何按钮。")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
