@echo off
setlocal
title Tertius
cd /d "%~dp0"

REM ---- settings you might want to change -------------------------------------
set "PORT=5005"
set "OUTPUT_DIR=%~dp0transcripts"
REM ---------------------------------------------------------------------------

set "PY=%~dp0.venv\Scripts\python.exe"
set "PYTHONPATH=%~dp0src"

echo.
echo   Tertius
echo   -------
echo   Local, offline transcription.
echo.

REM First run: build the virtual environment.
if not exist "%PY%" (
    echo   No virtual environment yet - creating one. This happens once.
    echo.
    py -3 -m venv "%~dp0.venv" 2>nul
    if not exist "%PY%" python -m venv "%~dp0.venv"
    if not exist "%PY%" (
        echo   ERROR: could not create the virtual environment.
        echo   Is Python installed and on PATH? Try running: python --version
        echo.
        pause
        exit /b 1
    )
)

REM Install dependencies if anything is missing.
"%PY%" -c "import flask, faster_whisper" >nul 2>&1
if errorlevel 1 (
    echo   Installing dependencies - a few hundred MB, one time only...
    echo.
    "%PY%" -m pip install --upgrade pip
    "%PY%" -m pip install -r "%~dp0requirements.txt"
    "%PY%" -c "import flask, faster_whisper" >nul 2>&1
    if errorlevel 1 (
        echo.
        echo   ERROR: dependencies failed to install. Scroll up for the reason.
        echo.
        pause
        exit /b 1
    )
    echo.
)

echo   Transcripts go to: %OUTPUT_DIR%
echo   Opening http://127.0.0.1:%PORT%/ in your browser...
echo.
echo   Leave this window open while transcribing.
echo   Closing it (or pressing Ctrl+C) stops Tertius.
echo   Lost the tab? Just double-click this file again.
echo.

REM --reuse-existing: if Tertius is already running on this port, this re-opens
REM its tab and exits rather than starting a second server.
"%PY%" -m tertius --host 127.0.0.1 --port %PORT% --output-dir "%OUTPUT_DIR%" --open-browser --reuse-existing

REM A clean exit means either "server shut down" or "reused the running one" -
REM neither needs a message. Only stop and explain if something actually broke.
if errorlevel 1 (
    echo.
    echo   Tertius stopped unexpectedly. Scroll up for the reason.
    echo   If port %PORT% is being used by something else, change PORT at the
    echo   top of this file.
    echo.
    pause
)
