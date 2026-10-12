# JARVIS — a local voice assistant for Windows

Push-to-talk (or wake-word) voice control with a JARVIS-style personality,
system automation (open/close 40+ apps, web search, volume, brightness,
system diagnostics, screenshots, clipboard, shutdown/restart with confirmation),
and Claude as the conversational brain.

## Wake words

You can address JARVIS in three ways:
- **"Jarvis, ..."** → `"Jarvis, open Chrome"`
- **"J, ..."** → `"J, open Chrome"`
- **"Hey, ..."** → `"Hey, open Chrome"`

Mix them however you like — all three work identically.

## 1. Install Python
Python 3.10+ from https://python.org (check "Add to PATH" during install).

## 2. Install dependencies
Open PowerShell in this folder:

```
pip install -r requirements.txt
```

**If `PyAudio` fails to install** (common on Windows — it needs a compiled
binary), run instead:

```
pip install pipwin
pipwin install pyaudio
```

## 3. Set your Anthropic API key
Create one at https://console.anthropic.com/ (this powers open-ended
conversation — system commands like "open chrome" work even without it).

```
setx ANTHROPIC_API_KEY "your-key-here"
```

Close and reopen PowerShell after running `setx` so it takes effect.

> **Never** hardcode your API key in the source files.

## 4. Run it
```
python main.py
```

It's in **continuous mode** by default: just say any wake word followed by
your command. Say "Jarvis, goodbye" or "J, exit" to quit.

## Example commands

### Apps (40+ supported)
- "Jarvis, open Chrome" / "J, open Discord" / "Hey, launch Spotify"
- "Jarvis, close Notepad" / "J, kill Chrome"
- "Hey, open WhatsApp" / "J, open Telegram" / "Jarvis, open Steam"

### Web
- "Jarvis, search the web for Falcon 9 launch schedule"
- "J, google best restaurants nearby"
- "Hey, go to github.com"

### System
- "Jarvis, what time is it?" / "J, today's date"
- "Hey, take a screenshot"
- "Jarvis, volume to 40" / "J, mute" / "Hey, volume up"
- "Jarvis, brightness to 60"
- "J, system status" / "Hey, diagnostics"
- "Jarvis, battery status"
- "J, lock the screen"

### Dangerous (always asks for confirmation)
- "Jarvis, shut down" → asks you to confirm before doing it
- "J, restart" → confirmation required
- "Hey, run C:\Users\you\scripts\backup.ps1" → confirmation required

### Chat
- "J, tell me something random" / any chit-chat → goes to Claude

Every command gets a quick spoken acknowledgment first ("Yes, Miss Aarushi" /
"On it, Miss Aarushi" / "Absolutely, Miss Aarushi" — randomized) before acting.

## On the voice
`en-GB-ThomasNeural` is the default — a deep, composed, measured British male
voice. Combined with SSML pitch (-5%) and rate (-3%) adjustments, it delivers
the calm, unhurried cadence that's closest to the MCU Jarvis feel using free,
legally-usable Microsoft neural voices.

Swap `EDGE_VOICE`, `EDGE_PITCH`, and `EDGE_RATE` in `config.py` to customize.
Run `edge-tts --list-voices` to browse all available voices.

## Supported apps (out of the box)

| Category | Apps |
|---|---|
| **Browsers** | Chrome, Firefox, Edge, Brave |
| **Communication** | WhatsApp, Telegram, Discord, Slack, Teams, Zoom, Skype |
| **Media** | Spotify, VLC, Media Player |
| **Productivity** | Word, Excel, PowerPoint, OneNote, Outlook, Notepad |
| **Dev Tools** | VS Code, Visual Studio, Terminal, PowerShell, CMD, Git Bash, Postman |
| **Utilities** | Calculator, File Explorer, Task Manager, Settings, Control Panel, Paint, Snipping Tool |
| **Gaming** | Steam, Epic Games |
| **Streaming** | OBS Studio |

Add your own in `jarvis_core/config.py` → `APP_MAP`.

## Customizing
Everything lives in `jarvis_core/config.py`:
- `USER_NAME` — how JARVIS addresses you
- `WAKE_WORDS` — tuple of wake words (default: `"jarvis"`, `"j"`, `"hey"`)
- `EDGE_VOICE` / `EDGE_PITCH` / `EDGE_RATE` — voice tuning
- `LISTEN_MODE` — `"continuous"` (default) or `"hotkey"` (push-to-talk)
- `APP_MAP` — add your own app shortcuts
- `STARTUP_GREETING` — enable/disable the startup greeting
- `SHOW_SYSTEM_STATS` — show CPU/RAM/battery on startup

## Safety notes
- Shutdown/restart/sleep/script-running always ask for a spoken "yes" before
  executing. Don't turn this off unless you're confident.
- `run_script` will execute any `.py`/`.ps1` file — only point it at trusted scripts.
- Your voice data goes to: (a) Google's free speech-to-text API and
  (b) Anthropic's API for chat replies. Swap in offline alternatives
  (e.g. `openai-whisper` for STT) if you want fully offline.

## Known rough edges / next steps
- Wake-word mode uses free continuous transcription, which can be laggy —
  hotkey mode is more responsive for daily use.
- No persistent memory between runs yet (conversation resets each launch).
- Smart home control isn't wired in — tell me what ecosystem you use and I'll add it.
- Weather requires an API key (OpenWeatherMap free tier) — ask and I'll wire it in.
