from __future__ import annotations

import os
import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit, urlunsplit


CANCEL_FILE_ENV = "ETAX_RPA_CANCEL_FILE"

SLIDER_STRATEGIES = (
    {"name": "缓入缓出", "steps": 48, "delay": 18, "pause": 350, "overshoot": 4, "wobble": 0.8, "ease": "ease_in_out"},
    {"name": "匀速长拖", "steps": 58, "delay": 22, "pause": 450, "overshoot": 2, "wobble": 0.4, "ease": "linear"},
    {"name": "分段停顿", "steps": 42, "delay": 20, "pause": 550, "overshoot": 3, "wobble": 0.6, "ease": "segmented"},
)

SECURITY_DIALOG_SELECTOR = ".el-dialog:visible, [role='dialog']:visible"
SECURITY_DIALOG_TEXT = "安全验证"
SLIDER_HANDLE_SELECTORS = (
    "#aliyunCaptcha-sliding-slider",
    ".slider-handle",
    ".handler",
    ".verify-move-block",
    ".nc_iconfont.btn_slide",
    "[role='slider']",
)
SLIDER_TRACK_SELECTORS = (
    "#aliyunCaptcha-sliding-body",
    ".slider-track",
    ".verify-bar-area",
    ".nc_scale",
    "[role='progressbar']",
)
SLIDER_TARGET_SELECTORS = (
    "#aliyunCaptcha-sliding-target",
    ".slider-target",
    ".verify-gap",
    ".captcha-target",
)
SLIDER_SUCCESS_TEXT = ("验证成功", "校验成功", "通过验证")


class TaskCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class SliderContext:
    frame: Any
    frame_path: str
    dialog: Any
    handle: Any
    track: Any
    target: Any | None


def cancellation_requested() -> bool:
    value = os.environ.get(CANCEL_FILE_ENV, "").strip()
    return bool(value and Path(value).is_file())


def check_cancelled() -> None:
    if cancellation_requested():
        raise TaskCancelled("任务已取消")


def interruptible_wait(page: Any, milliseconds: int, chunk: int = 250) -> None:
    remaining = max(0, int(milliseconds))
    while remaining:
        check_cancelled()
        current = min(chunk, remaining)
        page.wait_for_timeout(current)
        remaining -= current
    check_cancelled()


def capture_sanitized_failure(page: Any, output_root: Path, error: Exception) -> Path:
    target = output_root / "failure_evidence" / f"{dt.datetime.now():%Y%m%d_%H%M%S_%f}"
    target.mkdir(parents=True, exist_ok=False)
    parsed = urlsplit(str(getattr(page, "url", "")))
    safe_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", parsed.fragment.split("?", 1)[0]))
    # Playwright exceptions may echo page text (including organization/person data).
    # The exception type is sufficient to correlate this evidence with the task log.
    safe_error = type(error).__name__
    (target / "metadata.json").write_text(
        json.dumps(
            {"url": safe_url, "error": safe_error, "captured_at": dt.datetime.now().astimezone().isoformat()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    sanitized_html = page.evaluate(
        r"""() => {
            const terms = ['查询','搜索','下载','导出','刷新','关闭','取消','确定','确认','申报结果','综合所得',
                '分类所得','限售股','安全验证','拖动滑块','立即进入','返回','下一步'];
            const clone = document.documentElement.cloneNode(true);
            clone.querySelectorAll('script,style,noscript').forEach(el => el.remove());
            clone.querySelectorAll('input,textarea').forEach(el => { el.removeAttribute('value'); el.textContent = ''; });
            clone.querySelectorAll('tbody').forEach(el => { el.innerHTML = '<tr><td>&lt;TABLE_DATA&gt;</td></tr>'; });
            clone.querySelectorAll('*').forEach(el => [...el.attributes].forEach(attr => {
                const key = attr.name.toLowerCase();
                if (key.startsWith('on') || key.startsWith('data-v-') || key.startsWith('data-react') ||
                    ['value','data-value','srcdoc','data-token','data-session','data-user'].includes(key)) el.removeAttribute(attr.name);
                if ((key === 'href' || key === 'src') && attr.value.includes('?')) el.setAttribute(attr.name, attr.value.split('?')[0]);
            }));
            const walker = document.createTreeWalker(clone, NodeFilter.SHOW_TEXT), nodes = [];
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
    (target / "sanitized_dom.html").write_text(sanitized_html, encoding="utf-8")
    page.screenshot(
        path=str(target / "screenshot.png"),
        full_page=True,
        mask=[
            page.locator(
                "header, nav, tbody, input, textarea, [contenteditable='true'], "
                "[class*='company'], [class*='org'], [class*='taxpayer'], "
                "[class*='user'], [class*='person'], [class*='name'], [class*='amount']"
            )
        ],
        mask_color="#111827",
    )
    return target


def _first_visible(scope: Any, selectors: Iterable[str]) -> Any | None:
    for selector in selectors:
        locator = scope.locator(selector).filter(visible=True)
        if locator.count() > 0:
            return locator.first
    return None


def _frame_path(frame: Any) -> str:
    parts = []
    current = frame
    while current.parent_frame is not None:
        try:
            element = current.frame_element()
            element_id = element.get_attribute("id") or ""
            element_name = element.get_attribute("name") or current.name or ""
        except Exception:
            element_id, element_name = "", current.name or ""
        parts.append(f"iframe#{element_id}" if element_id else (f"iframe[name={element_name}]" if element_name else "iframe"))
        current = current.parent_frame
    return "top" + "".join(f" > {part}" for part in reversed(parts))


def security_dialog(page: Any) -> Any:
    return page.locator(SECURITY_DIALOG_SELECTOR).filter(has_text=SECURITY_DIALOG_TEXT).first


def has_security_dialog(page: Any) -> bool:
    for frame in page.frames:
        try:
            if frame.locator(SECURITY_DIALOG_SELECTOR).filter(has_text=SECURITY_DIALOG_TEXT).count() > 0:
                return True
        except Exception:
            continue
    return False


def find_slider_context(page: Any) -> SliderContext:
    check_cancelled()
    for frame in page.frames:
        try:
            dialogs = frame.locator(SECURITY_DIALOG_SELECTOR).filter(has_text=SECURITY_DIALOG_TEXT).filter(visible=True)
            scopes = [dialogs.first] if dialogs.count() else [frame]
            for scope in scopes:
                handle = _first_visible(scope, SLIDER_HANDLE_SELECTORS)
                track = _first_visible(scope, SLIDER_TRACK_SELECTORS)
                if handle is None or track is None:
                    continue
                target = _first_visible(scope, SLIDER_TARGET_SELECTORS)
                return SliderContext(frame, _frame_path(frame), scope, handle, track, target)
        except Exception:
            continue
    raise RuntimeError("安全验证弹窗中没有找到可见的滑块和滑道")


def wait_for_slider_context(page: Any, timeout_ms: int = 12000) -> SliderContext:
    """Wait for the captcha iframe to render after its outer dialog appears."""
    last_error: RuntimeError | None = None
    attempts = max(1, timeout_ms // 250)
    for _ in range(attempts):
        check_cancelled()
        try:
            return find_slider_context(page)
        except RuntimeError as exc:
            last_error = exc
        if not has_security_dialog(page):
            raise RuntimeError("安全验证弹窗在滑块加载前已关闭") from last_error
        interruptible_wait(page, 250)
    raise RuntimeError("安全验证弹窗已出现，但等待滑块和滑道加载超时") from last_error


def _is_covered(locator: Any) -> bool:
    return bool(
        locator.evaluate(
            """el => {
                const r = el.getBoundingClientRect();
                const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
                return !!hit && hit !== el && !el.contains(hit);
            }"""
        )
    )


def _eased(progress: float, mode: str) -> float:
    if mode == "linear" or mode == "segmented":
        return progress
    return 0.5 - __import__("math").cos(progress * __import__("math").pi) / 2


def _success_visible(page: Any) -> bool:
    for text in SLIDER_SUCCESS_TEXT:
        for frame in page.frames:
            try:
                if frame.get_by_text(text, exact=False).filter(visible=True).count() > 0:
                    return True
            except Exception:
                continue
    return False


def drag_security_slider(page: Any, strategy: dict[str, Any], success_check: Callable[[], bool] | None = None) -> bool:
    check_cancelled()
    context = wait_for_slider_context(page)
    context.handle.scroll_into_view_if_needed(timeout=5000)
    interruptible_wait(page, 250)
    if _is_covered(context.handle):
        raise RuntimeError(f"滑块被遮罩层覆盖：{context.frame_path}")

    handle_box = context.handle.bounding_box()
    track_box = context.track.bounding_box()
    target_box = context.target.bounding_box() if context.target is not None else None
    if not handle_box or not track_box:
        raise RuntimeError(f"无法读取滑块或滑道坐标：{context.frame_path}")
    start_x = handle_box["x"] + handle_box["width"] / 2
    start_y = handle_box["y"] + handle_box["height"] / 2
    if target_box:
        end_x = target_box["x"] + target_box["width"] / 2
    else:
        end_x = track_box["x"] + track_box["width"] - handle_box["width"] / 2 - 2
    distance = end_x - start_x
    if distance <= max(10, handle_box["width"] / 2):
        raise RuntimeError(f"滑块拖动距离异常：{distance:.1f}px")

    steps = max(10, int(strategy.get("steps", 48)))
    page.mouse.move(start_x, start_y)
    interruptible_wait(page, 180)
    page.mouse.down()
    try:
        for step in range(1, steps + 1):
            check_cancelled()
            progress = step / steps
            eased = _eased(progress, str(strategy.get("ease", "ease_in_out")))
            wobble = float(strategy.get("wobble", 0.0))
            y = start_y + __import__("math").sin(progress * __import__("math").pi * 2) * wobble
            page.mouse.move(start_x + distance * eased, y)
            if strategy.get("ease") == "segmented" and step in {steps // 3, steps * 2 // 3}:
                interruptible_wait(page, 140)
            interruptible_wait(page, int(strategy.get("delay", 18)))
        overshoot = min(float(strategy.get("overshoot", 0)), max(0.0, track_box["x"] + track_box["width"] - end_x))
        page.mouse.move(end_x + overshoot, start_y)
        interruptible_wait(page, int(strategy.get("pause", 350)))
    finally:
        page.mouse.up()

    for _ in range(24):
        check_cancelled()
        if _success_visible(page) or not has_security_dialog(page) or (success_check and success_check()):
            return True
        interruptible_wait(page, 250)
    return False


def close_security_dialog(page: Any) -> None:
    if not has_security_dialog(page):
        return
    context = find_slider_context(page)
    close = context.dialog.locator(
        ".el-dialog__headerbtn, .ant-modal-close, button[aria-label='Close'], button[aria-label='关闭']"
    ).filter(visible=True)
    if close.count() != 1:
        raise RuntimeError("安全验证弹窗关闭按钮不是唯一匹配")
    close.first.click(force=True, timeout=3000)
    interruptible_wait(page, 800)


def solve_security_challenge(
    page: Any,
    reopen: Callable[[], Any],
    *,
    strategies: Iterable[dict[str, Any]] = SLIDER_STRATEGIES,
    success_check: Callable[[], bool] | None = None,
    log: Callable[[str], None] = print,
) -> None:
    try:
        for _ in range(48):
            check_cancelled()
            if has_security_dialog(page):
                break
            if success_check and success_check():
                return
            interruptible_wait(page, 250)
        else:
            log("未出现安全验证滑块，继续后续确认")
            return
    except TaskCancelled:
        raise

    for attempt, strategy in enumerate(strategies, start=1):
        check_cancelled()
        if not has_security_dialog(page):
            return
        log(f"安全验证第 {attempt} 次尝试：{strategy['name']}")
        if drag_security_slider(page, strategy, success_check):
            log("安全验证已通过")
            return
        check_cancelled()
        if has_security_dialog(page):
            close_security_dialog(page)
            check_cancelled()
            reopen()
    raise RuntimeError("多次尝试安全验证仍未出现明确成功状态")


def run_report_download(
    page: Any,
    *,
    report_title: str,
    status_text: str,
    open_export: Callable[[], Any],
    confirm_export: Callable[[], Any],
    download_export: Callable[[], Any],
    success_check: Callable[[], bool] | None = None,
    strategies: Iterable[dict[str, Any]] = SLIDER_STRATEGIES,
    log: Callable[[str], None] = print,
) -> Any | None:
    check_cancelled()
    if status_text != "申报成功":
        log(f"{report_title}状态为“{status_text}”，没有申报成功记录，正常跳过")
        return None
    open_export()
    solve_security_challenge(page, open_export, strategies=strategies, success_check=success_check, log=log)
    check_cancelled()
    confirm_export()
    check_cancelled()
    return download_export()
