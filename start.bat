@echo off
setlocal
cd /d "%~dp0"
title Sidestick Edit

if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_CMD="%~dp0.venv\Scripts\python.exe""
    goto :python_found
)
if exist "%~dp0venv\Scripts\python.exe" (
    set "PYTHON_CMD="%~dp0venv\Scripts\python.exe""
    goto :python_found
)

where py >nul 2>nul
if not errorlevel 1 (
    py -3 --version >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=py -3"
        goto :python_found
    )
)

where python >nul 2>nul
if not errorlevel 1 (
    python --version >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=python"
        goto :python_found
    )
)

echo Python 3 was not found. Install Python 3 and enable the Python Launcher or add Python to PATH.
pause
exit /b 1

:python_found
%PYTHON_CMD% -c "import PyQt5, pyqtgraph, numpy, yaml" >nul 2>nul
if errorlevel 1 (
    echo Installing application dependencies from requirements.txt...
    %PYTHON_CMD% -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo.
        echo Dependency installation failed. Check your internet connection and try again.
        pause
        exit /b 1
    )
)

%PYTHON_CMD% "%~dp0main.py"

:finish
if errorlevel 1 (
    echo.
    echo The application exited with an error.
    pause
    exit /b 1
)
