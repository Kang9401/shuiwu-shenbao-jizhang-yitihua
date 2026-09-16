param(
    [string]$ChromePath = ""
)

$candidates = @(
    $ChromePath,
    "C:\Program Files\Google\Chrome\Application\chrome.exe",
    "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
) | Where-Object { $_ -and $_.Trim() -ne "" }

$chrome = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
$profile = Join-Path $PSScriptRoot ".chrome-debug-profile"

if (-not $chrome) {
    throw "找不到 Chrome。请在工具界面“Chrome地址”填写本机 chrome.exe 完整路径后重新初始化。已尝试路径：$($candidates -join '; ')"
}

New-Item -ItemType Directory -Force -Path $profile | Out-Null

Start-Process -FilePath $chrome -ArgumentList @(
    "--remote-debugging-port=9222",
    "--user-data-dir=$profile",
    "--start-maximized",
    "https://etax.chinatax.gov.cn/"
)

Write-Host "已启动可接管的 Chrome。"
Write-Host "Chrome 路径：$chrome"
Write-Host "已打开自然人电子税务局：https://etax.chinatax.gov.cn/"
Write-Host "请在该窗口手动登录业务系统，然后回到图形化工具点击对应任务按钮。"
