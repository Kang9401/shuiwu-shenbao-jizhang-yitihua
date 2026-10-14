# 税务局页面结构采集器

该工具连接用户手工启动并登录的 CDP Chrome，只采集页面结构。它不会读取输入框值，表格不保存明细行；URL 查询参数、动态标识和敏感文本会在写盘前移除。

## 采集

在项目根目录运行：

```powershell
E:\python项目\Learn\env\Scripts\python.exe tools\etax_page_probe\capture.py `
  --cdp http://127.0.0.1:9222 `
  --org 华南区域 `
  --page-type comprehensive_result `
  --stage entered `
  --audit-source backend\vendor\etax_rpa\etax_tax_certificate_download.py `
  --audit-source backend\app\rpa\extensions\etax_extra_income_reports.py
```

`--page-type` 支持：

- `comprehensive_result`
- `classified_result`
- `restricted_stock_result`
- `slider_dialog`
- `unknown_popup`

`--stage` 支持：`entered`、`queried`、`before_download`、`security_visible`、`security_finished`、`download_started`。

采集前由用户手工进入对应页面和阶段。采集器本身不点击下载、弹窗或滑块。发现未知 DOM 弹窗时，工具保存脱敏证据并以退出码 `3` 暂停。

输出目录：

```text
artifacts/etax_page_snapshots/<机构或地区>/<页面类型>/<采集时间>/
```

截图会遮罩表格明细、输入控件、机构名称、人员及金额区域。仍应把整个 `artifacts/etax_page_snapshots` 视为本机诊断数据，不提交到公共仓库。

## 静态选择器清单

不连接浏览器时可先提取源码选择器：

```powershell
E:\python项目\Learn\env\Scripts\python.exe tools\etax_page_probe\selector_audit.py `
  --source backend\vendor\etax_rpa\etax_tax_certificate_download.py `
  --source backend\app\rpa\extensions\etax_extra_income_reports.py `
  --output artifacts\etax_page_snapshots\selector_manifest.json
```

增加 `--cdp http://127.0.0.1:9222` 后，会在当前税务页面的全部 iframe 中验证选择器，并输出 `ok`、`missing`、`multiple`、`hidden`、`covered` 或 `wrong_frame`。

## 历史比较

```powershell
E:\python项目\Learn\env\Scripts\python.exe tools\etax_page_probe\compare.py `
  --baseline artifacts\etax_page_snapshots\华南区域\classified_result\20260801_090000_000000 `
  --current artifacts\etax_page_snapshots\华南区域\classified_result\20260804_090000_000000 `
  --output artifacts\etax_page_snapshots\diffs\classified_20260804.md
```

命令同时生成 Markdown 和 JSON 报告，列出 iframe、交互元素、弹窗和 RPA 选择器差异，并按“严重 / 警告 / 信息”分级。

## 安全边界

- 不保存 Cookie、Token、Local Storage 或 Session Storage。
- 不保存输入框 `value`。
- 表格只保存表头、列数和行数。
- 未知弹窗只采集，不自动关闭。
- 采集器不执行申报、确认、下载或滑块操作。
