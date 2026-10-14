from __future__ import annotations

from app.schemas.common import ValidationIssue


def missing_columns(columns: list[str], required: list[str]) -> list[ValidationIssue]:
    existing = set(columns)
    return [
        ValidationIssue(issue_type="缺失列", field=column, message=f"缺少必需列：{column}")
        for column in required
        if column not in existing
    ]
