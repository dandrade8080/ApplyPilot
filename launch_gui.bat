@echo off
:: ApplyPilot — Launch the desktop interface
:: Double-click this file or run from terminal.
cd /d "%~dp0"
python -m applypilot.gui
pause
