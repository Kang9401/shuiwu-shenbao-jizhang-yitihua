param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$PythonExe = "python.exe",
    [switch]$SkipTests,
    [switch]$ReuseDesktopBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$ReleaseBase = Join-Path $Root "release"
$VersionOutput = Join-Path $ReleaseBase $Version
$StagingOutput = Join-Path $ReleaseBase ".staging-$Version-$PID"
$PreviousOutput = Join-Path $ReleaseBase ".previous-$Version-$PID"
$PackageDir = Join-Path $StagingOutput "TaxWorkbench"
$SmokeData = Join-Path $StagingOutput "smoke-data"
$RpaHelperOutput = Join-Path $Root "build\rpa_helpers"
$RpaHelperWork = Join-Path $Root "build\rpa-pyinstaller"
$RpaHelperSpecs = Join-Path $Root "build\rpa-specs"
$env:PYTHONUSERBASE = Join-Path $Root "build\python-userbase"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    $PythonCommand = Get-Command $PythonExe -ErrorAction SilentlyContinue
    if ($null -eq $PythonCommand) {
        throw "Python executable not found: $PythonExe"
    }
    $PythonExe = $PythonCommand.Source
}

$VersionContent = Get-Content -Raw -Encoding UTF8 (Join-Path $Backend "app\core\version.py")
$VersionMatch = [regex]::Match($VersionContent, 'APP_VERSION\s*=\s*"([^"]+)"')
if (-not $VersionMatch.Success) {
    throw "Cannot read APP_VERSION"
}
$CodeVersion = $VersionMatch.Groups[1].Value
if ($CodeVersion -ne $Version) {
    throw "Requested version $Version does not match code version $CodeVersion"
}

$ReleaseFull = [System.IO.Path]::GetFullPath($ReleaseBase)
$OutputFull = [System.IO.Path]::GetFullPath($VersionOutput)
$StagingFull = [System.IO.Path]::GetFullPath($StagingOutput)
if (
    -not $OutputFull.StartsWith($ReleaseFull, [System.StringComparison]::OrdinalIgnoreCase) -or
    -not $StagingFull.StartsWith($ReleaseFull, [System.StringComparison]::OrdinalIgnoreCase)
) {
    throw "Release path is outside release root: $OutputFull"
}
New-Item -ItemType Directory -Path $ReleaseBase -Force | Out-Null
if (Test-Path -LiteralPath $StagingOutput) {
    Remove-Item -LiteralPath $StagingOutput -Recurse -Force
}
New-Item -ItemType Directory -Path $PackageDir -Force | Out-Null

if (-not $SkipTests) {
    Push-Location $Backend
    try { & $PythonExe -m pytest -q } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw "Backend tests failed" }
}

Push-Location $Frontend
try { & npm.cmd run build } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }

& $PythonExe (Join-Path $Root "packaging\generate_icon.py")
if ($LASTEXITCODE -ne 0) { throw "Icon generation failed" }
& $PythonExe (Join-Path $Root "packaging\generate_version_info.py")
if ($LASTEXITCODE -ne 0) { throw "Version resource generation failed" }

if (-not $ReuseDesktopBuild) {
    foreach ($Path in @($RpaHelperOutput, $RpaHelperWork, $RpaHelperSpecs)) {
        if (Test-Path -LiteralPath $Path) {
            Remove-Item -LiteralPath $Path -Recurse -Force
        }
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
    $RpaRunnerName = "etax_rpa_runner"
    $RpaRunnerWorkDir = Join-Path $RpaHelperWork $RpaRunnerName
    New-Item -ItemType Directory -Path $RpaRunnerWorkDir -Force | Out-Null
    & $PythonExe -s -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --collect-all playwright `
        --exclude-module pandas `
        --exclude-module numpy `
        --exclude-module scipy `
        --exclude-module lxml `
        --exclude-module matplotlib `
        --exclude-module PIL `
        --distpath $RpaHelperOutput `
        --workpath $RpaRunnerWorkDir `
        --specpath $RpaHelperSpecs `
        --name $RpaRunnerName `
        (Join-Path $Backend "app\rpa\runner.py")
    if ($LASTEXITCODE -ne 0) { throw "RPA runner build failed" }
    $RpaRunnerPath = Join-Path $RpaHelperOutput "$RpaRunnerName.exe"
    $RpaRunnerHash = Get-FileHash -Algorithm SHA256 -LiteralPath $RpaRunnerPath
    $RpaRunnerHash.Hash.ToLowerInvariant() | Set-Content -Encoding ASCII (Join-Path $RpaHelperOutput "$RpaRunnerName.sha256")
    Push-Location $Root
    try { & $PythonExe -s -m PyInstaller --noconfirm --clean (Join-Path $Root "packaging\TaxWorkbench.spec") } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }
}
if (-not (Test-Path -LiteralPath (Join-Path $Root "dist\TaxWorkbench\TaxWorkbench.exe"))) {
    throw "Desktop build output is missing"
}

Copy-Item -Path (Join-Path $Root "dist\TaxWorkbench\*") -Destination $PackageDir -Recurse -Force
Copy-Item -LiteralPath (Join-Path $Root "packaging\portable-readme.txt") -Destination $PackageDir -Force

$OldStorage = $env:STORAGE_ROOT
$OldBackup = $env:BACKUP_ROOT
try {
    $env:STORAGE_ROOT = $SmokeData
    $env:BACKUP_ROOT = (Join-Path $SmokeData "backups")
    $StartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $StartInfo.FileName = Join-Path $PackageDir "TaxWorkbench.exe"
    $StartInfo.Arguments = "--self-test"
    $StartInfo.UseShellExecute = $false
    $StartInfo.CreateNoWindow = $true
    $StartInfo.RedirectStandardOutput = $true
    $StartInfo.RedirectStandardError = $true
    $SelfTest = New-Object System.Diagnostics.Process
    $SelfTest.StartInfo = $StartInfo
    [void]$SelfTest.Start()
    $SelfTestOutput = $SelfTest.StandardOutput.ReadToEnd()
    $SelfTestError = $SelfTest.StandardError.ReadToEnd()
    $SelfTest.WaitForExit()
    Write-Host $SelfTestOutput
    if ($SelfTest.ExitCode -ne 0) {
        Write-Error $SelfTestError
        throw "Packaged application self-test failed"
    }
} finally {
    $env:STORAGE_ROOT = $OldStorage
    $env:BACKUP_ROOT = $OldBackup
}

$ZipPath = Join-Path $StagingOutput "TaxWorkbench_${Version}_Windows_x64.zip"
# Windows PowerShell Compress-Archive can race with Defender while scanning a new EXE.
# tar.exe is built into supported Windows versions and creates the same ZIP layout.
& tar.exe -a -c -f $ZipPath -C $StagingOutput "TaxWorkbench"
if ($LASTEXITCODE -ne 0) { throw "ZIP creation failed" }
$Hash = Get-FileHash -Algorithm SHA256 -LiteralPath $ZipPath
"$($Hash.Hash)  $([System.IO.Path]::GetFileName($ZipPath))" | Set-Content -Encoding UTF8 (Join-Path $StagingOutput "SHA256.txt")
if (Test-Path -LiteralPath $SmokeData) {
    Remove-Item -LiteralPath $SmokeData -Recurse -Force
}

if (Test-Path -LiteralPath $PreviousOutput) {
    Remove-Item -LiteralPath $PreviousOutput -Recurse -Force
}
$HadPrevious = Test-Path -LiteralPath $VersionOutput
if ($HadPrevious) {
    Move-Item -LiteralPath $VersionOutput -Destination $PreviousOutput
}
try {
    Move-Item -LiteralPath $StagingOutput -Destination $VersionOutput
    if ($HadPrevious -and (Test-Path -LiteralPath $PreviousOutput)) {
        Remove-Item -LiteralPath $PreviousOutput -Recurse -Force
    }
} catch {
    if (-not (Test-Path -LiteralPath $VersionOutput) -and (Test-Path -LiteralPath $PreviousOutput)) {
        Move-Item -LiteralPath $PreviousOutput -Destination $VersionOutput
    }
    throw
}

$FinalZip = Join-Path $VersionOutput "TaxWorkbench_${Version}_Windows_x64.zip"
Write-Host "Release completed: $FinalZip"
