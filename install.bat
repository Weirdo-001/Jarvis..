@echo off
echo ============================================================
echo  JARVIS — Installing / Updating all dependencies
echo ============================================================
echo.

pip install groq google-generativeai google-genai openai SpeechRecognition faster-whisper openai-whisper pygame edge-tts pdfplumber opencv-python pyperclip psutil pycaw comtypes pyttsx3 numpy keyboard pyautogui pytesseract Pillow pywin32

echo.
echo ============================================================
echo  Done! Run JARVIS:   py main.py
echo ============================================================
pause
