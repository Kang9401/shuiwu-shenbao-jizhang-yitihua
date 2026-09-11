from types import SimpleNamespace

import pytest

from app.rpa import service as service_module
from app.rpa.service import RpaService
from app.rpa.state_store import StateStore


class FakeQuery:
    def __init__(self, values):
        self.values = values

    def filter(self, *args):
        return self

    def order_by(self, *args):
        return self

    def all(self):
        return self.values


class FakeDb:
    def __init__(self, jobs, artifacts):
        self.responses = iter((jobs, artifacts))

    def query(self, *args):
        return FakeQuery(next(self.responses))


def make_service(tmp_path, monkeypatch):
    app = tmp_path / "app"
    (app / "input").mkdir(parents=True)
    (app / "output").mkdir()
    monkeypatch.setattr(service_module, "ensure_runtime_app", lambda: app)
    return RpaService(store=StateStore(tmp_path / "state.json")), app


def test_prepare_from_period_copies_latest_artifacts_without_renaming(tmp_path, monkeypatch):
    service, app = make_service(tmp_path, monkeypatch)
    source = tmp_path / "11818_3-个税申报表(2026年06月).xlsx"
    source.write_bytes(b"workbook")
    job = SimpleNamespace(id=9, workflow_code="general_salary_tax")
    artifact = SimpleNamespace(job_id=9, artifact_type="declaration", file_name=source.name, stored_path=str(source))

    result = service.prepare_from_period(FakeDb([job], [artifact]), 1, False)

    assert [item["name"] for item in result] == [source.name]
    assert (app / "input" / source.name).read_bytes() == b"workbook"


def test_prepare_from_period_rejects_conflicting_existing_file_without_partial_copy(tmp_path, monkeypatch):
    service, app = make_service(tmp_path, monkeypatch)
    source = tmp_path / "11818_个税申报表.xlsx"
    source.write_bytes(b"new")
    (app / "input" / source.name).write_bytes(b"old")
    job = SimpleNamespace(id=9, workflow_code="general_salary_tax")
    artifact = SimpleNamespace(job_id=9, artifact_type="declaration", file_name=source.name, stored_path=str(source))

    with pytest.raises(FileExistsError):
        service.prepare_from_period(FakeDb([job], [artifact]), 1, False)

    assert (app / "input" / source.name).read_bytes() == b"old"


def test_status_adds_new_task_column_to_existing_results(tmp_path, monkeypatch):
    service, _ = make_service(tmp_path, monkeypatch)
    state = service.store.read()
    state["results"] = {"2026-06": {"11818": {"name": "机构A", "special_deduction": "成功 1笔"}}}
    service.store.write(state)
    monkeypatch.setattr(service, "chrome_status", lambda: {"status": "stopped"})

    result = service.get_status(refresh_chrome=False)

    row = result["results"][0]
    assert row["extra_income_reports"] == "待处理"
    assert row["special_deduction"] == "成功 1笔"


def test_start_chrome_waits_until_cdp_is_ready(tmp_path, monkeypatch):
    service, app = make_service(tmp_path, monkeypatch)
    chrome = tmp_path / "chrome.exe"
    chrome.touch()
    statuses = iter(({"status": "stopped"}, {"status": "stopped"}, {"status": "ready"}))
    monkeypatch.setattr(service, "chrome_status", lambda: next(statuses))
    launched = []
    monkeypatch.setattr(service_module.subprocess, "Popen", lambda command, **kwargs: launched.append((command, kwargs)) or SimpleNamespace(poll=lambda: None))
    monkeypatch.setattr(service_module.time, "sleep", lambda _seconds: None)

    result = service.start_chrome(str(chrome))

    assert result["message"].startswith("已启动可接管的 Chrome")
    assert launched[0][0][0] == str(chrome)
    assert launched[0][1]["shell"] is False
    assert (app / ".chrome-debug-profile").is_dir()


def test_cancel_requested_between_composite_subtasks_prevents_next_process(tmp_path, monkeypatch):
    service, app = make_service(tmp_path, monkeypatch)
    state = service.store.read()
    state["current_run"].update(
        task_key="declaration_reports",
        subtask_key="income_report",
        display_name="申报结果下载",
        month="2026-06",
        started_at="2026-08-04T10:00:00+09:00",
        status="stopping",
        current_org_code=None,
    )
    service.store.write(state)
    service._composite = {
        "app_dir": app,
        "month": "2026-06",
        "all_orgs": True,
        "org_code": None,
        "start_org_code": None,
    }
    service._cancel_requested = True
    monkeypatch.setattr(service, "_sync_output_files", lambda: None)

    def unexpected_start(*_args, **_kwargs):
        raise AssertionError("取消后不应启动第二个子任务")

    monkeypatch.setattr(service.manager, "start", unexpected_start)

    service._handle_exit(0, False)

    assert service.store.read()["current_run"]["status"] == "cancelled"
    assert service._composite is None


def test_resume_reconciliation_is_restored_before_runtime_output_cleanup(tmp_path, monkeypatch):
    service, app = make_service(tmp_path, monkeypatch)
    configured = tmp_path / "configured-output"
    configured.mkdir()
    workbook = configured / "2026-08个税申报核对.xlsx"
    workbook.write_bytes(b"existing-sheets")
    state = service.store.read()
    state["config"]["output_path"] = str(configured)
    service.store.write(state)

    preserved = service._restore_resume_reconciliation("2026-08")

    assert preserved == {workbook.name}
    assert (app / "output" / workbook.name).read_bytes() == b"existing-sheets"
