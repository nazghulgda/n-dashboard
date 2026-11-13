@echo off
rem build.bat - builds dist\n-dashboard.exe (Windows, one file)
setlocal
cd /d "%~dp0"

rem python -m PyInstaller, not pyinstaller.exe: the .exe launcher keeps the absolute path
rem of the folder .venv was created in and breaks when the project folder is renamed
".venv\Scripts\python.exe" -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo ERROR: PyInstaller not found in .venv - run setup.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m PyInstaller --windowed --onefile --clean --noconfirm ^
    --name n-dashboard ^
    --icon assets\app.ico ^
    --add-data "assets\app.ico;assets" ^
    main_window.pyw || goto :error

echo.
echo Build finished: dist\n-dashboard.exe
exit /b 0

:error
echo.
echo ERROR: build failed - see the messages above.
echo If dist\n-dashboard.exe is running, close it and try again.
pause
exit /b 1
