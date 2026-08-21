from pathlib import Path
import json
import sys


ROOT = Path(__file__).parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.etax_page_probe.compare import compare_snapshots, cross_page_report  # noqa: E402
from tools.etax_page_probe.sanitize import sanitize_html, sanitize_url  # noqa: E402
from tools.etax_page_probe.selector_audit import extract_selectors  # noqa: E402


def test_url_and_html_are_sanitized():
    url = "https://example.test/page?token=secret#/route?sessionId=secret"
    source = '<input value="secret"><p>姓名：张三 13800138000 ￥1,234.00</p><button>下载</button>'

    assert sanitize_url(url) == "https://example.test/page#/route"
    result = sanitize_html(source)
    assert "secret" not in result
    assert "张三" not in result
    assert "13800138000" not in result
    assert "1,234" not in result
    assert "下载" in result


def test_selector_extractor_records_source_function_and_line(tmp_path):
    source = tmp_path / "sample.py"
    source.write_text('def download(page):\n    page.locator(".download").click()\n', encoding="utf-8")

    selectors = extract_selectors([source])

    assert selectors[0].function == "download"
    assert selectors[0].line == 2
    assert selectors[0].selector == ".download"


def test_compare_marks_disappeared_button_and_selector_as_severe(tmp_path):
    baseline, current = tmp_path / "baseline", tmp_path / "current"
    baseline.mkdir()
    current.mkdir()
    (baseline / "frame_tree.json").write_text('[{"path":"top","readable":true}]', encoding="utf-8")
    (current / "frame_tree.json").write_text('[{"path":"top","readable":true}]', encoding="utf-8")
    (baseline / "interactive_elements.json").write_text(
        '[{"frame":"top","recommended_selector":"button.download","tag":"button","text":"下载"}]', encoding="utf-8"
    )
    (current / "interactive_elements.json").write_text("[]", encoding="utf-8")
    audit = [{"source_file":"rpa.py","line":10,"selector":"button.download","status":"ok"}]
    (baseline / "selector_audit.json").write_text(json.dumps(audit), encoding="utf-8")
    audit[0]["status"] = "missing"
    (current / "selector_audit.json").write_text(json.dumps(audit), encoding="utf-8")

    report = compare_snapshots(baseline, current)

    assert report["summary"]["严重"] == 2


def test_cross_page_report_compares_frame_download_and_slider_shapes(tmp_path):
    snapshots = {}
    for label in ("comprehensive", "classified", "restricted"):
        directory = tmp_path / label
        directory.mkdir()
        (directory / "frame_tree.json").write_text('[{"path":"top"}]', encoding="utf-8")
        (directory / "interactive_elements.json").write_text(
            json.dumps(
                [
                    {"text": "下载", "recommended_selector": "button.download", "class": ""},
                    {
                        "text": "",
                        "recommended_selector": ".slider-handle",
                        "class": "slider-handle",
                        "box": {"width": 40},
                    },
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (directory / "structure.json").write_text(
            '[{"slider_event_listeners":{"event_types":["pointerdown"]}}]', encoding="utf-8"
        )
        snapshots[label] = directory

    report = cross_page_report(snapshots)

    assert report["same_frame_paths"] is True
    assert report["same_download_structure"] is True
    assert report["same_slider_structure"] is True
    assert report["same_slider_events"] is True
