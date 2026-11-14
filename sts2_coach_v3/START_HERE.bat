@echo off
title STS2 Coach
setlocal
cd /d "%~dp0"
echo ============================================
echo   STS2 Coach - starting up
echo ============================================
echo.

call :findpy
if defined PY goto run

echo Python was not found on this PC. Trying to install it automatically...
echo (This is a one-time step and needs an internet connection.)
echo.
where winget >nul 2>&1
if errorlevel 1 goto manual
winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
call :findpy
if defined PY goto run

:manual
echo.
echo Could not install Python automatically.
echo Opening the Python download page. Install it, TICK "Add python.exe to PATH"
echo on the first screen, then double-click START_HERE.bat again.
start "" https://www.python.org/downloads/
pause
exit /b 1

:run
echo Python found. Starting STS2 Coach...
echo Your browser will open at http://localhost:8765
echo Keep this window open while you use it. Close it to stop the app.
echo.
%PY% "%~dp0extract_art_from_game.py" --if-missing
echo.
%PY% "%~dp0sts2_coach_v3.py"
if errorlevel 1 (
  echo.
  echo Something went wrong. Take a screenshot of this window and send it to the person who sent you this.
  pause
)
exit /b

:findpy
set "PY="
where py >nul 2>&1 && set "PY=py"
if defined PY exit /b
where python >nul 2>&1 && for /f "delims=" %%i in ('python -c "print(1)" 2^>nul') do set "PY=python"
if defined PY exit /b
for %%d in ("%LocalAppData%\Programs\Python\Python312" "%LocalAppData%\Programs\Python\Python313" "%LocalAppData%\Programs\Python\Python311" "%ProgramFiles%\Python312" "%ProgramFiles%\Python313") do (
  if exist "%%~d\python.exe" set "PY="%%~d\python.exe""
)
exit /b
