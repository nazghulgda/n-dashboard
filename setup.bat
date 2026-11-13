@echo off
rem setup.bat - creates the .venv virtual environment and installs the libraries (Windows)
setlocal
cd /d "%~dp0"

rem Python 3.10+ with tkinter and the GIL. The free-threaded build (python3.xxt), which
rem "py -3" may pick, is skipped: tkinter and PyInstaller are not reliable with it.
set "CHECK=import sys, tkinter, venv; sys.exit(0 if sys.version_info >= (3, 10) and getattr(sys, '_is_gil_enabled', lambda: True)() else 1)"
set "PY="
py -3 -c "%CHECK%" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "%CHECK%" >nul 2>&1 && set "PY=python"

if not defined PY (
    echo ERROR: Python 3.10 or newer with tkinter was not found.
    echo Install it from https://www.python.org/downloads/ - keep "tcl/tk and IDLE" selected.
    echo The free-threaded build ^(python3.xxt^) does not work, use the standard one.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment .venv ...
    %PY% -m venv .venv || goto :error
)

".venv\Scripts\python.exe" -m pip install -U pip || goto :error
".venv\Scripts\python.exe" -m pip install -U -r requirements.txt pyinstaller || goto :error

echo.
echo Setup finished.
echo   Run the application:   .venv\Scripts\pythonw.exe main_window.pyw
echo   Build the executable:  build.bat
pause
exit /b 0

:error
echo.
echo ERROR: setup failed - see the messages above.
pause
exit /b 1
