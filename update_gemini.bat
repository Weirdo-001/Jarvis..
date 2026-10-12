@echo off
echo Installing updated packages...
pip install "google-genai" --upgrade
pip install "google-generativeai" --upgrade
echo.
echo Done. Run: py main.py
pause
