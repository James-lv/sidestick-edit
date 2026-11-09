@echo off
setlocal
cd /d "%~dp0"
title Sidestick Edit

if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON=%~dp0.venv\Scripts\python.exe"
) else if exist "%~dp0venv\Scripts\python.exe" (
    set "PYTHON=%~dp0venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python was not found. Install Python or create a .venv/venv in this folder.
        pause
        exit /b 1
    )
    set "PYTHON=python"
)

"%PYTHON%" "%~dp0main.py"
if errorlevel 1 (
    echo.
    echo The application exited with an error.
    pause
    exit /b 1
)
