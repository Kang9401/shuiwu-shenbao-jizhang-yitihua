$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$env:NO_PROXY = "*"
$env:no_proxy = "*"

python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "Default PyPI install failed. Retry with Tsinghua mirror."
    python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
}

New-Item -ItemType Directory -Force -Path ".\dist" | Out-Null

$commonArgs = @(
    "--onefile",
    "--clean",
    "--collect-all", "playwright",
    "--exclude-module", "pandas",
    "--exclude-module", "numpy",
    "--exclude-module", "scipy",
    "--exclude-module", "lxml",
    "--exclude-module", "matplotlib",
    "--exclude-module", "PIL"
)

python -m PyInstaller @commonArgs --name etax_batch_import etax_batch_import.py
if ($LASTEXITCODE -ne 0) { throw "build etax_batch_import failed" }
python -m PyInstaller @commonArgs --name etax_batch_export etax_batch_export.py
if ($LASTEXITCODE -ne 0) { throw "build etax_batch_export failed" }
python -m PyInstaller @commonArgs --name etax_tax_certificate_download etax_tax_certificate_download.py
if ($LASTEXITCODE -ne 0) { throw "build etax_tax_certificate_download failed" }
python -m PyInstaller @commonArgs --name etax_gui etax_gui.py
if ($LASTEXITCODE -ne 0) { throw "build etax_gui failed" }
$friendlyExe = (-join ([char[]](0x4e2a, 0x7a0e, 0x7533, 0x62a5))) + ".exe"
Copy-Item -Force ".\dist\etax_gui.exe" ".\dist\$friendlyExe"

Copy-Item -Force ".\start_debug_chrome.ps1" ".\dist\start_debug_chrome.ps1"
Get-ChildItem -Path "." -Filter "*.md" | ForEach-Object {
    Copy-Item -Force $_.FullName ".\dist\$($_.Name)"
}
Get-ChildItem -Path "." -Filter "*.xlsx" | Where-Object { $_.Name -notlike "~$*" } | ForEach-Object {
    Copy-Item -Force $_.FullName ".\dist\$($_.Name)"
}
New-Item -ItemType Directory -Force -Path ".\dist\input" | Out-Null
if (Test-Path ".\dist\output") {
    Remove-Item -LiteralPath ".\dist\output" -Recurse -Force
}
New-Item -ItemType Directory -Force -Path ".\dist\output" | Out-Null

Write-Host ""
Write-Host "Build complete. Files are in dist:"
Write-Host "  dist\etax_gui.exe"
Write-Host "  dist\etax_batch_import.exe"
Write-Host "  dist\etax_batch_export.exe"
Write-Host "  dist\etax_tax_certificate_download.exe"
Write-Host "  dist\start_debug_chrome.ps1"
Write-Host "  dist\*.md"
Write-Host "  dist\*.xlsx"
Write-Host "  dist\input\"
Write-Host "  dist\output\"
