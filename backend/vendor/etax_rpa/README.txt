自然人电子税务局自动化工具 - GitHub 源码包

一、源码包内容

本压缩包只包含系统源码和必要说明文件，适合上传到 GitHub：

1. etax_gui.py
   PyQt 图形化入口，负责参数配置、任务按钮、日志展示、任务结果表、执行历史和调用后台脚本。

2. etax_batch_export.py
   专项附加扣除导出后台脚本。

3. etax_batch_import.py
   个税申报导入后台脚本，并在导入后生成申报核对 Excel。

4. etax_tax_certificate_download.py
   完税证明下载、综合所得申报表下载后台脚本。

5. start_debug_chrome.ps1
   启动可被 CDP 接管的 Chrome，并打开自然人电子税务局。

6. build_exe.ps1
   使用 PyInstaller 打包 exe 的脚本。

7. requirements.txt
   Python 依赖清单。

8. 用户操作说明.md
   面向财务用户的操作说明。

二、未打包内容

以下内容不属于系统源码，已从本压缩包排除：

- dist/：已打包 exe 产物
- build/：PyInstaller 构建缓存
- output/：下载结果、任务历史、核对表等业务输出
- input/：导入用业务文件
- .chrome-debug-profile/、.chrome-etax-profile/：浏览器用户数据
- __pycache__/：Python 缓存
- 机构信息表.xlsx：机构业务清单
- 历史 zip、录屏、截图等临时或演示文件

三、本地开发运行

需要安装 Python 3.10+ 和 Google Chrome。

安装依赖：

python -m pip install -r requirements.txt

运行 GUI：

python etax_gui.py

四、打包 exe

在项目目录执行：

powershell -ExecutionPolicy Bypass -File .\build_exe.ps1

打包结果会生成到 dist 目录。

五、注意事项

本工具通过 Chrome CDP 连接本机浏览器，默认地址为：

http://127.0.0.1:9222

如果初始化失败，请在 GUI 中填写本机 chrome.exe 的完整路径后重新初始化。

不要把 output、input、浏览器 profile、真实机构清单或下载文件上传到公开仓库。
