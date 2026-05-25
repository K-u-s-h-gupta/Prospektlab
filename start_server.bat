@echo off
REM ============================================================
REM ProspektLab Server Launcher (Windows .bat)
REM Always uses the correct virtual environment Python
REM ============================================================

setlocal

set VENV_PYTHON=D:\PROSPEKTLAB\.venv-prospektlab311b\Scripts\python.exe

if not exist "%VENV_PYTHON%" (
    echo [ERROR] Virtual environment Python not found at:
    echo %VENV_PYTHON%
    echo.
    echo Please ensure the venv exists or update the path in this script.
    pause
    exit /b 1
)

echo Starting ProspektLab gateway using venv Python...
echo.

"%VENV_PYTHON%" -m uvicorn finagent.gateway.run:app --reload %*

endlocal
