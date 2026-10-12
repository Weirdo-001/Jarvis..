"""Quick dependency check for JARVIS — run: python check_deps.py"""
import sys

packages = {
    "groq":                ("groq",               "pip install groq"),
    "google-generativeai": ("google.generativeai", "pip install google-generativeai"),
    "openai":              ("openai",              "pip install openai"),
    "SpeechRecognition":   ("speech_recognition",  "pip install SpeechRecognition"),
    "openai-whisper":      ("whisper",             "pip install openai-whisper"),
    "pygame":              ("pygame",              "pip install pygame"),
    "edge-tts":            ("edge_tts",            "pip install edge-tts"),
    "pdfplumber":          ("pdfplumber",          "pip install pdfplumber"),
    "opencv-python":       ("cv2",                 "pip install opencv-python"),
    "psutil":              ("psutil",              "pip install psutil"),
    "pycaw":               ("pycaw",               "pip install pycaw"),
    "pyttsx3":             ("pyttsx3",             "pip install pyttsx3"),
    "numpy":               ("numpy",               "pip install numpy"),
    "keyboard":            ("keyboard",            "pip install keyboard"),
    "pyaudio":             ("pyaudio",             "pip install pyaudio"),
    "pyautogui":           ("pyautogui",           "pip install pyautogui"),
    "pyperclip":           ("pyperclip",           "pip install pyperclip"),
}

print("\n" + "="*55)
print("  JARVIS Dependency Check")
print("="*55)

missing = []
ok = []

for pkg_name, (import_name, install_cmd) in packages.items():
    try:
        __import__(import_name)
        ok.append(pkg_name)
        print(f"  ✅  {pkg_name}")
    except ImportError:
        missing.append((pkg_name, install_cmd))
        print(f"  ❌  {pkg_name}  <-- MISSING")

print("="*55)
if missing:
    print(f"\n⚠️  {len(missing)} package(s) missing. Run this to fix:\n")
    cmds = " ".join(pkg for pkg, _ in missing)
    print(f"  pip install {cmds}")
    print()
else:
    print(f"\n🎉 All {len(ok)} dependencies are installed! Run:  python main.py\n")
