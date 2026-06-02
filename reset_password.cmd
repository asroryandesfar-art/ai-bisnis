@echo off
setlocal
cd /d "%~dp0"

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

set /p EMAIL="Email yang mau direset: "
set /p PASS="Password baru: "

python reset_password.py "%EMAIL%" "%PASS%"
echo.
pause

