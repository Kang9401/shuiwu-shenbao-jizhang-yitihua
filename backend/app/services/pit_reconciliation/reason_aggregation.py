from __future__ import annotations

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


@dataclass
class AggregationResult:
    changed: bool
    updated_counts: dict[str, int]
    skipped_manual_fields: int


def _text(value: str | None) -> str:
    return (value or "").strip()


def _can_replace(current: str | None, mode: str) -> bool:
    value = _text(current)
    return not value or (mode == "refresh_generated" and value.startswith(AUTO_PREFIX))


def _render(entries: Iterable[str], *, chinese: bool = False) -> str | None:
    unique: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        value = _text(entry)
        # The reason itself, rather than the presentation prefix, determines deduplication.
        reason = value.rsplit("：", 1)[-1].strip()
        if value and reason not in seen:
            unique.append(value)
            seen.add(reason)
    if not unique:
        return None

    lines = [AUTO_PREFIX]
    for index, entry in enumerate(unique):
        marker = f"{CHINESE_ORDINALS[index]}、" if chinese and index < len(CHINESE_ORDINALS) else f"{index + 1}、"
        line = f"{marker}{entry}"
        remaining = len(unique) - index - 1
        omission = f"……另有{remaining}条原因，请查看明细" if remaining else ""
        candidate = "\n".join([*lines, line] + ([omission] if omission else []))
        if len(candidate) <= MAX_REASON_LENGTH:
            lines.append(line)
            continue
        omitted = len(unique) - index
        notice = f"……另有{omitted}条原因，请查看明细"
        return "\n".join([*lines, notice])
    return "\n".join(lines)


def _apply(target, field: str, generated: str | None, mode: str, result: AggregationResult) -> None:
    if not generated:
        return
    current = getattr(target, field)
    if not _can_replace(current, mode):
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


def aggregate_reasons(db, workpaper, mode: str) -> AggregationResult:
    """Roll detail-level human explanations into PIT check and organization fields."""
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
        if not reason:
            continue
        label = _text(row.person_or_customer_name) or "明细记录"
        detail_entries[(row.org_code, row.detail_type)].append(f"{label}：{reason}")

    # A1/A3/A4 detail explanations fill each corresponding tax-check difference 10 field.
    for (org_code, detail_type), entries in detail_entries.items():
        subject_code = DETAIL_TARGETS.get(detail_type)
        if subject_code:
            check = tax_by_key.get((org_code, subject_code))
            if check:
                _apply(check, "business_declared_manual_reason", _render(entries), mode, result)

    # Organization difference 3 comes directly from A2 human explanations.
    for org_code, summary in summary_by_org.items():
        _apply(summary, "difference_3_manual_reason", _render(detail_entries.get((org_code, "salary_taxable_income"), []), chinese=True), mode, result)

    # The remaining organization fields consolidate the persisted check-level reasons.
    tax_entries: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in tax_checks:
        subject_label = SUBJECT_LABELS.get(row.subject_code, row.subject_name or row.subject_code)
        if _text(row.current_manual_reason):
            tax_entries[(row.org_code, "difference_1")].append(f"{row.subject_code} {subject_label}—差异8：{_text(row.current_manual_reason)}")
        if _text(row.cumulative_manual_reason):
            tax_entries[(row.org_code, "difference_1")].append(f"{row.subject_code} {subject_label}—差异9：{_text(row.cumulative_manual_reason)}")
        if _text(row.business_declared_manual_reason):
            tax_entries[(row.org_code, "difference_2")].append(f"{subject_label}：{_text(row.business_declared_manual_reason)}")
    occurrence_entries: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in occurrences:
        label = SUBJECT_LABELS.get(row.subject_code, row.income_type or row.subject_name or row.subject_code)
        if _text(row.broker_occurrence_manual_reason):
            occurrence_entries[(row.org_code, "difference_6")].append(f"{label}：{_text(row.broker_occurrence_manual_reason)}")
        if _text(row.declared_income_manual_reason):
            occurrence_entries[(row.org_code, "difference_7")].append(f"{label}：{_text(row.declared_income_manual_reason)}")
    for org_code, summary in summary_by_org.items():
        _apply(summary, "difference_1_manual_reason", _render(tax_entries[(org_code, "difference_1")], chinese=True), mode, result)
        _apply(summary, "difference_2_manual_reason", _render(tax_entries[(org_code, "difference_2")], chinese=True), mode, result)
        _apply(summary, "difference_6_manual_reason", _render(occurrence_entries[(org_code, "difference_6")], chinese=True), mode, result)
        _apply(summary, "difference_7_manual_reason", _render(occurrence_entries[(org_code, "difference_7")], chinese=True), mode, result)
    return result
