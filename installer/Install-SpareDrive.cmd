@echo off
rem Installs SpareDrive from the wheel next to this file. See install_sparedrive.py.
setlocal
set "PYTHON=py -3"
%PYTHON% --version >nul 2>nul || set "PYTHON=python"
%PYTHON% --version >nul 2>nul || (
    echo Python 3.10 or newer is required. Install it from https://www.python.org/downloads/ and run this again.
    pause
    exit /b 1
)
%PYTHON% "%~dp0install_sparedrive.py" %*
set "RESULT=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %RESULT%
