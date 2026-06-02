$ErrorActionPreference = 'Stop'

Set-Location $PSScriptRoot

# Pastikan output tidak nabrak encoding console Windows
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

Write-Host "Starting BotNesia API on http://127.0.0.1:8000 ..."
python run_server.py
