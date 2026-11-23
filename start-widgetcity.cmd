@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m widgetcity
    exit /b
)
where pyw >nul 2>&1
if not errorlevel 1 (
    start "" pyw -m widgetcity
    exit /b
)
echo Install Python and create the .venv environment first. See README.md.
pause
