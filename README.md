# 税务申报核对工作台

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

当前 RPA 桌面打包方案暂不发布；Windows 免安装包仍按原有工作台功能构建。RPA 功能请使用 Python 3.12 源码开发环境运行。

## Windows 免安装版

```powershell
pip install -r backend\requirements-desktop.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_release.ps1 -Version 0.9.0
```

产物位于 `release/0.9.0/`。桌面版业务数据默认存放在 `%LOCALAPPDATA%\TaxWorkbench`，替换程序目录不会覆盖用户数据。

## 质量检查

```powershell
cd backend
python -m pytest -q
cd ..\frontend
npm run build
```

版本号统一维护在 `backend/app/core/version.py`，每次数据库结构变更必须增加迁移版本。

## 数据与模型文件

本项目是税务业务工作台，不依赖机器学习模型或模型权重，也不提供训练流程。`个税测试/`、`storage/` 和 `outputs/` 中可能包含业务样例、人员信息、申报底稿和运行结果，因此不会随源码仓库分发。仓库还会全局排除 `.xls/.xlsx` 和数据库文件。

如需本地开发或回归测试，请从具备授权的数据管理员处取得经过脱敏的测试文件，并放入本地受控目录；应用运行产生的数据会保存在本机 `storage/` 或桌面版的 `%LOCALAPPDATA%\\TaxWorkbench`。
