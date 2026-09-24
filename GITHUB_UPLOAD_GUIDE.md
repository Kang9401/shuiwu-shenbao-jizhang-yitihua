# GitHub 快速上传指引

适用于本仓库日常功能更新。默认将当前分支直接提交并推送到对应的 `origin` 远程分支，不重复执行全量文件、体积或敏感信息扫描。

## 固定排除项

以下目录及其内容不得暂存或上传：

- `storage/`
- `outputs/`
- `个税测试/`

同时保留现有 `.gitignore` 中的 `.env`、虚拟环境、依赖目录、缓存、构建产物和数据库文件排除规则。不要使用 `git add -f` 绕过这些规则。

## 一次性准备

本仓库只需配置一次作者信息：

```powershell
git config user.name "Kang9401"
git config user.email "87624910+Kang9401@users.noreply.github.com"
```

确认 GitHub CLI 已登录：

```powershell
gh auth status
```

若本机使用便携版 GitHub CLI，则替换为：

```powershell
& 'C:\tmp\github-cli\bin\gh.exe' auth status
```

## 日常快速同步

在项目根目录执行：

```powershell
git status --short --branch
git add -A
git commit -m "<本次更新说明>"
git push
```

如果没有新增或修改文件，`git commit` 会提示没有可提交内容，此时无需推送。

## 提交约定

- 新功能：`feat: <说明>`
- 问题修复：`fix: <说明>`
- 文档或配置：`docs: <说明>` 或 `chore: <说明>`

推送前只需确认当前分支是否正确；默认不合并、不改写 `main`，也不推送其他本地分支。

## 例外情况

如确实需要上传固定排除项中的文件，必须先单独说明文件用途和公开范围，再决定是否调整规则。不要把真实密钥写入代码、`.env` 或提交历史。
