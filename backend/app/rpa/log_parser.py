from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class LogEvent:
    kind: str
    org_code: str | None = None
    org_name: str | None = None
    count: int | None = None
    category: str | None = None
    status: str | None = None
    reason: str | None = None


START_PATTERNS = [
    r"开始处理单位：(.+?)（(\d+)）",
    r"开始处理申报导入：(.+?)（(\d+)）",
    r"开始下载完税证明：(.+?)（(\d+)）",
    r"开始下载综合所得申报表：(.+?)（(\d+)）",
    r"开始下载扩展申报表：(.+?)（(\d+)）",
]


def parse_log_line(line: str, task_key: str | None, current_org_code: str | None = None) -> list[LogEvent]:
    events: list[LogEvent] = []
    marker = re.search(r"\[RPA_RESULT\]\s+org_code=(\S+)\s+category=(\S+)\s+status=(\S+)\s+count=(\d+)(?:\s+reason=(\S+))?", line)
    if marker:
        events.append(LogEvent("result", marker.group(1), count=int(marker.group(4)), category=marker.group(2), status=marker.group(3), reason=marker.group(5)))
    for pattern in START_PATTERNS:
        match = re.search(pattern, line)
        if match:
            events.append(LogEvent("start", match.group(2), match.group(1)))
            current_org_code = match.group(2)
            break
    if task_key == "special_deduction" and "单位处理完成：" in line and current_org_code:
        events.append(LogEvent("done", current_org_code, count=1))
    if task_key == "import" and "文件导入成功：" in line and current_org_code:
        events.append(LogEvent("increment", current_org_code, count=1))
    if task_key == "import" and "机构申报导入完成：" in line and current_org_code:
        events.append(LogEvent("done", current_org_code))
    tax = re.search(r"机构(?:完税证明及综合所得申报表|完税证明)下载完成：.+?（(\d+)），共 (\d+) 个文件", line)
    if task_key == "tax_certificate" and tax:
        events.append(LogEvent("done", tax.group(1), count=int(tax.group(2))))
    income = re.search(r"机构综合所得申报表下载完成：.+?（(\d+)），共 (\d+) 个文件", line)
    if task_key == "income_report" and income:
        events.append(LogEvent("done", income.group(1), count=int(income.group(2))))
    extra = re.search(r"机构扩展申报表下载完成：.+?（(\d+)），共 (\d+) 个文件", line)
    if task_key == "extra_income_reports" and extra:
        events.append(LogEvent("done", extra.group(1), count=int(extra.group(2))))
    if task_key == "tax_certificate" and current_org_code and (
        "未查询到缴款记录，跳过机构：" in line or "未查询到缴款记录，跳过完税证明下载：" in line
    ):
        events.append(LogEvent("done", current_org_code, count=0))
    return events
