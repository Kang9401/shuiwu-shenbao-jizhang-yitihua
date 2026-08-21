from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SEVERITY_ORDER = {"严重": 0, "警告": 1, "信息": 2}


def load_json(directory: Path, name: str, default: Any) -> Any:
    path = directory / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def add(changes: list[dict[str, Any]], severity: str, category: str, message: str, **details: Any) -> None:
    changes.append({"severity": severity, "category": category, "message": message, **details})


def compare_frames(baseline: Path, current: Path, changes: list[dict[str, Any]]) -> None:
    before = {item["path"]: item for item in load_json(baseline, "frame_tree.json", [])}
    after = {item["path"]: item for item in load_json(current, "frame_tree.json", [])}
    for path in sorted(before.keys() - after.keys()):
        add(changes, "严重", "iframe", f"iframe 已删除或移动：{path}")
    for path in sorted(after.keys() - before.keys()):
        add(changes, "严重", "iframe", f"新增 iframe：{path}")
    for path in sorted(before.keys() & after.keys()):
        left, right = before[path], after[path]
        if left.get("src") != right.get("src"):
            add(changes, "警告", "iframe", f"iframe 地址变化：{path}", before=left.get("src"), current=right.get("src"))
        if left.get("readable") != right.get("readable"):
            add(changes, "严重", "iframe", f"iframe DOM 可访问性变化：{path}")
        if left.get("visible") != right.get("visible"):
            add(changes, "警告", "iframe", f"iframe 可见性变化：{path}")


def element_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (str(item.get("frame") or "top"), str(item.get("recommended_selector") or item.get("tag") or ""), str(item.get("text") or ""))


def compare_elements(baseline: Path, current: Path, changes: list[dict[str, Any]]) -> None:
    before_items = load_json(baseline, "interactive_elements.json", [])
    after_items = load_json(current, "interactive_elements.json", [])
    before = {element_key(item): item for item in before_items}
    after = {element_key(item): item for item in after_items}
    important = {"button", "table", "iframe", "canvas"}
    for key in sorted(before.keys() - after.keys()):
        item = before[key]
        severity = "严重" if item.get("tag") in important or "滑块" in str(item.get("text")) else "警告"
        add(changes, severity, "element", f"元素消失：{key[1]} @ {key[0]}", selector=key[1])
    for key in sorted(after.keys() - before.keys()):
        item = after[key]
        severity = "警告" if item.get("tag") in important else "信息"
        add(changes, severity, "element", f"新增元素：{key[1]} @ {key[0]}", selector=key[1])
    for key in sorted(before.keys() & after.keys()):
        left, right = before[key], after[key]
        if left.get("visible") and not right.get("visible"):
            add(changes, "严重", "element", f"元素从可见变为隐藏：{key[1]} @ {key[0]}")
        if left.get("pointer_events") != right.get("pointer_events"):
            add(changes, "警告", "element", f"pointer-events 变化：{key[1]} @ {key[0]}", before=left.get("pointer_events"), current=right.get("pointer_events"))
        if left.get("touch_action") != right.get("touch_action"):
            add(changes, "警告", "element", f"touch-action 变化：{key[1]} @ {key[0]}", before=left.get("touch_action"), current=right.get("touch_action"))
        if left.get("box") != right.get("box") and ("slider" in key[1].lower() or "slide" in key[1].lower()):
            add(changes, "警告", "slider", f"滑块或滑道尺寸/坐标变化：{key[1]}", before=left.get("box"), current=right.get("box"))


def audit_key(item: dict[str, Any]) -> tuple[str, int, str]:
    return (str(item.get("source_file") or ""), int(item.get("line") or 0), str(item.get("selector") or ""))


def compare_audit(baseline: Path, current: Path, changes: list[dict[str, Any]]) -> None:
    before = {audit_key(item): item for item in load_json(baseline, "selector_audit.json", [])}
    after = {audit_key(item): item for item in load_json(current, "selector_audit.json", [])}
    for key, item in after.items():
        prior = before.get(key)
        status = item.get("status")
        if status in {"missing", "multiple", "wrong_frame", "covered"} and (not prior or prior.get("status") == "ok"):
            add(
                changes,
                "严重",
                "selector",
                f"RPA 选择器异常：{key[2]} -> {status}",
                source_file=key[0],
                line=key[1],
                suggested_selector=item.get("suggested_selector"),
                evidence=item.get("evidence"),
            )
        elif status in {"hidden", "stale"} and (not prior or prior.get("status") == "ok"):
            add(changes, "警告", "selector", f"RPA 选择器状态变化：{key[2]} -> {status}", source_file=key[0], line=key[1])


def compare_dialogs(baseline: Path, current: Path, changes: list[dict[str, Any]]) -> None:
    before = {(item.get("frame"), item.get("title"), tuple(item.get("buttons", []))) for item in load_json(baseline, "dialogs.json", [])}
    after = {(item.get("frame"), item.get("title"), tuple(item.get("buttons", []))) for item in load_json(current, "dialogs.json", [])}
    for frame, title, buttons in sorted(after - before):
        add(changes, "严重", "dialog", f"出现新弹窗：{title or '<无标题>'} @ {frame}", buttons=list(buttons))
    for frame, title, _buttons in sorted(before - after):
        add(changes, "信息", "dialog", f"原弹窗未再出现：{title or '<无标题>'} @ {frame}")


def compare_snapshots(baseline: Path, current: Path) -> dict[str, Any]:
    changes: list[dict[str, Any]] = []
    compare_frames(baseline, current, changes)
    compare_elements(baseline, current, changes)
    compare_audit(baseline, current, changes)
    compare_dialogs(baseline, current, changes)
    changes.sort(key=lambda item: (SEVERITY_ORDER[item["severity"]], item["category"], item["message"]))
    return {
        "baseline": str(baseline),
        "current": str(current),
        "baseline_screenshot": str(baseline / "screenshot.png"),
        "current_screenshot": str(current / "screenshot.png"),
        "summary": {severity: sum(item["severity"] == severity for item in changes) for severity in SEVERITY_ORDER},
        "changes": changes,
    }


def markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# 税务局页面结构差异报告",
        "",
        f"- 基线：`{report['baseline']}`",
        f"- 当前：`{report['current']}`",
        f"- 严重：{summary['严重']}；警告：{summary['警告']}；信息：{summary['信息']}",
        f"- 基线截图：`{report['baseline_screenshot']}`",
        f"- 当前截图：`{report['current_screenshot']}`",
        "",
    ]
    for severity in ("严重", "警告", "信息"):
        lines.extend((f"## {severity}", ""))
        selected = [item for item in report["changes"] if item["severity"] == severity]
        if not selected:
            lines.append("无。")
        for item in selected:
            suffix = ""
            if item.get("source_file"):
                suffix = f"（{item['source_file']}:{item.get('line', 0)}）"
            lines.append(f"- [{item['category']}] {item['message']}{suffix}")
        lines.append("")
    return "\n".join(lines)


def cross_page_report(snapshots: dict[str, Path]) -> dict[str, Any]:
    pages: dict[str, Any] = {}
    for label, directory in snapshots.items():
        elements = load_json(directory, "interactive_elements.json", [])
        structures = load_json(directory, "structure.json", [])
        slider_events = next((item["slider_event_listeners"] for item in structures if "slider_event_listeners" in item), {})
        sliders = [
            item for item in elements
            if any(token in str(item.get("recommended_selector", "")).lower() for token in ("slider", "slide", "captcha"))
        ]
        downloads = [item for item in elements if any(token in str(item.get("text", "")) for token in ("下载", "导出"))]
        overlays = [
            item for item in elements
            if any(token in str(item.get("class", "")).lower() for token in ("mask", "overlay", "modal"))
        ]
        audit = load_json(directory, "selector_audit.json", [])
        pages[label] = {
            "snapshot": str(directory),
            "frames": [item.get("path") for item in load_json(directory, "frame_tree.json", [])],
            "download_selectors": sorted({item.get("recommended_selector") for item in downloads}),
            "slider_selectors": sorted({item.get("recommended_selector") for item in sliders}),
            "slider_boxes": [item.get("box") for item in sliders],
            "slider_touch_actions": sorted({item.get("touch_action") for item in sliders}),
            "slider_event_types": slider_events.get("event_types", []),
            "overlay_count": len(overlays),
            "dialogs": [item.get("title") for item in load_json(directory, "dialogs.json", [])],
            "selector_failures": [item for item in audit if item.get("status") != "ok"],
        }
    values = list(pages.values())
    return {
        "pages": pages,
        "same_frame_paths": len({json.dumps(item["frames"], ensure_ascii=False) for item in values}) <= 1,
        "same_download_structure": len({json.dumps(item["download_selectors"], ensure_ascii=False) for item in values}) <= 1,
        "same_slider_structure": len({json.dumps(item["slider_selectors"], ensure_ascii=False) for item in values}) <= 1,
        "same_slider_events": len({json.dumps(item["slider_event_types"], ensure_ascii=False) for item in values}) <= 1,
    }


def cross_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 三类申报结果页面横向对比",
        "",
        f"- iframe 路径一致：{'是' if report['same_frame_paths'] else '否'}",
        f"- 下载按钮结构一致：{'是' if report['same_download_structure'] else '否'}",
        f"- 滑块结构一致：{'是' if report['same_slider_structure'] else '否'}",
        f"- 滑块事件类型一致：{'是' if report['same_slider_events'] else '否'}",
        "",
        "| 页面 | iframe | 下载选择器 | 滑块选择器 | 事件 | 遮罩 | 异常选择器 |",
        "|---|---:|---:|---:|---|---:|---:|",
    ]
    for label, item in report["pages"].items():
        lines.append(
            f"| {label} | {len(item['frames'])} | {len(item['download_selectors'])} | "
            f"{len(item['slider_selectors'])} | {', '.join(item['slider_event_types']) or '-'} | "
            f"{item['overlay_count']} | {len(item['selector_failures'])} |"
        )
    lines.extend(("", "详细机器可读数据见同名 JSON 文件。"))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two e-tax page snapshots")
    parser.add_argument("--baseline")
    parser.add_argument("--current")
    parser.add_argument("--snapshot", action="append", default=[], help="横向对比项，格式 label=directory")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if args.snapshot:
        snapshots = {}
        for value in args.snapshot:
            label, separator, directory = value.partition("=")
            if not separator or not label or not directory:
                parser.error("--snapshot 必须使用 label=directory 格式")
            snapshots[label] = Path(directory).resolve()
        report = cross_page_report(snapshots)
        render = cross_markdown
    else:
        if not args.baseline or not args.current:
            parser.error("纵向比较需要 --baseline 和 --current")
        report = compare_snapshots(Path(args.baseline).resolve(), Path(args.current).resolve())
        render = markdown
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".json":
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        output.with_suffix(".md").write_text(render(report), encoding="utf-8")
    else:
        output.write_text(render(report), encoding="utf-8")
        output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
