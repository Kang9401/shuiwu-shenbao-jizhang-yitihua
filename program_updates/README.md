# 程序稳定更新目录

本目录用于维护可发布到 GitHub 的稳定版本信息和更新说明。

- 源码仍在仓库原有的 `backend/`、`frontend/` 等目录维护，不在这里重复复制。
- 业务 Excel、SQLite/MySQL 数据文件、RPA 运行数据和浏览器 Profile 不得提交。
- 大体积安装包不直接提交到 Git，应在打包方案稳定后上传到 GitHub Releases。
- `manifest.json` 记录当前稳定源码版本；正式发布安装包时再填写下载地址和 SHA-256。
