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
