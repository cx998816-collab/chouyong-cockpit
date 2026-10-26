@echo off
chcp 65001 >nul
title 抽佣驾驶舱机器人（关闭此窗口即停止）
cd /d "%~dp0"
"%USERPROFILE%\cockpit-bot-venv\Scripts\python.exe" run.py
pause
