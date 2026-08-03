# 工资薪金、经纪人申报与个税 RPA 修改实施报告

## 1. 文档用途与基线

本文档供 Codex 在本地仓库直接实施修改，不是业务需求概述。应以最新 Pull Request 的代码为基线：

- 仓库：`Kang9401/shuiwu-shenbao-jizhang-yitihua`
- Pull Request：`#1`
- 基线提交：`14a4f7b058a0580c58ffe3f0a82b188832c2acd8`
- 提交说明：`feat: extend finance AI and RPA workflows`

本次共处理 9 项需求。建议只修改本文列出的文件和相邻测试，不要顺带重构其他申报流程。

> 重要说明：当前会话中没有找到用户提到的“经纪人工资表”附件，因此第 6 项已经写出可直接落地的稳健取数方法，但“申报收入究竟是直接取某一列，还是应发工资减增值税”仍须本地 Codex 打开原始工资表确认。不能在未看原表时继续硬编码公式。

---

## 2. 当前代码问题结论

| 需求 | 当前代码问题 | 主要修改位置 |
|---|---|---|
| 1. 职级、营销统一取数 | 两类工资分别走 `load_rank_payroll` 和 `load_marketing_style_payroll`；营销“本期免税收入”被固定为 0；专项扣除正式列没有从营销工资带入 | `backend/app/services/verification.py` |
| 2. 仅员工号变动 | 主匹配键是“员工号+姓名”，纯员工号变化可能形成入职、离职；姓名+机构兜底只补证件信息，不更新本月人员主数据 | `verification.py`、`tax.py`、`personnel_master.py`、前端报告 |
| 3. 专项扣除缺失机构不阻断 | “重复人员”和“缺失机构”都进入阻断数量；且当前以金额合计为 0 判断缺失，可能把真实零扣除误认为缺失数据 | `verification.py`、`TaxDeclaration.vue` |
| 4. 生成页一键清空 | `resetAll()` 只清浏览器内存，后端生成文件和最新结果仍存在，刷新后会恢复 | `tax.py`、`api.ts`、`TaxDeclaration.vue` |
| 5. 开始申报跳转 RPA | 生成完成页没有“开始申报”动作，也没有向 `App.vue` 发出导航事件 | `TaxDeclaration.vue`、`App.vue` |
| 6. 经纪人工资取数 | 只认精确列名 `员工编号`、`应发工资(补足前)`、`增值税`；列名轻微差异会静默取 0；公式固定为两列相减 | `backend/app/services/formulas.py` |
| 7. RPA ZIP 无法使用 | 后端只打包但不做 CRC/完整性校验；前端触发下载后立即 `revokeObjectURL`，桌面 WebView 下可能产生空文件或截断文件 | `backend/app/rpa/service.py`、`frontend/src/views/EtaxRpa.vue` |
| 8. 运行日志位置 | 应用日志和 RPA 日志分开；RPA 每次运行会清空 `current.log`，没有按运行留存；部分被 API 捕获的异常未写入 `app.log` | `core/logging.py`、`rpa/service.py`、各 API |
| 9. 文件夹自动识别 | 前端只按“职级工资、营销工资”等关键词识别，没有按文件名中的“5位/7位”识别 | `TaxDeclaration.vue` |

---

## 3. 统一业务口径

### 3.1 工资薪金取数优先级

职级和营销必须使用同一个加载函数、同一份字段别名表。两者只保留“文件分类标签”的差别，不再保留金额取数差别。

统一后的核心字段：

| 目标字段 | 可接受源列名（按优先级） |
|---|---|
| 员工编号 | `员工编号`、`员工编码`、`人员编号`、`工号` |
| 姓名 | `*姓名`、`姓名`、`员工姓名`、`员工姓名CN` |
| 机构代码 | `机构代码`、`单位编号`、`单位编码`、`分支机构代码` |
| 应发工资 | `本期收入`、`应发合计 SUM`、`应发合计`、现有四个“应发工资…”公式列 |
| 调增应纳税所得额 | `调增应纳税所得额 SUM`、`调增应纳税所得额` |
| 本期免税收入 | `本期免税收入 SUM`、`本期免税收入`、`免税支出 SUM`、`免税支出` |
| 养老保险 | `基本养老保险费`、`养老(个人部分)`、`养老保险金的员工部分 SUM`、`养老保险金的员工部分` |
| 医疗保险 | `基本医疗保险费`、`医疗(个人部分)`、`医疗保险金的员工部分 SUM`、`医疗保险金的员工部分` |
| 失业保险 | `失业保险费`、`失业(个人部分)`、`失业保险金的员工部分 SUM`、`失业保险金的员工部分` |
| 住房公积金 | `住房公积金`、`公积金(个人部分)`、`公积金（个人部分）`、`住房公积金的员工部分 SUM`、`住房公积金的员工部分` |
| 企业年金 | `企业(职业)年金`、`企业年金(个人部分)`、`企业年金（个人部分）`、`企业年金的员工部分 SUM`、`企业年金的员工部分` |
| 商业健康保险 | `商业健康保险`、`商业保险扣除 SUM`、`商业保险扣除`、`累计商业保险扣除` |
| 本期应预扣预缴税额 | `本期应预扣预缴税额 SUM`、`本期应预扣预缴税额` |
| 个人所得税 | `个人所得税 SUM`、`个人所得税` |

统一公式保持：

```text
本期收入 = 应发工资 + 调增应纳税所得额
个税差异 = 本期应预扣预缴税额 - 个人所得税
```

### 3.2 专项附加扣除来源优先级

建议采用以下明确规则：

1. 工资表中存在七项明细列时，先作为申报值的默认值，同时保留 `工资单_...` 对账列。
2. 上传了独立专项附加扣除文件且人员匹配成功时，独立文件覆盖工资表默认值。
3. `年累计专项附加扣除金额` 只有总数，无法拆分为七项，不能把总数塞进任意一个专项扣除申报列；仅保留在底稿用于核对。
4. 独立专项扣除文件没有覆盖某营业部时只提示，不阻断；重复人员仍阻断。

七项明细映射：

| 申报列 | 工资表候选列 |
|---|---|
| 累计子女教育 | `累计子女教育`、`累计当月子女教育附加扣除`、`累计子女教育附加扣除` |
| 累计继续教育 | `累计继续教育`、`累计当月继续教育附加扣除`、`累计继续教育附加扣除` |
| 累计住房贷款利息 | `累计住房贷款利息`、`累计当月住房贷款利息附加扣除`、`累计住房贷款利息附加扣除` |
| 累计住房租金 | `累计住房租金`、`累计当月住房租金附加扣除`、`累计住房租金附加扣除` |
| 累计赡养老人 | `累计赡养老人`、`累计当月赡养老人附加扣除`、`累计赡养老人附加扣除` |
| 累计3岁以下婴幼儿照护 | `累计3岁以下婴幼儿照护`、`累计当月婴幼儿照护费用附加扣除`、`累计婴幼儿照护费用附加扣除` |
| 累计个人养老金 | `累计个人养老金` |

---

## 4. 修改要求 1：职级与营销使用同一取数逻辑

### 4.1 修改文件

- `backend/app/services/verification.py`
- `backend/tests/test_transformation_requirements.py`
- 必要时补充 `backend/tests/test_verification.py`

### 4.2 后端实施方法

保留 `load_headquarters_payroll()` 独立；将 `load_rank_payroll()` 和 `load_marketing_style_payroll()` 合并为 `load_employee_payroll()`。

建议先增加统一别名常量：

```python
EMPLOYEE_PAYROLL_FIELD_ALIASES = {
    "员工编号": ("员工编号", "员工编码", "人员编号", "工号"),
    "*姓名": ("*姓名", "姓名", "员工姓名", "员工姓名CN"),
    "机构代码": ("机构代码", "单位编号", "单位编码", "分支机构代码"),
    "应发工资": (
        "本期收入",
        "应发合计 SUM",
        "应发合计",
        "应发工资 I=A+B+C+D+E-F-G+H+J+K+A10",
        "应发工资 I=A+B+D-F-G9+K",
        "应发工资H=A+B+J",
        "应发工资H=A+B+E+I+J+K-A8",
    ),
    "调增应纳税所得额": ("调增应纳税所得额 SUM", "调增应纳税所得额"),
    "本期免税收入": ("本期免税收入 SUM", "本期免税收入", "免税支出 SUM", "免税支出"),
    "住房公积金": (
        "住房公积金",
        "公积金(个人部分)",
        "公积金（个人部分）",
        "住房公积金的员工部分 SUM",
        "住房公积金的员工部分",
    ),
    "基本养老保险费": (
        "基本养老保险费",
        "养老(个人部分)",
        "养老保险金的员工部分 SUM",
        "养老保险金的员工部分",
    ),
    "基本医疗保险费": (
        "基本医疗保险费",
        "医疗(个人部分)",
        "医疗保险金的员工部分 SUM",
        "医疗保险金的员工部分",
    ),
    "失业保险费": (
        "失业保险费",
        "失业(个人部分)",
        "失业保险金的员工部分 SUM",
        "失业保险金的员工部分",
    ),
    "企业(职业)年金": (
        "企业(职业)年金",
        "企业年金(个人部分)",
        "企业年金（个人部分）",
        "企业年金的员工部分 SUM",
        "企业年金的员工部分",
    ),
    "商业健康保险": (
        "商业健康保险",
        "商业保险扣除 SUM",
        "商业保险扣除",
        "累计商业保险扣除",
    ),
    "本期应预扣预缴税额 SUM": ("本期应预扣预缴税额 SUM", "本期应预扣预缴税额"),
    "个人所得税 SUM": ("个人所得税 SUM", "个人所得税"),
}

PAYROLL_DEDUCTION_ALIASES = {
    "累计子女教育": ("累计子女教育", "累计当月子女教育附加扣除", "累计子女教育附加扣除"),
    "累计继续教育": ("累计继续教育", "累计当月继续教育附加扣除", "累计继续教育附加扣除"),
    "累计住房贷款利息": ("累计住房贷款利息", "累计当月住房贷款利息附加扣除", "累计住房贷款利息附加扣除"),
    "累计住房租金": ("累计住房租金", "累计当月住房租金附加扣除", "累计住房租金附加扣除"),
    "累计赡养老人": ("累计赡养老人", "累计当月赡养老人附加扣除", "累计赡养老人附加扣除"),
    "累计3岁以下婴幼儿照护": (
        "累计3岁以下婴幼儿照护",
        "累计当月婴幼儿照护费用附加扣除",
        "累计婴幼儿照护费用附加扣除",
    ),
    "累计个人养老金": ("累计个人养老金",),
}
```

统一读取函数建议实现为：

```python
def _read_employee_payroll(file_path: str) -> pd.DataFrame:
    first = pd.read_excel(file_path, dtype=str)
    recognized = {"员工编号", "员工编码", "人员编号", "工号"}
    if recognized.intersection(first.columns):
        return first

    raw = pd.read_excel(file_path, header=None, dtype=str)
    markers = {"员工编号", "员工编码", "人员编号", "工号", "所在部门"}
    for row_index, row in raw.iterrows():
        values = {_clean_text(value) for value in row.tolist()}
        if values.intersection(markers):
            return pd.read_excel(file_path, skiprows=int(row_index), dtype=str)
    return first


def load_employee_payroll(
    file_path: str,
    taxpayer_org_map: dict[str, str] | None = None,
    duplicate_taxpayer_ids: set[str] | None = None,
) -> pd.DataFrame:
    source = _read_employee_payroll(file_path)
    columns = source.columns.tolist()
    result = pd.DataFrame(index=source.index)

    employee_id_col = _first_col(columns, *EMPLOYEE_PAYROLL_FIELD_ALIASES["员工编号"])
    name_col = _first_col(columns, *EMPLOYEE_PAYROLL_FIELD_ALIASES["*姓名"])
    org_col = _first_col(columns, *EMPLOYEE_PAYROLL_FIELD_ALIASES["机构代码"])

    result["员工编号"] = _normalize_emp_id(source[employee_id_col]) if employee_id_col else ""
    result["*姓名"] = source[name_col].map(_clean_text) if name_col else ""
    result["机构代码"] = (
        source[org_col].map(normalize_org_code)
        if org_col
        else pd.Series("", index=source.index, dtype=object)
    )
    _apply_payroll_org_mapping(
        result, source, columns, taxpayer_org_map, duplicate_taxpayer_ids
    )

    for target, aliases in EMPLOYEE_PAYROLL_FIELD_ALIASES.items():
        if target in {"员工编号", "*姓名", "机构代码"}:
            continue
        source_col = _first_col(columns, *aliases)
        result[target] = _to_numeric(source[source_col]) if source_col else 0

    # 七项专项扣除：正式申报列先取工资表；独立专项文件匹配成功后再覆盖。
    for target, aliases in PAYROLL_DEDUCTION_ALIASES.items():
        source_col = _first_col(columns, *aliases)
        values = _to_numeric(source[source_col]) if source_col else 0
        result[target] = values

    # 继续保留带前缀的工资对账列，不依赖申报列。
    _copy_payroll_reconciliation_fields(result, source)

    annual_total_col = _first_col(
        columns, "年累计专项附加扣除金额", "年累计专项附加扣除"
    )
    result["工资单_年累计专项附加扣除"] = (
        _to_numeric(source[annual_total_col]) if annual_total_col else 0
    )
    return result.reset_index(drop=True)
```

在 `build_working_sheet()` 中修改分派：

```python
if role in {"rank_salary", "marketing_salary"}:
    df = load_employee_payroll(path, taxpayer_org_map, duplicate_taxpayer_ids)
elif role == "headquarters_salary":
    df = load_headquarters_payroll(path, taxpayer_org_map, duplicate_taxpayer_ids)
else:
    df = load_employee_payroll(path, taxpayer_org_map, duplicate_taxpayer_ids)
```

如仍需兼容旧函数名，可以保留薄包装，避免其他调用方报错：

```python
load_rank_payroll = load_employee_payroll
load_marketing_style_payroll = load_employee_payroll
```

### 4.3 修正独立专项扣除覆盖逻辑

`apply_deduction_matches()` 当前会先把七项列全部置 0，这会抹掉工资表中已取到的值。改为仅补不存在的列：

```python
for column in DEDUCTION_COLUMNS:
    if column not in result.columns:
        result[column] = 0

result["专项附加扣除匹配状态"] = ""
result["专项附加扣除来源文件"] = ""
```

每次独立文件成功匹配后：

```python
for column in DEDUCTION_COLUMNS:
    result.at[target_index, column] = _to_numeric(
        pd.Series([deduction.get(column, 0)])
    ).iat[0]
result.at[target_index, "专项附加扣除匹配状态"] = "已匹配"
result.at[target_index, "专项附加扣除来源文件"] = deduction.get("文件名", "")
```

`load_deduction_files()` 不应在匹配前删除 `文件名`；去重后的数据仍需保留来源文件名，方便排查营销人员为何未匹配。

---

## 5. 修改要求 2：仅员工编号变化自动更新本月主数据

### 5.1 最终行为

只满足以下条件时自动认定为“仅员工编号变化”：

- 工资表与人员主数据的姓名相同；
- 归属机构相同；
- 人员主数据中“姓名+机构”唯一；
- 工资表中“姓名+机构”也唯一；
- 旧员工编号与新员工编号均非空且不同；
- 证件号码、人员状态和机构没有发生变化。

处理结果：

1. 只更新最新月份员工人员主数据的 `员工编号`，绝不能回写上月历史文件。
2. 在核对页面显示“员工编号自动更新”提醒，展示旧编号和新编号。
3. 不计入阻断。
4. 不生成入职、离职、调岗记录。
5. 不进入 `人员信息变动表-雇员.xlsx` 和人员信息采集申报表。

这里将用户原话解释为：页面要显示变化，但雇员变动申报表要剔除“仅员工编号变化”。

### 5.2 增加识别函数

在 `verification.py` 增加：

```python
def detect_employee_id_only_changes(
    payroll: pd.DataFrame,
    staff: pd.DataFrame,
) -> list[dict[str, str]]:
    if payroll.empty or staff.empty:
        return []

    payroll_work = payroll.copy()
    staff_work = staff.copy()
    payroll_work["_name"] = payroll_work["*姓名"].map(_key_text)
    payroll_work["_org"] = payroll_work["机构代码"].map(normalize_org_code)
    payroll_work["_employee_id"] = _normalize_emp_id(payroll_work["员工编号"])

    staff_work["_name"] = staff_work["*姓名"].map(_key_text)
    staff_work["_org"] = staff_work["机构代码"].map(normalize_org_code)
    staff_work["_employee_id"] = _normalize_emp_id(staff_work["员工编号"])

    payroll_unique = payroll_work[
        ~payroll_work.duplicated(["_name", "_org"], keep=False)
    ].set_index(["_name", "_org"])
    staff_unique = staff_work[
        ~staff_work.duplicated(["_name", "_org"], keep=False)
    ].set_index(["_name", "_org"])

    changes: list[dict[str, str]] = []
    for key in payroll_unique.index.intersection(staff_unique.index):
        payroll_row = payroll_unique.loc[key]
        staff_row = staff_unique.loc[key]
        old_id = _clean_text(staff_row.get("_employee_id"))
        new_id = _clean_text(payroll_row.get("_employee_id"))
        if not old_id or not new_id or old_id == new_id:
            continue
        changes.append({
            "name": _clean_text(staff_row.get("*姓名")),
            "id_number": _normalize_id_number(staff_row.get("证件号码")),
            "org_code": normalize_org_code(staff_row.get("机构代码")),
            "old_employee_id": old_id,
            "new_employee_id": new_id,
            "message": f"仅员工编号变化，已由 {old_id} 自动更新为 {new_id}",
        })
    return changes
```

### 5.3 只写本月主数据

在 `personnel_master.py` 增加一个明确的写入函数。输入是当前核对所用人员文件和上一步变化列表，输出本月展示文件及完整历史文件：

```python
def materialize_employee_id_updates(
    source_path: str | Path,
    changes: list[dict[str, str]],
    output_dir: str | Path,
    year: int,
    month: int,
) -> dict[str, str]:
    staff = read_excel(source_path).fillna("")
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    for change in changes:
        id_number = change["id_number"]
        org_code = change["org_code"]
        old_id = change["old_employee_id"]
        mask = (
            staff["证件号码"].map(_normalize_id_number).eq(id_number)
            & staff["机构代码"].map(normalize_org_code).eq(org_code)
            & staff["员工编号"].map(_clean).eq(old_id)
        )
        if int(mask.sum()) != 1:
            raise ValueError(
                f"{change['name']} 的员工编号自动更新匹配到 {int(mask.sum())} 条人员记录"
            )
        staff.loc[mask, "员工编号"] = change["new_employee_id"]

    history_path = output_root / f"人员信息表完整数据({year}年{month:02d}月).xlsx"
    display_path = output_root / f"人员信息表({year}年{month:02d}月).xlsx"
    _write_excel(staff, history_path)

    display = staff.copy()
    if "人员状态" in display.columns:
        display = display[
            display["人员状态"].map(_clean).isin(["", "正常", "在职"])
        ].copy()
    _write_excel(display, display_path)
    return {
        "updated_staff_path": str(display_path),
        "full_staff_path": str(history_path),
    }
```

实际落地时可复用现有 `_write_excel`、清洗函数，不要重复实现。

### 5.4 接入核对 API

`backend/app/api/tax.py` 中建议流程：

1. 用上月/当前来源人员表构建一次初始工资底稿。
2. 从工资与人员数据识别 `employee_id_changes`。
3. 如果有变化且本轮没有上传人工雇员变动表：
   - 生成本月更新后人员主数据；
   - 调用现有 `save_generated_employee_master()` 保存为本月人员主数据；
   - 使用更新后的本月人员表重新构建底稿。
4. 将变化写入：

```python
report["employee_id_changes"] = {
    "has_issues": bool(employee_id_changes),
    "items": employee_id_changes,
}
```

5. `summary.total_issues` 可计入提醒数量，但 `summary.blocking_issues` 不增加。

不要直接修改 `source_staff_path` 指向的上月文件。

### 5.5 前端展示

`frontend/src/api.ts` 的 `VerifyReport` 增加：

```ts
employee_id_changes?: {
  has_issues: boolean
  items: Array<{
    name: string
    id_number: string
    org_code: string
    old_employee_id: string
    new_employee_id: string
    message: string
  }>
}
```

`TaxDeclaration.vue` 在人员变动区增加独立提醒表，标题为“员工编号自动更新”，不要混入 `personnel_changes.items`。

---

## 6. 修改要求 3：专项扣除缺失只提示，重复才阻断

### 6.1 修正规则配置

`verification.py`：

```python
VERIFICATION_RULE_CONFIG = {
    ...
    "blocking_codes": {
        ...
        "deduction_duplicates",
        # 删除 deduction_missing_orgs
    },
    "warning_codes": {
        ...
        "deduction_missing_orgs",
        # 删除 deduction_duplicates
    },
}
```

### 6.2 修正缺失机构判定

不要再用“七项金额合计等于 0”直接判定缺失。合法情况下，某营业部全员确实可能为 0。

应使用第 4.3 节增加的 `专项附加扣除匹配状态`：

```python
def check_deduction_coverage(sheet: pd.DataFrame) -> list[str]:
    org_col = (
        "机构代码_工资单"
        if "机构代码_工资单" in sheet.columns
        else "机构代码"
    )
    if org_col not in sheet.columns or "专项附加扣除匹配状态" not in sheet.columns:
        return []

    missing: list[str] = []
    for org_code, group in sheet.groupby(org_col, dropna=False):
        matched = group["专项附加扣除匹配状态"].eq("已匹配")
        if not matched.any():
            missing.append(_clean_text(org_code))
    return [value for value in missing if value]
```

### 6.3 修正汇总与阻断数量

`verify()` 中：

```python
duplicates = report["deduction_warnings"]["duplicates"]
missing_orgs = report["deduction_warnings"]["missing_orgs"]

# 总问题数包含二者。
total += len(duplicates) + len(missing_orgs)

# 阻断数只加入重复人员。
blocking_issues += len(duplicates)
```

建议给专项扣除结构增加清晰字段：

```python
report["deduction_warnings"]["has_issues"] = bool(duplicates or missing_orgs)
report["deduction_warnings"]["has_blocking_issues"] = bool(duplicates)
```

`build_reconciliation_report()` 中：

- “专项附加扣除重复”：`阻断项`，`是否阻断=True`
- “专项附加扣除机构遗漏”：`提醒项`，`是否阻断=False`

`build_verification_checks()` 中：

- 有重复：`status="fail"`
- 只有缺失机构：`status="warn"`
- 都没有：`status="pass"`

`TaxDeclaration.vue` 中：

- 重复人员标签用红色；
- 只有缺失机构时用黄色；
- 提示文案改为“该营业部未匹配到独立专项附加扣除数据，仅提醒，不影响生成”。

---

## 7. 修改要求 4：生成申报表区域增加“一键清空”

### 7.1 清空范围

按钮放在步骤 3“申报表下载”的右上角，与“批量下载全部”并列。

为了避免误删人员主数据，建议“一键清空”只删除：

- 当前工资薪金核对会话的 `output` 目录；
- 页面上的 `generatedFiles`；
- 当前会话的生成状态。

保留：

- 最新核对报告；
- 底稿；
- 本月人员主数据；
- 人员编号自动更新结果。

清空后回到步骤 2，可以重新点击“生成申报表”。

### 7.2 后端接口

`backend/app/api/tax.py` 增加：

```python
@router.delete("/sessions/{session_id}/generated-files")
def clear_generated_files(
    session_id: int,
    db: Session = Depends(get_db),
):
    session = (
        db.query(VerificationSession)
        .filter(VerificationSession.id == session_id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.status == "generating":
        raise HTTPException(status_code=409, detail="申报表生成中，不能清空")

    output_dir = ARTIFACT_DIR / str(session_id) / "output"
    if output_dir.exists():
        shutil.rmtree(output_dir)

    latest_round = (
        db.query(VerificationRound)
        .filter(VerificationRound.session_id == session_id)
        .order_by(VerificationRound.round_number.desc())
        .first()
    )
    report = latest_round.report_data if latest_round else {}
    session.status = (
        "needs_review"
        if report.get("summary", {}).get("has_blocking_issues")
        else "ready_to_generate"
    )
    db.commit()
    return {"status": session.status, "files": []}
```

### 7.3 前端接口与按钮

`frontend/src/api.ts`：

```ts
clearGeneratedFiles: (sessionId: number) =>
  api.delete<{ status: string; files: GeneratedFile[] }>(
    `/tax/sessions/${sessionId}/generated-files`
  ),
```

`TaxDeclaration.vue`：

```ts
async function clearGeneratedFiles() {
  if (!props.sessionId) return
  try {
    await ElMessageBox.confirm(
      '确认清空本次生成的全部申报文件？核对报告和人员主数据会保留。',
      '一键清空',
      { type: 'warning', confirmButtonText: '确认清空' },
    )
    const { data } = await taxApi.clearGeneratedFiles(props.sessionId)
    generatedFiles.value = []
    step.value = 2
    if (props.session) {
      emit('session-updated', { ...props.session, status: data.status })
    }
    ElMessage.success('生成的申报文件已清空')
  } catch (error: any) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error('清空失败：' + getErrorMessage(error))
    }
  }
}
```

需要从 Element Plus 引入 `ElMessageBox` 和 `Delete` 图标。

---

## 8. 修改要求 5：“开始申报”进入个税 RPA

### 8.1 子组件发导航事件

`TaxDeclaration.vue`：

```ts
const emit = defineEmits<{
  (event: 'session-updated', session: TaxSession): void
  (event: 'open-rpa'): void
}>()
```

步骤 3 底部增加：

```vue
<button
  class="btn btn-primary btn-lg"
  :disabled="!generatedFiles.length"
  @click="emit('open-rpa')"
>
  开始申报
</button>
```

### 8.2 父组件切换栏目

`frontend/src/App.vue`：

```vue
<TaxDeclaration
  v-else
  :session="session"
  :session-id="sessionId"
  @session-updated="session = $event"
  @open-rpa="activeView = 'etax_rpa'"
/>
```

此按钮只负责进入“个税 RPA”栏目，不应未经确认直接启动 Chrome 或 RPA 任务。

补充注意：现有 `RpaService.prepare_from_period()` 只读取通用 `Job/Artifact` 生成记录，工资薪金专用接口生成的文件位于 `artifacts/{session_id}/output`，未必会被“从本期已生成文件准备 input”找到。建议同时扩展该方法，把当前期间最新 `VerificationSession` 的 `_1-人员信息采集_员工` 和 `_3-个税申报表` 文件加入候选，否则用户跳到 RPA 后仍可能需要手工上传。

---

## 9. 修改要求 6：修正经纪人工资取数

### 9.1 当前明确存在的代码缺陷

当前 `broker_tax_transform()`：

```python
broker["员工编号"] = text_series(broker, ["员工编号"]).map(normalize_emp_id)
broker["经纪人本期收入"] = (
    number_series(broker, ["应发工资(补足前)"])
    - number_series(broker, ["增值税"])
)
```

存在四个问题：

1. 员工号只认 `员工编号`，实际表若为 `人员编号`、`员工编码` 或 `工号`，所有明细都会被当空行删除。
2. 半角/全角括号、空格、换行不同都会导致列匹配失败。
3. 金额列不存在时 `number_series()` 静默返回 0，不会阻断，最终可能生成全 0 申报表。
4. 公式固定为“应发工资(补足前)-增值税”，没有先判断原表是否已经提供可直接申报的“本期收入/经纪人本期收入”。

### 9.2 先规范化列名

在 `formulas.py` 增加：

```python
def normalize_column_label(value: Any) -> str:
    text = _clean_cell(value)
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("\n", "").replace("\r", "")
    return re.sub(r"\s+", "", text)


def find_normalized_column(
    frame: pd.DataFrame,
    candidates: Iterable[str],
) -> str | None:
    lookup = {
        normalize_column_label(column): column
        for column in frame.columns
    }
    for candidate in candidates:
        found = lookup.get(normalize_column_label(candidate))
        if found is not None:
            return found
    return None
```

记得在文件顶部增加 `import re`。

### 9.3 使用别名并禁止静默取 0

```python
BROKER_COLUMN_ALIASES = {
    "employee_id": ("员工编号", "人员编号", "员工编码", "工号"),
    "direct_income": (
        "经纪人本期收入",
        "本期收入",
        "劳务报酬收入",
        "佣金收入",
    ),
    "gross_income": (
        "应发工资(补足前)",
        "应发工资（补足前）",
        "应发工资补足前",
        "应发工资",
    ),
    "vat": ("增值税", "增值税额", "应扣增值税"),
    "personal_tax": (
        "个人所得税(经纪人)",
        "个人所得税（经纪人）",
        "经纪人个人所得税",
        "个人所得税",
    ),
}


def broker_income_series(
    broker: pd.DataFrame,
) -> tuple[pd.Series, dict[str, str]]:
    direct_col = find_normalized_column(
        broker, BROKER_COLUMN_ALIASES["direct_income"]
    )
    if direct_col:
        return _to_number(broker[direct_col]), {
            "mode": "direct",
            "income_column": direct_col,
            "vat_column": "",
        }

    gross_col = find_normalized_column(
        broker, BROKER_COLUMN_ALIASES["gross_income"]
    )
    if not gross_col:
        raise ValueError(
            "经纪人工资表未找到本期收入或应发工资列，禁止按 0 继续生成"
        )
    vat_col = find_normalized_column(broker, BROKER_COLUMN_ALIASES["vat"])
    gross = _to_number(broker[gross_col])
    vat = (
        _to_number(broker[vat_col])
        if vat_col
        else pd.Series(0, index=broker.index, dtype="float64")
    )
    return gross - vat, {
        "mode": "gross_minus_vat",
        "income_column": gross_col,
        "vat_column": vat_col or "",
    }
```

其中 `_to_number()` 可直接复用现有数值清洗逻辑：

```python
def _to_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    ).fillna(0)
```

接入 `broker_tax_transform()`：

```python
employee_id_col = find_normalized_column(
    broker, BROKER_COLUMN_ALIASES["employee_id"]
)
if not employee_id_col:
    return {
        "detail": pd.DataFrame(),
        "summary": pd.DataFrame(),
        "issues": [{
            "issue_type": "经纪人工资列缺失",
            "message": "经纪人工资表未找到员工编号/人员编号/员工编码/工号列",
        }],
        "block_declarations": True,
    }

broker["员工编号"] = broker[employee_id_col].map(normalize_emp_id)
broker = broker[broker["员工编号"].map(_clean_cell) != ""].copy()
broker["经纪人本期收入"], income_rule = broker_income_series(broker)
```

并把 `income_rule` 写入 `metrics` 或结果工作簿，让使用者看得见本次实际用了哪一列、哪种公式。

### 9.4 必须用原表确认的唯一业务点

本地 Codex 打开用户原始经纪人工资表后，只需确认：

- 如果原表已经有“经纪人本期收入/本期收入/佣金收入”且该列就是申报口径，则直接取该列，不再减增值税。
- 如果原表只有“应发工资(补足前)”和“增值税”，则继续使用二者相减。
- 如果“应发工资(补足前)”本身已经不含增值税，则不能再次减增值税。

确认方式不需要复杂测试：对原表任选 2 人，用 Excel 手算并与业务确认的申报金额对比即可。

为了避免再次静默出错，找不到关键金额列必须阻断，不能再默认 0。

---

## 10. 修改要求 7：修复 RPA ZIP 打包后无法使用

### 10.1 代码审查结论

后端当前使用 Python `zipfile` 直接把输出目录顶层文件写入内存，基本格式没有明显错误；已有单元测试也只验证了 ZIP 能被 `zipfile` 打开。但是实际使用仍存在两个薄弱点：

- 后端不执行 `testzip()`，文件写入不完整或源文件仍在变化时无法提前发现。
- 前端创建 Blob URL 后立刻释放；在 Windows 桌面 WebView/较慢磁盘环境下，下载动作可能尚未真正读取完 URL。

因此建议后端增加完整性校验，前端延迟释放 URL。两处都改，避免只修一端。

### 10.2 后端稳健打包

`backend/app/rpa/service.py`：

```python
def build_output_archive(self) -> tuple[str, bytes]:
    if self.manager.running:
        raise RuntimeError("RPA 任务运行中，不能打包输出文件")

    root = self._output_root()
    files = sorted(
        (
            path for path in root.rglob("*")
            if path.is_file() and not path.name.startswith("~$")
        ),
        key=lambda item: item.relative_to(root).as_posix(),
    )
    if not files:
        raise ValueError("当前没有可下载的输出文件")

    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        allowZip64=True,
    ) as archive:
        for path in files:
            relative = path.relative_to(root).as_posix()
            archive.write(path, arcname=relative)

    content = buffer.getvalue()
    with zipfile.ZipFile(io.BytesIO(content), "r") as archive:
        bad_file = archive.testzip()
        if bad_file:
            raise RuntimeError(f"ZIP 完整性校验失败：{bad_file}")
        if len(archive.infolist()) != len(files):
            raise RuntimeError("ZIP 文件数量校验失败")

    return (
        f"RPA输出文件_{datetime.now():%Y%m%d_%H%M%S}.zip",
        content,
    )
```

这里同时修复当前只打包顶层文件、遗漏子目录输出的问题。

### 10.3 前端下载

`EtaxRpa.vue`：

```ts
async function downloadOutputArchive() {
  try {
    const response = await rpaApi.downloadArchive()
    const disposition = response.headers['content-disposition'] || ''
    const match = disposition.match(/filename\\*=UTF-8''([^;]+)/i)
    const fileName = match
      ? decodeURIComponent(match[1])
      : 'RPA输出文件.zip'

    const blob = response.data instanceof Blob
      ? response.data
      : new Blob([response.data], { type: 'application/zip' })
    if (!blob.size) throw new Error('下载到的 ZIP 文件为空')

    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = fileName
    link.style.display = 'none'
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 3000)
  } catch (error: any) {
    ElMessage.error(detail(error, 'ZIP 下载失败'))
  }
}
```

单文件下载的 `downloadOutput()` 也建议采用相同的“挂到 DOM + 延迟释放 URL”方法。

---

## 11. 修改要求 8：日志位置与留存

### 11.1 当前日志位置

Windows 桌面版默认数据根目录：

```text
%LOCALAPPDATA%\TaxWorkbench
```

应用日志：

```text
%LOCALAPPDATA%\TaxWorkbench\logs\app.log
```

RPA 当前运行日志：

```text
%LOCALAPPDATA%\TaxWorkbench\rpa\etax\state\current.log
```

开发模式默认：

```text
<仓库目录>\storage\logs\app.log
<仓库目录>\storage\rpa\etax\state\current.log
```

`app.log` 单文件上限 5 MB，保留 5 个轮转备份。系统维护页已有诊断包接口 `/api/system/diagnostics`，诊断 ZIP 会包含应用日志。

### 11.2 建议修改为每次 RPA 运行单独留档

当前每次 `start_task()` 都执行：

```python
log_path.write_text("", encoding="utf-8")
```

会覆盖上一次运行。建议改为：

```python
run_id = uuid.uuid4().hex
run_log_dir = state_dir() / "logs"
run_log_dir.mkdir(parents=True, exist_ok=True)
log_path = run_log_dir / f"{datetime.now():%Y%m%d_%H%M%S}_{task_key}_{run_id[:8]}.log"
log_path.write_text("", encoding="utf-8")
```

并让 `read_logs()` 使用状态中保存的真实路径：

```python
def read_logs(self, offset: int) -> dict:
    data = self.store.read()
    configured = data.get("current_run", {}).get("log_path")
    path = Path(configured) if configured else state_dir() / "current.log"
    ...
```

建议保留最近 30 个运行日志，启动新任务时删除更旧文件。

### 11.3 让异常真正写入 app.log

目前很多 API 用 `except Exception as exc: return bad_request(exc)`，异常会返回前端但不一定写入 `app.log`。在以下模块增加：

```python
import logging
logger = logging.getLogger(__name__)
```

并在异常转换为 HTTP 响应前调用：

```python
logger.exception("RPA ZIP 打包失败")
```

优先补充：

- `backend/app/api/rpa.py`
- `backend/app/api/tax.py`
- `backend/app/services/job_runner.py`
- `backend/app/rpa/service.py` 的启动、退出和文件同步异常

日志不得写入证件号码、完整工资数据或 API 密钥。

---

## 12. 修改要求 9：上传文件夹按文件名“5位/7位”识别

### 12.1 识别规则

工资薪金页面选择月份文件夹时：

- Excel 文件名包含 `5位` 或 `五位`：识别为职级工资单；
- Excel 文件名包含 `7位` 或 `七位`：识别为营销工资单；
- 同一文件名同时出现两种标记：直接提示冲突；
- 专项扣除、人员变动、总部、经纪人和已生成申报文件的关键词识别优先；
- 不要把日期、机构代码或文件名里任意一个 5 位/7 位数字当作规则，只识别文字标记“5位/7位”。

### 12.2 前端修改

`TaxDeclaration.vue` 的 `detectFileRole()`：

```ts
function detectFileRole(text: string) {
  const compact = compactFileText(text)

  // 先识别非普通工资文件，避免误判生成产物或经纪人申报表。
  if (compact.includes('人员信息采集员工') || compact.includes('人员信息采集表')) return 'personnel_collection'
  if (compact.includes('核对报告')) return 'reconciliation_report'
  if (compact.includes('平台底稿') || compact.includes('核对底稿') || compact.includes('底稿xlsx')) return 'working_sheet'
  if (compact.includes('当月人员信息表') || compact.includes('更新后人员信息表')) return 'updated_staff'
  if (compact.includes('专项附加扣除') || compact.includes('专项扣除')) return 'deduction_files'
  if (compact.includes('人员信息变动表雇员') || compact.includes('变动表雇员')) return 'staff_change'
  if (compact.includes('经纪人') || compact.includes('证券经纪')) return 'broker_salary'
  if (compact.includes('总部代发') || compact.includes('总部工资')) return 'headquarters_salary'

  const rankByName = compact.includes('5位') || compact.includes('五位')
  const marketingByName = compact.includes('7位') || compact.includes('七位')
  if (rankByName && marketingByName) return 'salary_role_conflict'
  if (rankByName) return 'rank_salary'
  if (marketingByName) return 'marketing_salary'

  // 保留原有关键词作为兼容回退。
  if (compact.includes('投资顾问') || compact.includes('理财经理') || compact.includes('投顾')) return 'marketing_salary'
  if (compact.includes('机构业务人员') || compact.includes('机构工资')) return 'marketing_salary'
  if (compact.includes('数字化运营')) return 'marketing_salary'
  if (compact.includes('营销人员') || compact.includes('营销工资')) return 'marketing_salary'
  if (compact.includes('工资横表') || compact.includes('职级工资') || compact.includes('薪资')) return 'rank_salary'
  return ''
}
```

`classifyFolderFiles()` 中处理冲突：

```ts
if (role === 'salary_role_conflict') {
  throw new Error(`文件名同时包含 5位和7位标记，无法判断工资类型：${file.name}`)
}
```

如果按规则识别出两份职级或两份营销文件，继续沿用现有“请先合并后上传”的错误处理。

---

## 13. 需要修改的文件清单

### 必改

1. `backend/app/services/verification.py`
2. `backend/app/api/tax.py`
3. `backend/app/services/personnel_master.py`
4. `backend/app/services/formulas.py`
5. `backend/app/rpa/service.py`
6. `backend/app/api/rpa.py`
7. `frontend/src/views/TaxDeclaration.vue`
8. `frontend/src/views/EtaxRpa.vue`
9. `frontend/src/App.vue`
10. `frontend/src/api.ts`

### 建议补充的测试

1. `backend/tests/test_transformation_requirements.py`
2. `backend/tests/test_verification.py`
3. `backend/tests/test_tax_monthly_artifacts.py`
4. `backend/tests/test_formulas.py`
5. `backend/tests/test_rpa_output_files.py`

---

## 14. 推荐实施顺序

1. 先统一职级/营销工资加载和专项扣除覆盖规则。
2. 再实现仅员工编号变化识别、本月主数据更新和页面提醒。
3. 调整专项扣除缺失/重复的阻断级别。
4. 增加生成文件清空接口与前端按钮。
5. 增加“开始申报”导航事件，并确认工资薪金产物能进入 RPA input。
6. 用用户原始经纪人工资表确认列名和收入公式后，替换经纪人硬编码取数。
7. 最后修 ZIP 下载和 RPA 日志留档。
8. 修改文件夹“5位/7位”识别规则。

---

## 15. 最少验收项目

无需做大范围回归，只保留以下最小验收：

1. 用一份职级工资和一份营销工资验证：相同列名得到相同映射结果；营销的本期免税收入和七项专项扣除不再为错误的 0。
2. 构造同姓名、同机构、同证件、员工编号变化一例：本月主数据编号被更新，页面提示，但雇员变动表没有该人。
3. 专项扣除缺一个营业部时仍可生成；同一人员出现在两份专项扣除文件时阻断。
4. 生成文件后点击“一键清空”，后端文件确实消失，刷新页面不再显示；核对报告仍保留。
5. 点击“开始申报”进入“个税 RPA”；下载 ZIP 后用系统解压工具可正常解压，且 `testzip()` 通过。
6. 经纪人原表抽查 2 人：系统计算金额与人工确认口径一致；缺失关键金额列时必须阻断。

---

## 16. 给本地 Codex 的执行约束

- 必须基于 PR #1 的最新提交修改，不要回到 `main`。
- 不要修改上月人员主数据文件；自动员工号更新只能写本月人员主数据。
- 不要把专项扣除“总额列”强行分配到任意专项扣除明细列。
- 专项扣除缺失机构只提醒；重复人员才阻断。
- 经纪人工资关键列找不到时必须报错，不能静默生成 0。
- ZIP 修复必须同时包含后端完整性校验和前端延迟释放 Blob URL。
- 清空按钮只清生成文件，默认不删除核对报告和人员主数据。
- 完成后只运行第 15 节列出的最小测试，不需要扩大验证范围。
