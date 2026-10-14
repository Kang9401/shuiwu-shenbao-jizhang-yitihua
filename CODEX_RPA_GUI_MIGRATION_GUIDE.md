# 自然人电子税务局 RPA 接入实施说明

> 目标仓库：`Kang9401/shuiwu-shenbao-jizhang-yitihua`

> **先完整阅读本文档，再检查仓库实际代码，最后开始修改。不要只输出方案，必须实际修改代码并运行测试。**

---

## 0. 最重要的原则

### 0.1 原 RPA 源码是只读黑盒

用户提供的 RPA 源码已经经过实际测试，目前没有已知 Bug。

**下列原始文件一个字符都不允许修改：**

```text
build_exe.ps1
etax_batch_export.py
etax_batch_import.py
etax_gui.py
etax_tax_certificate_download.py
README.txt
requirements(1).txt
start_debug_chrome.ps1
start_gui.ps1
用户操作说明.md
```

禁止进行以下操作：

- 修改任何代码、注释、空格、换行或文件编码；
- 自动格式化；
- 调整 import；
- 重命名函数；
- 提取公共函数；
- 修改 Playwright 选择器；
- 修改等待时间；
- 修改日志文本；
- 修改命令行参数；
- 新增命令行参数；
- 修改输出目录算法；
- 修改浏览器 CDP 连接逻辑；
- 修改机构循环和续跑逻辑；
- 修改异常处理；
- 修改打包脚本；
- 将原脚本内容复制后“优化”为另一份业务实现；
- 以“修复潜在问题”“代码规范”“架构升级”等理由改动原源码。

### 0.2 `etax_gui.py` 也不得修改

`etax_gui.py` 的用途只有两个：

1. 作为 Vue 前端迁移的唯一业务交互依据；
2. 作为外围适配层构造命令、解析日志、管理状态的依据。

前端需要尽量还原原 GUI，而不是重新设计一套 RPA 操作流程。

### 0.3 只允许黑盒调用

允许的调用链只有：

```text
Vue 页面
  ↓ HTTP
目标仓库新增的 FastAPI RPA 适配层
  ↓ subprocess 参数数组
原始 RPA Python 脚本 / 原始 PowerShell 脚本
  ↓
Chrome CDP + 自然人电子税务局
```

不允许：

```text
目标仓库代码 import etax_batch_export 内部函数
目标仓库代码复制 Playwright 业务逻辑
目标仓库代码重写税务网站自动化步骤
前端直接控制 Playwright
```

---

## 1. 原始文件校验基线

以下 SHA-256 是用户本次提供文件的基线值。

| 文件 | SHA-256 |
|---|---|
| `build_exe.ps1` | `a998521019b0f239463eb50db04b5febfc52b38b24e4a67a5ad854f6164c77b5` |
| `etax_batch_export.py` | `64a72f6c7f85985031ba2739621fce35bf80eb74f1614a510cfd0a1e37e96239` |
| `etax_batch_import.py` | `646675ef6e04bc63148407362153a730de631407b635ba2dc8e7fed91648ab21` |
| `etax_gui.py` | `dcd68e4ceb5b6cfda507b98e9c627b0085ffa9435d132b8a24a8d9cc03614640` |
| `etax_tax_certificate_download.py` | `7e8bf68d50432c263505335edf69d05128e3ad3dc47be0eb3812024eee2f988f` |
| `README.txt` | `99e4b8a7e3415642bdac77ff5d453adbf8486ac37c60acd3384d07e9099ff814` |
| `requirements(1).txt` | `0fc694270c95e312f5faaaa63869af1e06f409de070600d20d0c4d6b3deb65a4` |
| `start_debug_chrome.ps1` | `3ff42a6978821b230be03fe1de1c191b7103ef2b00752e9c522f4ebe51320826` |
| `start_gui.ps1` | `3950132ef07e7e5660be7062bcb5ac73ebb394853b22310d51bff69993444b44` |
| `用户操作说明.md` | `d79a1cc729f25d7ce9233fd90c6650538f98301040e46a5437cb4198980833ba` |

### 1.1 Codex 开工前必须执行

将原文件放入目标仓库后，先运行 SHA-256 校验。

PowerShell 示例：

```powershell
Get-FileHash -Algorithm SHA256 .\backend\vendor\etax_rpa\*
```

Python 示例：

```python
from hashlib import sha256
from pathlib import Path

for path in sorted(Path("backend/vendor/etax_rpa").iterdir()):
    if path.is_file():
        print(path.name, sha256(path.read_bytes()).hexdigest())
```

### 1.2 Codex 完工后必须再次执行

必须同时满足：

```text
修改前哈希 == 修改后哈希 == 本文档基线哈希
```

并执行：

```bash
git diff -- backend/vendor/etax_rpa
```

输出必须为空。

如有任何差异，撤销原文件的全部修改后再提交结果。

---

## 2. 目标仓库现状和本次接入边界

目标仓库当前采用：

```text
FastAPI + Vue 3 + SQLite
```

Windows 桌面发布采用：

```text
pywebview + PyInstaller
```

目标仓库已有：

```text
backend/app/api/
backend/app/core/
backend/app/models/
backend/app/schemas/
backend/app/services/
backend/app/workflows/
frontend/src/App.vue
frontend/src/api.ts
frontend/src/styles.css
frontend/src/views/
```

目标仓库当前普通 `/jobs` 创建接口会在 HTTP 请求中直接调用现有 `run_job()`。

RPA 是长时间运行并需要人工登录 Chrome 的任务，因此本次**不要修改现有普通 Job 执行机制**，也不要把 RPA 强行塞入现有同步 `job_runner.py`。

### 2.1 第一阶段明确不修改

除非仓库实际结构已经发生变化且确有必要，否则第一阶段不要修改：

```text
backend/app/services/job_runner.py
backend/app/api/jobs.py
backend/app/workflows/*
backend/app/models/core.py
backend/app/schemas/core.py
现有数据库表和迁移版本
```

原因：

- RPA 任务时间长；
- 需要实时日志；
- 需要终止进程；
- 需要独占 Chrome；
- 现有 Job 是同步执行模型；
- 为接入 RPA 大改现有 Job 会增加现有业务回归风险。

第一阶段使用独立的 `/api/rpa` 接口和独立状态文件。

后续确需把 RPA 历史合并进任务中心时，应另开第二阶段，不在本次擅自扩展。

---

## 3. 推荐目录结构

### 3.1 只读原始文件目录

在目标仓库新增：

```text
backend/
  vendor/
    etax_rpa/
      build_exe.ps1
      etax_batch_export.py
      etax_batch_import.py
      etax_gui.py
      etax_tax_certificate_download.py
      README.txt
      requirements(1).txt
      start_debug_chrome.ps1
      start_gui.ps1
      用户操作说明.md
```

要求：

- 这些文件必须以二进制原样复制；
- 不要改名；
- 不要把 `requirements(1).txt` 改为 `requirements.txt`；
- 不要在该目录下直接产生业务文件；
- 不要在该目录创建真实 `机构信息表.xlsx`；
- 不要在该目录放真实 `input/`、`output/` 或 Chrome Profile。

### 3.2 目标仓库新增适配代码

建议新增：

```text
backend/app/rpa/
  __init__.py
  paths.py
  protected_files.py
  runtime.py
  commands.py
  log_parser.py
  process_manager.py
  state_store.py
  service.py

backend/app/api/rpa.py
backend/app/schemas/rpa.py

backend/tests/
  test_rpa_protected_files.py
  test_rpa_commands.py
  test_rpa_log_parser.py
  test_rpa_process_manager.py
  test_rpa_api.py

frontend/src/views/EtaxRpa.vue
```

具体文件拆分可以根据仓库编码风格微调，但职责必须保持清晰。

### 3.3 运行时工作目录

不要直接执行 `backend/vendor/etax_rpa/` 中的只读文件。

原 RPA 脚本会根据自身路径确定：

- `WORK_DIR`
- `input`
- `output`
- `.chrome-debug-profile`
- `.chrome-etax-profile`
- `etax_config.json`
- 进度 JSON

PyInstaller 打包后，程序文件所在目录可能不可写或是临时解包目录。

因此必须在首次使用时，将原始文件完整复制到目标仓库的可写数据目录。

目标仓库已有：

```python
settings.storage_root
```

建议运行时目录：

```text
<settings.storage_root>/
  rpa/
    etax/
      app/
        原始 RPA 文件副本
        机构信息表.xlsx
        etax_config.json
        input/
        output/
        .chrome-debug-profile/
        .chrome-etax-profile/
      state/
        rpa_state.json
        history.json
        current.log
      uploads/
        org_excel/
        import_files/
```

关键要求：

- `app/` 内的 Python 和 PowerShell 文件必须是只读源文件的原样副本；
- 启动时如果副本不存在则复制；
- 如副本哈希与只读源文件不同，覆盖恢复；
- 绝对不要把运行时 `input/output/profile` 反向复制回只读源目录；
- 所有业务输出留在 `settings.storage_root` 下；
- 便携版替换程序目录时，不丢失用户运行数据。

---

## 4. 运行时文件复制方案

在 `backend/app/rpa/runtime.py` 中实现类似职责：

```python
def ensure_runtime_app() -> Path:
    # 将 backend/vendor/etax_rpa 下受保护文件原样复制到
    # settings.storage_root/rpa/etax/app。
    # 返回运行时 app 目录。
    ...
```

要求：

1. 使用 `shutil.copy2` 或字节级写入；
2. 复制后计算 SHA-256；
3. 哈希不一致立即报错；
4. 创建：

```text
input/
output/
```

5. 不清空用户已有输出；
6. 不删除 Chrome Profile；
7. 不修改复制后的 `.py/.ps1/.md/.txt`；
8. 只有原始文件版本变化且哈希基线同步更新时，才替换运行时副本。

推荐常量：

```python
PROTECTED_SHA256 = {
    "build_exe.ps1": "...",
}
```

`protected_files.py` 只保存文件名和哈希，不保存或复制业务源码。

---

## 5. 允许修改的目标仓库文件

Codex 可以修改目标仓库自己的文件，包括：

```text
backend/app/main.py
backend/app/core/config.py（仅确有必要时）
backend/requirements.txt
backend/requirements-desktop.txt
packaging 下的 PyInstaller 配置
scripts/build_release.ps1
frontend/src/App.vue
frontend/src/api.ts
frontend/src/styles.css
```

也可以新增前述 RPA 适配文件。

### 5.1 任何目标仓库修改都必须最小化

不要顺手：

- 重构整个 `App.vue`；
- 重写全局样式；
- 调整已有流程名称；
- 更换 UI 组件库；
- 升级无关依赖；
- 修改数据库模型；
- 改变已有 `/jobs` 行为；
- 修改已有 Excel 生成逻辑；
- 处理无关 lint 问题；
- 格式化整个仓库。

---

## 6. 后端 RPA 数据结构

第一阶段不新增数据库表，使用一个持久化 JSON 状态文件：

```text
<storage_root>/rpa/etax/state/rpa_state.json
```

推荐结构：

```json
{
  "config": {
    "chrome_path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "org_excel_path": "C:\\...\\机构信息表.xlsx"
  },
  "chrome": {
    "status": "stopped",
    "last_checked_at": null,
    "message": ""
  },
  "current_run": {
    "run_id": null,
    "task_key": null,
    "display_name": null,
    "month": null,
    "backend_month": null,
    "all_orgs": true,
    "org_code": null,
    "current_org_code": null,
    "current_org_name": null,
    "status": "idle",
    "pid": null,
    "started_at": null,
    "finished_at": null,
    "exit_code": null,
    "error_message": null,
    "log_path": null
  },
  "results": {
    "2026-06": {
      "11818": {
        "name": "机构名称",
        "special_deduction": "待处理",
        "import": "待处理",
        "tax_certificate": "待处理",
        "income_report": "待处理"
      }
    }
  },
  "history": [],
  "last_failure": {
    "task_key": null,
    "org_code": null,
    "month": null
  }
}
```

### 6.1 状态字段

后台内部状态可使用：

```text
idle
starting
running
succeeded
failed
cancelled
```

前端必须继续显示原 GUI 中文状态：

```text
待处理
处理中
成功 0笔
成功 1笔
成功 N笔
失败
```

不要让用户看到不必要的英文状态。

### 6.2 原子写入

状态文件必须：

1. 写入临时文件；
2. flush；
3. 使用 `replace()` 原子替换；
4. 使用 UTF-8；
5. JSON 使用 `ensure_ascii=False`；
6. 多线程访问加锁。

---

## 7. 后端 API 设计

新增：

```text
backend/app/api/rpa.py
```

在 `backend/app/main.py` 中注册：

```python
from app.api import rpa
app.include_router(rpa.router, prefix=settings.api_prefix)
```

路由前缀：

```python
APIRouter(prefix="/rpa", tags=["rpa"])
```

最终接口前缀为：

```text
/api/rpa
```

### 7.1 获取完整状态

```http
GET /api/rpa/status
```

返回至少包括：

```json
{
  "chrome": {
    "status": "ready",
    "message": "CDP 已连接"
  },
  "config": {
    "chrome_path": "...",
    "org_excel_name": "机构信息表.xlsx"
  },
  "current_run": {},
  "results": [],
  "history": [],
  "last_failure": {},
  "can_start": true,
  "can_stop": false,
  "can_resume": false
}
```

### 7.2 保存界面配置

```http
PUT /api/rpa/config
```

请求：

```json
{
  "chrome_path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
}
```

只保存外围系统配置。

不要修改原始 `etax_gui.py`。

运行时可以把同样字段同步到运行目录的 `etax_config.json`，但字段含义必须与原 GUI 一致。

### 7.3 上传机构 Excel

```http
POST /api/rpa/org-excel
Content-Type: multipart/form-data
```

参数：

```text
file
```

要求：

- 只接受 `.xlsx`；
- 保存到运行时可写目录；
- 文件名必须清洗；
- 上传成功后复制为：

```text
<runtime_app>/机构信息表.xlsx
```

- 保留原文件名用于界面展示；
- 使用原脚本已有 `read_orgs_from_excel()` 的业务效果，但外围层不要 import 该函数；
- 适配层如需预览机构，应使用独立、简单、只读的 openpyxl 解析；
- 预览解析只能用于确认界面，不能替代原脚本的正式校验。

### 7.4 上传导入文件

优先使用目标系统已经生成的申报文件。

如当前系统无法直接提供，新增：

```http
POST /api/rpa/import-files
Content-Type: multipart/form-data
```

允许多文件。

保存到：

```text
<runtime_app>/input/
```

要求：

- 用户确认覆盖同名文件；
- 文件名必须保持原业务文件名；
- 不擅自改名；
- 不解析并重写文件；
- 不改变 Excel 内容；
- 不把上传文件提交 Git。

### 7.5 清理导入目录

```http
DELETE /api/rpa/import-files
```

只清理运行时 `input/` 内用户明确要求删除的业务文件。

不能清理：

- 原始 RPA 程序；
- output；
- Chrome Profile；
- 进度文件；
- 用户未确认的文件。

### 7.6 启动 Chrome

```http
POST /api/rpa/chrome/start
```

请求：

```json
{
  "chrome_path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
}
```

执行原始：

```text
start_debug_chrome.ps1
```

参数数组应等价于：

```text
powershell
-NoProfile
-ExecutionPolicy
Bypass
-File
<runtime_app>\start_debug_chrome.ps1
-ChromePath
<chrome.exe完整路径>
```

如果 `chrome_path` 为空，不传 `-ChromePath`，由原脚本自行查找。

禁止：

- 复制 PowerShell 内容到 Python；
- 修改原 PowerShell；
- 用另一套 Chrome 参数替代；
- 自动登录；
- 读取账号密码；
- 保存 Cookie 到业务数据库。

### 7.7 检查 Chrome 状态

```http
GET /api/rpa/chrome/status
```

检查：

```text
http://127.0.0.1:9222/json/version
```

状态：

```text
stopped
starting
ready
unavailable
```

建议使用 Python 标准库 `urllib.request` 或项目已有 HTTP 客户端。

不要把普通 Chrome 窗口误判为可接管 Chrome。

### 7.8 预览机构

```http
POST /api/rpa/orgs/preview
```

请求：

```json
{
  "all_orgs": true,
  "org_code": null
}
```

返回：

```json
{
  "count": 2,
  "items": [
    {"code": "11818", "name": "机构A"},
    {"code": "11831", "name": "机构B"}
  ]
}
```

对应原 GUI 的 `OrgPreviewDialog`。

开始任务前必须弹出确认。

### 7.9 启动任务

```http
POST /api/rpa/tasks/start
```

请求：

```json
{
  "task_key": "special_deduction",
  "month": "2026-06",
  "all_orgs": true,
  "org_code": null,
  "resume_mode": null
}
```

`task_key` 只能是：

```text
special_deduction
import
tax_certificate
income_report
```

立即返回，不能阻塞到脚本执行完成。

### 7.10 停止任务

```http
POST /api/rpa/tasks/stop
```

要求：

- 没有任务时返回可理解提示；
- 先 `terminate()`；
- 等待短时间；
- Windows 下必要时使用：

```text
taskkill /PID <pid> /T /F
```

- 终止进程树；
- 状态设为 `cancelled`；
- 界面显示“已停止”或“已取消”；
- 不伪造成功状态。

### 7.11 从失败继续

```http
POST /api/rpa/tasks/resume
```

使用状态文件中的：

```text
last_failure.task_key
last_failure.org_code
last_failure.month
```

必须先向前端返回预览，或前端确认后再执行。

### 7.12 读取增量日志

```http
GET /api/rpa/logs?offset=0
```

返回：

```json
{
  "text": "...",
  "next_offset": 1024,
  "finished": false
}
```

前端轮询间隔建议：

```text
1000ms ～ 2000ms
```

不要每几十毫秒请求。

### 7.13 输出文件列表

```http
GET /api/rpa/files
```

只列出：

```text
<runtime_app>/output/
```

中的文件。

返回：

```json
[
  {
    "name": "2026-06_11818_机构名称_....pdf",
    "size": 123456,
    "modified_at": "...",
    "download_url": "/api/rpa/files/download?name=..."
  }
]
```

### 7.14 下载输出文件

```http
GET /api/rpa/files/download?name=<文件名>
```

安全要求：

- `resolve()` 后确认仍位于 output 根目录；
- 拒绝 `..`；
- 拒绝绝对路径；
- 拒绝目录；
- 只允许真实存在文件；
- 使用 FastAPI `FileResponse`；
- 正确处理中文文件名。

---

## 8. 命令构造必须严格照搬原 GUI

新增：

```text
backend/app/rpa/commands.py
```

只负责构造参数数组。

禁止：

```python
shell=True
```

禁止：

```python
command = f'python "{script}" --month "{month}" ...'
```

必须：

```python
command = [
    sys.executable,
    str(script),
    "--cdp",
    "http://127.0.0.1:9222",
]
```

### 8.1 通用环境变量

启动任务时设置：

```text
PYTHONIOENCODING=utf-8
PYTHONUNBUFFERED=1
```

工作目录：

```text
<runtime_app>
```

### 8.2 专项附加导出

脚本：

```text
etax_batch_export.py
```

基础参数：

```text
--cdp http://127.0.0.1:9222
--month <界面申报月份>
--org-excel <runtime_app>\机构信息表.xlsx
--yes
```

单机构增加：

```text
--org-code <机构代码>
```

失败续跑增加：

```text
--start-org-code <失败机构代码>
```

完整示例：

```text
python etax_batch_export.py
  --cdp http://127.0.0.1:9222
  --month 2026-06
  --org-excel D:\...\机构信息表.xlsx
  --yes
  --org-code 11818
```

不要添加原脚本没有的参数。

### 8.3 导入数据

脚本：

```text
etax_batch_import.py
```

基础参数：

```text
--cdp http://127.0.0.1:9222
--month <界面申报月份>
--org-excel <runtime_app>\机构信息表.xlsx
--input-root <runtime_app>\input
--yes
```

单机构增加：

```text
--org-code <机构代码>
```

续跑模式：

```text
--resume
--start-org-code <失败机构代码>
```

重新执行时按原 GUI 逻辑使用：

```text
--reset-progress
```

不要自行更改原进度文件：

```text
output/import_progress_YYYY-MM.json
```

### 8.4 完税证明下载

脚本：

```text
etax_tax_certificate_download.py
```

必须增加：

```text
--task tax_certificate
```

关键规则：

```text
实际脚本月份 = 界面申报月份 + 1个月
```

示例：

```text
界面：2026-06
脚本：2026-07
```

跨年测试：

```text
界面：2026-12
脚本：2027-01
```

基础参数：

```text
--cdp http://127.0.0.1:9222
--month <加一个月后的月份>
--org-excel <runtime_app>\机构信息表.xlsx
--yes
--task tax_certificate
```

### 8.5 综合所得申报表下载

脚本：

```text
etax_tax_certificate_download.py
```

必须增加：

```text
--task income_report
```

关键规则：

```text
实际脚本月份 = 界面申报月份
```

不要加一个月。

### 8.6 Python 与打包模式

开发模式：

```text
sys.executable + 原脚本路径
```

桌面打包模式优先继续运行打包应用携带的 Python 环境和原 `.py` 文件。

如目标 PyInstaller 是单文件且无法稳定启动 `.py`，可以在目标仓库外围打包配置中把三个原脚本分别作为独立可执行文件构建，但：

- 不能修改原 `build_exe.ps1`；
- 不能修改原 Python 文件；
- 新建目标仓库自己的打包步骤；
- 运行时仍使用相同参数；
- 不运行 `etax_gui.exe`。

---

## 9. 进程管理

新增：

```text
backend/app/rpa/process_manager.py
```

使用全局单例或应用级服务。

必须保证：

```text
同一时刻最多一个自然人电子税务局 RPA 任务
```

### 9.1 启动流程

1. 检查无正在运行任务；
2. 检查 Chrome CDP 状态；
3. 检查机构 Excel；
4. 校验月份格式；
5. 校验单机构代码；
6. 构造参数数组；
7. 创建本次日志文件；
8. 启动子进程；
9. 保存 PID；
10. 启动 stdout/stderr 读取线程；
11. HTTP 立即返回。

### 9.2 子进程参数

建议：

```python
subprocess.Popen(
    command,
    cwd=runtime_app,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    encoding="utf-8",
    errors="replace",
    bufsize=1,
    env=env,
)
```

Windows 下可以按需要创建新进程组，但不能弹出额外命令行黑窗。

### 9.3 stdout 和 stderr

要求：

- 两者都实时读取；
- 原文写入日志；
- 前端展示时不改写；
- 每行送入原 GUI 日志解析器；
- 不因一行编码错误终止读取；
- 任务结束前等待读取线程收尾。

### 9.4 应用退出

FastAPI / pywebview 应用退出时：

- 不直接杀死用户已启动的 Chrome；
- 如 RPA 脚本仍运行，按目标应用既有退出策略处理；
- 最安全做法是提示并停止 RPA 子进程；
- 不删除 Chrome Profile；
- 不删除 output。

---

## 10. 日志解析必须复制原 GUI 行为

新增：

```text
backend/app/rpa/log_parser.py
```

只复制 `etax_gui.py` 中对**日志文本的识别规则和状态语义**。

不要修改原脚本日志。

不要发明 JSONL 协议。

不要要求原脚本增加回调。

### 10.1 开始处理机构

识别：

```regex
开始处理单位：(.+?)（(\d+)）
开始处理申报导入：(.+?)（(\d+)）
开始下载完税证明：(.+?)（(\d+)）
开始下载综合所得申报表：(.+?)（(\d+)）
```

识别后：

```text
current_org_name = group(1)
current_org_code = group(2)
当前任务状态 = 处理中
当前机构计数 = 0
```

### 10.2 专项附加导出成功

识别：

```regex
单位处理完成：(.+?) ->
```

当前机构状态：

```text
成功 1笔
```

### 10.3 导入文件成功

每出现一行包含：

```text
文件导入成功：
```

当前机构导入成功数量加 1。

### 10.4 机构导入完成

出现：

```text
机构申报导入完成：
```

状态：

```text
成功 N笔
```

其中 `N` 是该机构累计“文件导入成功”数量。

### 10.5 完税证明成功

识别：

```regex
机构完税证明及综合所得申报表下载完成：.+?（(\d+)），共 (\d+) 个文件
机构完税证明下载完成：.+?（(\d+)），共 (\d+) 个文件
```

当任务是 `tax_certificate`：

```text
对应机构状态 = 成功 N笔
```

### 10.6 综合所得申报表成功

识别：

```regex
机构综合所得申报表下载完成：.+?（(\d+)），共 (\d+) 个文件
```

当任务是 `income_report`：

```text
对应机构状态 = 成功 N笔
```

### 10.7 无缴款记录

出现：

```text
未查询到缴款记录，跳过机构：
```

或：

```text
未查询到缴款记录，跳过完税证明下载：
```

当任务是 `tax_certificate`：

```text
当前机构状态 = 成功 0笔
```

### 10.8 失败处理

子进程非 0 退出时：

- 当前机构存在：当前机构状态设为 `失败`；
- 保存最后失败任务；
- 保存最后失败机构代码；
- 启用“从失败继续”；
- 保存退出码；
- 保存 stderr 原文；
- 不把后续未处理机构设成失败，保持 `待处理`。

---

## 11. 前端页面必须迁移原 GUI

新增：

```text
frontend/src/views/EtaxRpa.vue
```

不要把 RPA 塞入 `GenericWorkflow.vue`。

不要在 `TaskCenter.vue` 中实现完整 RPA 操作页。

### 11.1 页面整体布局

桌面宽度下尽量还原原 GUI：

```text
┌──────────────────────────────────────────────────────┐
│ 自然人电子税务局自动化工具                           │
├──────────────────────┬───────────────────────────────┤
│ 左侧约 440px         │ 右侧                         │
│                      │                              │
│ 操作参数             │ 任务处理结果表               │
│ 执行任务             │                              │
│ 执行历史             │ 日志展示                     │
└──────────────────────┴───────────────────────────────┘
```

小屏可以上下排列，但业务分组和任务顺序不能变。

### 11.2 页面标题

必须显示：

```text
自然人电子税务局自动化工具
```

### 11.3 操作参数

字段和顺序：

| 标签 | 控件 | 规则 |
|---|---|---|
| 申报月份 | 月份选择器 | 默认当前月上一个月 |
| 申报机构 | 文件显示框 + 选择按钮 | 选择机构 Excel |
| 处理全部 | 是/否单选 | 默认“是” |
| 指定机构 | 文本框 | 处理全部为“否”时启用 |
| Chrome地址 | 文本框 | 使用原 GUI 默认路径 |

Chrome 默认路径：

```text
C:\Program Files\Google\Chrome\Application\chrome.exe
```

提示文字：

```text
如果浏览器初始化失败，请粘贴本机 chrome.exe 的完整路径，重新初始化。
```

### 11.4 月份逻辑

原 GUI 展示当前月份前后各 6 个月。

可以使用 `el-date-picker type="month"`，但：

- 显示和提交格式必须是 `YYYY-MM`；
- 默认上一个月；
- 不改变完税证明月份转换规则；
- 如目标仓库已有全局“所属期间”，初始值可以跟随全局期间；
- 用户在 RPA 页修改月份时，不应擅自修改目标仓库其他业务期间。

### 11.5 机构 Excel 选择

浏览器前端无法取得用户真实完整本机路径。

因此界面保持：

```text
只读文件名输入框 + 选择按钮
```

点击“选择”后上传文件到后端。

不要向用户伪造一个不存在的完整路径。

前端展示原始文件名即可。

### 11.6 执行任务区域

严格保持顺序：

```text
步骤 1  浏览器初始化
步骤 2  专项附加导出
步骤 3  导入数据
步骤 4  完税证明下载
步骤 5  综合所得申报表下载
```

说明文字尽量使用原 GUI：

#### 步骤 1

标题：

```text
浏览器初始化
```

按钮：

```text
初始化
```

说明：

```text
启动可接管的 Chrome。启动后请在该窗口手工登录自然人电子税务局。
```

#### 步骤 2

标题：

```text
专项附加导出
```

按钮：

```text
开始
```

说明：

```text
批量导出专项附加扣除文件。执行前会校验月份和机构 Excel。
```

#### 步骤 3

标题：

```text
导入数据
```

按钮：

```text
开始
```

说明：

```text
从 input 目录按机构代码前缀匹配文件，批量导入人员信息、工资薪金、劳务报酬、奖金等文件。
```

#### 步骤 4

标题：

```text
完税证明下载
```

按钮：

```text
开始
```

说明：

```text
按机构查询缴款记录并下载完税证明 PDF。默认查询申报月份的次月缴款记录。
```

#### 步骤 5

标题：

```text
综合所得申报表下载
```

按钮：

```text
开始
```

说明：

```text
按机构导出综合所得申报表到 output 文件夹。
```

### 11.7 开始任务确认流程

点击任一“开始”按钮后：

1. 校验 Chrome 是否 ready；
2. 校验月份；
3. 校验机构 Excel；
4. 处理全部为“否”时校验机构代码；
5. 调用机构预览 API；
6. 弹出机构列表；
7. 用户点击“确认执行”才启动；
8. 用户取消则不启动；
9. 如果本月该任务已有结果，弹出重新执行确认；
10. 确认后只清除本次目标机构的当前任务状态，不清除其他任务列。

机构预览弹窗标题：

```text
确认执行机构
```

确认按钮：

```text
确认执行
```

取消按钮：

```text
取消
```

表格列：

```text
机构代码
机构名称
```

### 11.8 任务结果表

标题：

```text
任务处理结果表
```

列必须是：

```text
机构代码
机构名称
专项申报
个税申报导入
完税证明
综合所得申报表
```

状态颜色：

- `成功`：绿色；
- `失败`：红色；
- `处理中`：蓝色；
- `待处理`：灰色。

不要改成英文状态。

### 11.9 执行历史

标题：

```text
执行历史
```

列：

```text
任务
开始时间
结束时间
耗时
```

任务名称：

```text
专项附加导出
导入数据
完税证明下载
综合所得申报表下载
```

### 11.10 日志区域

标题：

```text
日志展示
```

按钮顺序尽量保持：

```text
从失败继续
停止任务
复制
清空
```

要求：

- 使用 `<pre>`、只读 textarea 或等价控件；
- 禁止 `v-html`；
- 不自动换行；
- 等宽字体；
- 深色背景；
- 新日志自动滚动到底部；
- 用户主动滚动到上方时，可以暂停自动滚动；
- “复制”复制当前完整日志；
- “清空”只清前端显示，不能删除后台审计日志；
- stdout 和 stderr 都展示原文。

### 11.11 运行中控件状态

运行中禁用：

```text
月份
机构 Excel 选择
处理全部
指定机构
Chrome 地址
初始化
四个开始按钮
```

运行中启用：

```text
停止任务
复制
清空
```

有失败记录且没有任务运行时启用：

```text
从失败继续
```

---

## 12. 前端 API 类型和调用

在：

```text
frontend/src/api.ts
```

新增类型，命名服从现有风格，例如：

```ts
export type RpaTaskKey =
  | 'special_deduction'
  | 'import'
  | 'tax_certificate'
  | 'income_report'

export interface RpaChromeStatus {
  status: 'stopped' | 'starting' | 'ready' | 'unavailable'
  message: string
}

export interface RpaCurrentRun {
  run_id: string | null
  task_key: RpaTaskKey | null
  month: string | null
  backend_month: string | null
  current_org_code: string | null
  current_org_name: string | null
  status: string
  started_at: string | null
  finished_at: string | null
}
```

新增调用方法：

```ts
rpaApi.getStatus()
rpaApi.saveConfig()
rpaApi.uploadOrgExcel()
rpaApi.uploadImportFiles()
rpaApi.clearImportFiles()
rpaApi.startChrome()
rpaApi.getChromeStatus()
rpaApi.previewOrgs()
rpaApi.startTask()
rpaApi.stopTask()
rpaApi.resumeTask()
rpaApi.getLogs(offset)
rpaApi.listFiles()
```

必须复用现有 Axios 实例和统一错误处理。

不要另装 HTTP 库。

---

## 13. App.vue 导航接入

目标仓库目前由 `App.vue` 管理主要导航和当前页面。

增加一个独立导航项：

```text
个税 RPA
```

说明：

```text
自然人电子税务局批量自动化
```

要求：

- 不修改其他导航项名称；
- 不调整其他页面顺序，除非插入 RPA 项需要；
- 不改动已有期间管理逻辑；
- RPA 页面接收当前全局期间作为初始月份；
- RPA 页面内部月份改变不应自动切换全局其他业务页面，除非现有 App 架构天然双向绑定且无副作用。

不要引入 Vue Router，除非仓库当前已经使用。

---

## 14. 输入文件衔接策略

### 14.1 优先复用目标系统已有产物

导入任务执行前，先检查目标系统现有任务产物中是否已有本期个税申报导入文件。

如可以明确、安全地识别，则提供：

```text
从本期已生成文件准备 input
```

动作只做：

```text
复制原文件到 runtime_app/input
```

禁止：

- 修改 Excel；
- 重命名导致原脚本无法匹配；
- 合并工作簿；
- 二次生成；
- 对原文件做格式转换。

### 14.2 无法自动识别时

提供多文件上传按钮：

```text
选择导入文件
```

或目录选择：

```html
<input type="file" multiple webkitdirectory>
```

但不要要求用户必须重新上传目标系统已经能提供的文件。

### 14.3 文件名规则

原导入脚本按机构代码前缀和业务关键字匹配。

必须保留用户文件名。

不要在外围层自行判断“这个文件不需要”，除非原脚本本身会跳过。

---

## 15. 输出文件处理

原脚本输出统一位于：

```text
<runtime_app>/output
```

外围层只负责：

- 列出；
- 下载；
- 显示最近更新时间；
- 可选打开所在目录（仅桌面模式且已有安全桥接时）。

不要：

- 改名；
- 移动到其他目录后删除原文件；
- 修改 PDF；
- 修改 Excel；
- 重新压缩；
- 更改原脚本重复文件跳过行为。

---

## 16. Chrome 行为

原始 `start_debug_chrome.ps1` 会：

- 查找用户配置的 Chrome；
- 查找常见 Chrome 安装位置；
- 使用脚本目录下 `.chrome-debug-profile`；
- 启动 `--remote-debugging-port=9222`；
- 打开自然人电子税务局首页。

外围层不得改变这些参数。

### 16.1 前端提示

Chrome 启动成功后展示：

```text
已启动可接管的 Chrome。
请在该窗口手工登录自然人电子税务局，登录完成后回到本页面执行任务。
```

### 16.2 不允许的功能

- 自动填写账号；
- 自动填写密码；
- 保存密码；
- 读取短信验证码；
- 绕过人工登录；
- 将浏览器 Profile 上传；
- 将 Profile 打包进安装包；
- 启动多个 9222 Chrome。

---

## 17. 依赖和打包

目标仓库当前后端已经包含：

```text
openpyxl
```

需要增加：

```text
playwright
```

### 17.1 后端开发依赖

在目标仓库：

```text
backend/requirements.txt
```

增加：

```text
playwright>=1.40.0
```

不要添加：

```text
PyQt6
pyinstaller
```

到普通后端依赖。

原因：

- 新前端已替代 PyQt GUI；
- 目标仓库已有自己的 PyInstaller 打包体系；
- 原 `requirements(1).txt` 仍保持不变，仅作为原包文件保存。

### 17.2 桌面依赖

检查：

```text
backend/requirements-desktop.txt
```

确保桌面打包运行环境包含 Playwright Python 包。

不要求下载 Playwright Chromium，因为原脚本通过系统 Google Chrome 或 CDP 工作。

### 17.3 PyInstaller 数据文件

修改目标仓库自己的 PyInstaller spec，将：

```text
backend/vendor/etax_rpa/
```

作为数据文件完整打包。

不要执行原 `build_exe.ps1` 来构建整个目标系统。

不要把：

```text
input/
output/
.chrome-debug-profile/
.chrome-etax-profile/
机构信息表.xlsx
```

打包进去。

### 17.4 打包后的源文件定位

`runtime.py` 必须兼容：

- 开发环境项目目录；
- PyInstaller `_MEIPASS`；
- 目标仓库现有资源路径辅助函数。

优先复用目标仓库已有 `core.paths` 机制。

不要硬编码开发机绝对路径。

---

## 18. `.gitignore`

确保忽略：

```gitignore
storage/rpa/
backend/vendor/etax_rpa/input/
backend/vendor/etax_rpa/output/
backend/vendor/etax_rpa/.chrome-debug-profile/
backend/vendor/etax_rpa/.chrome-etax-profile/
backend/vendor/etax_rpa/机构信息表.xlsx
**/etax_config.json
```

注意：

- 不要用过宽的 `*.pdf` 忽略规则影响仓库已有合法测试资源；
- 不要忽略受保护源文件；
- 不要删除仓库已有 `.gitignore` 规则。

---

## 19. 安全要求

### 19.1 路径安全

所有下载和文件操作必须确认最终路径仍在允许根目录内。

### 19.2 日志安全

原脚本日志必须原样展示，但外围层不得额外记录：

- Cookie；
- Authorization Header；
- 登录密码；
- 身份证完整号码；
- 页面 LocalStorage；
- Chrome Profile 内容。

### 19.3 API 安全

- 校验请求参数；
- 限制上传扩展名；
- 限制单文件大小；
- 防止路径穿越；
- 同一时间只运行一个任务；
- 不允许任意脚本路径；
- `task_key` 使用固定白名单；
- Chrome 路径只能作为参数数组传递。

---

## 20. 测试要求

所有测试不得访问真实自然人电子税务局。

所有测试不得启动真实 Chrome。

所有测试不得执行真实 Playwright 页面操作。

### 20.1 受保护文件测试

文件：

```text
backend/tests/test_rpa_protected_files.py
```

测试：

- 每个文件存在；
- SHA-256 与基线一致；
- 没有缺失；
- 没有被误改。

### 20.2 命令构造测试

文件：

```text
backend/tests/test_rpa_commands.py
```

覆盖：

1. 专项附加导出全部机构；
2. 专项附加导出单机构；
3. 专项附加导出从失败机构继续；
4. 导入全部机构；
5. 导入单机构；
6. 导入 `--resume`；
7. 导入 `--reset-progress`；
8. 完税证明月份加一；
9. `2026-12 -> 2027-01`；
10. 综合所得申报表月份不变；
11. Windows 带空格路径；
12. 中文路径；
13. 所有命令是 list；
14. 不使用 `shell=True`；
15. 不出现原脚本不支持的参数。

### 20.3 日志解析测试

文件：

```text
backend/tests/test_rpa_log_parser.py
```

使用原日志样例测试：

```text
开始处理单位：机构A（11818）
单位处理完成：机构A -> D:\output\a.xlsx
开始处理申报导入：机构A（11818）
文件导入成功：11818_工资薪金.xlsx
机构申报导入完成：机构A（11818）
开始下载完税证明：机构A（11818）
机构完税证明下载完成：机构A（11818），共 2 个文件
开始下载综合所得申报表：机构A（11818）
机构综合所得申报表下载完成：机构A（11818），共 1 个文件
未查询到缴款记录，跳过完税证明下载：机构A（11818）
```

验证状态和数量。

### 20.4 进程管理测试

文件：

```text
backend/tests/test_rpa_process_manager.py
```

使用 mock：

- 启动成功；
- 重复启动被拒绝；
- stdout 读取；
- stderr 读取；
- 退出码 0；
- 非 0 退出；
- 当前机构失败；
- 无当前机构时失败；
- terminate；
- taskkill fallback；
- 取消状态；
- 状态持久化；
- 应用重启后清理遗留 running 状态。

### 20.5 API 测试

文件：

```text
backend/tests/test_rpa_api.py
```

覆盖：

- 获取状态；
- 保存 Chrome 路径；
- 上传有效机构 Excel；
- 拒绝非 Excel；
- 机构预览；
- Chrome 未 ready 时拒绝启动任务；
- 参数错误；
- 启动任务立即返回；
- 停止任务；
- 续跑；
- 日志 offset；
- 安全下载；
- 路径穿越被拒绝。

### 20.6 前端验证

至少执行：

```bash
cd frontend
npm run build
```

如仓库已有类型检查：

```bash
npm run typecheck
```

### 20.7 原仓库回归

必须执行：

```bash
cd backend
python -m pytest -q
```

不能只执行新增 RPA 测试。

---

## 21. 推荐实施顺序

### 阶段 1：检查和保护

- [ ] 阅读本文档；
- [ ] 检查目标仓库实际结构；
- [ ] 放入原始 RPA 文件；
- [ ] 校验 SHA-256；
- [ ] 确认 Git 无原文件修改；
- [ ] 不启动任何真实税务任务。

### 阶段 2：只读运行时复制

- [ ] 新增 `protected_files.py`；
- [ ] 新增 `runtime.py`；
- [ ] 创建可写运行目录；
- [ ] 测试文件复制和哈希；
- [ ] 确认业务文件不会写进 vendor。

### 阶段 3：命令和日志

- [ ] 新增 `commands.py`；
- [ ] 新增月份加一函数；
- [ ] 新增 `log_parser.py`；
- [ ] 完成单元测试；
- [ ] 对照 `etax_gui.py` 逐条确认。

### 阶段 4：进程管理

- [ ] 新增 `state_store.py`；
- [ ] 新增 `process_manager.py`；
- [ ] 实现单任务互斥；
- [ ] 实现 stdout/stderr；
- [ ] 实现停止和进程树；
- [ ] 实现失败续跑；
- [ ] 全部使用 mock 测试。

### 阶段 5：API

- [ ] 新增 Schema；
- [ ] 新增 `/api/rpa`；
- [ ] 注册 router；
- [ ] 上传机构 Excel；
- [ ] 上传导入文件；
- [ ] Chrome 启动与状态；
- [ ] 任务启动、停止、续跑；
- [ ] 日志和输出下载；
- [ ] API 测试。

### 阶段 6：Vue GUI 迁移

- [ ] 新增 `EtaxRpa.vue`；
- [ ] 迁移操作参数；
- [ ] 迁移 5 个步骤；
- [ ] 迁移结果表；
- [ ] 迁移历史；
- [ ] 迁移日志工具栏；
- [ ] 加入 App 导航；
- [ ] 增加 api.ts 类型和方法；
- [ ] 最小化增加样式；
- [ ] 构建验证。

### 阶段 7：打包

- [ ] 后端增加 Playwright；
- [ ] 桌面依赖增加 Playwright；
- [ ] PyInstaller 收集 vendor 文件；
- [ ] 运行时复制兼容打包；
- [ ] 不打包业务数据；
- [ ] 不修改原 `build_exe.ps1`。

### 阶段 8：最终校验

- [ ] 全部后端测试；
- [ ] 前端构建；
- [ ] 原 RPA 文件哈希再次校验；
- [ ] `git diff -- backend/vendor/etax_rpa` 为空；
- [ ] 输出修改文件清单；
- [ ] 输出人工验证步骤。

---

## 22. 禁止 Codex 自行作出的设计决定

以下内容没有用户授权，禁止擅自实施：

- 把原 RPA 改成 async Playwright；
- 把同步 Playwright 改成 Selenium；
- 修改滑块处理；
- 修改税务页面 CSS 选择器；
- 修改下载命名；
- 修改机构 Excel 表头支持；
- 自动登录；
- 自动验证码；
- 增加 Redis；
- 增加 Celery；
- 增加消息队列；
- 增加云端执行；
- 并发处理多个机构；
- 并发运行多个 RPA；
- 改造现有 Job 数据库；
- 将 RPA 强行注册成普通 workflow；
- 删除原 GUI 文件；
- 运行原 GUI 作为子窗口；
- 在 Vue 中嵌套 PyQt；
- 改变前端任务顺序；
- 改变中文按钮和状态；
- 自动清空 output；
- 自动删除 Chrome Profile；
- 把真实机构 Excel 提交 Git。

遇到不明确问题时，优先：

```text
保持原行为
最小改动
外围适配
不碰原脚本
```

---

## 23. 验收标准

### 23.1 源码保护

- [ ] 10 个受保护文件 SHA-256 全部一致；
- [ ] 受保护目录 Git diff 为空；
- [ ] 没有自动格式化；
- [ ] 原 GUI 和三个后台脚本未改。

### 23.2 Chrome

- [ ] 页面能启动原 PowerShell；
- [ ] 能显示 CDP ready；
- [ ] 用户可手工登录；
- [ ] 不自动保存凭据；
- [ ] 不重复启动调试 Chrome。

### 23.3 前端

- [ ] 页面整体布局接近原 GUI；
- [ ] 操作参数完整；
- [ ] 5 个步骤顺序一致；
- [ ] 结果表列一致；
- [ ] 历史列一致；
- [ ] 日志按钮一致；
- [ ] 状态中文一致；
- [ ] 运行中控件禁用正确。

### 23.4 任务

- [ ] 专项导出命令正确；
- [ ] 导入命令正确；
- [ ] 完税证明月份正确加一；
- [ ] 综合所得月份不变；
- [ ] 单机构正确；
- [ ] 全部机构正确；
- [ ] 停止正确；
- [ ] 从失败继续正确；
- [ ] stdout/stderr 实时显示；
- [ ] 输出文件可以安全下载。

### 23.5 回归

- [ ] 原后端测试通过；
- [ ] 新 RPA 测试通过；
- [ ] 前端 build 通过；
- [ ] 原有工作流不受影响；
- [ ] 原有任务中心不受影响；
- [ ] 原有期间逻辑不受影响；
- [ ] Windows 打包不丢失 RPA 源文件。

---

## 24. Codex 最终回复格式

完成后必须输出：

1. 实施摘要；
2. 新增文件列表；
3. 修改文件列表；
4. 前端迁移内容；
5. 外围适配层说明；
6. 新增 API 列表；
7. 四类 RPA 命令示例；
8. 测试命令及结果；
9. 打包说明；
10. 人工验证步骤；
11. 未完成内容；
12. 受保护文件 SHA-256 对比表。

受保护文件表格格式：

| 文件 | 修改前 SHA-256 | 修改后 SHA-256 | 结果 |
|---|---|---|---|
| ... | ... | ... | 一致 |

---

## 25. 给 Codex 的最终执行指令

请按本文档实施。

再次强调：

> 用户提供的 RPA 文件已经测试完成。  
> 这些文件一个字符都不能修改。  
> `etax_gui.py` 只用于迁移界面和复制交互行为。  
> 三个 Playwright 脚本只能作为黑盒子进程调用。  
> 目标仓库只新增薄适配层和 Vue 页面。  
> 不重构原 RPA，不优化原 RPA，不修复原 RPA。  
> 前端尽量保持原 GUI 的字段、任务顺序、状态、确认流程和日志规则。  
> 完工后必须用 SHA-256 和 Git diff 证明原文件没有变化。
