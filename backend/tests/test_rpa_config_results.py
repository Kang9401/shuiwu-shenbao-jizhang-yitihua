from app.rpa import service as service_module
from app.rpa.service import RpaService
from app.rpa.state_store import StateStore


class FakeManager:
    def __init__(self, running=False):
        self.running = running


def test_rpa_config_uses_custom_input_and_output_paths(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    (app_dir / "input").mkdir(parents=True)
    (app_dir / "output").mkdir()
    monkeypatch.setattr(service_module, "ensure_runtime_app", lambda: app_dir)
    store = StateStore(tmp_path / "state.json")
    service = RpaService(store=store, manager=FakeManager())
    input_dir = tmp_path / "custom-input"
    output_dir = tmp_path / "custom-output"

    config = service.save_config("chrome.exe", str(input_dir), str(output_dir))
    assert config["input_path"] == str(input_dir.resolve())
    assert config["output_path"] == str(output_dir.resolve())

    service.upload_import_files([("10001_申报.xlsx", b"data")], overwrite=False)
    assert (input_dir / "10001_申报.xlsx").read_bytes() == b"data"
    (output_dir / "result.xlsx").write_bytes(b"result")
    assert service.list_output_files()[0]["name"] == "result.xlsx"


def test_rpa_results_can_reset_by_month(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    (app_dir / "input").mkdir(parents=True)
    (app_dir / "output").mkdir()
    monkeypatch.setattr(service_module, "ensure_runtime_app", lambda: app_dir)
    store = StateStore(tmp_path / "state.json")
    store.update(lambda data: data["results"].update({"2026-06": {"10001": {"name": "机构一"}}, "2026-07": {"10002": {"name": "机构二"}}}))
    service = RpaService(store=store, manager=FakeManager())

    result = service.reset_results("2026-06")
    assert all(row["month"] == "2026-07" for row in result["results"])
    assert "2026-06" not in store.read()["results"]

