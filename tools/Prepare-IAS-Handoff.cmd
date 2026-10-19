@echo off
setlocal
set "taskGame=%~1"
if not defined taskGame set "taskGame=%~dp0.."
"%~dp0validate_runtime_profile.exe" --ias-prepare "%taskGame%"
exit /b %errorlevel%
