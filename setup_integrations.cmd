@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================
echo BotNesia - Setup Integrations (Local)
echo ============================================
echo.
echo Paste values when asked. Leave blank to keep existing value.
echo Note: Don't share these secrets in chat/screenshots.
echo.

set /p GROQ_API_KEY=GROQ_API_KEY (GroqCloud, starts with gsk_): 
set /p GROQ_MODEL=GROQ_MODEL (default: llama-3.3-70b-versatile): 
set /p GMAIL_CLIENT_ID=GMAIL_CLIENT_ID (Google OAuth Client ID): 
set /p GMAIL_CLIENT_SECRET=GMAIL_CLIENT_SECRET (Google OAuth Client Secret): 
set /p GMAIL_REDIRECT_URI=GMAIL_REDIRECT_URI (default: http://127.0.0.1:8000/integrations/gmail/callback): 
set /p META_VERIFY_TOKEN=META_VERIFY_TOKEN (Meta webhook verify token, any random string): 

if "%GROQ_MODEL%"=="" set GROQ_MODEL=llama-3.3-70b-versatile
if "%GMAIL_REDIRECT_URI%"=="" set GMAIL_REDIRECT_URI=http://127.0.0.1:8000/integrations/gmail/callback

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p = Join-Path (Get-Location) '.env';" ^
  "if (!(Test-Path $p)) { New-Item -ItemType File -Path $p -Force | Out-Null }" ^
  "$lines = Get-Content $p -ErrorAction SilentlyContinue;" ^
  "function Set-EnvLine($k,$v){ if ([string]::IsNullOrWhiteSpace($v)) { return };" ^
  "  $re = '^\s*' + [regex]::Escape($k) + '\s*=';" ^
  "  $idx = -1; for($i=0;$i -lt $lines.Count;$i++){ if($lines[$i] -match $re){ $idx=$i; break } }" ^
  "  if($idx -ge 0){ $lines[$idx] = ($k + '=' + $v) } else { $lines += ($k + '=' + $v) } }" ^
  "Set-EnvLine 'GROQ_API_KEY' $env:GROQ_API_KEY;" ^
  "Set-EnvLine 'GROQ_MODEL' $env:GROQ_MODEL;" ^
  "Set-EnvLine 'GMAIL_CLIENT_ID' $env:GMAIL_CLIENT_ID;" ^
  "Set-EnvLine 'GMAIL_CLIENT_SECRET' $env:GMAIL_CLIENT_SECRET;" ^
  "Set-EnvLine 'GMAIL_REDIRECT_URI' $env:GMAIL_REDIRECT_URI;" ^
  "Set-EnvLine 'META_VERIFY_TOKEN' $env:META_VERIFY_TOKEN;" ^
  "Set-Content -Path $p -Value $lines -Encoding utf8;"

echo.
echo [OK] .env updated.
echo Restarting server...
call start_bg.cmd

echo.
echo Next:
echo - Dashboard: http://127.0.0.1:8000/dashboard
echo - Settings ^> Integrations: click Connect Gmail, and set Meta tokens.
echo.
pause
