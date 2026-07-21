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
    close_common_popups,
    close_duplicate_etax_tabs,
    default_month,
    ensure_withholding_page,
    log,
    make_context,
    month_label,
    read_orgs_from_excel,
    set_tax_month,
    switch_org,
    wait_for_user,
)


INPUT_ROOT = WORK_DIR / "input"


class ImportTask:
    def __init__(
        self,
        menu: str,
        item: str | None,
        patterns: list[str],
        label: str,
        *,
        needs_month: bool = True,
    ) -> None:
        self.menu = menu
        self.item = item
        self.patterns = patterns
        self.label = label
        self.needs_month = needs_month


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
        page.wait_for_timeout(5000)

    raise TimeoutError(f"超过 {max_wait_seconds} 秒仍未看到导入成功：{filename}；最后状态：{last_status}")


def progress_file_for_month(target_month: str) -> Path:
    return OUTPUT_DIR / f"import_progress_{target_month}.json"


def load_progress(target_month: str) -> dict:
    path = progress_file_for_month(target_month)
    if not path.exists():
        return {"month": target_month, "completed": {}}
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception as exc:
        log(f"读取进度文件失败，将忽略旧进度：{path}；原因：{exc}")
        return {"month": target_month, "completed": {}}
    if not isinstance(data, dict):
        return {"month": target_month, "completed": {}}
    data.setdefault("month", target_month)
    data.setdefault("completed", {})
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
    for org in orgs:
        completed.pop(org.code, None)
    save_progress(target_month, progress)
    log("已按用户选择清除本次机构的历史完成记录，将全部重跑")
    return progress


def mark_org_completed(target_month: str, org: TaxOrg, progress: dict) -> None:
    completed = progress.setdefault("completed", {})
    completed[org.code] = {
        "name": org.name,
        "code": org.code,
        "completed_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_progress(target_month, progress)
    log(f"已记录机构完成状态：{org.name}（{org.code}）")


def find_one_file(base_dir: Path, patterns: list[str]) -> Path | None:
    if not base_dir.exists():
        log(f"未找到申报表目录，跳过该目录下文件匹配：{base_dir}")
        return None

    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(base_dir.glob(pattern))
    matches = sorted({path.resolve() for path in matches if path.is_file()}, key=lambda p: p.name)
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


def extract_summary_table(page: Page) -> list[dict[str, str]]:
    tables = page.locator(".el-table").filter(visible=True)
    for table_index in range(tables.count()):
        table = tables.nth(table_index)
        text = table.inner_text(timeout=3000)
        if all(header in text for header in ["所得项目", "填写人次", "收入合计", "应补/退税额"]):
            rows = table.locator("tbody tr, .el-table__row").filter(visible=True)
            results: list[dict[str, str]] = []
            for i in range(rows.count()):
                cells = [cell.strip() for cell in rows.nth(i).locator("td").all_inner_texts()]
                cells = [cell for cell in cells if cell and cell != "暂无数据"]
                if len(cells) < 4:
                    continue
                results.append(
                    {
                        "所得项目": cells[0],
                        "填写人次": cells[1],
                        "收入合计（元）": cells[2],
                        "应补/退税额（元）": cells[3],
                    }
                )
            return results
    return []


def extract_restricted_share_summary(page: Page) -> list[dict[str, str]]:
    rows = page.locator(".el-table__body-wrapper tbody tr, .el-table__row").filter(visible=True)
    person_count = 0
    income_total = 0.0
    tax_total = 0.0
    for i in range(rows.count()):
        cells = [cell.strip() for cell in rows.nth(i).locator("td").all_inner_texts()]
        if not cells or any("暂无数据" in cell for cell in cells):
            continue
        person_count += 1
        if len(cells) >= 18:
            income_total += parse_amount(cells[10])
            tax_total += parse_amount(cells[-1])
    if person_count == 0:
        log("限售股所得申报无明细数据，本次不写入核对表")
        return []
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
        rows = extract_summary_table(page)
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

    workbook.save(path)
    workbook.close()
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
        ),
        ImportTask(
            "人员信息采集",
            None,
            org_file_patterns(org_code, ["人员信息采集_客户*.xls", "人员信息采集_客户*.xlsx"]),
            "人员信息采集-客户",
            needs_month=False,
        ),
        ImportTask(
            "综合所得申报",
            "正常工资薪金所得",
            org_file_patterns(org_code, ["个税申报表*.xls", "个税申报表*.xlsx"]),
            "综合所得申报-正常工资薪金所得",
        ),
        ImportTask(
            "综合所得申报",
            "劳务报酬",
            org_file_patterns(org_code, ["个税申报_经纪人*.xls", "个税申报_经纪人*.xlsx"]),
            "综合所得申报-劳务报酬（适用累计预扣法）",
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
        ),
    ]


def process_org(page: Page, org: TaxOrg, target_month: str, input_root: Path, max_wait_seconds: int) -> Page:
    log("=" * 70)
    log(f"开始处理申报导入：{org.name}（{org.code}）")
    input_dirs = input_dirs_for_org(input_root, target_month, org.code)
    log(f"申报表读取目录：{', '.join(str(path) for path in input_dirs)}")

    task_files: list[tuple[ImportTask, Path]] = []
    for task in build_tasks(org.code):
        file_path = None
        for input_dir in input_dirs:
            file_path = find_one_file(input_dir, task.patterns)
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

    for task, file_path in task_files:
        enter_declaration_page(page, task.menu, task.item, target_month, needs_month=task.needs_month)
        upload_and_verify(page, file_path, label=task.label, max_wait_seconds=max_wait_seconds)

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
                page = process_org(page, org, args.month, input_root, args.max_wait)
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
