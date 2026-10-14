import importlib.util
from pathlib import Path


_START_PATH = Path(__file__).resolve().parents[2] / "start.py"
_SPEC = importlib.util.spec_from_file_location("tax_workbench_start", _START_PATH)
start = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(start)


def test_port_selection_uses_preferred_port_when_available():
    port = start.find_available_port(0, range(45000, 45001))
    assert port == 0


def test_backend_reload_is_opt_in():
    assert "--reload" not in start.backend_command(8000, False)
    assert "--reload" in start.backend_command(8000, True)


def test_frontend_command_receives_selected_port():
    command = start.frontend_command(5175)
    assert command[-1] == "5175"
