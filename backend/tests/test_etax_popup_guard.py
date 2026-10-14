from __future__ import annotations

import json

from app.rpa.extensions import etax_popup_guard as module


class FakeButton:
    def __init__(self, popup):
        self.popup = popup
        self.first = self

    def filter(self, **_kwargs):
        return self

    def count(self):
        return 1

    def click(self, **_kwargs):
        self.popup.visible = False


class FakePopup:
    def __init__(self, text: str):
        self.text = text
        self.visible = True

    def inner_text(self, **_kwargs):
        return self.text

    def is_visible(self):
        return self.visible

    def locator(self, _selector):
        return FakeButton(self)

    def get_by_role(self, *_args, **_kwargs):
        return FakeButton(self)


class FakeDialogs:
    def __init__(self, popups):
        self.popups = popups
        self.first = self

    def count(self):
        return len([popup for popup in self.popups if popup.visible])

    def nth(self, index):
        return [popup for popup in self.popups if popup.visible][index]


class FakePage:
    def __init__(self, popups):
        self.popups = popups
        self.url = "https://etax.chinatax.gov.cn/path?secret=value#/route?token=value"
        self.waits = []
        self.events = {}
        self.locator_handler = None
        self.screenshots = []

    def locator(self, _selector):
        return FakeDialogs(self.popups)

    def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)

    def on(self, event, handler):
        self.events[event] = handler

    def add_locator_handler(self, _locator, handler, **_kwargs):
        self.locator_handler = handler

    def screenshot(self, **kwargs):
        self.screenshots.append(kwargs)


def test_guard_defers_unknown_popup_and_records_workflow_resolution(tmp_path):
    unexpected_before_month = FakePopup("系统繁忙额外提醒，请稍后处理")
    workflow_dialog = FakePopup("文件导入 导入结果")
    page = FakePage([unexpected_before_month, workflow_dialog])
    logs = []
    module.set_popup_guard_context(org_code="10001", month="2026-08", task="special_deduction")

    detected = module.drain_unexpected_popups(page, log=logs.append, record_dir=tmp_path, rules=[])

    assert detected == 1
    assert unexpected_before_month.visible is True
    assert workflow_dialog.visible is True
    assert "系统繁忙额外提醒" in logs[0]
    first_record = json.loads((tmp_path / "popup_events.jsonl").read_text(encoding="utf-8").strip())
    assert first_record["event"] == "popup_unknown_detected"
    assert first_record["action"] == "defer_to_workflow"
    assert first_record["org_code"] == "10001"
    assert first_record["month"] == "2026-08"
    assert first_record["task"] == "special_deduction"
    assert first_record["content"] == "系统繁忙额外提醒，请稍后处理"
    assert "secret" not in first_record["url"]

    unexpected_before_month.visible = False
    module.drain_unexpected_popups(page, log=logs.append, record_dir=tmp_path, rules=[])
    records = [json.loads(line) for line in (tmp_path / "popup_events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert records[-1]["event"] == "popup_unknown_resolved"
    assert records[-1]["resolution"] == "workflow"


def test_installed_guard_deduplicates_unknown_popups(tmp_path):
    before = FakePopup("选择月份前提醒")
    page = FakePage([before])

    module.install_popup_guard(page, log=lambda _message: None, record_dir=tmp_path)

    assert before.visible is True
    assert page.waits == []
    assert not (tmp_path / "popup_events.jsonl").exists()
    assert callable(page.locator_handler)
    page.locator_handler()
    assert before.visible is True
    page.locator_handler()
    assert len((tmp_path / "popup_events.jsonl").read_text(encoding="utf-8").splitlines()) == 1

    before.visible = False
    after = FakePopup("选择月份后提醒")
    page.popups.append(after)
    page.locator_handler()
    assert after.visible is True
    assert page.waits == []
    records = [json.loads(line) for line in (tmp_path / "popup_events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [record["event"] for record in records] == [
        "popup_unknown_detected",
        "popup_unknown_resolved",
        "popup_unknown_detected",
    ]


def test_blocking_guard_does_not_close_known_workflow_dialog(tmp_path):
    workflow_dialog = FakePopup("安全验证 导出报表文件")
    page = FakePage([workflow_dialog])

    module.install_popup_guard(page, log=lambda _message: None, record_dir=tmp_path)
    page.locator_handler()

    assert workflow_dialog.visible is True
    assert page.waits == []
    assert not (tmp_path / "popup_events.jsonl").exists()


def test_blocking_guard_runs_known_handler_before_unknown_fallback(tmp_path):
    known = FakePopup("未注册个税APP提醒")
    unexpected = FakePopup("连续出现的额外提醒")
    page = FakePage([known, unexpected])
    handled = []

    def close_known(_page):
        handled.append(known.text)
        known.visible = False
        return 1

    module.install_popup_guard(
        page,
        log=lambda _message: None,
        record_dir=tmp_path,
        known_popup_handler=close_known,
    )
    page.locator_handler()

    assert handled == ["未注册个税APP提醒"]
    assert known.visible is False
    assert unexpected.visible is True
    assert page.waits == []


def test_unknown_popup_stops_only_after_popup_and_progress_timeout(tmp_path):
    popup = FakePopup("无法识别的新提示")
    page = FakePage([popup])
    logs = []

    module.drain_unexpected_popups(page, log=logs.append, record_dir=tmp_path, rules=[])
    entry = next(iter(page._etax_unknown_popups.values()))
    entry["first_seen_monotonic"] -= 61.0
    module._CONTEXT["last_progress_at"] = module.time.monotonic() - 61.0

    try:
        module.drain_unexpected_popups(page, log=logs.append, record_dir=tmp_path, rules=[])
    except RuntimeError as exc:
        assert "超过 60 秒无进展" in str(exc)
    else:
        raise AssertionError("unknown popup watchdog did not stop the blocked workflow")

    records = [json.loads(line) for line in (tmp_path / "popup_events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert records[-1]["event"] == "popup_blocked_timeout"
    assert records[-1]["blocked_seconds"] >= 60.0
    assert page.screenshots


def test_protected_marker_matching_ignores_spaces_between_chinese_characters():
    assert module._is_protected("自 然 人 代 开 发 票 提 醒", ("自然人代开发票提醒",))
