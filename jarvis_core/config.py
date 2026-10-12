"""
Central configuration for JARVIS.
Edit these values, or set them as environment variables.

API ROTATION ORDER: Groq → Gemini → Cerebras → OpenRouter
All are free tiers. JARVIS auto-rotates when one hits a rate limit.
"""
import os

# Automatically load .env from the project root
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_env_file = os.path.join(_project_root, ".env")

try:
    from dotenv import load_dotenv
    load_dotenv(_env_file)
except ImportError:
    pass

# Built-in fallback loader in case python-dotenv is not installed
if os.path.exists(_env_file):
    try:
        with open(_env_file, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    _k = _k.strip()
                    _v = _v.strip().strip("'\"")
                    if _k and _k not in os.environ:
                        os.environ[_k] = _v
    except Exception:
        pass

# ---- Identity ----
USER_NAME = os.getenv("JARVIS_USER_NAME", "Miss Aarushi")  # how JARVIS addresses you
ASSISTANT_NAME = "Jarvis"

# ---- Wake words ----
WAKE_WORDS = ("jarvis", "j", "hey jarvis", "hey j")
WAKE_WORD = "jarvis"  # kept for backward compat

# ---- Conversation Mode ----
# After a wake word is heard, JARVIS stays "awake" for this many seconds.
# Within that window, you can speak follow-ups WITHOUT repeating the wake word.
# (Like GPT — say "Jarvis" once, have a full conversation.)
CONVERSATION_TIMEOUT_SECONDS = 60  # seconds of silence before going back to sleep
CONVERSATION_MODE = True            # set False to require wake word every time

# ============================================================
# ---- API KEYS — Loaded securely from .env ----
# ============================================================

# --- 1. Groq (fastest, free tier: ~14k tokens/min on free accounts) ---
GROQ_API_KEYS = [
    k for k in [
        os.getenv("GROQ_API_KEY_1") or os.getenv("GROQ_API_KEY", ""),
        os.getenv("GROQ_API_KEY_2", ""),
    ] if k
]

# --- 2. Google Gemini (free: ~1500 req/day on gemini-2.0-flash-lite) ---
# Get yours FREE at: https://aistudio.google.com/app/apikey
GEMINI_API_KEYS = [
    k for k in [
        os.getenv("GEMINI_API_KEY_1") or os.getenv("GEMINI_API_KEY", ""),
        os.getenv("GEMINI_API_KEY_2", ""),
    ] if k
]

# --- 3. Cerebras (free: ~1M tokens/day, VERY fast) ---
# Sign up free at: https://cloud.cerebras.ai/
CEREBRAS_API_KEYS = [
    k for k in [
        os.getenv("CEREBRAS_API_KEY_1") or os.getenv("CEREBRAS_API_KEY", ""),
    ] if k
]

# --- 4. OpenRouter (free: 20+ free models, great fallback) ---
# Get key free at: https://openrouter.ai/
OPENROUTER_API_KEYS = [
    k for k in [
        os.getenv("OPENROUTER_API_KEY_1") or os.getenv("OPENROUTER_API_KEY", ""),
    ] if k
]

# ---- Model names per provider ----
GROQ_MODEL        = "llama-3.3-70b-versatile"  # current high-quality Groq model
GEMINI_MODEL      = "gemini-3.5-flash-lite"    # current Gemini model
CEREBRAS_MODEL    = "gpt-oss-120b"             # Cerebras' current recommended model
OPENROUTER_MODEL  = "openrouter/auto"          # auto-routes to best available FREE model
SHOW_GROQ_ERRORS   = os.getenv("JARVIS_SHOW_GROQ_ERRORS", "0") == "1"

# ============================================================
# ---- Voice ----
# ============================================================
# TTS_ENGINE: "edge" (natural neural, needs internet) or "pyttsx3" (offline, robotic)
TTS_ENGINE = os.getenv("JARVIS_TTS_ENGINE", "edge")

EDGE_VOICE  = "en-GB-RyanNeural"   # Deep, natural British male
EDGE_PITCH  = "-10Hz"   # edge-tts uses Hz, NOT %. Negative = deeper voice.
EDGE_RATE   = "-3%"     # rate still uses % (this one is fine)
PYTTSX3_RATE = 170
TTS_START_DELAY = 0.3    # Silence before speech (Bluetooth wake-up). Was 0.8 — reduced for speed.

# ---- STT (Speech-to-Text) ----
# "whisper" = local OpenAI Whisper (best quality, adds punctuation, offline-capable)
#             requires: pip install openai-whisper
# "google"  = Google Web Speech API (fast, needs internet, no punctuation)
STT_ENGINE = os.getenv("JARVIS_STT_ENGINE", "whisper")
# Model sizes: tiny (fastest/worst) | base | small | medium | large-v3 (best accuracy, slowest)
# THIS is the line that was silently overriding voice.py's default and keeping you
# on "small" no matter what got changed there — max-accuracy mode now lives here.
WHISPER_MODEL = "large-v3"   # was "small" — you said you don't care about speed, so: max accuracy
WHISPER_LANGUAGE = "en"     # Force English
# Add company names, tech terms, proper nouns that Whisper keeps mishearing.
# BARE WORDS/NAMES ONLY — never full example sentences. Whisper treats this as
# recent context and will literally echo full phrases back when it hears silence
# or ambient noise, which is exactly what "open Chrome" and "text Ashna saying
# hello" were doing here (that's why "open WhatsApp" kept coming out as "open
# Chrome" — the model was reciting this list, not mishearing you).
WHISPER_VOCAB = "Tekion, Chitkara, fintech, OWASP, RDBMS, bcrypt, JWT, CSRF, DSA"

# ---- Contacts — add all your WhatsApp contact names here ----
# These are injected into Whisper's vocabulary so it doesn't mishear
# your contacts as other words (e.g. "Ashna" → "Aarushi").
CONTACTS = [
    "Raghav", "Ashna", "Aditya", "Mummy", "Papa","Sneehhaaaaa"
    # Add more names below:
]

# ---- Mic Sensitivity ----
# Set JARVIS_MIC_DEVICE_INDEX to the number shown by the startup microphone list.
# Leave empty to use the Windows default recording device.
MIC_DEVICE_INDEX = os.getenv("JARVIS_MIC_DEVICE_INDEX", "")
MIC_DEVICE_NAME = os.getenv("JARVIS_MIC_DEVICE_NAME", "")
# Energy threshold: how loud your voice needs to be to register as speech.
# LOWER = more sensitive (hears quiet/distant voices but may pick up noise)
# HIGHER = less sensitive (only hears loud/close voices)
# After startup, Jarvis auto-calibrates this from ambient noise.
# If it STILL can't hear you, manually override here (try 100–300):
MIC_ENERGY_THRESHOLD = 100      # LOWERED for better sensitivity (was 200). Raise if noisy environment.
MIC_PAUSE_THRESHOLD  = 0.8       # seconds of silence = end of sentence (was 1.5 — too slow)
MIC_PHRASE_TIME_LIMIT = 15       # max seconds for a single utterance (was 25 — absurd)
MIC_RETRY_TIMEOUT = 3           # short retry window for microphone hot-swapping

# Input mode: "continuous" (always listening for wake word) or "hotkey" (push-to-talk)
LISTEN_MODE = os.getenv("JARVIS_LISTEN_MODE", "continuous")
PUSH_TO_TALK_KEY = "ctrl+alt+space"

# ============================================================
# ---- Marvel Universe Knowledge ----
# ============================================================
MARVEL_MODE = True  # Inject deep Marvel lore into Jarvis's system prompt

# ============================================================
# ---- Interview Mode ----
# ============================================================
# Triggered by saying: "Jarvis, start interview mode" or "interview me"
INTERVIEW_MODE_ENABLED = True
# Path to store uploaded resumes/JDs (created automatically)
INTERVIEW_DATA_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Jarvis_Interview")
# How many follow-up questions per answer (like a real interviewer)
INTERVIEW_MAX_FOLLOWUPS = 2
# Camera proctoring: detects if you look away (requires opencv)
INTERVIEW_CAMERA_PROCTORING = True
# Screen monitoring: flags tab-switches during interview
INTERVIEW_SCREEN_PROCTORING = True
# Runtime flag — set True while InterviewSession is active so Whisper uses tech vocabulary
# Do NOT edit manually. interview.py sets/resets this automatically.
INTERVIEW_ACTIVE = False

# ============================================================
# ---- Startup behavior ----
# ============================================================
STARTUP_GREETING  = True
SHOW_SYSTEM_STATS = True

# ---- Safety ----
CONFIRM_DANGEROUS_ACTIONS = True

# ============================================================
# ---- App shortcuts ----
# ============================================================
APP_MAP = {
    # — Browsers —
    "chrome": r'"C:\Program Files\Google\Chrome\Application\chrome.exe" --profile-directory="Profile 1"',
    "google chrome": r'"C:\Program Files\Google\Chrome\Application\chrome.exe" --profile-directory="Profile 1"',
    "browser": r'"C:\Program Files\Google\Chrome\Application\chrome.exe" --profile-directory="Profile 1"',
    "firefox": "firefox",
    "edge": "msedge",
    "brave": "brave",
    # — Communication —
    "whatsapp": r"explorer shell:AppsFolder\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App",
    "telegram": r"explorer shell:AppsFolder\TelegramMessenger.TelegramDesktop_t4vj0pshhgkwm!App",
    "discord": "discord",
    "slack": "slack",
    "teams": "msteams",
    "microsoft teams": "msteams",
    "zoom": "zoom",
    "skype": "skype",
    # — Media —
    "spotify": "spotify",
    "vlc": "vlc",
    "media player": "wmplayer",
    # — Productivity —
    "notepad": "notepad",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "onenote": "onenote",
    "outlook": "outlook",
    # — Dev tools —
    "vs code": "code",
    "visual studio code": "code",
    "visual studio": "devenv",
    "terminal": "wt",
    "powershell": "powershell",
    "cmd": "cmd",
    "command prompt": "cmd",
    "git bash": r"C:\Program Files\Git\git-bash.exe",
    "postman": "postman",
    # — Utilities —
    "calculator": "calc",
    "explorer": "explorer",
    "files": "explorer",
    "file explorer": "explorer",
    "task manager": "taskmgr",
    "settings": "ms-settings:",
    "control panel": "control",
    "paint": "mspaint",
    "snipping tool": "snippingtool",
    "clock": "ms-clock:",
    "calendar": "outlookcal:",
    "store": "ms-windows-store:",
    "microsoft store": "ms-windows-store:",
    # — Gaming —
    "steam": "steam",
    "epic games": r"com.epicgames.launcher:",
    # — Recording / Streaming —
    "obs": "obs64",
    "obs studio": "obs64",
}