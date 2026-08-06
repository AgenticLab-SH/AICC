@echo off
setlocal
set "CM_REPO_ROOT=%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0cm.ps1" %*
exit /b %ERRORLEVEL%
