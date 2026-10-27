@echo off
title Upload code to GitHub
cd /d "%~dp0"
echo Uploading code to GitHub...
echo If a sign-in window pops up, choose "Sign in with your browser" and click Authorize.
echo.
"C:\Program Files\Git\cmd\git.exe" push -u origin main
echo.
if %errorlevel%==0 (echo === UPLOAD OK. You can close this window. ===) else (echo === UPLOAD FAILED. Please screenshot this window. ===)
pause
