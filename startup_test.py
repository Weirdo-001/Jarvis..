"""
startup_test.py — Run this BEFORE main.py to catch any issues early.
python startup_test.py
"""
import sys
import os
print("\n" + "="*55)
print("  JARVIS — Pre-flight Check")
print("="*55)

errors = []
warnings = []

# 1. Check Python version
major, minor = sys.version_info[:2]
if major < 3 or (major == 3 and minor < 9):
    errors.append(f"Python 3.9+ required, you have {major}.{minor}")
else:
    print(f"  ✅  Python {major}.{minor}")

# 2. Check core files exist
core_files = [
    "jarvis_core/config.py",
    "jarvis_core/brain.py",
    "jarvis_core/voice.py",
    "jarvis_core/commands.py",
    "jarvis_core/interview.py",
    "main.py",
]
for f in core_files:
    if os.path.exists(f):
        print(f"  ✅  {f}")
    else:
        errors.append(f"Missing file: {f}")
        print(f"  ❌  {f}  <-- MISSING")

# 3. Check imports (syntax check)
print("\n  Checking imports...")
import importlib
import traceback

test_modules = {
    "groq":               "Groq (primary LLM)",
    "google.generativeai": "Gemini (secondary LLM)",
    "openai":             "OpenAI client (Cerebras/OpenRouter)",
    "speech_recognition": "SpeechRecognition (STT)",
    "whisper":            "Whisper (smart STT)",
    "pygame":             "pygame (audio)",
    "edge_tts":           "edge-tts (voice)",
    "psutil":             "psutil (system stats)",
    "keyboard":           "keyboard (hotkeys)",
    "pyautogui":          "pyautogui (screenshots)",
    "pyperclip":          "pyperclip (clipboard)",
    "numpy":              "numpy (Whisper dep)",
    "pyttsx3":            "pyttsx3 (offline TTS)",
    "pdfplumber":         "pdfplumber (interview PDF)",
    "cv2":                "opencv (camera proctor)",
}

missing_pkgs = []
for mod, desc in test_modules.items():
    try:
        importlib.import_module(mod)
        print(f"  ✅  {desc}")
    except ImportError:
        missing_pkgs.append(mod)
        # Non-critical modules (interview extras)
        if mod in ("pdfplumber", "cv2"):
            warnings.append(f"{desc} not installed (interview PDF/camera won't work)")
            print(f"  ⚠️  {desc}  (optional for interview mode)")
        else:
            errors.append(f"{desc} not installed")
            print(f"  ❌  {desc}  <-- MISSING")

# 4. Check config values
print("\n  Checking API keys...")
sys.path.insert(0, ".")
try:
    from jarvis_core import config

    groq_keys = [k for k in config.GROQ_API_KEYS if k and len(k) > 8]
    # Both "AIzaSy..." (old) and "AQ." (new 2025/2026 format) are valid Gemini API keys
    gem_keys  = [k for k in config.GEMINI_API_KEYS if k and len(k) > 8 and not k.startswith("ya29.")]
    cer_keys  = [k for k in config.CEREBRAS_API_KEYS if k and len(k) > 8]
    or_keys   = [k for k in config.OPENROUTER_API_KEYS if k and len(k) > 8]

    print(f"  {'✅' if groq_keys else '⚠️ '}  Groq keys: {len(groq_keys)}")
    print(f"  {'✅' if gem_keys  else '⚠️ '}  Gemini keys: {len(gem_keys)}")
    print(f"  {'✅' if cer_keys  else '⚠️ '}  Cerebras keys: {len(cer_keys)}")
    print(f"  {'✅' if or_keys   else '⚠️ '}  OpenRouter keys: {len(or_keys)}")

    active = sum([bool(groq_keys), bool(gem_keys), bool(cer_keys), bool(or_keys)])
    print(f"\n  🔗  {active}/4 providers active")
    if active == 0:
        errors.append("No API providers have valid keys! Add at least one key in config.py")

except Exception as e:
    errors.append(f"Config error: {e}")
    print(f"  ❌  Config failed to load: {e}")

# 5. Summary
print("\n" + "="*55)
if errors:
    print(f"  ❌  {len(errors)} ERROR(S) — fix before running main.py:\n")
    for e in errors:
        print(f"     • {e}")
    if missing_pkgs:
        core_missing = [p for p in missing_pkgs if p not in ("pdfplumber", "cv2")]
        if core_missing:
            print(f"\n  Run:  pip install {' '.join(core_missing)}")
else:
    print("  🎉  All checks passed! JARVIS is ready.")
    print("\n  Run:  python main.py")

if warnings:
    print(f"\n  ⚠️  Warnings ({len(warnings)}):")
    for w in warnings:
        print(f"     • {w}")

print("="*55 + "\n")
