import pandas as pd

from app.services.formulas import (
    annual_bonus_transform,
    broker_tax_transform,
    general_salary_tax_transform,
    intern_tax_transform,
    merge_duplicate_invoice_lines,
    normalize_org_code,
    restricted_stock_interest_transform,
    staff_change_analysis,
)


def test_normalize_org_code_matches_legacy_mapping():
    assert normalize_org_code(9001) == "17001"
    assert normalize_org_code(301) == "10301"


def test_general_salary_tax_computes_income_tax_diff_and_staff_changes():
    salary = pd.DataFrame(
        [
            {
                "员工编号": "1001.0",
                "员工姓名": "张三",
                "单位编号": "301",
                "应发工资 I=A+B+D-F-G9+K": 10000,
                "调增应纳税所得额": 500,
                "个人所得税": 900,
                "本期应预扣预缴税额 SUM": 1000,
            }
        ]
    )
    staff = pd.DataFrame(
        [{"员工编号": "1002", "*姓名": "李四", "机构代码": "10302", "人员状态": "正常"}]
    )
    result = general_salary_tax_transform({"salary_sheet": salary, "staff_info": staff})
    assert result["detail"].loc[0, "本期收入"] == 10500
    assert result["extra_sheets"]["个税差异"].loc[0, "个税差异"] == 100
    assert any(issue["issue_type"] == "金额不一致" for issue in result["issues"])
    assert any("本月新增人员" in issue["message"] for issue in result["issues"])
    assert any("本月离职人员" in issue["message"] for issue in result["issues"])


def test_general_salary_tax_keeps_legacy_split_salary_role_compatible():
    salary = pd.DataFrame(
        [
            {
                "员工编号": "1001",
                "员工姓名": "张三",
                "单位编号": "301",
                "应发工资 I=A+B+D-F-G9+K": 10000,
                "个人所得税": 900,
                "本期应预扣预缴税额 SUM": 900,
            }
        ]
    )
    result = general_salary_tax_transform({"marketing_salary_sheet": salary})
    assert len(result["detail"]) == 1
    assert result["detail"].loc[0, "本期收入"] == 10000
    assert result["detail"].loc[0, "工资单类型"] == "营销工资单"


def test_general_salary_tax_normalizes_headquarters_salary_sheet():
    salary = pd.DataFrame(
        [
            {
                "员工编号": "1001",
                "姓名": "张三",
                "机构代码": "10301",
                "本期收入": 9000,
                "住房公积金的员工部分": 100,
                "养老保险金的员工部分": 200,
                "医疗保险金的员工部分": 50,
                "失业保险金的员工部分": 10,
                "企业年金的员工部分": 30,
                "累计商业保险扣除": 20,
                "免税支出": 300,
                "个人所得税": 800,
            }
        ]
    )
    result = general_salary_tax_transform({"headquarters_salary_sheet": salary})
    row = result["detail"].iloc[0]
    assert row["*姓名"] == "张三"
    assert row["本期收入"] == 9000
    assert row["住房公积金"] == 100
    assert row["基本养老保险费"] == 200
    assert row["企业(职业)年金"] == 30
    assert row["商业健康保险"] == 20
    assert row["本期免税收入"] == 300
    assert row["工资单类型"] == "总部工资单"


def test_staff_change_analysis_detects_org_change():
    staff = pd.DataFrame([{"员工编号": "1001", "姓名": "张三", "机构代码": "10301"}])
    payroll = pd.DataFrame([{"员工编号": "1001", "姓名": "张三", "单位编号": "302"}])
    result = staff_change_analysis(staff, payroll)
    assert len(result["本月人员变动"]) == 1


def test_annual_bonus_transform_merges_active_staff_only():
    bonus = pd.DataFrame(
        [
            {"员工编号": "1001.0", "员工姓名": "张三", "年终奖汇总": 20000, "年终奖计税": 2000},
            {"员工编号": "1002", "员工姓名": "李四", "年终奖汇总": 0, "年终奖计税": 0},
        ]
    )
    staff = pd.DataFrame(
        [
            {"员工编号": "1001", "*姓名": "张三", "证件类型": "居民身份证", "证件号码": "1", "机构代码": "10301", "人员状态": "正常"},
            {"员工编号": "1002", "*姓名": "李四", "证件类型": "居民身份证", "证件号码": "2", "机构代码": "10302", "人员状态": "正常"},
        ]
    )
    result = annual_bonus_transform({"annual_bonus_sheet": bonus, "staff_info": staff})
    assert len(result["detail"]) == 1
    assert result["detail"].iloc[0]["*全年一次性奖金收入"] == 20000


def test_annual_bonus_transform_combines_old_and_new_templates():
    bonus = pd.DataFrame([
        {"员工编号": "1001", "员工姓名": "张三", "年终奖发放": 10000, "本次扣税": 1000},
        {"员工编号": "1002", "员工姓名": "李四", "年终奖汇总": 20000, "年终奖计税": 2000},
    ])
    staff = pd.DataFrame([
        {"员工编号": "1001", "*姓名": "张三", "证件类型": "居民身份证", "证件号码": "1", "机构代码": "10301", "人员状态": "正常"},
        {"员工编号": "1002", "*姓名": "李四", "证件类型": "居民身份证", "证件号码": "2", "机构代码": "10301", "人员状态": "正常"},
    ])
    result = annual_bonus_transform({"annual_bonus_sheet": bonus, "staff_info": staff})
    assert result["detail"]["*全年一次性奖金收入"].tolist() == [10000, 20000]
    assert result["summary"].iloc[0]["收入合计"] == 30000


def test_broker_tax_subtracts_vat_and_checks_staff():
    broker = pd.DataFrame(
        [{"员工编号": "2001", "应发工资(补足前)": 1200, "增值税": 200, "个人所得税(经纪人)": 100}]
    )
    staff = pd.DataFrame([{
        "员工编号": "2001", "分支机构代码": "10301", "*姓名": "张三",
        "*证件类型": "居民身份证", "*证件号码": "110101199001010011",
    }])
    result = broker_tax_transform({"broker_salary_sheet": broker, "broker_staff_info": staff})
    assert result["detail"].iloc[0]["经纪人本期收入"] == 1000
    assert result["issues"] == []
    assert result["detail"].iloc[0]["*所得项目"] == "证券经纪人佣金收入"
    assert result["summary"].iloc[0]["个人所得税(经纪人)"] == 100


def test_broker_tax_adds_adjustment_and_deducts_additional_tax():
    broker = pd.DataFrame([{
        "员工编号": "2001", "应发合计（补足前）": 1200,
        "调增应纳税所得额": 80, "增值税": 200, "附加税": 30,
        "个人所得税": 100,
    }])
    staff = pd.DataFrame([{
        "员工编号": "2001", "分支机构代码": "10301", "姓名": "张三",
        "证件类型": "居民身份证", "证件号码": "110101199001010011",
    }])
    result = broker_tax_transform({"broker_salary_sheet": broker, "broker_staff_info": staff})
    assert result["detail"].iloc[0]["经纪人本期收入"] == 1080
    assert result["detail"].iloc[0]["允许扣除的税费"] == 30


def test_broker_tax_warns_when_personnel_master_has_unmatched_broker():
    broker = pd.DataFrame([{"员工编号": "2001", "应发工资(补足前)": 1200, "增值税": 200}])
    staff = pd.DataFrame([{"员工编号": "2002", "分支机构代码": "10301"}])
    result = broker_tax_transform({"broker_salary_sheet": broker, "broker_staff_info": staff})
    assert result["block_declarations"] is False
    assert {item["issue_type"] for item in result["issues"]} == {"经纪人新增待维护", "经纪人无本月收入提醒"}
    assert all(item["severity"] == "warning" for item in result["issues"])


def test_intern_tax_builds_legacy_personnel_and_declaration_data():
    intern = pd.DataFrame([{
        "营业部名称": "广州昌岗中路", "*姓名": "张三", "*证件类型": "居民身份证",
        "*证件号码": "110101199001010011", "实习开始时间": "2026-06-01",
        "发放补贴数\n（元）": 500, "联系方式": "13800138000",
    }])
    result = intern_tax_transform({"intern_salary_sheet": intern})
    row = result["detail"].iloc[0]
    assert result["issues"] == []
    assert row["分支机构代码"] == "10367"
    assert row["任职受雇从业类型"] == "实习学生（全日制学历教育）"
    assert row["*所得项目"] == "其他连续劳务报酬"
    assert row["本期收入"] == 500


def test_intern_tax_blocks_unknown_branch_instead_of_silent_export():
    intern = pd.DataFrame([{
        "营业部名称": "未维护营业部", "*姓名": "张三", "*证件类型": "居民身份证",
        "*证件号码": "110101199001010011", "实习开始时间": "2026-06-01", "发放补贴数\n（元）": 500,
    }])
    result = intern_tax_transform({"intern_salary_sheet": intern})
    assert result["detail"].empty
    assert result["block_declarations"] is True
    assert result["issues"][0]["issue_type"] == "实习生机构未匹配"
    assert result["metrics"]["intern_records"] == 1
    assert result["metrics"]["intern_valid_records"] == 0
    assert result["metrics"]["intern_total_amount"] == 500


def test_restricted_stock_interest_computes_balance_difference():
    xsg = pd.DataFrame(
        [
            {
                "机构代码": "301",
                "客户姓名": "张三",
                "证件类型": "居民身份证",
                "证件号码": "110101199001010011",
                "证券账号": "A001",
                "证券代码": "000001",
                "证券名称": "示例股票",
                "成交价格": 10,
                "成交数量": 100,
                "原值总金额": 200,
                "卖出经手费": 10,
                "卖出印花税": 5,
                "手续费": 5,
                "卖出过户费": 0,
            }
        ]
    )
    lxs = pd.DataFrame([{
        "机构代码": "301", "客户姓名": "李四", "证件类型": "居民身份证",
        "证件号码": "110101199001010022", "债券兑息": 1000, "税率（%）": 20,
    }])
    balance = pd.DataFrame(
        [
            {"公司段": "10301", "会计科目": 21510009, "币种": "CNY", "贷方金额(N)": 100},
            {"公司段": "10301", "会计科目": 21510008, "币种": "CNY", "贷方金额(N)": 200},
        ]
    )
    result = restricted_stock_interest_transform(
        {"restricted_stock_sheet": xsg, "interest_tax_sheet": lxs, "balance_sheet": balance}
    )
    row = result["summary"].iloc[0]
    assert row["限售股税费(申报表)"] == 156
    assert row["利息税税费(申报表)"] == 200
    assert row["限售股差额"] == -56
    assert result["metrics"]["restricted_stock_declared_amount"] == 780
    assert result["metrics"]["total_withheld_tax"] == 356
    assert result["reconciliation_rows"][0]["公司段"] == "10301"


def test_restricted_stock_interest_generation_does_not_require_balance_sheet():
    xsg = pd.DataFrame([
        {
            "机构代码": "301", "客户姓名": "张三", "证件类型": "居民身份证",
            "证件号码": "110101199001010011", "证券账号": "A001", "证券代码": "000001",
            "证券名称": "示例股票", "成交价格": 10, "成交数量": 100, "原值总金额": 200,
        },
    ])

    result = restricted_stock_interest_transform({"restricted_stock_sheet": xsg})

    assert result["issues"] == []
    assert result["summary"].iloc[0]["限售股税费(申报表)"] == 160


def test_restricted_stock_standard_formula_includes_fees_and_donation():
    xsg = pd.DataFrame([{
        "机构代码": "301", "客户姓名": "张三", "证件类型": "居民身份证",
        "证件号码": "110101199001010011", "证券账号": "A001", "证券代码": "000001",
        "证券名称": "示例股票", "成交价格": 10, "成交数量": 100, "原值总金额": 200,
        "卖出经手费": 10, "卖出印花税": 5, "手续费": 5, "卖出过户费": 0,
        "准予扣除的捐赠额": 100,
    }])

    result = restricted_stock_interest_transform({"restricted_stock_sheet": xsg})

    assert result["metrics"]["restricted_stock_declared_amount"] == 680
    assert result["metrics"]["restricted_stock_withheld_tax"] == 136


def test_merge_duplicate_invoice_lines_sums_amount_columns():
    df = pd.DataFrame(
        [
            {"发票代码": "A", "发票号码": "1", "金额": "10", "税额": "1"},
            {"发票代码": "A", "发票号码": "1", "金额": "20", "税额": "2"},
            {"发票代码": "B", "发票号码": "2", "金额": "5", "税额": "0.5"},
        ]
    )
    merged, duplicates = merge_duplicate_invoice_lines(df, ["发票代码", "发票号码"], ["金额", "税额"])
    row = merged[merged["发票号码"] == "1"].iloc[0]
    assert row["金额"] == 30
    assert row["税额"] == 3
    assert len(duplicates) == 2
