# Windows 桌面版打包指南

本文记录 TaxWorkbench Windows 桌面版的实际打包流程、关键实现和已验证的故障处理方法。目标是让后续发布可直接复用，避免重复排查 Python 3.12、PyInstaller、WebView2 和 RPA 资源问题。

## 1. 当前打包方案

- Python：3.12，当前使用 `E:\python项目\Learn\env\Scripts\python.exe`
- 前端：Vue + Vite，先生成 `frontend/dist`
- 桌面容器：pywebview，Windows 使用 WebView2/WinForms 后端
- 本地服务：FastAPI + Uvicorn，仅监听随机分配的 `127.0.0.1` 端口
- 主程序：PyInstaller `onedir` 模式，入口为 `backend/desktop.py`
- RPA 助手：PyInstaller `onefile` 模式，每个脚本生成一个独立 EXE
- 发布形式：便携目录 + ZIP + SHA256 文件
- 用户数据：默认保存在 `%LOCALAPPDATA%\TaxWorkbench`，不放在程序目录内

主要文件：

| 文件 | 用途 |
| --- | --- |
| `scripts/build_release.ps1` | 完整发布流程、测试、自检、压缩和原子替换 |
| `packaging/TaxWorkbench.spec` | 主桌面程序的 PyInstaller 配置 |
| `backend/desktop.py` | 桌面入口和 `--self-test` 自检入口 |
| `packaging/portable-readme.txt` | 随便携包交付的使用说明 |
| `backend/app/core/version.py` | 应用版本号来源 |

## 2. 发布包包含的 RPA 内容

打包脚本只生成一个共享助手 `etax_rpa_runner.exe`。它通过任务键运行已复制到 RPA 运行目录的原始脚本，Python、Playwright 和 OpenPyXL 只打包一次：

| runner 任务键 | 实际脚本 |
| --- | --- |
| `import` | `backend/vendor/etax_rpa/etax_batch_import.py` |
| `special_deduction` | `backend/vendor/etax_rpa/etax_batch_export.py` |
| `tax_certificate` / `income_report` | `backend/vendor/etax_rpa/etax_tax_certificate_download.py` |
| `extra_income_reports` | `backend/app/rpa/extensions/etax_extra_income_reports.py` |

主程序还必须包含：

- `backend/vendor/etax_rpa`：受保护的 RPA 原始程序
- `app/rpa/extensions`：项目自有 RPA 扩展
- `rpa_helpers`：`etax_rpa_runner.exe` 及其 SHA256 清单
- `frontend_dist`：已构建的前端静态资源

这些路径由 `packaging/TaxWorkbench.spec` 的 `datas` 配置复制到 `TaxWorkbench\_internal`。

注意：不要为解决打包问题直接修改 `backend/vendor/etax_rpa/**`。这些文件带有哈希校验，修改后会导致 RPA 运行时自检失败。项目自有功能应放到 `backend/app/rpa/extensions`。

## 3. 首次或正式全量打包

先确认 `backend/app/core/version.py` 中的 `APP_VERSION` 与命令参数完全一致。然后在项目根目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_release.ps1 `
  -Version 0.9.0 `
  -PythonExe 'E:\python项目\Learn\env\Scripts\python.exe'
```

全量流程会依次执行：

1. 校验代码版本号。
2. 运行后端测试 `pytest -q`。
3. 运行前端生产构建 `npm.cmd run build`。
4. 生成应用图标和 Windows 版本资源。
5. 清理并重新生成共享 RPA runner 及其 SHA256 清单。
6. 根据 `TaxWorkbench.spec` 重新生成主桌面程序。
7. 复制到发布暂存目录。
8. 执行打包后主程序的 `--self-test`。
9. 生成 ZIP 和 SHA256。
10. 自检全部成功后，原子替换 `release/<版本号>`。

正式发布建议不要使用 `-SkipTests` 或 `-ReuseDesktopBuild`。

## 4. 节省时间的重试方法

### 4.1 测试已通过，但完整构建中途失败

如果本轮代码未再变化，而且后端测试已经通过，可跳过重复测试：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_release.ps1 `
  -Version 0.9.0 `
  -PythonExe 'E:\python项目\Learn\env\Scripts\python.exe' `
  -SkipTests
```

前端仍会重新构建，RPA 助手和主程序也会重新生成。

### 4.2 只有发布装配或压缩失败

只有在以下文件均未变化时，才可复用现有桌面构建：

- `backend/**`
- `frontend/**`
- `packaging/TaxWorkbench.spec`
- RPA 脚本和扩展
- Python 依赖

命令：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_release.ps1 `
  -Version 0.9.0 `
  -PythonExe 'E:\python项目\Learn\env\Scripts\python.exe' `
  -SkipTests `
  -ReuseDesktopBuild
```

`-ReuseDesktopBuild` 会直接复用 `dist\TaxWorkbench` 和 `build\rpa_helpers`。如果修改了 `backend/desktop.py` 或其他后端代码，直接使用该参数会把旧代码打进发布包。

### 4.3 修改了主程序，但 RPA 助手已经成功生成

可只重建主程序，再复用构建结果完成发布：

```powershell
$env:PYTHONUSERBASE = Join-Path (Get-Location) 'build\python-userbase'
& 'E:\python项目\Learn\env\Scripts\python.exe' -s -m PyInstaller `
  --noconfirm --clean .\packaging\TaxWorkbench.spec

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_release.ps1 `
  -Version 0.9.0 `
  -PythonExe 'E:\python项目\Learn\env\Scripts\python.exe' `
  -SkipTests `
  -ReuseDesktopBuild
```

该方式可避免再次构建约 48 MB 的共享 RPA runner。

## 5. Python 3.12 / PyInstaller 权限问题

### 现象

即使使用 `python -s`，PyInstaller 6.21 仍可能报错：

```text
PermissionError: [WinError 5] Access denied:
C:\Users\Admin\AppData\Roaming\Python\Python312\site-packages
```

### 原因

PyInstaller 的二进制依赖扫描会无条件调用 `site.getusersitepackages()`。`-s` 只禁止用户站点进入 `sys.path`，不能阻止 PyInstaller 枚举这个目录。

### 已实施的解决方法

`scripts/build_release.ps1` 将本次构建的用户站点重定向到项目内：

```powershell
$env:PYTHONUSERBASE = Join-Path $Root "build\python-userbase"
```

同时所有 PyInstaller 调用都使用：

```powershell
& $PythonExe -s -m PyInstaller ...
```

不要通过修改全局 Python 配置或放宽用户目录权限来规避此问题。项目内 `PYTHONUSERBASE` 更可控，也不会污染系统环境。

## 6. 桌面自检设计

发布脚本不是只检查 EXE 是否存在，而是实际运行：

```powershell
TaxWorkbench.exe --self-test
```

当前自检覆盖：

- 用户数据目录可创建和写入
- SQLite 数据库可初始化
- 前端 `index.html` 已打包
- 本地 Uvicorn 服务可启动并通过 `/health`
- 前端首页可通过 HTTP 读取
- pywebview WinForms 后端可导入
- RPA 受保护源文件哈希正确
- RPA 扩展文件存在且哈希正确
- RPA 运行目录可生成
- 共享 RPA runner 已按 SHA256 清单复制到运行目录

### RPA runner 的安装和升级规则

`ensure_runtime_app()` 会读取随包发布的 `etax_rpa_runner.sha256`：

- runner 不存在、哈希版本变化或文件大小变化时才复制
- 复制完成后校验目标文件 SHA256
- runner 未变化时直接跳过，不再每次启动覆盖写入 EXE
- 新 runner 安装成功后删除旧版四个生成型助手 EXE
- `input`、`output`、机构配置和业务数据不会被删除

旧方案每次启动会覆盖复制四个 EXE，总计约 194.5 MB，在杀毒软件扫描时可能超过服务的 20 秒等待时间。共享 runner 将首次复制量降到约 48 MB，正常二次启动不再复制；桌面服务等待时间也调整为 60 秒。

### pywebview 窗口卡死问题

不要在传给 `js_api` 的对象中保存 pywebview `Window` 或 WinForms 原生窗口。pywebview 会遍历公开属性，进而递归访问：

```text
monitor_window.native.AccessibilityObject.Bounds.Empty...
maximum recursion depth exceeded
```

当前实现把监控窗口保存在 `backend/desktop.py` 的模块内部，`DesktopWindowManager` 只暴露 `open_rpa_monitor()` 和 `hide_rpa_monitor()` 两个方法。修改桌面桥接 API 时必须维持这个边界。

### RPA 日志乱码和“单位办税”入口超时

PyInstaller runner 在 Windows 管道中可能仍按系统代码页输出，即使父进程设置了 `PYTHONIOENCODING=utf-8`。因此 `backend/app/rpa/runner.py` 会在执行业务脚本前显式调用 `stdout/stderr.reconfigure(encoding="utf-8")`。不要移除这一步，否则任务监控日志和 Playwright 错误中的中文可能显示为 `���`。

电子税务局首页可能保留“单位办税”DOM 节点，但在当前登录身份没有扣缴端权限时将其父元素设为 `display: none`。只延长 Playwright 等待时间不能解决这个问题。项目通过 `etax_runtime_compat.py` 实现以下兼容行为：

- 优先复用已经打开的 `withholding/index.html` 扣缴端标签页
- “单位办税”可见时按原流程进入
- 节点存在但被隐藏时立即提示切换到具有扣缴端权限的单位办税身份
- 不通过 JavaScript 强行点击隐藏入口，不绕过税局权限控制

运行申报结果下载前，应确认 Chrome 中实际可见“单位办税”，或已经手工打开单位办税扣缴端。只看到个人首页和个人姓名不代表扣缴端权限已经就绪。

### 为什么不在自动自检中创建隐藏 WebView2 窗口

无交互构建会话中，pywebview 可能无法真正创建浏览器进程，并出现：

```text
[pywebview] Failed to delete user data folder: 'NoneType' object has no attribute 'BrowserProcessId'
WebView2 页面加载超时
```

这不是主程序、前端或 RPA 打包失败，而是隐藏 GUI 探测依赖交互式桌面会话。当前自动自检改为验证 WinForms 后端可加载；正式交付前仍应人工双击一次 `TaxWorkbench.exe`，确认主窗口正常显示。

## 7. 发布安全设计

发布脚本使用以下目录：

- 暂存：`release/.staging-<版本>-<PID>`
- 旧版本临时备份：`release/.previous-<版本>-<PID>`
- 最终目录：`release/<版本>`

只有构建、自检、压缩和哈希全部成功后，暂存目录才会移动到最终目录。若替换失败，脚本会尝试恢复旧版本。因此，失败构建不会直接覆盖一个可用发布包。

失败后可能留下 `.staging-*` 目录。确认没有构建进程正在使用后再删除，不要清空整个 `release` 目录。

## 8. 发布结果和验证清单

成功后应生成：

```text
release/<版本>/
├── TaxWorkbench/
│   ├── TaxWorkbench.exe
│   ├── portable-readme.txt
│   └── _internal/
├── TaxWorkbench_<版本>_Windows_x64.zip
└── SHA256.txt
```

建议执行以下检查：

```powershell
$release = Resolve-Path 'release\0.9.0'

Get-Item `
  "$release\TaxWorkbench\TaxWorkbench.exe", `
  "$release\TaxWorkbench_0.9.0_Windows_x64.zip", `
  "$release\SHA256.txt"

Get-ChildItem "$release\TaxWorkbench\_internal\rpa_helpers" -Filter *.exe

Test-Path "$release\TaxWorkbench\_internal\backend\vendor\etax_rpa"
Test-Path "$release\TaxWorkbench\_internal\app\rpa\extensions\etax_extra_income_reports.py"

Get-Content "$release\SHA256.txt"
Get-FileHash -Algorithm SHA256 "$release\TaxWorkbench_0.9.0_Windows_x64.zip"

git diff --exit-code -- backend\vendor\etax_rpa
git diff --check
```

验收标准：

- 主程序、ZIP 和 `SHA256.txt` 都存在
- `rpa_helpers` 中只有 `etax_rpa_runner.exe` 和 `etax_rpa_runner.sha256`
- RPA vendor 和 extension 目录都存在
- 实际 ZIP 哈希与 `SHA256.txt` 一致
- `backend/vendor/etax_rpa` 没有被修改
- `git diff --check` 没有空白错误
- 人工启动主窗口正常
- 目标电脑已安装 Google Chrome
- RPA 启动的 Chrome 窗口允许用户手动登录自然人电子税务局

## 9. 版本升级时的操作顺序

1. 修改 `backend/app/core/version.py` 中的 `APP_VERSION`。
2. 更新 `CHANGELOG.md` 和必要的用户说明。
3. 运行后端测试和前端构建。
4. 使用新版本号执行完整发布脚本。
5. 核对共享 RPA runner、哈希清单和打包资源。
6. 比对 ZIP SHA256。
7. 在正常 Windows 桌面会话中人工启动程序。
8. 用干净测试数据执行一次关键业务流程和 RPA 启动检查。

## 10. 0.9.0 共享 runner 构建记录

- Python：3.12.13
- PyInstaller：6.21.0
- 后端测试：123 passed
- 前端生产构建：通过
- 打包后 `--self-test`：通过
- 真实桌面窗口：启动后持续响应，未再出现 pywebview 递归错误
- RPA runner 外部脚本加载：通过，中文帮助输出正常
- RPA runner：`48,593,360` 字节（46.34 MiB）
- 旧版四助手总计：`194,480,918` 字节
- 助手体积降幅：约 75%
- ZIP：`110,077,953` 字节（104.98 MiB），较旧 ZIP 减少约 56.8%
- ZIP：`release/0.9.0/TaxWorkbench_0.9.0_Windows_x64.zip`
- ZIP SHA256：`69CAFAA4272DB915DF16580CB9F74F2E947297F9D7865063683CFF5AFEB098F5`

后续若代码或依赖变化，应以新构建生成的测试数量、文件大小和 SHA256 为准，不要沿用本节数值。
