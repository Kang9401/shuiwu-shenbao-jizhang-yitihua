from pathlib import Path

import pytest

from app.rpa.extensions import etax_report_download as report_download


def test_cancel_file_interrupts_report_flow(tmp_path, monkeypatch):
    marker = tmp_path / "cancel"
    marker.write_text("cancelled", encoding="ascii")
    monkeypatch.setenv(report_download.CANCEL_FILE_ENV, str(marker))

    with pytest.raises(report_download.TaskCancelled):
        report_download.check_cancelled()


def test_unfiled_report_skips_without_opening_export(monkeypatch):
    monkeypatch.delenv(report_download.CANCEL_FILE_ENV, raising=False)
    opened = []

    result = report_download.run_report_download(
        object(),
        report_title="分类所得申报表",
        status_text="未申报",
        open_export=lambda: opened.append(True),
        confirm_export=lambda: None,
        download_export=lambda: Path("report.xlsx"),
    )

    assert result is None
    assert opened == []


def test_wait_for_slider_context_retries_until_captcha_iframe_is_ready(monkeypatch):
    monkeypatch.delenv(report_download.CANCEL_FILE_ENV, raising=False)
    expected = object()
    attempts = []

    def find_context(_page):
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("安全验证弹窗中没有找到可见的滑块和滑道")
        return expected

    waits = []
    monkeypatch.setattr(report_download, "find_slider_context", find_context)
    monkeypatch.setattr(report_download, "has_security_dialog", lambda _page: True)
    monkeypatch.setattr(report_download, "interruptible_wait", lambda _page, milliseconds: waits.append(milliseconds))

    assert report_download.wait_for_slider_context(object(), timeout_ms=1000) is expected
    assert waits == [250]
