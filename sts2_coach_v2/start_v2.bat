@echo off
rem STS2 Coach v2 launcher. Lives in the sts2_coach_v2 folder; does not touch the old version.
setlocal
cd /d "%~dp0"

rem --- find Python ---------------------------------------------------------
set "PY="
where py >nul 2>&1 && set "PY=py"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY goto nopython

rem --- install pywebview the first time --------------------------------------
%PY% -c "import webview" >nul 2>&1
if errorlevel 1 goto install
goto run

:install
echo Installing pywebview - first start only, takes about 30 seconds...
%PY% -m pip install --user --disable-pip-version-check pywebview
%PY% -c "import webview" >nul 2>&1
if errorlevel 1 goto browser
goto run

:run
rem --- start without a console window ----------------------------------------
set "PYW="
where pyw >nul 2>&1 && set "PYW=pyw"
if not defined PYW where pythonw >nul 2>&1 && set "PYW=pythonw"
if defined PYW (
  start "" %PYW% "%~dp0sts2_coach_v2.py"
) else (
  start "" /min %PY% "%~dp0sts2_coach_v2.py"
)
exit /b

:browser
echo.
echo pywebview could not be installed. Opening STS2 Coach v2 in your web browser instead.
echo Keep this window open while you use it - close it to stop the app.
%PY% "%~dp0sts2_coach_v2.py" --browser
exit /b

:nopython
echo Python was not found. Install it from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" during setup, then run this again.
pause
exit /b
