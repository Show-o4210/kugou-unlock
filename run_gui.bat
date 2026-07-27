@echo off
title KuGou Music Unlock Tool - GUI
cd /d "%~dp0"
echo Starting GUI...
python "%~dp0unlock_gui.py"
if errorlevel 1 (
  echo.
  echo If PySide6 is missing, run: pip install -r requirements.txt
  pause
)
