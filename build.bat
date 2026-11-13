@echo off
rem build.bat - builds dist\WinDashboard.exe (Windows, one file)
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pyinstaller.exe" (
    echo ERROR: PyInstaller not found in .venv - run setup.bat first.
    pause
    exit /b 1
)

".venv\Scripts\pyinstaller.exe" --windowed --onefile --clean --noconfirm ^
    --name WinDashboard ^
    --icon assets\app.ico ^
    --add-data "assets\app.ico;assets" ^
    main_window.pyw || goto :error

echo.
echo Build finished: dist\WinDashboard.exe
exit /b 0

:error
echo.
echo ERROR: build failed - see the messages above.
echo If dist\WinDashboard.exe is running, close it and try again.
pause
exit /b 1
