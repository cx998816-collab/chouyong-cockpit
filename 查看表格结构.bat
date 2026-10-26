@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%USERPROFILE%\cockpit-bot-venv\Scripts\python.exe" inspect_sheet.py
pause
