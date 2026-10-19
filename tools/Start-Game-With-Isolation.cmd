@echo off
setlocal
call "%~dp0Prepare-IAS-Handoff.cmd" "%~1"
if errorlevel 1 exit /b %errorlevel%
start "" "steam://rungameid/553850"
