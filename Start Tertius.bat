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
set "STATUS_URL=http://127.0.0.1:%PORT%/api/status"

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

REM ---- is something already on this port? ------------------------------------
REM A server that is already running was started from the code as it was *then*.
REM Python holds the templates in memory but reads the stylesheet and script off
REM disk on every request, so reconnecting to an old server after an update
REM serves last week's page with this week's script - and the page breaks. So:
REM   4  a Tertius is there and idle  -> stop it, so this launch loads the
REM                                      current version. Nothing is lost; the
REM                                      queue lives in the state file on disk.
REM   3  a Tertius is there and busy  -> leave it strictly alone and open its
REM                                      tab. Never interrupt a running batch.
REM   1  nothing answered             -> start normally.
"%PY%" -c "import json,urllib.request,sys; sys.exit(3 if json.load(urllib.request.urlopen('%STATUS_URL%',timeout=3)).get('running') else 4)" 2>nul
if errorlevel 4 goto takeover
if errorlevel 3 goto busy
goto launch

:busy
echo   Tertius is already running, and is part-way through a batch.
echo   Opening its tab rather than interrupting the work.
echo.
echo   If you have just updated Tertius, close this window, let the batch
echo   finish, then launch again - that start will pick up the new version.
echo.
start "" "http://127.0.0.1:%PORT%/"
timeout /t 4 /nobreak >nul 2>&1
exit /b 0

:takeover
echo   An older Tertius is still running on port %PORT%. Restarting it so this
echo   launch uses the current version.
echo.
echo   Nothing is lost - it has no batch in flight, and the queue is kept in
echo   the state file on disk.
echo.
"%PY%" -c "import urllib.request; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:%PORT%/api/job/force-stop',data=b'{}',headers={'Content-Type':'application/json'}),timeout=5).read()" >nul 2>&1
set /a WAITED=0

:waitport
REM Exits non-zero once the port stops answering, i.e. the old server is gone.
"%PY%" -c "import urllib.request; urllib.request.urlopen('%STATUS_URL%',timeout=2)" >nul 2>&1
if errorlevel 1 goto launch
set /a WAITED+=1
if %WAITED% geq 10 (
    echo   ERROR: the old Tertius would not stop.
    echo   Close its console window - the one titled Tertius - and run this again.
    echo.
    pause
    exit /b 1
)
timeout /t 1 /nobreak >nul 2>&1
goto waitport

:launch
echo   Transcripts go to: %OUTPUT_DIR%
echo   Opening http://127.0.0.1:%PORT%/ in your browser...
echo.
echo   Leave this window open while transcribing.
echo   Closing it (or pressing Ctrl+C) stops Tertius.
echo   Lost the tab? Just double-click this file again.
echo.

REM --reuse-existing is still passed as a backstop against two launches racing
REM each other: on Windows a second process can bind a port that is already in
REM use, which would leave two servers writing one state file.
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
