# 智能税务平台

本项目将个税申报、人员主数据、专项附加扣除、限售股/利息税和核对底稿整合为本地桌面工作台。开发架构为 `FastAPI + Vue 3 + SQLite`，Windows 发布版使用 `pywebview + PyInstaller`，用户电脑不需要安装 Python、Node.js 或数据库。

## 项目结构

- `backend/`：API、SQLite 数据模型、业务规则、Excel 处理与桌面入口。
- `frontend/`：Vue 3 工作台。
- `packaging/`：应用图标、PyInstaller 配置和便携版说明。
- `scripts/`：一键发布脚本。
- `program_updates/`：稳定版本清单和更新发布说明。
- `storage/`：开发环境数据库、上传文件和产物。
- `个税测试/`：业务回归测试文件。

## 开发启动

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd ..\frontend
npm install
```

分别启动前后端：

```powershell
cd backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

cd frontend
npm run dev
```

也可以在根目录运行 `python start.py` 同时启动。

## 生产运行

```powershell
cd frontend
npm run build
cd ..\backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

生产模式由 FastAPI 直接托管 `frontend/dist`。

## 自然人电子税务局 RPA

源码开发模式已接入独立的“个税 RPA”页面，通过 Chrome CDP 调用受保护的原始 RPA 脚本。使用前需要上传机构信息表，并在系统启动的 Chrome 窗口中手工登录自然人电子税务局。

Windows 免安装包已包含 RPA 后台程序。目标电脑无需安装 Python 或 Node.js，但使用 RPA 时仍需安装 Google Chrome，并在程序启动的可接管 Chrome 窗口中手工登录自然人电子税务局。

## 财务 SKILL 大模型配置

“财务 SKILL”通过后端调用 OpenAI 兼容的 `chat/completions` 接口，API Key 不会发送到前端。启动服务前配置以下环境变量：

```powershell
$env:FINANCE_AI_BASE_URL="https://your-model-service.example/v1"
$env:FINANCE_AI_API_KEY="your-api-key"
$env:FINANCE_AI_MODEL="your-model-name"
```

开发环境也可以将相同配置写入后端启动目录的 `.env` 文件。可选的 `FINANCE_AI_TIMEOUT_SECONDS` 用于调整请求超时，默认值为 60 秒。输入模型前应先对身份证号、银行卡号等敏感信息脱敏；模型结果仅作为工作建议，正式入账和申报仍需有权限的业务人员复核。

## Windows 免安装版

```powershell
pip install -r backend\requirements-desktop.txt
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_release.ps1 -Version 1.0.0
```

  产物位于 `release/1.0.0/`。桌面版业务数据默认存放在 `%LOCALAPPDATA%\TaxWorkbench`，替换程序目录不会覆盖用户数据。

## 质量检查

```powershell
cd backend
python -m pytest -q
cd ..\frontend
npm run build
```

版本号统一维护在 `backend/app/core/version.py`，每次数据库结构变更必须增加迁移版本。

## 个税 RPA 与银行流水

- RPA 机构列表来自所属期间的员工人员主数据，标准列为 `营业部全称`、`机构代码`；运行时自动生成黑盒程序需要的 `机构信息表.xlsx`。
- 申报月份默认跟随所属期间，允许在 RPA 页面手工覆盖。
- “下载申报结果”会顺序执行综合所得和分类/限售股两个内部任务；正常无记录记为“无需处理”，程序异常记为“失败”。
- RPA 任务启动后可打开独立监控窗口；关闭监控窗口不会停止后台任务。
- 自动银行流水通过真实本地工具适配。默认在用户文档目录查找 `自动获取银行流水/server.cjs`，也可用 `BANK_FETCHER_ROOT` 指向该源码目录。登录态仍由原工具管理，本项目不保存账号密码、Cookie 或 Token。

## 数据与模型文件

本项目不随安装包提供模型权重，也不提供训练流程；财务 SKILL 仅在配置外部大模型服务后启用。`个税测试/`、`storage/` 和 `outputs/` 中可能包含业务样例、人员信息、申报底稿和运行结果，因此不会随源码仓库分发。仓库还会全局排除 `.xls/.xlsx` 和数据库文件。

如需本地开发或回归测试，请从具备授权的数据管理员处取得经过脱敏的测试文件，并放入本地受控目录；应用运行产生的数据会保存在本机 `storage/` 或桌面版的 `%LOCALAPPDATA%\\TaxWorkbench`。
