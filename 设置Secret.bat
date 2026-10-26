@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%USERPROFILE%\cockpit-bot-venv\Scripts\python.exe" set_secret.py
pause
