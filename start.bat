@echo off
setlocal
cd /d "%~dp0"
title Sidestick Edit

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
set "PYTHON_EXE="
set "PYTHON_ARGS="

if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" --version >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=%VENV_PYTHON%"
        goto :python_found
    )
    echo The existing project environment is invalid or was copied from another computer.
    echo Recreating the project environment...
)

where py >nul 2>nul
if not errorlevel 1 (
    py -3 --version >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3"
        goto :create_venv
    )
)

where python >nul 2>nul
if not errorlevel 1 (
    python --version >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=python"
        goto :create_venv
    )
)

for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
    if exist "%%~fD\python.exe" (
        "%%~fD\python.exe" --version >nul 2>nul
        if not errorlevel 1 (
            set "PYTHON_EXE=%%~fD\python.exe"
            goto :create_venv
        )
    )
)

echo Python 3 was not found.
echo Install Python 3, then run this file again.
echo If it is already installed, enable "Add Python to PATH".
echo Download: https://www.python.org/downloads/
goto :failed

:create_venv
echo Preparing the project environment...
"%PYTHON_EXE%" %PYTHON_ARGS% -m venv --clear "%~dp0.venv"
if errorlevel 1 (
    echo Failed to create the project virtual environment.
    goto :failed
)
set "PYTHON_EXE=%VENV_PYTHON%"
set "PYTHON_ARGS="

:python_found
"%PYTHON_EXE%" -c "import PyQt5, pyqtgraph, numpy, yaml" >nul 2>nul
if errorlevel 1 (
    echo Installing application dependencies...
    "%PYTHON_EXE%" -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo.
        echo Dependency installation failed.
        echo Check your internet connection and try again.
        goto :failed
    )
)

"%PYTHON_EXE%" "%~dp0main.py" %*
if errorlevel 1 (
    echo.
    echo The application exited with an error.
    goto :failed
)
exit /b 0

:failed
echo.
pause
exit /b 1
