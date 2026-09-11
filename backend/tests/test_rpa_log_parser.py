from app.rpa.log_parser import parse_log_line


def test_start_and_task_completion_samples():
    start = parse_log_line("开始处理单位：机构A（11818）", "special_deduction")
    done = parse_log_line("单位处理完成：机构A -> D:\\output\\a.xlsx", "special_deduction", "11818")
    assert (start[0].kind, start[0].org_code, start[0].org_name) == ("start", "11818", "机构A")
    assert done[0].count == 1


def test_import_and_download_samples():
    assert parse_log_line("文件导入成功：11818_工资薪金.xlsx", "import", "11818")[0].kind == "increment"
    assert parse_log_line("机构申报导入完成：机构A（11818）", "import", "11818")[0].kind == "done"
    assert parse_log_line("机构完税证明下载完成：机构A（11818），共 2 个文件", "tax_certificate")[0].count == 2
    assert parse_log_line("机构综合所得申报表下载完成：机构A（11818），共 1 个文件", "income_report")[0].count == 1
    assert parse_log_line("未查询到缴款记录，跳过完税证明下载：机构A（11818）", "tax_certificate", "11818")[0].count == 0


def test_extra_income_report_start_completion_and_normal_skip():
    start = parse_log_line("开始下载扩展申报表：机构A（11818）", "extra_income_reports")
    assert (start[0].kind, start[0].org_code, start[0].org_name) == ("start", "11818", "机构A")
    for count in (0, 1, 2):
        done = parse_log_line(f"机构扩展申报表下载完成：机构A（11818），共 {count} 个文件", "extra_income_reports")
        assert done[0].count == count
    assert parse_log_line("机构A（11818）分类所得申报表没有申报成功记录，正常跳过", "extra_income_reports", "11818") == []
