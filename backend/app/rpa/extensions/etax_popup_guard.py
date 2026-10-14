from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit, urlunsplit


DIALOG_SELECTOR = (
    ".el-message-box__wrapper:visible, .el-dialog:visible, .ant-modal:visible, "
    "[role='dialog']:visible"
)
CLOSE_SELECTOR = (
    ".el-message-box__headerbtn, .el-dialog__headerbtn, .ant-modal-close, "
    "button[aria-label='Close'], button[aria-label='关闭']"
)
PROTECTED_DIALOG_SELECTOR = ".company-switch-modal, .export-result-list-message-dialog"
PROTECTED_MARKERS = (
    "请选择为哪个单位办税",
    "办理个税业务",
    "安全验证",
    "拖动滑块",
    "导出报表文件",
    "正在生成导出文件",
    "立即进入",
    "导出记录",
    "确认导出",
    "个人所得税扣缴申报表",
    "文件导入",
    "导入文件",
    "导入结果",
    "完税证明",
    "生成零工资",
    "税款计算",
    "清空数据",
    "删除数据",
    "其他窗口进行了单位切换",
)
GENERIC_REMINDER_KEYWORDS = {"温馨提示", "温 馨 提 示"}
UNKNOWN_POPUP_TIMEOUT_SECONDS = 60.0
_CONTEXT = {
    "org_code": "",
    "month": "",
    "task": "",
    "step": "workflow",
    "trigger": "",
    "last_progress_at": time.monotonic(),
    "last_progress_event": "guard_initialized",
}
_TASK_BY_SCRIPT = {
    "etax_batch_export.py": "special_deduction",
    "etax_batch_import.py": "import",
    "etax_tax_certificate_download.py": "tax_certificate_or_income_report",
    "etax_extra_income_reports.py": "extra_income_reports",
}
_BUILTIN_RULE_CONTEXT = {
    "unregistered-app": ("switch_org", "select_org"),
    "natural-person-invoice": ("switch_org", "select_org"),
    "previous-period-unfiled": ("switch_month", "select_tax_month"),
    "previous-tax-period-unfiled": ("switch_month", "select_tax_month"),
    "prior-period-unfiled": ("switch_month", "select_tax_month"),
    "annual-settlement-tax": ("enter_menu", "综合所得申报"),
    "annual-settlement-incomplete": ("enter_menu", "综合所得申报"),
    "annual-settlement-not-finished": ("enter_menu", "综合所得申报"),
}


def _load_popup_rules() -> list[dict[str, Any]]:
    config_path = Path(sys.argv[0]).resolve().parent / "etax_config.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        rules = payload.get("popup_rules", [])
        result = []
        for rule in rules:
            if not isinstance(rule, dict) or not rule.get("enabled", True):
                continue
            keyword = re.sub(r"\s+", "", str(rule.get("keyword") or ""))
            # Runtime may be carrying an older config written before workflow
            # protection was enforced. Never allow it back into the guard.
            if not keyword or keyword in {re.sub(r"\s+", "", value) for value in GENERIC_REMINDER_KEYWORDS}:
                continue
            if any(re.sub(r"\s+", "", marker) in keyword or keyword in re.sub(r"\s+", "", marker) for marker in PROTECTED_MARKERS):
                continue
            default_step, default_trigger = _BUILTIN_RULE_CONTEXT.get(str(rule.get("id") or ""), ("all", "all"))
            result.append({
                **rule,
                "step": rule.get("step", default_step),
                "trigger": rule.get("trigger", default_trigger),
            })
        return result
    except (OSError, json.JSONDecodeError, AttributeError):
        return []


def _task_from_runtime() -> str:
    script_name = Path(sys.argv[0]).name
    if script_name == "etax_tax_certificate_download.py":
        try:
            index = sys.argv.index("--task")
            return str(sys.argv[index + 1])
        except (ValueError, IndexError):
            return "tax_certificate_or_income_report"
    return _TASK_BY_SCRIPT.get(script_name, Path(sys.argv[0]).stem)


def set_popup_guard_context(
    *,
    org_code: str | None = None,
    month: str | None = None,
    task: str | None = None,
    step: str | None = None,
    trigger: str | None = None,
) -> None:
    if org_code is not None:
        _CONTEXT["org_code"] = org_code
    if month is not None:
        _CONTEXT["month"] = month
    if task is not None:
        _CONTEXT["task"] = task
    if step is not None:
        _CONTEXT["step"] = step
    if trigger is not None:
        _CONTEXT["trigger"] = trigger


def set_popup_step(step: str, trigger: str = "") -> None:
    set_popup_guard_context(step=step, trigger=trigger)


def mark_rpa_progress(event: str, page: Any | None = None) -> None:
    """Mark effective workflow progress and reconcile deferred popups when possible."""
    _CONTEXT["last_progress_at"] = time.monotonic()
    _CONTEXT["last_progress_event"] = str(event or "workflow_progress")
    if page is None:
        return
    guard_state = getattr(page, "_etax_popup_guard_state", None)
    if not isinstance(guard_state, dict):
        return
    try:
        drain_unexpected_popups(
            page,
            log=guard_state["log"],
            record_dir=guard_state["record_dir"],
            protected_markers=guard_state["protected_markers"],
            rules=guard_state["rules"],
            enforce_timeout=False,
        )
    except Exception as exc:
        guard_state["log"](f"popup_guard_checkpoint_failed：事件={event}；原因={exc}")


def _compact(value: Any, limit: int = 1000) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _safe_url(page: Any) -> str:
    try:
        parsed = urlsplit(str(page.url or ""))
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", parsed.fragment.split("?", 1)[0]))
    except Exception:
        return ""


def _write_record(record_dir: Path | None, payload: dict[str, Any]) -> None:
    if record_dir is None:
        return
    record_dir.mkdir(parents=True, exist_ok=True)
    with (record_dir / "popup_events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _record(
    page: Any,
    text: str,
    close_action: str,
    *,
    record_dir: Path | None,
    popup_type: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "captured_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "popup_type": popup_type,
        "org_code": _CONTEXT["org_code"],
        "month": _CONTEXT["month"],
        "task": _CONTEXT["task"],
        "step": _CONTEXT["step"],
        "trigger": _CONTEXT["trigger"],
        "url": _safe_url(page),
        "content": _compact(text),
        "close_action": close_action,
    }
    if extra:
        payload.update(extra)
    _write_record(record_dir, payload)
    return payload


def _is_protected(text: str, markers: Iterable[str]) -> bool:
    normalized = re.sub(r"\s+", "", text)
    return any(re.sub(r"\s+", "", marker) in normalized for marker in markers)


def _is_protected_popup(popup: Any, text: str, markers: Iterable[str]) -> bool:
    if _is_protected(text, markers):
        return True
    try:
        return bool(
            popup.evaluate(
                "(node, selector) => Boolean(node.closest(selector)) || Boolean(node.querySelector(selector))",
                PROTECTED_DIALOG_SELECTOR,
            )
        )
    except Exception:
        return False


def _rule_matches(rule: dict[str, Any], text: str) -> bool:
    keyword = re.sub(r"\s+", "", str(rule.get("keyword") or ""))
    if not keyword or keyword not in re.sub(r"\s+", "", text):
        return False
    task = str(rule.get("task") or "all")
    current = _CONTEXT["task"]
    if task != "all" and task != current and not (
        task == "declaration_reports"
        and current in {"income_report", "extra_income_reports", "tax_certificate_or_income_report"}
    ):
        return False
    step = str(rule.get("step") or "all")
    if step != "all" and step != _CONTEXT["step"]:
        return False
    trigger = str(rule.get("trigger") or "all")
    if trigger != "all" and trigger != _CONTEXT["trigger"]:
        return False
    return True


def _matching_rule(rules: Iterable[dict[str, Any]], text: str) -> dict[str, Any] | None:
    return next((rule for rule in rules if _rule_matches(rule, text)), None)


def _popup_title(popup: Any) -> str:
    selector = ".el-message-box__title, .el-dialog__title, .ant-modal-title, [role='heading']"
    try:
        titles = popup.locator(selector).filter(visible=True)
        if titles.count() > 0:
            return _compact(titles.first.inner_text(timeout=500), limit=200)
    except Exception:
        pass
    return ""


def _popup_buttons(popup: Any) -> list[str]:
    try:
        values = popup.locator("button:visible").all_inner_texts()
    except Exception:
        return []
    return [text for value in values if (text := _compact(value, limit=100))]


def _popup_fingerprint(*, title: str, text: str, buttons: Iterable[str]) -> str:
    source = json.dumps(
        {
            "step": _CONTEXT["step"],
            "trigger": _CONTEXT["trigger"],
            "title": _compact(title),
            "text": _compact(text),
            "buttons": [_compact(button) for button in buttons],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _unknown_registry(page: Any) -> dict[str, dict[str, Any]]:
    registry = getattr(page, "_etax_unknown_popups", None)
    if not isinstance(registry, dict):
        registry = {}
        setattr(page, "_etax_unknown_popups", registry)
    return registry


def _timeout_screenshot(page: Any, record_dir: Path | None, fingerprint: str) -> str:
    if record_dir is None:
        return ""
    record_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = record_dir / f"popup_blocked_{timestamp}_{fingerprint[:10]}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
    except Exception:
        return ""
    return str(path)


def handle_configured_popups(
    page: Any,
    *,
    rules: list[dict[str, Any]] | None = None,
    log: Callable[[str], None] = print,
    record_dir: Path | None = None,
    protected_markers: Iterable[str] = PROTECTED_MARKERS,
    max_popups: int = 8,
) -> int:
    rules = _load_popup_rules() if rules is None else rules
    handled = 0
    for _ in range(max_popups):
        dialogs = page.locator(DIALOG_SELECTOR)
        selected = None
        selected_text = ""
        selected_rule = None
        for index in range(dialogs.count()):
            popup = dialogs.nth(index)
            try:
                text = _compact(popup.inner_text(timeout=1500))
            except Exception:
                continue
            if _is_protected_popup(popup, text, protected_markers):
                continue
            rule = _matching_rule(rules, text)
            if rule and rule.get("action") != "keep":
                selected, selected_text, selected_rule = popup, text, rule
                break
        if selected is None or selected_rule is None:
            break

        delay_ms = int(selected_rule.get("delay_ms") or 0)
        if delay_ms:
            page.wait_for_timeout(delay_ms)
        try:
            if not selected.is_visible():
                continue
            selected_text = _compact(selected.inner_text(timeout=1500))
        except Exception:
            continue
        if not _rule_matches(selected_rule, selected_text):
            continue
        if _is_protected_popup(selected, selected_text, protected_markers):
            continue

        action = str(selected_rule.get("action"))
        button_text = str(selected_rule.get("button_text") or "").strip()
        close_action = action
        if action == "click":
            button = selected.get_by_role("button", name=button_text, exact=True).filter(visible=True)
            if button.count() == 0:
                payload = _record(
                    page, selected_text, "configured_click_failed", record_dir=record_dir, popup_type="dom",
                    extra={"rule_id": selected_rule.get("id"), "keyword": selected_rule.get("keyword")},
                )
                raise RuntimeError(f"弹窗规则要求点击“{button_text}”，但未找到该按钮：{payload['content']}")
            button.first.click(force=True, timeout=3000)
            close_action = f"button:{button_text}"
        elif action == "close":
            close_button = selected.locator(CLOSE_SELECTOR).filter(visible=True)
            if close_button.count() > 0:
                close_button.first.click(force=True, timeout=3000)
                close_action = "header_close"
            elif button_text:
                button = selected.get_by_role("button", name=button_text, exact=True).filter(visible=True)
                if button.count() == 0:
                    raise RuntimeError(f"弹窗规则没有找到关闭按钮“{button_text}”：{selected_text}")
                button.first.click(force=True, timeout=3000)
                close_action = f"button:{button_text}"
            else:
                raise RuntimeError(f"弹窗规则没有找到右上角关闭按钮：{selected_text}")

        payload = _record(
            page, selected_text, close_action, record_dir=record_dir, popup_type="dom",
            extra={"rule_id": selected_rule.get("id"), "keyword": selected_rule.get("keyword")},
        )
        log(
            "popup_rule_applied："
            f"规则={selected_rule.get('keyword')}；动作={close_action}；"
            f"步骤={payload['step'] or '未知'}；触发={payload['trigger'] or '未知'}；"
            f"机构代码={payload['org_code'] or '未知'}；内容={payload['content'] or '<空>'}"
        )
        mark_rpa_progress("popup_rule_applied")
        handled += 1
        page.wait_for_timeout(300)
    return handled


def drain_unexpected_popups(
    page: Any,
    *,
    log: Callable[[str], None] = print,
    record_dir: Path | None = None,
    protected_markers: Iterable[str] = PROTECTED_MARKERS,
    max_popups: int = 8,
    confirmation_delay_ms: int = 4000,
    rules: list[dict[str, Any]] | None = None,
    timeout_seconds: float = UNKNOWN_POPUP_TIMEOUT_SECONDS,
    enforce_timeout: bool = True,
) -> int:
    """Observe unknown dialogs without taking over the original workflow."""
    del confirmation_delay_ms  # Kept for compatibility with older callers.
    rules = _load_popup_rules() if rules is None else rules
    registry = _unknown_registry(page)
    now = time.monotonic()
    now_iso = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    visible: dict[str, dict[str, Any]] = {}
    dialogs = page.locator(DIALOG_SELECTOR)

    for index in range(min(dialogs.count(), max_popups)):
        popup = dialogs.nth(index)
        try:
            text = _compact(popup.inner_text(timeout=1500))
        except Exception:
            continue
        if _is_protected_popup(popup, text, protected_markers):
            continue
        if _matching_rule(rules, text) is not None:
            continue
        title = _popup_title(popup)
        buttons = _popup_buttons(popup)
        fingerprint = _popup_fingerprint(title=title, text=text, buttons=buttons)
        visible[fingerprint] = {"title": title, "text": text, "buttons": buttons}

    for fingerprint, entry in list(registry.items()):
        if fingerprint in visible:
            continue
        duration = max(0.0, now - float(entry["first_seen_monotonic"]))
        payload = _record(
            page,
            entry["text"],
            "workflow",
            record_dir=record_dir,
            popup_type="dom",
            extra={
                "event": "popup_unknown_resolved",
                "resolution": "workflow",
                "fingerprint": fingerprint,
                "title": entry["title"],
                "buttons": entry["buttons"],
                "first_seen_at": entry["first_seen_at"],
                "last_seen_at": entry["last_seen_at"],
                "duration": round(duration, 3),
            },
        )
        log(
            "popup_unknown_resolved：resolution=workflow；"
            f"duration={payload['duration']}s；步骤={payload['step'] or '未知'}；"
            f"触发={payload['trigger'] or '未知'}；内容={payload['content'] or '<空>'}"
        )
        del registry[fingerprint]

    detected = 0
    for fingerprint, snapshot in visible.items():
        entry = registry.get(fingerprint)
        if entry is None:
            entry = {
                **snapshot,
                "first_seen_at": now_iso,
                "last_seen_at": now_iso,
                "first_seen_monotonic": now,
            }
            registry[fingerprint] = entry
            payload = _record(
                page,
                snapshot["text"],
                "defer_to_workflow",
                record_dir=record_dir,
                popup_type="dom",
                extra={
                    "event": "popup_unknown_detected",
                    "action": "defer_to_workflow",
                    "fingerprint": fingerprint,
                    "title": snapshot["title"],
                    "buttons": snapshot["buttons"],
                    "first_seen_at": now_iso,
                    "last_seen_at": now_iso,
                },
            )
            log(
                "popup_unknown_detected：action=defer_to_workflow；"
                f"步骤={payload['step'] or '未知'}；触发={payload['trigger'] or '未知'}；"
                f"机构代码={payload['org_code'] or '未知'}；"
                f"税款所属期={payload['month'] or '未知'}；内容={payload['content'] or '<空>'}"
            )
            detected += 1
        else:
            entry["last_seen_at"] = now_iso

        if not enforce_timeout:
            continue
        popup_age = now - float(entry["first_seen_monotonic"])
        no_progress = now - float(_CONTEXT["last_progress_at"])
        if popup_age < timeout_seconds or no_progress < timeout_seconds:
            continue
        blocked_seconds = min(popup_age, no_progress)
        screenshot = _timeout_screenshot(page, record_dir, fingerprint)
        payload = _record(
            page,
            entry["text"],
            "stop_rpa",
            record_dir=record_dir,
            popup_type="dom",
            extra={
                "event": "popup_blocked_timeout",
                "fingerprint": fingerprint,
                "title": entry["title"],
                "buttons": entry["buttons"],
                "first_seen_at": entry["first_seen_at"],
                "last_seen_at": entry["last_seen_at"],
                "blocked_seconds": round(blocked_seconds, 3),
                "last_progress_event": _CONTEXT["last_progress_event"],
                "screenshot": screenshot,
            },
        )
        log(
            "popup_blocked_timeout："
            f"blocked_seconds={payload['blocked_seconds']}；步骤={payload['step'] or '未知'}；"
            f"触发={payload['trigger'] or '未知'}；机构代码={payload['org_code'] or '未知'}；"
            f"税款所属期={payload['month'] or '未知'}；截图={screenshot or '保存失败'}；"
            f"内容={payload['content'] or '<空>'}"
        )
        raise RuntimeError(
            f"未知弹窗持续阻塞且业务流程超过 {int(timeout_seconds)} 秒无进展，RPA 已停止："
            f"{entry['text'][:200]}"
        )
    return detected


def install_popup_guard(
    page: Any,
    *,
    log: Callable[[str], None] = print,
    record_dir: Path | None = None,
    protected_markers: Iterable[str] = PROTECTED_MARKERS,
    known_popup_handler: Callable[[Any], int] | None = None,
) -> Any:
    """Install continuous DOM and browser-native popup handling on a Playwright page."""
    if getattr(page, "_etax_popup_guard_installed", False):
        return page
    if not _CONTEXT["task"]:
        _CONTEXT["task"] = _task_from_runtime()
    setattr(page, "_etax_popup_guard_installed", True)
    configured_rules = _load_popup_rules()
    setattr(page, "_etax_popup_guard_state", {
        "log": log,
        "record_dir": record_dir,
        "protected_markers": tuple(protected_markers),
        "rules": configured_rules,
    })

    def handle_native(dialog: Any) -> None:
        text = _compact(getattr(dialog, "message", ""))
        if _is_protected(text, protected_markers):
            log(f"popup_guard_skipped：交由原有 RPA 流程处理；内容={text or '<空>'}")
            return
        rule = _matching_rule(configured_rules, text)
        if rule and rule.get("action") == "keep":
            log(f"popup_guard_skipped：受既有流程保护的浏览器弹窗；内容={text or '<空>'}")
            return
        if rule:
            time.sleep(int(rule.get("delay_ms") or 0) / 1000)
            action = "accept" if rule.get("action") == "click" else "dismiss"
            payload = _record(
                page, text, action, record_dir=record_dir, popup_type="browser",
                extra={"rule_id": rule.get("id"), "keyword": rule.get("keyword")},
            )
            dialog.accept() if action == "accept" else dialog.dismiss()
            log(
                f"popup_rule_applied：规则={rule.get('keyword')}；动作={action}；"
                f"步骤={payload['step'] or '未知'}；触发={payload['trigger'] or '未知'}；"
                f"内容={payload['content'] or '<空>'}"
            )
            return
        fingerprint = _popup_fingerprint(title="browser_dialog", text=text, buttons=[])
        seen = getattr(page, "_etax_native_unknown_popups", set())
        if fingerprint in seen:
            return
        seen.add(fingerprint)
        setattr(page, "_etax_native_unknown_popups", seen)
        payload = _record(
            page,
            text,
            "defer_to_workflow",
            record_dir=record_dir,
            popup_type="browser",
            extra={
                "event": "popup_unknown_detected",
                "action": "defer_to_workflow",
                "fingerprint": fingerprint,
            },
        )
        log(
            "popup_unknown_detected：action=defer_to_workflow；"
            f"类型=浏览器弹窗；步骤={payload['step'] or '未知'}；触发={payload['trigger'] or '未知'}；"
            f"机构代码={payload['org_code'] or '未知'}；"
            f"税款所属期={payload['month'] or '未知'}；内容={payload['content'] or '<空>'}"
        )

    page.on("dialog", handle_native)
    # During dialog transitions the old modal and the next modal can both be
    # visible briefly. A locator-handler trigger must resolve to one element.
    trigger = page.locator(DIALOG_SELECTOR).first

    def handle_blocking_popups() -> None:
        # Preserve the established RPA flow. Configured reminders only run
        # after its deterministic handler has had the first opportunity.
        if known_popup_handler is not None:
            known_popup_handler(page)
        handle_configured_popups(
            page,
            rules=configured_rules,
            log=log,
            record_dir=record_dir,
            protected_markers=protected_markers,
        )
        drain_unexpected_popups(
            page,
            log=log,
            record_dir=record_dir,
            protected_markers=protected_markers,
            rules=configured_rules,
        )

    page.add_locator_handler(
        trigger,
        handle_blocking_popups,
        no_wait_after=True,
    )
    return page
