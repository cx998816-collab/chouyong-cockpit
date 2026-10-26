@echo off
title Commission cockpit bot - close this window to stop
cd /d "%~dp0"
"%USERPROFILE%\cockpit-bot-venv\Scripts\python.exe" run.py
pause
