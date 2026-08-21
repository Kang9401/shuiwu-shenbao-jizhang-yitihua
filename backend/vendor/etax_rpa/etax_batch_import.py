from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from etax_batch_export import (
    DEFAULT_ORG_EXCEL,
    OUTPUT_DIR,
    WORK_DIR,
    TaxOrg,
    click_button,
    click_text,
    check_cancelled,
    close_common_popups,
    close_duplicate_etax_tabs,
    default_month,
    ensure_withholding_page,
    interruptible_wait,
    log,
    make_context,
    month_label,
    read_orgs_from_excel,
    set_popup_context,
    set_tax_month,
    switch_org,
    wait_for_user,
)


INPUT_ROOT = WORK_DIR / "input"

# The eTax SPA can take noticeably longer to render the action bar after an
# organization/month switch.  Keep these waits separate so a delayed dropdown
# or confirmation dialog does not look like a missing control.
ACTION_BAR_WAIT_SECONDS = 30
DROPDOWN_MENU_WAIT_SECONDS = 30
CLEAR_CONFIRMATION_WAIT_SECONDS = 30


class ImportTask:
    def __init__(
        self,
        menu: str,
        item: str | None,
        patterns: list[str],
        label: str,
        *,
        needs_month: bool = True,
        clear_before_import: bool = True,
        exclude_patterns: list[str] | None = None,
    ) -> None:
        self.menu = menu
        self.item = item
        self.patterns = patterns
        self.label = label
        self.needs_month = needs_month
        self.clear_before_import = clear_before_import
        self.exclude_patterns = exclude_patterns or []

    @property
    def task_id(self) -> str:
        return "|".join((self.menu, self.item or "", self.label))


def visible_dialog(page: Page, title_text: str):
    return page.locator(".el-dialog, .el-message-box, [role='dialog']").filter(has_text=title_text).filter(visible=True).first


def close_import_dialog(page: Page) -> None:
    dialogs = page.locator(".el-dialog, [role='dialog']").filter(has_text="文件导入").filter(visible=True)
    if dialogs.count() == 0:
        return
    try:
        dialogs.first.locator(".el-dialog__headerbtn, button[aria-label='Close'], button[aria-label='关闭']").first.click(timeout=2000)
        page.wait_for_timeout(500)
        log("已关闭文件导入弹框")
    except Exception:
        pass


def handle_confirm_dialogs(page: Page, *, seconds: int = 8) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        box = page.locator(".el-message-box__wrapper:visible, .el-dialog:visible").filter(
            has_text="确定"
        )
        if box.count() == 0:
            page.wait_for_timeout(300)
            continue
        text = box.first.inner_text(timeout=1000)
        if "文件导入" in text or "导入结果" in text:
            return
        for name in ["确定", "确认", "继续", "是"]:
            button = box.first.get_by_role("button", name=name, exact=True).filter(visible=True)
            if button.count() > 0:
                log(f"处理确认弹框：{text[:80].replace(chr(10), ' ')}")
                button.first.click()
                page.wait_for_timeout(800)
                break
        else:
            return


def ensure_withholding_menu_open(page: Page) -> None:
    submenu = page.locator(".el-submenu").filter(has_text="扣缴申报").first.locator("ul.el-menu--inline").first
    try:
        display = submenu.evaluate("el => getComputedStyle(el).display", timeout=2000)
    except Exception:
        display = "none"
    if display != "none":
        return

    log("展开左侧菜单：扣缴申报")
    page.locator(".el-submenu").filter(has_text="扣缴申报").first.locator(":scope > .el-submenu__title").click()
    page.wait_for_timeout(800)


def click_left_menu(page: Page, text: str) -> None:
    log(f"点击左侧菜单：{text}")
    if text == "扣缴申报":
        ensure_withholding_menu_open(page)
        close_common_popups(page)
        return

    ensure_withholding_menu_open(page)
    locator = page.locator(".sidebar-container, .el-menu, aside, nav").get_by_text(text, exact=False).filter(visible=True)
    try:
        locator.first.wait_for(state="visible", timeout=8000)
        locator.first.evaluate("el => el.scrollIntoView({block: 'center', inline: 'nearest'})")
        locator.first.click()
    except PlaywrightTimeoutError:
        raw_locator = page.locator(".el-menu-item").filter(has_text=text).first
        raw_locator.evaluate("el => el.scrollIntoView({block: 'center', inline: 'nearest'})")
        page.wait_for_timeout(300)
        raw_locator.click(force=True)
    page.wait_for_timeout(1200)
    close_common_popups(page)


def enter_declaration_page(page: Page, menu: str, item: str | None, target_month: str, *, needs_month: bool) -> None:
    click_left_menu(page, "扣缴申报")
    click_left_menu(page, menu)
    if needs_month:
        set_tax_month(page, target_month)
    if item:
        log(f"进入申报项目：{item}")
        click_text(page, item, exact=False, timeout=15000)
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        page.wait_for_timeout(1500)
        close_common_popups(page)
        # Detail pages render the action bar asynchronously after the route
        # changes. Wait for the actual button instead of racing the renderer.
        page.get_by_role("button", name="更多操作", exact=False).filter(visible=True).first.wait_for(
            state="visible", timeout=ACTION_BAR_WAIT_SECONDS * 1000
        )


def open_import_dialog(page: Page) -> Page:
    close_import_dialog(page)
    log("点击导入 -> 导入文件")
    click_button(page, "导入", exact=False, timeout=15000)
    page.wait_for_timeout(500)
    try:
        page.locator(".el-dropdown-menu:visible, .ant-dropdown:visible").get_by_text("导入文件", exact=False).first.click(timeout=5000)
    except Exception:
        click_text(page, "导入文件", exact=False, timeout=8000)
    dialog = visible_dialog(page, "文件导入")
    dialog.wait_for(state="visible", timeout=15000)
    return dialog


def clear_existing_data(page: Page, task: ImportTask) -> None:
    """Clear the current declaration page before the first upload for its scope."""
    if not task.clear_before_import:
        log(f"clear_data_skipped：{task.label}；原因：当前税局页面不支持清空或按业务规则不清空")
        return
    log(f"clear_data_started：{task.label}")
    try:
        action_button = page.get_by_role("button", name="更多操作", exact=False).filter(visible=True).first
        action_button.wait_for(state="visible", timeout=ACTION_BAR_WAIT_SECONDS * 1000)
        # Element UI attaches the popper to <body>.  Re-open it once if the
        # first click is swallowed during a component re-render.
        clear_item = None
        visible_menu_items: list[str] = []
        for attempt in range(2):
            action_button.click()
            deadline = time.monotonic() + DROPDOWN_MENU_WAIT_SECONDS
            while time.monotonic() < deadline:
                check_cancelled()
                menu_items = page.locator(
                    "ul.el-dropdown-menu.el-popper:visible li.el-dropdown-menu__item:visible, "
                    ".el-dropdown-menu:visible li.el-dropdown-menu__item:visible, "
                    ".ant-dropdown:visible [role='menuitem']:visible"
                )
                visible_menu_items = [item.strip() for item in menu_items.all_inner_texts() if item.strip()]
                clear_item = menu_items.filter(has_text="清空数据")
                if clear_item.count() == 0:
                    clear_item = page.get_by_text("清空数据", exact=True).filter(visible=True)
                if clear_item.count() == 1:
                    break
                page.wait_for_timeout(500)
            if clear_item is not None and clear_item.count() == 1:
                break
            if attempt == 0:
                log(f"清空数据菜单尚未出现，将重新打开更多操作：已见菜单项={visible_menu_items or ['无']}")
        if clear_item is None or clear_item.count() != 1:
            raise RuntimeError(
                f"未找到清空数据菜单：{task.label}；路由={page.url}；已见菜单项={visible_menu_items or ['无']}"
            )
        clear_item.click()
        dialogs = page.locator(
            ".el-message-box__wrapper:visible, .el-dialog:visible, [role='dialog']:visible"
        )
        # The tax site uses a generic "提示" title and asks whether to clear
        # the whole month's data; the body does not repeat the menu label.
        confirmation = None
        deadline = time.monotonic() + CLEAR_CONFIRMATION_WAIT_SECONDS
        while time.monotonic() < deadline:
            check_cancelled()
            for marker in ("是否确定清空当前所得的整月数据", "清空当前所得的整月数据", "清空数据", "删除数据"):
                candidate = dialogs.filter(has_text=marker)
                if candidate.count() == 1:
                    confirmation = candidate.first
                    break
            if confirmation is not None:
                break
            page.wait_for_timeout(500)
        if confirmation is None:
            visible_dialog_text = [text.strip().replace("\n", " ")[:120] for text in dialogs.all_inner_texts() if text.strip()]
            raise RuntimeError(
                f"清空数据确认弹窗无法唯一识别：{task.label}；路由={page.url}；可见弹窗={visible_dialog_text or ['无']}"
            )
        buttons = confirmation.get_by_role("button", name="确定", exact=True).filter(visible=True)
        if buttons.count() == 0:
            buttons = confirmation.get_by_role("button", name="确认", exact=True).filter(visible=True)
        if buttons.count() != 1:
            raise RuntimeError(f"清空数据确认按钮不唯一：{task.label}")
        buttons.first.click()
        confirmation.wait_for(state="hidden", timeout=CLEAR_CONFIRMATION_WAIT_SECONDS * 1000)
        page.wait_for_timeout(1200)
        close_common_popups(page)
    except Exception as exc:
        log(f"clear_data_failed：{task.label}；原因：{exc}")
        raise
    log(f"clear_data_completed：{task.label}")


def choose_input_file(dialog, file_path: Path) -> None:
    file_input = dialog.locator("input[type='file']").first
    file_input.wait_for(state="attached", timeout=10000)
    file_input.set_input_files(str(file_path))


def click_import_result_tab(dialog) -> None:
    tab = dialog.locator("#tab-result, .el-tabs__item", has_text="导入结果").filter(visible=True)
    tab.first.wait_for(state="visible", timeout=10000)
    tab.first.click()


def import_status_text(dialog, filename: str) -> str | None:
    rows = dialog.locator(".el-table__body-wrapper tr, tbody tr, .el-table__row").filter(has_text=filename)
    if rows.count() == 0:
        return None
    return rows.first.inner_text(timeout=3000).strip()


def wait_import_success(page: Page, filename: str, *, max_wait_seconds: int) -> None:
    dialog = visible_dialog(page, "文件导入")
    deadline = time.monotonic() + max_wait_seconds
    last_status = ""
    while time.monotonic() < deadline:
        check_cancelled()
        click_import_result_tab(dialog)
        row_text = import_status_text(dialog, filename)
        if row_text:
            last_status = row_text.replace("\n", " | ")
            log(f"导入结果：{last_status[:160]}")
            if "成功" in row_text and "失败" not in row_text:
                log(f"文件导入成功：{filename}")
                return
            if "失败" in row_text:
                raise RuntimeError(f"文件导入失败：{filename}；结果行：{last_status}")
        else:
            log(f"导入结果中暂未找到文件：{filename}")

        refresh = dialog.get_by_role("button", name="刷新", exact=False).filter(visible=True)
        if refresh.count() > 0:
            refresh.first.click()
        interruptible_wait(page, 5000)

    raise TimeoutError(f"超过 {max_wait_seconds} 秒仍未看到导入成功：{filename}；最后状态：{last_status}")


def progress_file_for_month(target_month: str) -> Path:
    return OUTPUT_DIR / f"import_progress_{target_month}.json"


def load_progress(target_month: str) -> dict:
    path = progress_file_for_month(target_month)
    if not path.exists():
        return {"month": target_month, "completed": {}, "tasks": {}}
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception as exc:
        log(f"读取进度文件失败，将忽略旧进度：{path}；原因：{exc}")
        return {"month": target_month, "completed": {}, "tasks": {}}
    if not isinstance(data, dict):
        return {"month": target_month, "completed": {}}
    data.setdefault("month", target_month)
    data.setdefault("completed", {})
    data.setdefault("tasks", {})
    return data


def save_progress(target_month: str, progress: dict) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = progress_file_for_month(target_month)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as file:
        json.dump(progress, file, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def reset_progress_for_orgs(target_month: str, orgs: list[TaxOrg]) -> dict:
    progress = load_progress(target_month)
    completed = progress.setdefault("completed", {})
    tasks = progress.setdefault("tasks", {})
    for org in orgs:
        completed.pop(org.code, None)
        tasks.pop(org.code, None)
    save_progress(target_month, progress)
    log("已按用户选择清除本次机构的历史完成记录，将全部重跑")
    return progress


def completed_task_ids(progress: dict, org: TaxOrg) -> set[str]:
    tasks = progress.setdefault("tasks", {}).get(org.code, [])
    return {str(task_id) for task_id in tasks if task_id}


def mark_task_completed(target_month: str, org: TaxOrg, task: ImportTask, progress: dict) -> None:
    task_progress = progress.setdefault("tasks", {})
    task_ids = set(task_progress.get(org.code, []))
    task_ids.add(task.task_id)
    task_progress[org.code] = sorted(task_ids)
    save_progress(target_month, progress)
    log(f"已记录任务完成状态：{org.name}（{org.code}）/{task.label}")


def mark_org_completed(target_month: str, org: TaxOrg, progress: dict) -> None:
    completed = progress.setdefault("completed", {})
    previous = completed.get(org.code, {})
    tasks = previous.get("tasks", []) if isinstance(previous, dict) else []
    completed[org.code] = {
        "name": org.name,
        "code": org.code,
        "tasks": sorted(set(tasks)),
        "completed_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_progress(target_month, progress)
    log(f"已记录机构完成状态：{org.name}（{org.code}）")


def find_one_file(base_dir: Path, patterns: list[str], exclude_patterns: list[str] | None = None) -> Path | None:
    if not base_dir.exists():
        log(f"未找到申报表目录，跳过该目录下文件匹配：{base_dir}")
        return None

    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(base_dir.glob(pattern))
    excluded = exclude_patterns or []
    matches = sorted(
        {
            path.resolve()
            for path in matches
            if path.is_file() and not any(path.match(pattern) for pattern in excluded)
        },
        key=lambda p: p.name,
    )
    if not matches:
        log(f"未找到待上传文件，跳过：目录={base_dir}，匹配={patterns}")
        return None
    if len(matches) > 1:
        chosen = max(matches, key=lambda p: p.stat().st_mtime)
        log(f"匹配到多个文件，使用最近修改的文件：{chosen.name}")
        return chosen
    return matches[0]


def upload_and_verify(page: Page, file_path: Path, *, label: str, max_wait_seconds: int) -> None:
    log(f"开始上传：{label} -> {file_path.name}")
    dialog = open_import_dialog(page)
    choose_input_file(dialog, file_path)
    log(f"已选择文件：{file_path}")
    page.wait_for_timeout(1500)
    handle_confirm_dialogs(page)
    wait_import_success(page, file_path.name, max_wait_seconds=max_wait_seconds)
    close_import_dialog(page)


def parse_amount(value: str) -> float:
    text = str(value or "").strip().replace(",", "")
    if not text or text in {"--", "暂无数据"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


SUMMARY_COLUMN_ALIASES = {
    "所得项目": ("所得项目",),
    "填写人次": ("填写人次", "填报人次"),
    "收入合计（元）": ("收入合计", "收入合计（元）"),
    "应补/退税额（元）": ("应补/退税额", "应补/退税额（元）"),
}


def summary_column_indices(headers: list[str]) -> dict[str, int]:
    indices: dict[str, int] = {}
    for key, aliases in SUMMARY_COLUMN_ALIASES.items():
        for index, header in enumerate(headers):
            if any(alias in header for alias in aliases):
                indices[key] = index
                break
    return indices


def map_summary_cells(headers: list[str], cells: list[str]) -> dict[str, str] | None:
    if not cells or all(cell.strip() in {"", "暂无数据"} for cell in cells):
        return None
    indices = summary_column_indices(headers)
    if len(indices) == len(SUMMARY_COLUMN_ALIASES) and max(indices.values()) < len(cells):
        return {key: cells[index].strip() for key, index in indices.items()}
    values = [cell.strip() for cell in cells if cell.strip() and cell.strip() != "暂无数据"]
    if len(values) < 4:
        return None
    return dict(zip(SUMMARY_COLUMN_ALIASES, values[:4]))


def wait_for_declaration_table(page: Page, *, timeout_seconds: int = 15) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        check_cancelled()
        loading = page.locator(".el-loading-mask:visible, .ant-spin-spinning:visible")
        tables = page.locator(".el-table:visible, table:visible")
        empty = page.get_by_text("暂无数据", exact=False).filter(visible=True)
        if loading.count() == 0 and (tables.count() > 0 or empty.count() > 0):
            return
        interruptible_wait(page, 300)
    raise TimeoutError("reconciliation_capture_failed：申报页面表格异步加载超时")


def _next_page_button(page: Page):
    buttons = page.locator(
        ".el-pagination:visible .btn-next, .ant-pagination:visible .ant-pagination-next"
    ).filter(visible=True)
    if buttons.count() == 0:
        return None
    button = buttons.first
    class_name = button.get_attribute("class") or ""
    if button.get_attribute("disabled") is not None or "disabled" in class_name:
        return None
    return button


def extract_summary_table(page: Page, *, allow_missing: bool = False) -> list[dict[str, str]]:
    wait_for_declaration_table(page)
    results: list[dict[str, str]] = []
    seen_pages: set[tuple[tuple[str, str, str, str], ...]] = set()
    page_number = 1
    while True:
        check_cancelled()
        page_rows: list[dict[str, str]] = []
        matched_table = False
        tables = page.locator(".el-table").filter(visible=True)
        for table_index in range(tables.count()):
            table = tables.nth(table_index)
            text = table.inner_text(timeout=3000)
            if not all(header in text for header in ["所得项目", "收入合计", "应补/退税额"]):
                continue
            matched_table = True
            header_cells = table.locator(
                ".el-table__header-wrapper th, thead th"
            ).filter(visible=True)
            headers = [cell.inner_text(timeout=1000).strip() for cell in header_cells.all()]
            rows = table.locator("tbody tr, .el-table__row").filter(visible=True)
            for i in range(rows.count()):
                values = map_summary_cells(headers, rows.nth(i).locator("td").all_inner_texts())
                if values is not None:
                    page_rows.append(values)
            break
        if not matched_table:
            if page.get_by_text("暂无数据", exact=False).filter(visible=True).count() > 0:
                log("核对表抓取：页面显示暂无数据")
                return []
            if allow_missing:
                log("核对表抓取：当前页面没有汇总表，改为读取限售股明细")
                return []
            raise RuntimeError("reconciliation_capture_failed：未识别到申报汇总表")
        signature = tuple(
            (row["所得项目"], row["填写人次"], row["收入合计（元）"], row["应补/退税额（元）"])
            for row in page_rows
        )
        if signature in seen_pages:
            log(f"核对表抓取：检测到重复分页内容，停止于第 {page_number} 页")
            break
        seen_pages.add(signature)
        results.extend(page_rows)
        log(f"核对表抓取：页码={page_number}，行数={len(page_rows)}")
        next_button = _next_page_button(page)
        if next_button is None:
            break
        next_button.click()
        page_number += 1
        interruptible_wait(page, 800)
        wait_for_declaration_table(page)

    income_total = sum(parse_amount(row["收入合计（元）"]) for row in results)
    tax_total = sum(parse_amount(row["应补/退税额（元）"]) for row in results)
    log(f"核对表抓取完成：行数={len(results)}，收入合计={income_total:.2f}，税额合计={tax_total:.2f}")
    return results


def _header_index(headers: list[str], aliases: tuple[str, ...]) -> int | None:
    for index, header in enumerate(headers):
        if any(alias in header for alias in aliases):
            return index
    return None


def extract_restricted_share_summary(page: Page) -> list[dict[str, str]]:
    wait_for_declaration_table(page)
    tables = page.locator(".el-table").filter(visible=True)
    person_count = 0
    income_total = 0.0
    tax_total = 0.0
    for table_index in range(tables.count()):
        table = tables.nth(table_index)
        headers = [
            cell.inner_text(timeout=1000).strip()
            for cell in table.locator(".el-table__header-wrapper th, thead th").filter(visible=True).all()
        ]
        income_index = _header_index(headers, ("应纳税所得额", "收入合计", "收入额", "收入"))
        tax_index = _header_index(headers, ("应补/退税额", "应纳税额", "应扣缴税额", "税额"))
        rows = table.locator("tbody tr, .el-table__row").filter(visible=True)
        if rows.count() == 0:
            continue
        for i in range(rows.count()):
            cells = [cell.strip() for cell in rows.nth(i).locator("td").all_inner_texts()]
            if not cells or any("暂无数据" in cell for cell in cells):
                continue
            person_count += 1
            if income_index is not None and income_index < len(cells):
                income_total += parse_amount(cells[income_index])
            elif len(cells) >= 18:
                income_total += parse_amount(cells[10])
            if tax_index is not None and tax_index < len(cells):
                tax_total += parse_amount(cells[tax_index])
            elif len(cells) >= 18:
                tax_total += parse_amount(cells[-1])
        if person_count:
            break
    if person_count == 0:
        log("限售股所得申报无明细，已跳过")
        return []
    log(f"限售股核对抓取完成：行数={person_count}，收入合计={income_total:.2f}，税额合计={tax_total:.2f}")
    return [
        {
            "所得项目": "限售股转让所得",
            "填写人次": str(person_count),
            "收入合计（元）": f"{income_total:.2f}",
            "应补/退税额（元）": f"{tax_total:.2f}",
        }
    ]


def collect_declaration_check(page: Page, menu: str, target_month: str) -> list[dict[str, str]]:
    log(f"申报导入后核对：{menu}")
    enter_declaration_page(page, menu, None, target_month, needs_month=True)
    page.wait_for_timeout(1200)
    if menu == "限售股所得申报":
        rows = extract_summary_table(page, allow_missing=True)
        if rows:
            return rows
        return extract_restricted_share_summary(page)
    return extract_summary_table(page)


def safe_sheet_name(value: str) -> str:
    name = "".join("_" if ch in r'[]:*?/\\' else ch for ch in value).strip()
    return (name or "核对结果")[:31]


def write_declaration_check_excel(target_month: str, org: TaxOrg, sections: list[tuple[str, list[dict[str, str]]]]) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"{target_month}个税申报核对.xlsx"
    if path.exists():
        workbook = load_workbook(path)
    else:
        workbook = Workbook()
        default_sheet = workbook.active
        workbook.remove(default_sheet)

    sheet_name = safe_sheet_name(f"{org.code}_{org.name}")
    if sheet_name in workbook.sheetnames:
        del workbook[sheet_name]
    sheet = workbook.create_sheet(sheet_name)

    summary_fill = PatternFill("solid", fgColor="D9EAF7")
    summary_font = Font(bold=True, size=12)
    header_font = Font(bold=True)
    headers = ["申报类型", "所得项目", "填写人次", "收入合计（元）", "应补/退税额（元）"]

    row_index = 1
    for column, header in enumerate(headers, start=1):
        sheet.cell(row=row_index, column=column, value=header)
        sheet.cell(row=row_index, column=column).font = header_font
    row_index += 1

    summary: list[dict[str, float | int | str]] = []
    for title, rows in sections:
        if title == "限售股所得申报" and not rows:
            continue
        item_count = 0
        people_total = 0
        income_total = 0.0
        tax_total = 0.0
        if rows:
            for item in rows:
                item_count += 1
                people_total += int(parse_amount(item.get("填写人次", "0")))
                income_total += parse_amount(item.get("收入合计（元）", "0"))
                tax_total += parse_amount(item.get("应补/退税额（元）", "0"))
                sheet.cell(row=row_index, column=1, value=title)
                sheet.cell(row=row_index, column=2, value=item.get("所得项目", ""))
                sheet.cell(row=row_index, column=3, value=item.get("填写人次", ""))
                sheet.cell(row=row_index, column=4, value=item.get("收入合计（元）", ""))
                sheet.cell(row=row_index, column=5, value=item.get("应补/退税额（元）", ""))
                row_index += 1
        else:
            sheet.cell(row=row_index, column=1, value=title)
            sheet.cell(row=row_index, column=2, value="未提取到数据")
            row_index += 1

        summary.append(
            {
                "申报类型": title,
                "项目数": item_count,
                "填写人次合计": people_total,
                "收入合计（元）": income_total,
                "应补/退税额（元）": tax_total,
            }
        )

    row_index += 2
    sheet.cell(row=row_index, column=1, value="统计结果")
    sheet.cell(row=row_index, column=1).font = summary_font
    sheet.cell(row=row_index, column=1).fill = summary_fill
    row_index += 1
    summary_headers = ["申报类型", "项目数", "填写人次合计", "收入合计（元）", "应补/退税额（元）"]
    for column, header in enumerate(summary_headers, start=1):
        sheet.cell(row=row_index, column=column, value=header)
        sheet.cell(row=row_index, column=column).font = header_font
    row_index += 1
    for item in summary:
        sheet.cell(row=row_index, column=1, value=item["申报类型"])
        sheet.cell(row=row_index, column=2, value=item["项目数"])
        sheet.cell(row=row_index, column=3, value=item["填写人次合计"])
        sheet.cell(row=row_index, column=4, value=round(float(item["收入合计（元）"]), 2))
        sheet.cell(row=row_index, column=5, value=round(float(item["应补/退税额（元）"]), 2))
        row_index += 1

    widths = [18, 30, 12, 16, 18]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[chr(64 + index)].width = width

    temp_path = path.with_name(f".{path.stem}.tmp-{dt.datetime.now():%Y%m%d%H%M%S%f}{path.suffix}")
    workbook.save(temp_path)
    workbook.close()
    temp_path.replace(path)
    log(f"申报导入后核对结果已保存：{path}")
    return path


def run_post_import_check(page: Page, org: TaxOrg, target_month: str) -> Path:
    sections = [
        ("综合所得申报", collect_declaration_check(page, "综合所得申报", target_month)),
        ("分类所得申报", collect_declaration_check(page, "分类所得申报", target_month)),
        ("限售股所得申报", collect_declaration_check(page, "限售股所得申报", target_month)),
    ]
    return write_declaration_check_excel(target_month, org, sections)


def input_dirs_for_org(input_root: Path, target_month: str, org_code: str) -> list[Path]:
    legacy_dir = input_root / f"申报表{target_month}" / org_code
    dirs = [input_root]
    if legacy_dir.exists():
        dirs.append(legacy_dir)
    return dirs


def org_file_patterns(org_code: str, suffix_patterns: list[str]) -> list[str]:
    prefixes = [org_code]
    first_five = org_code[:5]
    if first_five and first_five not in prefixes:
        prefixes.append(first_five)
    patterns: list[str] = []
    for prefix in prefixes:
        for suffix in suffix_patterns:
            patterns.append(f"{prefix}*{suffix}")
    return patterns


def build_tasks(org_code: str) -> list[ImportTask]:
    return [
        ImportTask(
            "人员信息采集",
            None,
            org_file_patterns(org_code, ["人员信息采集_员工*.xls", "人员信息采集_员工*.xlsx"]),
            "人员信息采集-员工",
            needs_month=False,
            clear_before_import=False,
        ),
        ImportTask(
            "人员信息采集",
            None,
            org_file_patterns(org_code, ["人员信息采集_客户*.xls", "人员信息采集_客户*.xlsx"]),
            "人员信息采集-客户",
            needs_month=False,
            clear_before_import=False,
        ),
        ImportTask(
            "人员信息采集",
            None,
            org_file_patterns(org_code, ["人员信息采集_实习生*.xls", "人员信息采集_实习生*.xlsx"]),
            "人员信息采集-实习生",
            needs_month=False,
            clear_before_import=False,
        ),
        ImportTask(
            "综合所得申报",
            "正常工资薪金所得",
            org_file_patterns(org_code, ["个税申报表*.xls", "个税申报表*.xlsx"]),
            "综合所得申报-正常工资薪金所得",
            exclude_patterns=["*实习生*"],
        ),
        ImportTask(
            "综合所得申报",
            "劳务报酬",
            org_file_patterns(org_code, ["个税申报_经纪人*.xls", "个税申报_经纪人*.xlsx"]),
            "综合所得申报-劳务报酬（适用累计预扣法）",
        ),
        ImportTask(
            "综合所得申报",
            "劳务报酬",
            org_file_patterns(org_code, ["个税申报表_实习生*.xls", "个税申报表_实习生*.xlsx"]),
            "综合所得申报-劳务报酬（实习生）",
            clear_before_import=False,
        ),
        ImportTask(
            "综合所得申报",
            "解除劳动合同一次性补偿金",
            org_file_patterns(org_code, ["解除劳动合同一次性补偿金*.xls", "解除劳动合同一次性补偿金*.xlsx"]),
            "综合所得申报-解除劳动合同一次性补偿金",
        ),
        ImportTask(
            "综合所得申报",
            "全年一次性奖金",
            org_file_patterns(org_code, ["全年一次性奖金申报表*.xls", "全年一次性奖金申报表*.xlsx"]),
            "综合所得申报-全年一次性奖金",
        ),
        ImportTask(
            "分类所得申报",
            "利息",
            org_file_patterns(org_code, ["利息*股息*红利所得*.xls", "利息*股息*红利所得*.xlsx"]),
            "分类所得申报-利息股息红利所得",
        ),
        ImportTask(
            "限售股所得申报",
            None,
            org_file_patterns(org_code, ["限售股转让所得*.xls", "限售股转让所得*.xlsx"]),
            "限售股所得申报",
            clear_before_import=False,
        ),
    ]


def process_org(
    page: Page,
    org: TaxOrg,
    target_month: str,
    input_root: Path,
    max_wait_seconds: int,
    *,
    progress: dict | None = None,
    resume: bool = False,
) -> Page:
    check_cancelled()
    set_popup_context(org, target_month)
    log("=" * 70)
    log(f"开始处理申报导入：{org.name}（{org.code}）")
    input_dirs = input_dirs_for_org(input_root, target_month, org.code)
    log(f"申报表读取目录：{', '.join(str(path) for path in input_dirs)}")

    progress = progress if progress is not None else {"month": target_month, "completed": {}}
    completed_ids = completed_task_ids(progress, org) if resume else set()
    task_files: list[tuple[ImportTask, Path]] = []
    for task in build_tasks(org.code):
        check_cancelled()
        if task.task_id in completed_ids:
            log(f"续跑跳过已完成任务：{task.label}")
            continue
        file_path = None
        for input_dir in input_dirs:
            file_path = find_one_file(input_dir, task.patterns, task.exclude_patterns)
            if file_path is not None:
                break
        if file_path is None:
            log(f"跳过上传步骤：{task.label}")
            continue
        task_files.append((task, file_path))

    if not task_files:
        log(f"本机构未找到任何可上传文件，跳过机构：{org.name}（{org.code}）")
        return page

    page = ensure_withholding_page(page)
    switch_org(page, org)
    page = ensure_withholding_page(page)

    cleared_scopes: set[tuple[str, str | None]] = set()
    completed_scopes = {
        (task.menu, task.item)
        for task in build_tasks(org.code)
        if task.task_id in completed_ids
    }
    for task, file_path in task_files:
        check_cancelled()
        enter_declaration_page(page, task.menu, task.item, target_month, needs_month=task.needs_month)
        scope = (task.menu, task.item)
        if scope not in cleared_scopes and scope not in completed_scopes:
            clear_existing_data(page, task)
            cleared_scopes.add(scope)
        upload_and_verify(page, file_path, label=task.label, max_wait_seconds=max_wait_seconds)
        mark_task_completed(target_month, org, task, progress)

    run_post_import_check(page, org, target_month)
    log(f"机构申报导入完成：{org.name}（{org.code}）")
    return page


def resolve_orgs(orgs_from_excel: list[TaxOrg], org_code: str | None, org_name: str | None) -> list[TaxOrg]:
    orgs = orgs_from_excel
    if org_code:
        orgs = [org for org in orgs if org.code == org_code]
    if org_name:
        orgs = [org for org in orgs if org.name == org_name or org_name in org.name]
    if not orgs:
        raise RuntimeError(f"没有找到机构：code={org_code or '-'}，name={org_name or '-'}")
    return orgs


def main() -> int:
    parser = argparse.ArgumentParser(description="自然人电子税务局个税申报表批量导入自动化")
    parser.add_argument("--cdp", help="连接当前 Chrome 的 CDP 地址，例如 http://127.0.0.1:9222")
    parser.add_argument("--url", help="可选：启动后自动打开的税务局具体页面地址")
    parser.add_argument("--slow-mo", type=int, default=120, help="每步操作延迟毫秒，方便财务复核")
    parser.add_argument("--max-wait", type=int, default=180, help="单个导入文件最长等待秒数")
    parser.add_argument("--month", default=default_month(), help="税款所属月份，格式 YYYY-MM，例如 2026-06")
    parser.add_argument("--input-root", default=str(INPUT_ROOT), help="申报表根目录，默认当前项目 input")
    parser.add_argument("--org-excel", default=str(DEFAULT_ORG_EXCEL), help="机构信息 Excel 路径")
    parser.add_argument("--org-code", help="只处理指定机构代码，例如 11818；不传则处理全部机构")
    parser.add_argument("--org-name", help="只处理指定机构名称，可填简称，例如 东莞长安")
    parser.add_argument("--start-org-code", help="从指定机构代码开始处理后续机构，例如 11831")
    parser.add_argument("--resume", action="store_true", help="跳过同月份进度文件中已完成的机构，从上次失败处继续")
    parser.add_argument("--reset-progress", action="store_true", help="清除同月份本次机构的历史完成记录，全部重跑")
    parser.add_argument("--yes", action="store_true", help="跳过命令行确认提示")
    parser.add_argument("--keep-tabs", action="store_true", help="CDP 模式下保留其他自然人电子税务局标签页")
    parser.add_argument(
        "--proxy",
        default="system",
        help="代理设置：system 表示使用系统默认；none 表示禁用代理；也可填 http://host:port",
    )
    parser.add_argument("--persistent", action="store_true", help="使用脚本专用持久化 Chrome 配置目录")
    args = parser.parse_args()

    org_excel = Path(args.org_excel).resolve()
    input_root = Path(args.input_root).resolve()
    log(f"目标税款所属月份：{month_label(args.month)}")
    log(f"申报表根目录：{input_root}")

    orgs_from_excel = read_orgs_from_excel(org_excel)
    orgs = resolve_orgs(orgs_from_excel, args.org_code, args.org_name)
    if args.start_org_code:
        start_index = next((i for i, org in enumerate(orgs) if org.code == args.start_org_code), None)
        if start_index is None:
            raise RuntimeError(f"没有找到开始机构代码：{args.start_org_code}")
        orgs = orgs[start_index:]
        log(f"从机构代码 {args.start_org_code} 开始续跑，剩余 {len(orgs)} 个机构")

    if args.reset_progress:
        progress = reset_progress_for_orgs(args.month, orgs)
    else:
        progress = load_progress(args.month)

    completed = progress.setdefault("completed", {})
    completed_orgs = [org for org in orgs if org.code in completed]
    if completed_orgs:
        log(f"检测到同月份已有 {len(completed_orgs)} 个机构完成记录：")
        for org in completed_orgs:
            completed_at = completed.get(org.code, {}).get("completed_at", "")
            log(f"已完成：{org.name}（{org.code}） {completed_at}")

    if args.resume:
        skipped = [org for org in orgs if org.code in completed]
        orgs = [org for org in orgs if org.code not in completed]
        for org in skipped:
            log(f"续跑模式跳过已完成机构：{org.name}（{org.code}）")

    log(f"本次待处理机构数：{len(orgs)}")
    for org in orgs:
        log(f"待处理：{org.name}（{org.code}）")

    if not orgs:
        log("没有需要处理的机构，任务结束")
        return 0

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
            else:
                log(f"沿用当前页面：{page.url}")
            wait_for_user("请确认浏览器已登录自然人电子税务局，并停留在可办理个税业务的页面。", skip=args.yes)

            for org in orgs:
                check_cancelled()
                page = process_org(
                    page,
                    org,
                    args.month,
                    input_root,
                    args.max_wait,
                    progress=progress,
                    resume=args.resume,
                )
                mark_org_completed(args.month, org, progress)

            log("=" * 70)
            log("全部申报导入任务完成")
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
