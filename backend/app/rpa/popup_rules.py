from __future__ import annotations

import copy


POPUP_ACTIONS = {"keep", "close", "click"}
POPUP_TASKS = {
    "all",
    "special_deduction",
    "import",
    "tax_certificate",
    "income_report",
    "extra_income_reports",
    "declaration_reports",
    "tax_certificate_or_income_report",
}

PROTECTED_WORKFLOW_MARKERS = (
    "请选择为哪个单位办税",
    "办理个税业务",
    "安全验证",
    "拖动滑块",
    "导出报表文件",
    "正在生成导出文件",
    "立即进入",
    "导出记录",
    "确认导出",
    "个人所得税扣缴申报表",
    "文件导入",
    "导入文件",
    "导入结果",
    "完税证明",
    "生成零工资",
    "税款计算",
    "清空数据",
    "删除数据",
    "其他窗口进行了单位切换",
)


DEFAULT_POPUP_RULES = [
    {"id": "unregistered-app", "keyword": "未注册个税APP提醒", "task": "all", "action": "close", "button_text": "", "delay_ms": 4000, "enabled": True},
    {"id": "natural-person-invoice", "keyword": "自然人代开发票提醒", "task": "all", "action": "close", "button_text": "", "delay_ms": 4000, "enabled": True},
    {"id": "friendly-reminder-spaced", "keyword": "温 馨 提 示", "task": "all", "action": "close", "button_text": "", "delay_ms": 4000, "enabled": True},
    {"id": "friendly-reminder", "keyword": "温馨提示", "task": "all", "action": "close", "button_text": "", "delay_ms": 4000, "enabled": True},
    {"id": "previous-period-unfiled", "keyword": "上一属期未申报", "task": "all", "action": "close", "button_text": "", "delay_ms": 4000, "enabled": True},
    {"id": "previous-tax-period-unfiled", "keyword": "上一个所属期未申报", "task": "all", "action": "close", "button_text": "", "delay_ms": 4000, "enabled": True},
    {"id": "prior-period-unfiled", "keyword": "上期所属期未申报", "task": "all", "action": "close", "button_text": "", "delay_ms": 4000, "enabled": True},
    {"id": "annual-settlement-tax", "keyword": "综合所得年度汇算补税提醒", "task": "all", "action": "close", "button_text": "", "delay_ms": 4000, "enabled": True},
    {"id": "annual-settlement-incomplete", "keyword": "汇算清缴未完成", "task": "all", "action": "close", "button_text": "", "delay_ms": 4000, "enabled": True},
    {"id": "annual-settlement-not-finished", "keyword": "未完成办理综合所得汇算清缴", "task": "all", "action": "close", "button_text": "", "delay_ms": 4000, "enabled": True},
]


def default_popup_rules() -> list[dict]:
    return copy.deepcopy(DEFAULT_POPUP_RULES)


def _compact(value: object) -> str:
    return "".join(str(value or "").split()).lower()


def is_protected_popup_keyword(keyword: str) -> bool:
    value = _compact(keyword)
    return bool(value) and any(
        value in _compact(marker) or _compact(marker) in value
        for marker in PROTECTED_WORKFLOW_MARKERS
    )


def normalize_popup_rules(rules: list[dict], *, drop_protected: bool = False) -> list[dict]:
    normalized: list[dict] = []
    seen: set[str] = set()
    for index, raw in enumerate(rules):
        rule_id = str(raw.get("id") or f"rule-{index + 1}").strip()
        keyword = str(raw.get("keyword") or "").strip()
        task = str(raw.get("task") or "all").strip()
        action = str(raw.get("action") or "keep").strip()
        button_text = str(raw.get("button_text") or "").strip()
        delay_ms = int(raw.get("delay_ms") or 0)
        if not rule_id or rule_id in seen:
            raise ValueError("弹窗规则标识不能为空且不能重复")
        if not keyword:
            raise ValueError(f"弹窗规则 {rule_id} 的匹配关键字不能为空")
        if is_protected_popup_keyword(keyword):
            if drop_protected:
                continue
            raise ValueError(
                f"弹窗规则 {rule_id} 命中了受保护的原有 RPA 流程，不能配置：{keyword}"
            )
        if task not in POPUP_TASKS:
            raise ValueError(f"弹窗规则 {rule_id} 的适用任务无效")
        if action not in POPUP_ACTIONS:
            raise ValueError(f"弹窗规则 {rule_id} 的处理动作无效")
        if action == "click" and not button_text:
            raise ValueError(f"弹窗规则 {rule_id} 选择点击按钮时必须填写按钮文字")
        if delay_ms < 0 or delay_ms > 10000:
            raise ValueError(f"弹窗规则 {rule_id} 的延迟必须在 0 至 10000 毫秒之间")
        seen.add(rule_id)
        normalized.append({
            "id": rule_id,
            "keyword": keyword,
            "task": task,
            "action": action,
            "button_text": button_text,
            "delay_ms": delay_ms,
            "enabled": bool(raw.get("enabled", True)),
        })
    return normalized
