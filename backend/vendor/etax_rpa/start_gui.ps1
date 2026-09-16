$ErrorActionPreference = "Stop"

if (Test-Path ".\etax_gui.exe") {
    Start-Process -FilePath ".\etax_gui.exe"
    exit
}

if (Test-Path ".\dist\etax_gui.exe") {
    Start-Process -FilePath ".\dist\etax_gui.exe"
    exit
}

python .\etax_gui.py
