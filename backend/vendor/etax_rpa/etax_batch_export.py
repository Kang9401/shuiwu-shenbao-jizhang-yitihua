from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from openpyxl import load_workbook
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

try:
    from etax_report_download import TaskCancelled, check_cancelled, interruptible_wait
    from etax_popup_guard import (
        handle_configured_popups,
        install_popup_guard,
        mark_rpa_progress,
        set_popup_guard_context,
        set_popup_step,
    )
except ImportError:  # Source-tree execution before runtime synchronization.
    extension_dir = Path(__file__).parents[2] / "app" / "rpa" / "extensions"
    if str(extension_dir) not in sys.path:
        sys.path.insert(0, str(extension_dir))
    from etax_report_download import TaskCancelled, check_cancelled, interruptible_wait  # type: ignore[no-redef]
    from etax_popup_guard import (  # type: ignore[no-redef]
        install_popup_guard,
        handle_configured_popups,
        mark_rpa_progress,
        set_popup_guard_context,
        set_popup_step,
    )


ETAX_URL = "https://etax.chinatax.gov.cn/"
WORK_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
OUTPUT_DIR = WORK_DIR / "output"
PROFILE_DIR = WORK_DIR / ".chrome-etax-profile"
DEFAULT_ORG_EXCEL = WORK_DIR / "机构信息表.xlsx"
SECURITY_DIALOG_SETTLE_MS = 2000


@dataclass(frozen=True)
class TaxOrg:
    name: str
    code: str
    search_result_index: int = 1


NAME_HEADERS = {"机构名称", "机构简称", "单位名称", "名称"}
CODE_HEADERS = {"机构代码", "机构编号", "代码", "编号"}
RESULT_INDEX_HEADERS = {"RPA搜索结果序号", "RPA机构序号"}
WORKFLOW_DIALOG_MARKERS = ("请选择为哪个单位办税", "安全验证", "导出报表文件", "文件导入")
TAX_REMINDER_MARKERS = ("上一属期未申报", "上一个所属期未申报", "上期所属期未申报")
# Shared page-guard contract used by the desktop test suite and sibling RPA runners.
COMMON_POPUP_TITLES = ("未注册个税APP提醒", "自然人代开发票提醒", "温馨提示", "温 馨 提 示")
POPUP_CLOSE_SELECTOR = (
    ".el-message-box__headerbtn, .el-dialog__headerbtn, .ant-modal-close, "
    "button[aria-label='Close'], button[aria-label='关闭']"
)
POPUP_CONTEXT = {"org_code": "", "month": ""}


def _known_popup_marker(text: str) -> str | None:
    compact = "".join(str(text or "").split())
    for marker in (*COMMON_POPUP_TITLES, *TAX_REMINDER_MARKERS):
        if marker in compact:
            return marker
    return None


def set_popup_context(org: TaxOrg | None = None, target_month: str | None = None) -> None:
    if org is not None:
        POPUP_CONTEXT["org_code"] = org.code
    if target_month is not None:
        POPUP_CONTEXT["month"] = target_month
    set_popup_guard_context(
        org_code=org.code if org is not None else None,
        month=target_month,
        step="workflow",
        trigger="",
    )


def guard_page(page: Page) -> Page:
    return install_popup_guard(page, log=log, record_dir=OUTPUT_DIR, known_popup_handler=drain_common_popups)


def normalize_header(value) -> str:
    return str(value or "").strip().replace(" ", "").replace("\u3000", "")


def read_orgs_from_excel(path: Path) -> list[TaxOrg]:
    if not path.exists():
        raise FileNotFoundError(f"找不到机构信息表：{path}")

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        rows = sheet.iter_rows(values_only=True)
        headers = [normalize_header(cell) for cell in next(rows, [])]
        name_index = next((i for i, header in enumerate(headers) if header in NAME_HEADERS), None)
        code_index = next((i for i, header in enumerate(headers) if header in CODE_HEADERS), None)
        result_index_column = next((i for i, header in enumerate(headers) if header in RESULT_INDEX_HEADERS), None)
        if name_index is None or code_index is None:
            raise ValueError(
                "机构信息表必须包含名称列和代码列；"
                "名称列支持：机构名称/机构简称/单位名称/名称；"
                "代码列支持：机构代码/机构编号/代码/编号。"
            )

        orgs: list[TaxOrg] = []
        seen: set[tuple[str, str]] = set()
        for row_number, row in enumerate(rows, start=2):
            name = str(row[name_index] or "").strip() if name_index < len(row) else ""
            code = str(row[code_index] or "").strip() if code_index < len(row) else ""
            if code.endswith(".0"):
                code = code[:-2]
            result_index = 1
            if result_index_column is not None and result_index_column < len(row) and row[result_index_column] not in (None, ""):
                try:
                    result_index = int(float(str(row[result_index_column]).strip()))
                except (TypeError, ValueError):
                    raise ValueError(f"第 {row_number} 行的 RPA 搜索结果序号必须为正整数") from None
                if result_index < 1:
                    raise ValueError(f"第 {row_number} 行的 RPA 搜索结果序号必须从 1 开始")
            if not name and not code:
                continue
            if not name or not code:
                log(f"跳过第 {row_number} 行：机构名称或代码为空")
                continue
            key = (name, code)
            if key in seen:
                log(f"跳过重复机构：{name}（{code}）")
                continue
            seen.add(key)
            orgs.append(TaxOrg(name, code, result_index))

        if not orgs:
            raise ValueError(f"机构信息表没有有效机构数据：{path}")
        return orgs
    finally:
        workbook.close()


def default_month() -> str:
    today = dt.datetime.now()
    return f"{today.year}-{today.month:02d}"


def month_label(month: str) -> str:
    year, month_num = month.split("-", 1)
    return f"{int(year)}年{int(month_num)}月"


def log(message: str) -> None:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {message}", flush=True)


def wait_for_user(message: str, skip: bool = False) -> None:
    log(message)
    if skip:
        log("已启用 --yes，跳过人工命令行确认")
        return
    input("确认后按 Enter 继续...")


def close_duplicate_etax_tabs(context, active_page: Page) -> Page:
    etax_pages = [p for p in context.pages if "etax.chinatax.gov.cn" in p.url]
    if len(etax_pages) <= 1:
        return guard_page(active_page)

    withholding_pages = [p for p in etax_pages if "withholding/index.html" in p.url]
    preferred = active_page if active_page in etax_pages else etax_pages[-1]
    if active_page not in withholding_pages and withholding_pages:
        preferred = withholding_pages[-1]

    for page in list(etax_pages):
        if page == preferred:
            continue
        try:
            log(f"关闭重复税务标签：{page.url}")
            page.close()
        except Exception as exc:
            log(f"关闭重复税务标签失败：{exc}")

    preferred.bring_to_front()
    return guard_page(preferred)


def visible_count(page: Page, selector: str) -> int:
    return page.locator(selector).filter(visible=True).count()


def click_text(page: Page, text: str, *, exact: bool = True, timeout: int = 15000) -> None:
    locator = page.get_by_text(text, exact=exact).filter(visible=True)
    locator.first.wait_for(state="visible", timeout=timeout)
    locator.first.click()


def click_button(page: Page, name: str, *, exact: bool = True, timeout: int = 15000) -> None:
    button = page.get_by_role("button", name=name, exact=exact).filter(visible=True)
    try:
        button.first.wait_for(state="visible", timeout=timeout)
        button.first.click()
    except PlaywrightTimeoutError:
        click_text(page, name, exact=exact, timeout=timeout)


def fill_first_visible(page: Page, selectors: list[str], value: str, timeout: int = 15000) -> None:
    last_error: Exception | None = None
    for selector in selectors:
        locator = page.locator(selector).filter(visible=True)
        try:
            locator.first.wait_for(state="visible", timeout=timeout)
            locator.first.fill(value)
            return
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"找不到可输入控件，候选选择器：{selectors}") from last_error


def capture_unknown_popup(page: Page, popup) -> Path:
    evidence = OUTPUT_DIR / "failure_evidence" / "unknown_popups" / f"{dt.datetime.now():%Y%m%d_%H%M%S_%f}"
    evidence.mkdir(parents=True, exist_ok=False)
    details = popup.evaluate(
        r"""dialog => {
            const title = dialog.querySelector('.el-dialog__title,.ant-modal-title,[role=heading],h1,h2,h3');
            const clone = dialog.cloneNode(true);
            clone.querySelectorAll('input,textarea').forEach(el => { el.removeAttribute('value'); el.textContent = ''; });
            clone.querySelectorAll('tbody').forEach(el => { el.innerHTML = '<tr><td>&lt;TABLE_DATA&gt;</td></tr>'; });
            clone.querySelectorAll('*').forEach(el => [...el.attributes].forEach(attr => {
                if (attr.name.startsWith('on') || attr.name.startsWith('data-v-') || ['value','data-value','srcdoc'].includes(attr.name)) el.removeAttribute(attr.name);
            }));
            const safeTerms = ['查询','搜索','下载','导出','刷新','关闭','取消','确定','确认','我知道了','申报结果',
                '综合所得','分类所得','限售股','安全验证','拖动滑块','立即进入','返回','下一步'];
            const safeText = value => {
                const raw = String(value || '').replace(/\s+/g, '');
                const kept = safeTerms.filter(term => raw.includes(term));
                return kept.length ? kept.join(' / ') : (raw ? '<TEXT>' : '');
            };
            const walker = document.createTreeWalker(clone, NodeFilter.SHOW_TEXT);
            const textNodes = [];
            while (walker.nextNode()) textNodes.push(walker.currentNode);
            for (const node of textNodes) {
                const raw = (node.nodeValue || '').replace(/\s+/g, '');
                if (!raw) continue;
                const kept = safeTerms.filter(term => raw.includes(term));
                node.nodeValue = kept.length ? kept.join(' / ') : '<TEXT>';
            }
            return {
                title: safeText(title?.textContent), body: safeText(dialog.textContent),
                buttons: [...dialog.querySelectorAll('button,[role=button]')].map(el => safeText(el.textContent)).filter(Boolean),
                html: clone.outerHTML
            };
        }"""
    )
    parsed = urlsplit(page.url)
    details.update(
        url=urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", parsed.fragment.split("?", 1)[0])),
        captured_at=dt.datetime.now().astimezone().isoformat(),
    )
    sanitized_html = details.pop("html")
    (evidence / "metadata.json").write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")
    (evidence / "sanitized_dom.html").write_text(sanitized_html, encoding="utf-8")
    masks = [
        page.locator(
            "header, nav, tbody, input, textarea, [contenteditable='true'], "
            "[class*='company'], [class*='org'], [class*='taxpayer'], "
            "[class*='user'], [class*='person'], [class*='name'], [class*='amount']"
        ),
        popup.locator(".el-dialog__body, .ant-modal-body"),
    ]
    page.screenshot(path=str(evidence / "screenshot.png"), full_page=True, mask=masks, mask_color="#111827")
    try:
        popup.screenshot(
            path=str(evidence / "dialog.png"),
            mask=[popup.locator(".el-dialog__body, .ant-modal-body, input, textarea, tbody")],
            mask_color="#111827",
        )
    except Exception:
        pass
    log(f"检测到未知弹窗，已保存脱敏证据并暂停：{evidence}")
    return evidence


def _close_one_common_popup(page: Page) -> bool:
    other_window_box = page.locator(".el-message-box__wrapper:visible").filter(has_text="其他窗口进行了单位切换")
    if other_window_box.count() > 0:
        other_window_box.first.locator("button.el-button--primary", has_text="确定").first.click()
        page.wait_for_timeout(800)
        log("已处理其他窗口单位切换提示")
        return True

    return False


def drain_common_popups(page: Page, max_popups: int = 8) -> int:
    closed = 0
    for _ in range(max_popups):
        if not _close_one_common_popup(page):
            break
        closed += 1
    if closed == max_popups:
        log(f"连续关闭已知提示弹框达到上限：{max_popups}")
    return closed


def close_common_popups(page: Page) -> None:
    guard_page(page)
    log("检查并关闭既有流程已识别的提示弹框")
    drain_common_popups(page)
    handle_configured_popups(page, log=log, record_dir=OUTPUT_DIR)


def close_export_record_dialog(page: Page) -> bool:
    """Close an export-record dialog only after its download work is complete."""
    dialogs = page.locator(".export-result-list-message-dialog:visible")
    if dialogs.count() == 0:
        return False
    dialog = dialogs.first
    close_button = dialog.locator(
        ".el-dialog__headerbtn, button[aria-label='Close'], button[aria-label='关闭']"
    ).filter(visible=True)
    if close_button.count() == 0:
        raise RuntimeError("导出记录下载完成，但未找到弹框关闭按钮")
    close_button.first.click(force=True, timeout=3000)
    dialog.wait_for(state="hidden", timeout=5000)
    log("导出记录下载完成，已关闭导出记录弹框")
    return True


def ensure_withholding_page(page: Page) -> Page:
    guard_page(page)
    if "withholding/index.html" in page.url:
        page.bring_to_front()
        return page

    context = page.context
    log("当前不在单位办税页面，点击首页“单位办税”进入扣缴端")
    entry = page.locator("a.navbar-first-menu", has_text="单位办税").filter(visible=True)
    entry.first.wait_for(state="visible", timeout=15000)
    with context.expect_page(timeout=15000) as new_page_info:
        entry.first.click(force=True)
    new_page = new_page_info.value
    new_page.wait_for_load_state("domcontentloaded", timeout=30000)
    guard_page(new_page)
    new_page.bring_to_front()
    log(f"已进入单位办税页面：{new_page.url}")
    return new_page


def open_company_switch_dialog(page: Page) -> None:
    dialog = page.locator(".company-switch-modal:visible")
    if dialog.count() > 0:
        log("单位切换弹框已打开")
        return

    switch_button = page.locator(".switch-company-button").filter(visible=True)
    try:
        switch_button.first.wait_for(state="visible", timeout=8000)
        switch_button.first.click()
    except PlaywrightTimeoutError:
        click_text(page, "切换", exact=False, timeout=8000)

    page.locator(".company-switch-modal:visible").first.wait_for(state="visible", timeout=15000)


def switch_org(page: Page, org: TaxOrg) -> None:
    log(f"切换纳税单位：{org.name}（{org.code}）")
    close_export_record_dialog(page)
    close_common_popups(page)
    open_company_switch_dialog(page)

    dialog = page.locator(".company-switch-modal:visible, .el-dialog, .ant-modal, [role='dialog']").filter(has_text="单位名称").filter(visible=True)
    dialog.first.wait_for(state="visible", timeout=15000)

    name_input = dialog.first.locator(".company-search-input input, input[placeholder='请输入']").filter(visible=True).first
    name_input.fill(org.name)
    log(f"已输入单位名称：{org.name}")

    dialog.first.get_by_role("button", name="搜索", exact=True).click()
    log("已点击搜索")

    results = dialog.first.locator("label.el-radio").filter(has_text=org.name).filter(visible=True)
    results.first.wait_for(state="visible", timeout=20000)
    count = results.count()
    if org.search_result_index > count:
        raise RuntimeError(
            f"机构 {org.name}（{org.code}）配置选择第 {org.search_result_index} 条搜索结果，但税局只返回 {count} 条"
        )
    set_popup_step("switch_org", "select_org")
    results.nth(org.search_result_index - 1).click()
    log(f"已选择搜索结果第 {org.search_result_index} 条（共 {count} 条）")

    dialog.first.get_by_role("button", name="办理个税业务", exact=True).click()
    page.wait_for_load_state("domcontentloaded", timeout=20000)
    page.wait_for_timeout(1500)
    close_common_popups(page)
    # 新版提醒可能在扣缴端首页完成渲染后延迟出现。
    page.wait_for_timeout(1000)
    close_common_popups(page)
    mark_rpa_progress("org_switched", page)
    set_popup_step("workflow")


def set_tax_month(page: Page, target_month: str) -> None:
    close_common_popups(page)
    target_label = month_label(target_month)
    target_month_text = f"{int(target_month.split('-', 1)[1])}月"
    month_input = page.locator(".tax-period-date-picker input, input.el-input__inner").filter(visible=True).first
    month_input.wait_for(state="visible", timeout=15000)
    current_value = month_input.input_value(timeout=3000)
    if current_value == target_label:
        log(f"税款所属月份已是：{target_label}")
        mark_rpa_progress("month_selected", page)
        return

    log(f"切换税款所属月份：{current_value} -> {target_label}")
    month_input.click()
    picker = page.locator(".el-picker-panel:visible").first
    picker.wait_for(state="visible", timeout=8000)
    set_popup_step("switch_month", "select_tax_month")
    picker.locator(".el-month-table td", has_text=target_month_text).filter(visible=True).first.click()
    # The previous-period reminder is rendered asynchronously after the month
    # picker closes. Check once during the initial refresh and once more after
    # the small delayed popup window observed on the tax site.
    page.wait_for_timeout(1200)
    close_common_popups(page)
    page.wait_for_timeout(2200)
    close_common_popups(page)

    actual_value = month_input.input_value(timeout=5000)
    if actual_value != target_label:
        raise RuntimeError(f"税款所属月份切换失败，当前值：{actual_value}，目标值：{target_label}")
    log(f"税款所属月份已切换为：{target_label}")
    mark_rpa_progress("month_selected", page)
    set_popup_step("workflow")


def enter_salary_page(page: Page, target_month: str) -> None:
    log("进入：扣缴申报 -> 综合所得申报 -> 正常工资薪金所得")
    if "income_declaration/salary" in page.url:
        log("当前已在正常工资薪金所得明细页")
        set_tax_month(page, target_month)
        mark_rpa_progress("salary_page_opened", page)
        return

    click_text(page, "扣缴申报", exact=False)
    page.wait_for_timeout(500)
    set_popup_step("enter_menu", "综合所得申报")
    click_text(page, "综合所得申报", exact=False)
    page.wait_for_timeout(1500)
    close_common_popups(page)
    set_popup_step("workflow")
    set_tax_month(page, target_month)
    click_text(page, "正常工资薪金所得", exact=False)
    page.wait_for_load_state("domcontentloaded", timeout=20000)
    page.wait_for_timeout(1500)
    close_common_popups(page)
    mark_rpa_progress("salary_page_opened", page)


def table_has_salary_rows(page: Page) -> bool:
    log("检查正常工资薪金所得页面是否已有姓名、本期收入条目")
    page.get_by_text("本期收入", exact=False).first.wait_for(state="attached", timeout=15000)

    rows = page.locator(".el-table__body-wrapper tr").filter(visible=True)
    count = rows.count()
    if count == 0:
        log("未发现表格行，需要生成零工资")
        return False

    for i in range(min(count, 30)):
        text = rows.nth(i).inner_text(timeout=2000).strip()
        if text and "暂无数据" not in text:
            log(f"发现已有数据行：{text[:80]}")
            return True
    log("表格无有效数据行，需要生成零工资")
    return False


def generate_zero_salary(page: Page) -> None:
    log("执行生成零工资")
    click_button(page, "更多操作", exact=False)
    click_text(page, "生成零工资", exact=True)
    log("已点击生成零工资，等待确认弹框")
    click_button(page, "确定", exact=True, timeout=15000)
    page.wait_for_timeout(2500)
    close_common_popups(page)


SLIDER_STRATEGIES = [
    {"name": "慢速缓出", "steps": 44, "delay": 20, "pause": 350, "overshoot": 6, "wobble": 1.5, "ease": "ease_out"},
    {"name": "匀速长拖", "steps": 58, "delay": 24, "pause": 500, "overshoot": 4, "wobble": 0.6, "ease": "linear"},
    {"name": "分段停顿", "steps": 36, "delay": 18, "pause": 650, "overshoot": 8, "wobble": 1.2, "ease": "segmented"},
    {"name": "先快后慢", "steps": 50, "delay": 16, "pause": 450, "overshoot": 10, "wobble": 2.0, "ease": "ease_in_out"},
    {"name": "末端回拉", "steps": 46, "delay": 22, "pause": 450, "overshoot": 14, "wobble": 1.0, "ease": "ease_out_back"},
]


def security_dialog(page: Page):
    return page.locator(".el-dialog:visible, [role='dialog']:visible").filter(has_text="安全验证").first


def export_name_dialog(page: Page):
    return page.locator(".el-dialog:visible, [role='dialog']:visible").filter(has_text="导出报表文件").first


def has_visible_security_dialog(page: Page) -> bool:
    return page.locator(".el-dialog:visible, [role='dialog']:visible").filter(has_text="安全验证").count() > 0


def has_visible_export_name_dialog(page: Page) -> bool:
    return page.locator(".el-dialog:visible, [role='dialog']:visible").filter(has_text="导出报表文件").count() > 0


def open_export_all_people(page: Page) -> None:
    export_button = page.locator(".dropdown-export button, button", has_text="导出").filter(visible=True).first
    export_button.wait_for(state="visible", timeout=15000)
    export_button.click()
    item = page.locator(".el-dropdown-menu:visible .el-dropdown-menu__item", has_text="全部人员").first
    item.wait_for(state="visible", timeout=8000)
    item.click()
    # The tax site renders the slider asynchronously after selecting export.
    page.wait_for_timeout(SECURITY_DIALOG_SETTLE_MS)


def close_security_dialog(page: Page) -> None:
    dialog = security_dialog(page)
    if page.locator(".el-dialog:visible, [role='dialog']:visible").filter(has_text="安全验证").count() == 0:
        return
    try:
        dialog.locator(".el-dialog__headerbtn").first.click(force=True, timeout=2000)
    except Exception:
        page.keyboard.press("Escape")
    page.wait_for_timeout(1200)


def drag_aliyun_slider(page: Page, strategy: dict) -> bool:
    check_cancelled()
    aliyun_slider = page.locator("#aliyunCaptcha-sliding-slider").filter(visible=True)
    aliyun_track = page.locator("#aliyunCaptcha-sliding-body").filter(visible=True)
    if aliyun_slider.count() == 0 or aliyun_track.count() == 0:
        return False

    handle_box = aliyun_slider.first.bounding_box()
    track_box = aliyun_track.first.bounding_box()
    if not handle_box or not track_box:
        raise RuntimeError("无法读取阿里云滑块位置。")

    start_x = handle_box["x"] + handle_box["width"] / 2
    start_y = handle_box["y"] + handle_box["height"] / 2
    end_x = track_box["x"] + track_box["width"] - 3
    distance = end_x - start_x
    steps = strategy["steps"]

    page.mouse.move(start_x, start_y)
    page.wait_for_timeout(280)
    page.mouse.down()
    page.wait_for_timeout(260)

    for step in range(1, steps + 1):
        check_cancelled()
        progress = step / steps
        if strategy["ease"] == "linear":
            eased = progress
        elif strategy["ease"] == "ease_in_out":
            eased = 0.5 - math.cos(progress * math.pi) / 2
        elif strategy["ease"] == "segmented":
            eased = progress
            if step in (10, 20, 30):
                page.wait_for_timeout(180)
        elif strategy["ease"] == "ease_out_back":
            eased = 1 - (1 - progress) ** 2
            if progress > 0.86:
                eased = min(1.0, eased + 0.015)
        else:
            eased = 1 - (1 - progress) ** 2

        x = start_x + distance * eased
        y = start_y + math.sin(progress * math.pi * 3) * strategy["wobble"]
        page.mouse.move(x, y)
        page.wait_for_timeout(strategy["delay"])

    page.wait_for_timeout(strategy["pause"])
    page.mouse.move(end_x + strategy["overshoot"], start_y + 1)
    if strategy["ease"] == "ease_out_back":
        page.wait_for_timeout(140)
        page.mouse.move(end_x - 2, start_y)
    page.wait_for_timeout(260)
    page.mouse.up()
    page.wait_for_timeout(4500)
    return has_visible_export_name_dialog(page) or not has_visible_security_dialog(page)


def drag_generic_slider(page: Page, strategy: dict) -> bool:
    check_cancelled()
    candidates = [
        ".slider-handle",
        ".handler",
        ".verify-move-block",
        ".nc_iconfont.btn_slide",
        "div[role='button']",
    ]
    handle = None
    for selector in candidates:
        loc = page.locator(selector).filter(visible=True)
        if loc.count() > 0:
            handle = loc.first
            break
    if handle is None:
        return False

    handle.scroll_into_view_if_needed(timeout=5000)
    box = handle.bounding_box()
    track_box = handle.evaluate(
        """el => {
            let current = el.parentElement;
            const handleRect = el.getBoundingClientRect();
            while (current) {
                const rect = current.getBoundingClientRect();
                if (rect.width >= handleRect.width * 3 && rect.height >= handleRect.height) {
                    return {x: rect.x, y: rect.y, width: rect.width, height: rect.height};
                }
                current = current.parentElement;
            }
            return null;
        }"""
    )
    if not box or not track_box:
        raise RuntimeError("无法读取滑块或滑道位置。")

    start_x = box["x"] + box["width"] / 2
    start_y = box["y"] + box["height"] / 2
    end_x = track_box["x"] + track_box["width"] - box["width"] / 2 - 2
    if end_x <= start_x:
        raise RuntimeError("滑块拖动距离无效。")

    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(end_x, start_y, steps=strategy["steps"])
    page.wait_for_timeout(strategy["pause"])
    page.mouse.up()
    page.wait_for_timeout(2500)
    return has_visible_export_name_dialog(page) or not has_visible_security_dialog(page)


def drag_visible_slider_to_end(page: Page, strategy: dict) -> bool:
    log(f"处理安全验证滑块：策略={strategy['name']}")
    if drag_aliyun_slider(page, strategy):
        return True
    if drag_generic_slider(page, strategy):
        return True
    raise RuntimeError("没有找到安全验证滑块。")


def solve_security_slider_with_retries(page: Page, max_attempts: int = 5) -> None:
    for attempt, strategy in enumerate(SLIDER_STRATEGIES[:max_attempts], start=1):
        check_cancelled()
        if not has_visible_security_dialog(page):
            return
        log(f"安全验证第 {attempt} 次尝试：{strategy['name']}")
        try:
            if drag_visible_slider_to_end(page, strategy):
                if has_visible_export_name_dialog(page):
                    log("安全验证已通过，进入导出文件命名弹框")
                    return
                if not has_visible_security_dialog(page):
                    log("安全验证弹框已消失")
                    return
        except TaskCancelled:
            raise
        except Exception as exc:
            log(f"安全验证策略失败：{exc}")

        if has_visible_security_dialog(page):
            log("安全验证未通过，关闭当前验证弹框并重新发起导出")
            close_security_dialog(page)
            open_export_all_people(page)
            security_dialog(page).wait_for(state="visible", timeout=12000)

    raise RuntimeError("多次尝试安全验证滑块仍未通过，请手动拖动当前弹框后再继续。")


def export_all_people(page: Page, org: TaxOrg, target_month: str) -> str:
    for attempt in range(1, 4):
        if has_visible_export_name_dialog(page):
            break

        log(f"点击导出 -> 全部人员，第 {attempt} 次")
        open_export_all_people(page)

        try:
            security_dialog(page).wait_for(state="visible", timeout=12000)
            solve_security_slider_with_retries(page, max_attempts=len(SLIDER_STRATEGIES))
        except PlaywrightTimeoutError:
            log("未出现安全验证滑块，继续后续导出文件命名")

        try:
            page.locator(".el-dialog:visible, [role='dialog']:visible").filter(has_text="导出报表文件").first.wait_for(
                state="visible",
                timeout=8000,
            )
            break
        except PlaywrightTimeoutError:
            log("本次未进入导出文件命名弹框，准备重新发起导出")
            if has_visible_security_dialog(page):
                close_security_dialog(page)
            page.wait_for_timeout(1200)

    log("等待导出报表文件命名弹框")
    export_dialog = page.locator(".el-dialog:visible, [role='dialog']:visible").filter(has_text="导出报表文件").first
    export_dialog.wait_for(state="visible", timeout=20000)
    filename_input = export_dialog.locator("textarea, input").filter(visible=True).first
    current_name = filename_input.input_value(timeout=5000).strip()
    if not current_name:
        current_name = filename_input.inner_text(timeout=2000).strip()
    month_prefix = target_month.replace("-", "")
    export_name = current_name
    if not export_name.startswith(f"{month_prefix}_"):
        export_name = f"{month_prefix}_{export_name}"
    org_suffix = f"{org.code}({org.name})"
    if not export_name.endswith(f"_{org_suffix}"):
        if export_name.endswith(f"_{org.code}"):
            export_name = f"{export_name}({org.name})"
        else:
            export_name = f"{export_name}_{org_suffix}"
    filename_input.fill(export_name)
    log(f"导出文件名设置为：{export_name}")
    export_dialog.get_by_role("button", name="确定", exact=True).click()

    message_box = page.locator(".el-message-box__wrapper:visible").filter(has_text="正在生成导出文件").first
    message_box.wait_for(state="visible", timeout=30000)
    message_box.locator("button.el-button--primary", has_text="立即进入").first.click()
    page.wait_for_load_state("domcontentloaded", timeout=20000)
    page.wait_for_timeout(1500)
    return export_name


def ensure_export_ready(page: Page, target_month: str) -> None:
    if "income_declaration/salary" not in page.url or page.locator("button", has_text="导出").filter(visible=True).count() == 0:
        log("当前不在正常工资薪金所得明细页或导出按钮不可见，重新进入明细页")
        enter_salary_page(page, target_month)
    page.locator("button", has_text="导出").filter(visible=True).first.wait_for(state="visible", timeout=15000)


def wait_and_download_export(page: Page, export_name: str, org: TaxOrg, max_wait_seconds: int = 300) -> Path:
    log(f"等待导出记录处理成功：{export_name}")
    deadline = time.monotonic() + max_wait_seconds
    row = page.locator("tr, .el-table__row").filter(has_text=export_name).filter(visible=True)
    if row.count() == 0:
        try:
            page.get_by_text("查看导出记录", exact=True).filter(visible=True).first.click(timeout=5000)
            page.wait_for_timeout(2000)
        except Exception:
            pass

    while time.monotonic() < deadline:
        check_cancelled()
        try:
            row.first.wait_for(state="visible", timeout=10000)
            row_text = row.first.inner_text(timeout=3000)
            log(f"当前导出记录状态：{row_text[:120].replace(chr(10), ' | ')}")
            if "处理成功" in row_text:
                OUTPUT_DIR.mkdir(exist_ok=True)
                with page.expect_download(timeout=30000) as download_info:
                    try:
                        row.first.get_by_text("下载", exact=False).first.click()
                    except Exception:
                        row.first.locator("button, a").filter(has_text="下载").first.click()
                download = download_info.value
                suggested = download.suggested_filename
                suffix = Path(suggested).suffix
                target = OUTPUT_DIR / f"{export_name}{suffix or '.xlsx'}"
                download.save_as(str(target))
                log(f"文件已下载：{target}")
                close_export_record_dialog(page)
                return target
        except Exception as exc:
            log(f"暂未找到成功记录：{exc}")

        log("处理未完成，等待10秒后刷新")
        interruptible_wait(page, 10000)
        try:
            click_button(page, "刷新", exact=False, timeout=3000)
        except Exception:
            page.reload(wait_until="domcontentloaded", timeout=20000)

    raise TimeoutError(f"超过 {max_wait_seconds} 秒仍未处理成功：{export_name}")


def process_org(page: Page, org: TaxOrg, target_month: str, max_wait_seconds: int) -> tuple[Path, Page]:
    check_cancelled()
    set_popup_context(org, target_month)
    log("=" * 70)
    log(f"开始处理单位：{org.name}（{org.code}）")
    page = ensure_withholding_page(page)
    switch_org(page, org)
    page = ensure_withholding_page(page)
    enter_salary_page(page, target_month)
    if not table_has_salary_rows(page):
        generate_zero_salary(page)
    ensure_export_ready(page, target_month)
    export_name = export_all_people(page, org, target_month)
    result = wait_and_download_export(page, export_name, org, max_wait_seconds=max_wait_seconds)
    log(f"单位处理完成：{org.name} -> {result}")
    return result, page


def make_context(playwright, args):
    if args.cdp:
        log(f"连接已开启远程调试的 Chrome：{args.cdp}")
        browser = playwright.chromium.connect_over_cdp(args.cdp)
        context = browser.contexts[0] if browser.contexts else browser.new_context(accept_downloads=True)
        withholding_pages = [p for p in context.pages if "withholding/index.html" in p.url]
        etax_pages = [p for p in context.pages if "etax.chinatax.gov.cn" in p.url]
        page = withholding_pages[-1] if withholding_pages else (etax_pages[-1] if etax_pages else context.new_page())
        return browser, context, guard_page(page)

    chrome_args = ["--start-maximized", "--disable-features=AutomationControlled"]
    if args.proxy == "none":
        chrome_args.append("--no-proxy-server")
    elif args.proxy == "system":
        pass
    elif args.proxy.startswith("http://") or args.proxy.startswith("https://") or ":" in args.proxy:
        chrome_args.append(f"--proxy-server={args.proxy}")

    if not args.persistent:
        log("启动可见 Chrome（普通临时会话，避免历史自动化配置目录影响联网）")
        browser = playwright.chromium.launch(
            channel="chrome",
            headless=False,
            slow_mo=args.slow_mo,
            args=chrome_args,
        )
        context = browser.new_context(accept_downloads=True, ignore_https_errors=True, no_viewport=True)
        page = context.new_page()
        return browser, context, guard_page(page)

    log(f"启动可见 Chrome（持久化用户数据目录）：{PROFILE_DIR}")
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        channel="chrome",
        headless=False,
        accept_downloads=True,
        slow_mo=args.slow_mo,
        ignore_https_errors=True,
        args=chrome_args,
    )
    page = context.pages[0] if context.pages else context.new_page()
    return None, context, guard_page(page)


def main() -> int:
    parser = argparse.ArgumentParser(description="自然人电子税务局个税申报导出批量自动化")
    parser.add_argument("--cdp", help="连接当前 Chrome 的 CDP 地址，例如 http://127.0.0.1:9222")
    parser.add_argument("--url", help="可选：启动后自动打开的税务局具体页面地址。未提供时等待你手动进入业务页面。")
    parser.add_argument("--slow-mo", type=int, default=120, help="每步操作延迟毫秒，方便财务复核")
    parser.add_argument("--max-wait", type=int, default=300, help="单个导出文件最长等待秒数")
    parser.add_argument("--month", default=default_month(), help="税款所属月份，格式 YYYY-MM，例如 2026-06")
    parser.add_argument("--org-excel", default=str(DEFAULT_ORG_EXCEL), help="机构信息 Excel 路径，默认读取当前目录的机构信息表.xlsx")
    parser.add_argument("--org-code", help="只处理指定机构代码，例如 1121；不传则处理全部机构")
    parser.add_argument("--start-org-code", help="从指定机构代码开始处理后续机构，例如 11831")
    parser.add_argument(
        "--proxy",
        default="system",
        help="代理设置：system 表示使用系统默认；none 表示禁用代理；也可填 http://host:port",
    )
    parser.add_argument("--persistent", action="store_true", help="使用脚本专用持久化 Chrome 配置目录，便于保存登录态")
    parser.add_argument("--yes", action="store_true", help="跳过命令行确认提示，用于已确认页面状态后的联调")
    parser.add_argument("--keep-tabs", action="store_true", help="CDP 模式下保留其他自然人电子税务局标签页；默认会关闭重复税务标签以避免单位切换冲突")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)
    log(f"输出目录：{OUTPUT_DIR}")
    log(f"目标税款所属月份：{month_label(args.month)}")
    org_excel = Path(args.org_excel).resolve()
    orgs_from_excel = read_orgs_from_excel(org_excel)
    log(f"已从机构信息表读取 {len(orgs_from_excel)} 个机构：{org_excel}")

    with sync_playwright() as playwright:
        browser, context, page = make_context(playwright, args)
        page.set_default_timeout(15000)
        page.set_default_navigation_timeout(30000)
        if args.cdp and not args.keep_tabs:
            page = close_duplicate_etax_tabs(context, page)

        try:
            if args.url:
                log(f"打开网址：{args.url}")
                page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
                log(f"当前页面：{page.url}")
            elif "127.0.0.1:9222" in page.url:
                log("当前页是 Chrome 调试接口，不是税务业务页。请在同一浏览器中打开自然人电子税务局业务页面。")
            elif page.url == "about:blank":
                log("未指定自动打开地址，请在浏览器中手动进入自然人电子税务局业务页面。")
            else:
                log(f"沿用当前页面：{page.url}")
            wait_for_user("请确认浏览器已登录自然人电子税务局，并停留在可办理个税业务的页面。", skip=args.yes)
            page = ensure_withholding_page(page)

            orgs = [org for org in orgs_from_excel if not args.org_code or org.code == args.org_code]
            if args.start_org_code:
                start_index = next((i for i, org in enumerate(orgs) if org.code == args.start_org_code), None)
                if start_index is None:
                    raise RuntimeError(f"没有找到开始机构代码：{args.start_org_code}")
                orgs = orgs[start_index:]
                log(f"从机构代码 {args.start_org_code} 开始续跑，剩余 {len(orgs)} 个机构")
            if not orgs:
                raise RuntimeError(f"没有找到机构代码：{args.org_code}")

            downloaded: list[Path] = []
            for org in orgs:
                check_cancelled()
                result, page = process_org(page, org, args.month, args.max_wait)
                downloaded.append(result)

            log("=" * 70)
            log("全部单位处理完成")
            for path in downloaded:
                log(f"已下载：{path}")
            return 0
        finally:
            wait_for_user("脚本已结束，浏览器将保持到你确认后关闭。", skip=args.yes)
            if args.cdp:
                log("CDP 模式不关闭你手动打开的 Chrome")
            else:
                context.close()
                if browser is not None:
                    browser.close()


if __name__ == "__main__":
    sys.exit(main())
