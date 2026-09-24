from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from app.models.pit_reconciliation import (
    PitOccurrenceCheck,
    PitReconciliationDifferenceDetail,
    PitReconciliationOrgSummary,
    PitTaxAmountCheck,
)


AUTO_PREFIX = "【自动汇总】"
MAX_REASON_LENGTH = 4000
CHINESE_ORDINALS = "一二三四五六七八九十"
DETAIL_TARGETS = {
    "salary_tax": "21510006",
    "bond_interest_tax": "21510008",
    "restricted_stock_tax": "21510009",
}
SUBJECT_LABELS = {
    "21510006": "工资薪金",
    "21510008": "债券利息",
    "21510009": "限售股",
    "21510016": "证券经纪人",
}
_NUMBER_PREFIX = re.compile(r"^(?:[一二三四五六七八九十]+、|\d+[、.)）])\s*")


@dataclass
class AggregationResult:
    changed: bool
    updated_counts: dict[str, int]
    skipped_manual_fields: int


def _text(value: str | None) -> str:
    return (value or "").strip()


def is_generated_reason(value: str | None) -> bool:
    return _text(value).startswith(AUTO_PREFIX)


def can_auto_replace(value: str | None, mode: str = "refresh_generated") -> bool:
    return not _text(value) or (mode == "refresh_generated" and is_generated_reason(value))


def parse_generated_reason(value: str | None) -> list[str]:
    """Return user-meaningful entries without automatic headers or numbering."""
    text = _text(value)
    if not is_generated_reason(text):
        return [text] if text else []
    entries: list[str] = []
    for line in text.removeprefix(AUTO_PREFIX).splitlines():
        item = _NUMBER_PREFIX.sub("", line.strip())
        # Legacy automatic values could be nested by an older aggregation pass.
        # Treat their presentation header as metadata, never as a new reason item.
        if not item or item.startswith("……另有") or AUTO_PREFIX in item:
            continue
        # A grouped automatic reason has standalone category headers.
        if "：" not in item and ":" not in item:
            continue
        entries.append(item)
    return entries


def generated_reason_count(value: str | None) -> int:
    return len(parse_generated_reason(value))


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _dedupe_key(value: str) -> str:
    return _normalize(value.rsplit("：", 1)[-1].rsplit(":", 1)[-1])


def _fit(lines: list[str], next_line: str, remaining: int) -> bool:
    notice = f"……另有{remaining}条原因，请查看明细" if remaining else ""
    return len("\n".join([*lines, next_line] + ([notice] if notice else []))) <= MAX_REASON_LENGTH


def _render(entries: Iterable[str], *, chinese: bool = False) -> str | None:
    unique: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        value = _text(entry)
        key = _dedupe_key(value)
        if value and key not in seen:
            unique.append(value)
            seen.add(key)
    if not unique:
        return None

    lines = [AUTO_PREFIX]
    for index, entry in enumerate(unique):
        marker = f"{CHINESE_ORDINALS[index]}、" if chinese and index < len(CHINESE_ORDINALS) else f"{index + 1}、"
        line = f"{marker}{entry}"
        if _fit(lines, line, len(unique) - index - 1):
            lines.append(line)
            continue
        return "\n".join([*lines, f"……另有{len(unique) - index}条原因，请查看明细"])
    return "\n".join(lines)


def _render_grouped(groups: Iterable[tuple[str, Iterable[str]]]) -> str | None:
    normalized_groups: list[tuple[str, list[str]]] = []
    for label, entries in groups:
        unique: list[str] = []
        seen: set[str] = set()
        for entry in entries:
            value = _text(entry)
            key = _dedupe_key(value)
            if value and key not in seen:
                unique.append(value)
                seen.add(key)
        if unique:
            normalized_groups.append((label, unique))
    if not normalized_groups:
        return None

    total = sum(len(entries) for _, entries in normalized_groups)
    rendered = 0
    lines = [AUTO_PREFIX]
    for group_index, (label, entries) in enumerate(normalized_groups):
        heading = f"{CHINESE_ORDINALS[group_index] if group_index < len(CHINESE_ORDINALS) else group_index + 1}、{label}"
        if _fit(lines, heading, total - rendered):
            lines.append(heading)
        else:
            return "\n".join([*lines, f"……另有{total - rendered}条原因，请查看明细"])
        for item_index, entry in enumerate(entries):
            line = f"{item_index + 1}）{entry}"
            if _fit(lines, line, total - rendered - 1):
                lines.append(line)
                rendered += 1
                continue
            return "\n".join([*lines, f"……另有{total - rendered}条原因，请查看明细"])
    return "\n".join(lines)


def _reason_items(value: str | None) -> list[str]:
    return parse_generated_reason(value) if is_generated_reason(value) else ([_text(value)] if _text(value) else [])


def _apply(target, field: str, generated: str | None, mode: str, result: AggregationResult) -> None:
    if not generated:
        return
    current = getattr(target, field)
    if not can_auto_replace(current, mode):
        result.skipped_manual_fields += 1
        return
    if _text(current) == generated:
        return
    setattr(target, field, generated)
    if isinstance(target, PitTaxAmountCheck):
        result.updated_counts["tax_checks"] += 1
    elif isinstance(target, PitOccurrenceCheck):
        result.updated_counts["occurrence_checks"] += 1
    else:
        result.updated_counts["org_summaries"] += 1
    result.changed = True


def aggregate_reasons(db, workpaper, mode: str = "refresh_generated") -> AggregationResult:
    """Roll human detail explanations upward without nesting generated text."""
    result = AggregationResult(False, {"tax_checks": 0, "occurrence_checks": 0, "org_summaries": 0}, 0)
    details = db.query(PitReconciliationDifferenceDetail).filter_by(workpaper_id=workpaper.id).order_by(
        PitReconciliationDifferenceDetail.org_code,
        PitReconciliationDifferenceDetail.detail_type,
        PitReconciliationDifferenceDetail.person_or_customer_name,
        PitReconciliationDifferenceDetail.identity_key,
    ).all()
    tax_checks = db.query(PitTaxAmountCheck).filter_by(workpaper_id=workpaper.id).order_by(
        PitTaxAmountCheck.org_code, PitTaxAmountCheck.subject_code,
    ).all()
    occurrences = db.query(PitOccurrenceCheck).filter_by(workpaper_id=workpaper.id).order_by(
        PitOccurrenceCheck.org_code, PitOccurrenceCheck.subject_code,
    ).all()
    summaries = db.query(PitReconciliationOrgSummary).filter_by(workpaper_id=workpaper.id).order_by(
        PitReconciliationOrgSummary.org_code,
    ).all()
    tax_by_key = {(row.org_code, row.subject_code): row for row in tax_checks}
    summary_by_org = {row.org_code: row for row in summaries}

    detail_entries: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in details:
        reason = _text(row.manual_reason)
        if reason:
            detail_entries[(row.org_code, row.detail_type)].append(f"{_text(row.person_or_customer_name) or '明细记录'}：{reason}")

    for (org_code, detail_type), entries in detail_entries.items():
        subject_code = DETAIL_TARGETS.get(detail_type)
        check = tax_by_key.get((org_code, subject_code)) if subject_code else None
        if check:
            _apply(check, "business_declared_manual_reason", _render(entries), mode, result)

    for org_code, summary in summary_by_org.items():
        _apply(summary, "difference_3_manual_reason", _render(detail_entries[(org_code, "salary_taxable_income")], chinese=True), mode, result)

    difference_1: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    difference_2: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for row in tax_checks:
        label = SUBJECT_LABELS.get(row.subject_code, row.subject_name or row.subject_code)
        for reason in _reason_items(row.current_manual_reason):
            difference_1[row.org_code][label].append(f"差异8：{reason}")
        for reason in _reason_items(row.cumulative_manual_reason):
            difference_1[row.org_code][label].append(f"差异9：{reason}")
        for reason in _reason_items(row.business_declared_manual_reason):
            difference_2[row.org_code][label].append(reason)

    difference_6: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    difference_7: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for row in occurrences:
        label = SUBJECT_LABELS.get(row.subject_code, row.income_type or row.subject_name or row.subject_code)
        difference_6[row.org_code][label].extend(_reason_items(row.broker_occurrence_manual_reason))
        difference_7[row.org_code][label].extend(_reason_items(row.declared_income_manual_reason))

    for org_code, summary in summary_by_org.items():
        _apply(summary, "difference_1_manual_reason", _render_grouped(difference_1[org_code].items()), mode, result)
        _apply(summary, "difference_2_manual_reason", _render_grouped(difference_2[org_code].items()), mode, result)
        _apply(summary, "difference_6_manual_reason", _render_grouped(difference_6[org_code].items()), mode, result)
        _apply(summary, "difference_7_manual_reason", _render_grouped(difference_7[org_code].items()), mode, result)
    return result
