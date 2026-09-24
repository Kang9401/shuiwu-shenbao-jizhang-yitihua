from __future__ import annotations

from typing import Any


WITHHOLDING_URL_MARKER = "withholding/index.html"


def ensure_withholding_page(page: Any) -> Any:
    if WITHHOLDING_URL_MARKER in page.url:
        page.bring_to_front()
        return page

    for candidate in page.context.pages:
        if WITHHOLDING_URL_MARKER in candidate.url:
            candidate.bring_to_front()
            return candidate

    entry = page.locator("a.navbar-first-menu", has_text="单位办税")
    visible_entry = entry.filter(visible=True)
    if visible_entry.count() == 0:
        if entry.count() > 0:
            raise RuntimeError(
                "当前登录身份未开放“单位办税”入口。请在自然人电子税务局切换到具有扣缴端权限的单位办税身份，"
                "确认页面可见“单位办税”后再执行 RPA。"
            )
        raise RuntimeError(
            "当前页面未找到“单位办税”入口。请确认已登录自然人电子税务局首页，或先手工打开单位办税扣缴端。"
        )

    context = page.context
    with context.expect_page(timeout=15000) as new_page_info:
        visible_entry.first.click(force=True)
    new_page = new_page_info.value
    new_page.wait_for_load_state("domcontentloaded", timeout=30000)
    new_page.bring_to_front()
    return new_page


def install() -> None:
    import etax_batch_export

    etax_batch_export.ensure_withholding_page = ensure_withholding_page
