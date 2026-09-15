@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
where py >nul 2>nul
if errorlevel 1 goto missing
py -3.11 -m venv .venv
if errorlevel 1 goto failed
:install
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" server.py
pause
exit /b
:missing
echo Install Python 3.11 from https://www.python.org/downloads/windows/
pause
exit /b 1
:failed
echo Setup failed. Check Python 3.11 installation and network access.
pause
exit /b 1
