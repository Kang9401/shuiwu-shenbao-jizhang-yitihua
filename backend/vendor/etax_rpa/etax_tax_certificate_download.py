import argparse
import base64
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from etax_batch_export import (
    DEFAULT_ORG_EXCEL,
    OUTPUT_DIR,
    TaxOrg,
    click_button,
    click_text,
    close_common_popups,
    close_duplicate_etax_tabs,
    default_month,
    ensure_withholding_page,
    set_tax_month,
    log,
    make_context,
    month_label,
    read_orgs_from_excel,
    set_popup_context,
    switch_org,
    wait_for_user,
)

try:
    from etax_report_download import (
        SLIDER_STRATEGIES,
        TaskCancelled,
        check_cancelled,
        interruptible_wait,
        run_report_download,
        solve_security_challenge,
    )
except ImportError:  # Source-tree execution before runtime synchronization.
    extension_dir = Path(__file__).parents[2] / "app" / "rpa" / "extensions"
    if str(extension_dir) not in sys.path:
        sys.path.insert(0, str(extension_dir))
    from etax_report_download import (  # type: ignore[no-redef]
        SLIDER_STRATEGIES,
        TaskCancelled,
        check_cancelled,
        interruptible_wait,
        run_report_download,
        solve_security_challenge,
    )


CDP_URL = "http://127.0.0.1:9222"
SECURITY_DIALOG_SETTLE_MS = 2000


def safe_filename_part(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|\s]+', "_", value.strip())
    return value.strip("_") or "未命名"


def previous_month(month: str) -> str:
    match = re.fullmatch(r"(\d{4})-(0[1-9]|1[0-2])", month)
    if not match:
        raise ValueError(f"月份格式无效：{month}")
    year, value = map(int, match.groups())
    return f"{year - 1 if value == 1 else year}-{12 if value == 1 else value - 1:02d}"


def certificate_filename(org: TaxOrg, payment_month: str, item: dict) -> str:
    declaration_month = previous_month(payment_month)
    return (
        f"{declaration_month}_"
        f"{safe_filename_part(org.code)}_"
        f"{safe_filename_part(org.name)}_"
        f"个税完税证明_"
        f"{safe_filename_part(item['report_type'])}_"
        f"{item['ticket_suffix']}.pdf"
    )


def comprehensive_report_filename(org: TaxOrg, target_month: str, suggested_filename: str) -> str:
    suffix = Path(suggested_filename).suffix or ".xlsx"
    report_name = safe_filename_part(Path(suggested_filename).stem)
    for identifier in (safe_filename_part(org.code), safe_filename_part(org.name)):
        report_name = report_name.replace(identifier, "")
    report_name = report_name.strip("_-") or "综合所得申报表"
    return (
        f"{target_month}_"
        f"{safe_filename_part(org.code)}_"
        f"{safe_filename_part(org.name)}_"
        f"{report_name}{suffix}"
    )


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for i in range(2, 1000):
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法生成不重复文件名：{path}")


def reusable_or_skip_path(path: Path) -> Path | None:
    if path.exists() and path.stat().st_size > 0:
        log(f"文件已存在，跳过重复下载：{path}")
        return None
    return path


def close_pdf_tabs(page: Page) -> None:
    for tab in list(page.context.pages):
        if tab == page:
            continue
        if tab.url.startswith("blob:") or tab.url == "about:blank":
            try:
                tab.close()
            except Exception:
                pass


def ensure_withholding_menu_open(page: Page) -> None:
    if page.locator(".el-menu-item").filter(has_text="人员信息采集").filter(visible=True).count() > 0:
        return
    title = page.locator(".el-submenu__title").filter(has_text="扣缴申报").filter(visible=True).first
    title.wait_for(state="visible", timeout=10000)
    try:
        title.click()
    except Exception:
        title.click(force=True)
    page.locator(".el-menu-item").filter(has_text="人员信息采集").filter(visible=True).first.wait_for(
        state="visible", timeout=10000
    )
    page.wait_for_timeout(500)


def click_sidebar_item(page: Page, text: str) -> None:
    ensure_withholding_menu_open(page)
    if text == "查询统计":
        submenu = page.locator(".statistics_left.el-submenu").filter(has_text="查询统计").filter(visible=True).first
        submenu.wait_for(state="visible", timeout=10000)
        try:
            opened = "is-opened" in (submenu.get_attribute("class", timeout=1000) or "")
        except Exception:
            opened = False
        if not opened:
            submenu.locator(":scope > .el-submenu__title").click(force=True)
            page.wait_for_timeout(800)
        close_common_popups(page)
        return

    locator = page.locator(".sidebar-container, .el-menu, aside, nav").get_by_text(text, exact=False).filter(visible=True)
    try:
        locator.first.wait_for(state="visible", timeout=8000)
        locator.first.evaluate("el => el.scrollIntoView({block: 'center', inline: 'nearest'})")
        locator.first.click()
    except PlaywrightTimeoutError:
        if text == "缴款记录查询":
            click_sidebar_item(page, "查询统计")
            locator = page.locator(".el-menu-item").filter(has_text=text).filter(visible=True).first
            locator.wait_for(state="visible", timeout=8000)
            locator.evaluate("el => el.scrollIntoView({block: 'center', inline: 'nearest'})")
            page.wait_for_timeout(300)
            locator.click()
        else:
            raw_locator = page.locator(".el-menu-item, .el-submenu__title").filter(has_text=text).filter(visible=True).first
            raw_locator.wait_for(state="visible", timeout=8000)
            raw_locator.evaluate("el => el.scrollIntoView({block: 'center', inline: 'nearest'})")
            page.wait_for_timeout(300)
            raw_locator.click(force=True)
    page.wait_for_timeout(1000)
    close_common_popups(page)


def enter_payment_record_page(page: Page) -> None:
    log("进入：扣缴申报 -> 查询统计 -> 缴款记录查询")
    click_sidebar_item(page, "查询统计")
    click_sidebar_item(page, "缴款记录查询")
    page.wait_for_load_state("domcontentloaded", timeout=20000)
    page.wait_for_timeout(1200)
    close_common_popups(page)
    if "statistics_tax_payment" not in page.url and page.get_by_text("缴款日期", exact=False).filter(visible=True).count() == 0:
        log("菜单点击后未进入缴款记录查询，使用页面路由兜底进入")
        page.evaluate("location.hash = '#/withholding/statistics_home/statistics_tax_payment'")
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        page.wait_for_timeout(1800)
        close_common_popups(page)
    page.get_by_text("缴款日期", exact=False).filter(visible=True).first.wait_for(state="visible", timeout=15000)


def fill_month_input(input_locator, value: str) -> None:
    try:
        input_locator.fill(value, timeout=3000)
        input_locator.press("Enter", timeout=1000)
        return
    except Exception:
        pass
    input_locator.evaluate(
        """(el, value) => {
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
            setter.call(el, value);
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }""",
        value,
    )


def set_payment_month_and_query(page: Page, target_month: str) -> None:
    log(f"设置缴款日期起止月份：{target_month} 至 {target_month}")
    if page.get_by_text("缴款日期", exact=False).filter(visible=True).count() == 0:
        enter_payment_record_page(page)
    inputs = page.locator("input.el-input__inner").filter(visible=True)
    if inputs.count() < 2:
        raise RuntimeError("找不到缴款日期起止输入框")
    fill_month_input(inputs.nth(0), target_month)
    fill_month_input(inputs.nth(1), target_month)
    page.wait_for_timeout(500)
    page.get_by_role("button", name="查询", exact=True).click()
    page.wait_for_timeout(2500)
    close_common_popups(page)


def extract_payment_rows(page: Page) -> list[dict]:
    rows = page.locator(".el-table__body-wrapper tbody tr, .el-table__row").filter(visible=True)
    results: list[dict] = []
    seen: set[str] = set()
    for i in range(rows.count()):
        row = rows.nth(i)
        text = row.inner_text(timeout=2000)
        ticket_match = re.search(r"\b(\d{18})\b", text)
        if not ticket_match:
            continue
        ticket = ticket_match.group(1)
        if ticket in seen:
            continue
        cells = [cell.strip() for cell in row.locator("td").all_inner_texts()]
        report_type = next((cell for cell in cells if "表" in cell), "")
        if not report_type:
            report_type = next((line.strip() for line in text.splitlines() if "表" in line), "未知报表")
        seen.add(ticket)
        results.append(
            {
                "row": row,
                "report_type": report_type,
                "ticket": ticket,
                "ticket_suffix": ticket[-4:],
                "text": text,
            }
        )
    log(f"查询结果有效缴款记录数：{len(results)}")
    return results


def clear_row_selection(rows: list[dict]) -> None:
    for item in rows:
        checkbox = item["row"].locator(".el-checkbox__input").first
        try:
            cls = checkbox.get_attribute("class", timeout=1000) or ""
            if "is-checked" in cls:
                checkbox.click(force=True)
        except Exception:
            continue


def select_row(item: dict) -> None:
    checkbox = item["row"].locator(".el-checkbox__input").first
    checkbox.evaluate("el => el.scrollIntoView({block: 'center', inline: 'nearest'})")
    cls = checkbox.get_attribute("class", timeout=1000) or ""
    if "is-checked" not in cls:
        checkbox.click(force=True)


def install_pdf_blob_hook(page: Page) -> None:
    page.evaluate(
        """() => {
            window.__capturedPdfBlobs = [];
            if (window.__pdfBlobHookInstalled) {
                return;
            }
            window.__pdfBlobHookInstalled = true;
            const originalCreateObjectURL = URL.createObjectURL.bind(URL);
            URL.createObjectURL = function(obj) {
                try {
                    if (obj && typeof obj.arrayBuffer === "function") {
                        obj.arrayBuffer().then(buffer => {
                            const bytes = new Uint8Array(buffer);
                            let binary = "";
                            const chunkSize = 0x8000;
                            for (let i = 0; i < bytes.length; i += chunkSize) {
                                binary += String.fromCharCode(...bytes.slice(i, i + chunkSize));
                            }
                            window.__capturedPdfBlobs.push({
                                type: obj.type || "",
                                size: obj.size || bytes.length,
                                data: btoa(binary)
                            });
                        }).catch(error => {
                            window.__capturePdfBlobError = String(error);
                        });
                    }
                } catch (error) {
                    window.__capturePdfBlobError = String(error);
                }
                return originalCreateObjectURL(obj);
            };
        }"""
    )


def clear_captured_pdf_blobs(page: Page) -> None:
    try:
        page.evaluate("() => { window.__capturedPdfBlobs = []; window.__capturePdfBlobError = ''; }")
    except Exception:
        pass


def save_captured_pdf_blob(page: Page, target: Path, timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    blob_count = 0
    while time.monotonic() < deadline:
        blob_count = page.evaluate("() => window.__capturedPdfBlobs ? window.__capturedPdfBlobs.length : 0")
        if blob_count > 0:
            break
        page.wait_for_timeout(1000)
    if blob_count == 0:
        error = page.evaluate("() => window.__capturePdfBlobError || ''")
        raise TimeoutError(f"超过 {timeout_seconds} 秒仍未捕获到 PDF Blob；页面错误：{error}")

    encoded = page.evaluate("() => window.__capturedPdfBlobs[window.__capturedPdfBlobs.length - 1].data")
    data = base64.b64decode(encoded)
    if not data.startswith(b"%PDF"):
        raise RuntimeError("捕获到的内容不是 PDF")
    target.write_bytes(data)


def download_certificate_for_row(page: Page, org: TaxOrg, payment_month: str, item: dict) -> Path:
    report_type = item["report_type"]
    ticket_suffix = item["ticket_suffix"]
    filename = certificate_filename(org, payment_month, item)
    target = reusable_or_skip_path(OUTPUT_DIR / filename)
    if target is None:
        return OUTPUT_DIR / filename
    last_error: Exception | None = None

    for attempt in range(1, 4):
        check_cancelled()
        try:
            interruptible_wait(page, 1000)
            log(f"下载完税证明：{report_type}，电子税票后四位：{ticket_suffix}，第 {attempt} 次")
            current_rows = extract_payment_rows(page)
            current = next((row for row in current_rows if row["ticket"] == item["ticket"]), item)
            clear_row_selection(current_rows)
            select_row(current)
            install_pdf_blob_hook(page)
            clear_captured_pdf_blobs(page)
            interruptible_wait(page, 1000)
            with page.expect_response(lambda response: "/web/dkdj/levy/kjsbsk/wszmkj" in response.url, timeout=30000):
                page.get_by_role("button", name="完税证明", exact=True).click()
                confirm = page.locator(".el-message-box__wrapper:visible, .el-dialog:visible").filter(has_text="确定")
                confirm.first.wait_for(state="visible", timeout=10000)
                interruptible_wait(page, 1000)
                confirm.first.get_by_role("button", name="确定", exact=True).click()

            save_captured_pdf_blob(page, target)
            close_pdf_tabs(page)
            log(f"已保存完税证明：{target}")
            return target
        except TaskCancelled:
            raise
        except Exception as exc:
            last_error = exc
            log(f"本次下载未成功，准备重试：{exc}")
            close_common_popups(page)
            close_pdf_tabs(page)
            interruptible_wait(page, 3000)

    raise RuntimeError(f"完税证明下载失败：{report_type}，电子税票后四位：{ticket_suffix}") from last_error


def enter_comprehensive_income_page(page: Page, target_month: str) -> None:
    log("进入：扣缴申报 -> 综合所得申报")
    page = ensure_withholding_page(page)
    click_sidebar_item(page, "综合所得申报")
    page.wait_for_load_state("domcontentloaded", timeout=20000)
    page.wait_for_timeout(1500)
    close_common_popups(page)
    if (
        not is_comprehensive_income_overview_url(page.url)
        or page.get_by_text("税款所属月份", exact=False).filter(visible=True).count() == 0
    ):
        log("菜单点击后未进入综合所得申报，使用页面路由兜底进入")
        page.evaluate("location.hash = '#/withholding/income_declaration'")
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        page.wait_for_timeout(1800)
        close_common_popups(page)
    if not is_comprehensive_income_overview_url(page.url):
        raise RuntimeError(f"未进入综合所得申报总览页，当前页面：{page.url}")
    page.get_by_text("税款所属月份", exact=False).filter(visible=True).first.wait_for(
        state="visible", timeout=15000
    )
    set_tax_month(page, target_month)


def is_comprehensive_income_overview_url(url: str) -> bool:
    route = urlsplit(url).fragment.split("?", 1)[0].rstrip("/")
    return route == "/withholding/income_declaration"


def visible_comprehensive_income_status(page: Page) -> str:
    for status in ("申报成功", "未申报", "申报失败", "申报处理中", "待申报", "未完成"):
        if page.get_by_text(status, exact=True).filter(visible=True).count() > 0:
            return status
    return "未显示申报成功状态"


def open_withholding_report_export(page: Page) -> bool:
    log("点击导出 -> 个人所得税扣缴申报表")
    close_common_popups(page)
    if not is_comprehensive_income_overview_url(page.url):
        raise RuntimeError(f"当前不是综合所得申报总览页，无法导出申报表：{page.url}")
    export_button = page.locator(".dropdown-export button, button", has_text="导出").filter(visible=True).first
    try:
        export_button.wait_for(state="visible", timeout=15000)
    except PlaywrightTimeoutError as exc:
        status = visible_comprehensive_income_status(page)
        if status == "申报成功":
            raise RuntimeError("综合所得申报状态为“申报成功”，但页面没有显示导出按钮") from exc
        log(f"综合所得申报状态为“{status}”，没有申报成功记录，正常跳过")
        return False
    export_button.click()
    item = page.locator(".el-dropdown-menu:visible .el-dropdown-menu__item", has_text="个人所得税扣缴申报表").first
    item.wait_for(state="visible", timeout=10000)
    item.click()
    # Allow the security dialog and slider iframe to finish rendering.
    page.wait_for_timeout(SECURITY_DIALOG_SETTLE_MS)
    return True


def solve_report_export_security(page: Page, max_attempts: int = 5) -> None:
    solve_security_challenge(
        page,
        lambda: open_withholding_report_export(page),
        strategies=SLIDER_STRATEGIES[:max_attempts],
        success_check=lambda: has_visible_confirm_export(page),
        log=log,
    )


def export_confirmation_dialog(page: Page):
    return page.locator(".el-message-box__wrapper:visible, .el-dialog:visible").filter(
        has_text="确定", has_not_text="安全验证"
    )


def has_visible_confirm_export(page: Page) -> bool:
    return export_confirmation_dialog(page).count() == 1


def confirm_report_export(page: Page) -> None:
    dialogs = export_confirmation_dialog(page)
    dialogs.first.wait_for(state="visible", timeout=20000)
    if dialogs.count() != 1:
        raise RuntimeError(f"导出确认弹窗不是唯一匹配：{dialogs.count()}")
    confirm = dialogs.first
    buttons = confirm.get_by_role("button", name="确定", exact=True).filter(visible=True)
    if buttons.count() != 1:
        raise RuntimeError(f"导出确认按钮不是唯一匹配：{buttons.count()}")
    buttons.first.click()
    log("已确认导出个人所得税扣缴申报表")

    message_box = page.locator(".el-message-box__wrapper:visible, .el-dialog:visible").filter(
        has_text="正在生成导出文件"
    ).first
    message_box.wait_for(state="visible", timeout=30000)
    message_box.locator("button.el-button--primary", has_text="立即进入").first.click()
    page.wait_for_load_state("domcontentloaded", timeout=20000)
    page.wait_for_timeout(1500)
    log("已进入查看导出记录页面")


def download_latest_export_record(page: Page, org: TaxOrg, target_month: str, max_attempts: int = 20) -> Path:
    log("等待综合所得申报表导出记录处理成功")
    row_locator = page.locator(".el-table__body-wrapper tbody tr, .el-table__row").filter(visible=True)
    last_text = ""
    for attempt in range(1, max_attempts + 1):
        check_cancelled()
        try:
            row_locator.first.wait_for(state="visible", timeout=10000)
            row = row_locator.first
            last_text = row.inner_text(timeout=3000)
            log(f"导出记录第 {attempt} 次检查：{last_text[:120].replace(chr(10), ' | ')}")
            if "处理成功" in last_text:
                OUTPUT_DIR.mkdir(exist_ok=True)
                with page.expect_download(timeout=30000) as download_info:
                    row.get_by_text("下载", exact=False).first.click()
                download = download_info.value
                target = unique_path(
                    OUTPUT_DIR
                    / comprehensive_report_filename(org, target_month, download.suggested_filename)
                )
                download.save_as(str(target))
                log(f"已下载综合所得申报表：{target}")
                return target
        except Exception as exc:
            log(f"暂未找到可下载的成功记录：{exc}")

        if attempt < max_attempts:
            log("处理未完成，等待5秒后刷新")
            interruptible_wait(page, 5000)
            try:
                click_button(page, "刷新", exact=False, timeout=3000)
            except Exception:
                page.reload(wait_until="domcontentloaded", timeout=20000)

    raise TimeoutError(f"综合所得申报表导出记录未处理成功，最后状态：{last_text[:200]}")


def download_comprehensive_income_report(page: Page, org: TaxOrg, target_month: str) -> Path | None:
    interruptible_wait(page, 1000)
    enter_comprehensive_income_page(page, target_month)
    interruptible_wait(page, 1000)
    status_text = visible_comprehensive_income_status(page)

    def open_export() -> None:
        if not open_withholding_report_export(page):
            raise RuntimeError("综合所得申报状态与导出按钮不一致")

    return run_report_download(
        page,
        report_title=f"{org.name}（{org.code}）综合所得申报表",
        status_text=status_text,
        open_export=open_export,
        confirm_export=lambda: confirm_report_export(page),
        download_export=lambda: download_latest_export_record(page, org, target_month),
        success_check=lambda: has_visible_confirm_export(page),
        log=log,
    )


def process_org(page: Page, org: TaxOrg, target_month: str, task: str = "all") -> tuple[Page, list[Path]]:
    check_cancelled()
    set_popup_context(org, target_month)
    log("=" * 70)
    if task in {"all", "tax_certificate"}:
        log(f"开始下载完税证明：{org.name}（{org.code}）")
    if task in {"all", "income_report"}:
        log(f"开始下载综合所得申报表：{org.name}（{org.code}）")
    page = ensure_withholding_page(page)
    switch_org(page, org)
    page = ensure_withholding_page(page)
    close_pdf_tabs(page)
    downloaded: list[Path] = []
    certificate_count = 0

    if task in {"all", "tax_certificate"}:
        enter_payment_record_page(page)
        page.wait_for_timeout(1000)
        set_payment_month_and_query(page, target_month)
        page.wait_for_timeout(1000)

        rows = extract_payment_rows(page)
        if not rows:
            log(f"未查询到缴款记录，跳过完税证明下载：{org.name}（{org.code}）")
        else:
            for row in rows:
                check_cancelled()
                current_rows = extract_payment_rows(page)
                current = next((item for item in current_rows if item["ticket"] == row["ticket"]), row)
                downloaded.append(download_certificate_for_row(page, org, target_month, current))
                certificate_count += 1
                page.wait_for_timeout(1000)
        log(f"机构完税证明下载完成：{org.name}（{org.code}），共 {certificate_count} 个文件")

    if task in {"all", "income_report"}:
        income_report = download_comprehensive_income_report(page, org, target_month)
        if income_report is not None:
            downloaded.append(income_report)
        log(f"机构综合所得申报表下载完成：{org.name}（{org.code}），共 {int(income_report is not None)} 个文件")

    if task == "all":
        log(f"机构完税证明及综合所得申报表下载完成：{org.name}（{org.code}），共 {len(downloaded)} 个文件")
    return page, downloaded


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
    parser = argparse.ArgumentParser(description="自然人电子税务局完税证明批量下载自动化")
    parser.add_argument("--cdp", default=CDP_URL, help="连接当前 Chrome 的 CDP 地址，例如 http://127.0.0.1:9222")
    parser.add_argument("--url", help="可选：启动后自动打开的税务局具体页面地址")
    parser.add_argument("--slow-mo", type=int, default=120, help="每步操作延迟毫秒，方便财务复核")
    parser.add_argument("--month", default=default_month(), help="缴款日期月份，格式 YYYY-MM，例如 2026-06")
    parser.add_argument("--org-excel", default=str(DEFAULT_ORG_EXCEL), help="机构信息 Excel 路径")
    parser.add_argument("--org-code", help="只处理指定机构代码，例如 11818；不传则处理全部机构")
    parser.add_argument("--org-name", help="只处理指定机构名称，可填简称，例如 东莞长安")
    parser.add_argument("--start-org-code", help="从指定机构代码开始处理后续机构，例如 11831")
    parser.add_argument("--yes", action="store_true", help="跳过命令行确认提示")
    parser.add_argument("--keep-tabs", action="store_true", help="CDP 模式下保留其他自然人电子税务局标签页")
    parser.add_argument("--proxy", default="system", help="代理设置：system/none/http://host:port")
    parser.add_argument("--persistent", action="store_true", help="使用脚本专用持久化 Chrome 配置目录")
    parser.add_argument(
        "--task",
        choices=["all", "tax_certificate", "income_report"],
        default="all",
        help="执行子任务：all=完税证明+综合所得申报表，tax_certificate=仅完税证明，income_report=仅综合所得申报表",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)
    org_excel = Path(args.org_excel).resolve()
    orgs = resolve_orgs(read_orgs_from_excel(org_excel), args.org_code, args.org_name)
    if args.start_org_code:
        start_index = next((i for i, org in enumerate(orgs) if org.code == args.start_org_code), None)
        if start_index is None:
            raise RuntimeError(f"没有找到开始机构代码：{args.start_org_code}")
        orgs = orgs[start_index:]
        log(f"从机构代码 {args.start_org_code} 开始续跑，剩余 {len(orgs)} 个机构")
    log(f"输出目录：{OUTPUT_DIR}")
    log(f"目标缴款日期月份：{month_label(args.month)}")
    log(f"本次待处理机构数：{len(orgs)}")
    for org in orgs:
        log(f"待处理：{org.name}（{org.code}）")

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

            all_downloaded: list[Path] = []
            for org in orgs:
                check_cancelled()
                page, downloaded = process_org(page, org, args.month, args.task)
                all_downloaded.extend(downloaded)

            log("=" * 70)
            log(f"全部完税证明下载任务完成，共 {len(all_downloaded)} 个文件")
            for path in all_downloaded:
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
