@echo off
setlocal
title Tertius
cd /d "%~dp0"

REM All of the real work - building the virtual environment, installing
REM dependencies, deciding what to do about an already-running server - lives in
REM app\src\tertius\launcher.py, so Windows, macOS and Linux share one copy of
REM it. This file only has to find a Python and hand over.

set "LAUNCHER=%~dp0app\src\tertius\launcher.py"

set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo.
    echo   ERROR: Python is not installed, or not on PATH.
    echo   Install it from https://www.python.org/downloads/ and tick
    echo   "Add python.exe to PATH", then run this again.
    echo.
    pause
    exit /b 1
)

%PY% "%LAUNCHER%" %*

if errorlevel 1 (
    echo.
    echo   Tertius stopped unexpectedly. Scroll up for the reason.
    echo.
    pause
)
