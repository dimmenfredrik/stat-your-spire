@echo off
rem STS2 Coach v4 launcher. Lives in the sts2_coach_v4 folder; does not touch older versions.
setlocal
cd /d "%~dp0"
set "PY="
where py >nul 2>&1 && set "PY=py"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY goto nopython
echo Starting STS2 Coach v4 - your browser will open at http://localhost:8766
echo Keep this window open while you use it. Close it to stop the app.
%PY% "%~dp0extract_art_from_game.py" --if-missing
%PY% "%~dp0sts2_coach_v4.py"
if errorlevel 1 pause
exit /b

:nopython
echo Python was not found. Install it from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" during setup, then run this again.
pause
exit /b
