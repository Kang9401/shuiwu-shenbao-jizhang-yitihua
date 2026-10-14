from app.services.pit_reconciliation.workpaper_layout import HEADERS


def test_a1_uses_branch_name_header():
    headers = HEADERS["附A1 工资薪金等个税差异"]
    assert headers[1] == "营业部名称"
    assert "机构简称" not in headers
