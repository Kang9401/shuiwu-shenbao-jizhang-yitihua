"""Declaration-only blanks; source payroll amounts remain available for reconciliation."""
SPECIAL_ADDITIONAL_COLUMNS = (
    "累计子女教育", "累计继续教育", "累计住房贷款利息", "累计住房租金",
    "累计赡养老人", "累计3岁以下婴幼儿照护", "累计大病医疗",
)


def blank_special_additional(frame):
    result = frame.copy()
    for column in SPECIAL_ADDITIONAL_COLUMNS:
        if column in result.columns:
            result[column] = ""
    return result
