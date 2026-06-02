@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM ngrok is installed via winget. If the command is not found, restart your terminal.
set "NGROK_EXE=ngrok"

echo Starting ngrok tunnel for http://127.0.0.1:8000 ...
echo - If this is your first run, set authtoken first:
echo     "%NGROK_EXE%" config add-authtoken YOUR_TOKEN
echo.
echo Webhook URL will be: https://xxxx.ngrok-free.app/webhooks/meta
echo.

REM Keep ngrok running in this window so you can see errors.
"%NGROK_EXE%" http 8000
