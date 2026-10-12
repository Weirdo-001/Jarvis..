"""
main.py — run this. `python main.py`

CONVERSATION MODE:
  Say "Jarvis" once -> stays awake for the full conversation.
  No need to repeat "Jarvis" for every follow-up.

DEBUGGING:
  Every phrase Whisper hears is printed. If you see "[heard] ..." but no
  [JARVIS] response, you'll now see exactly WHY (no wake word / in sleep mode).
  This makes tuning the wake word much easier.
"""
import datetime
import random
import re
import time
from difflib import SequenceMatcher, get_close_matches

try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

from jarvis_core import config, voice
from jarvis_core.brain import Brain

EXIT_PHRASES = (
    "goodbye jarvis", "goodbye j", "exit", "quit",
    "shut yourself down", "that's all jarvis", "that's all j",
    "power down", "goodnight jarvis",
)

INTERVIEW_TRIGGERS = (
    "start interview mode", "interview me", "interview mode",
    "practice interview", "mock interview", "take my interview",
)

# ----------------------------------------------------------------
# Startup greeting
# ----------------------------------------------------------------

def _startup_greeting():
    hour = datetime.datetime.now().hour
    tod = "Good morning" if hour < 12 else ("Good afternoon" if hour < 17 else "Good evening")
    time_str = datetime.datetime.now().strftime("%I:%M %p").lstrip("0")
    greeting = f"{tod}, {config.USER_NAME}. It's {time_str}."

    stats = ""
    if config.SHOW_SYSTEM_STATS:
        try:
            import psutil
            cpu  = psutil.cpu_percent(interval=0.5)
            ram  = psutil.virtual_memory().percent
            batt = psutil.sensors_battery()
            stats = f" Systems at {cpu}% CPU, {ram}% memory"
            if batt:
                stats += f", battery {batt.percent}%"
            stats += "."
        except ImportError:
            pass

    quips = [
        "All systems nominal. Ready when you are.",
        "Online and at your service.",
        "Systems engaged. Standing by for your command.",
        "I've run diagnostics. Everything looks rather splendid.",
        "All suits are in the hangar. What can I do for you?",
        "The arc reactor is humming nicely. Awaiting instructions.",
    ]
    voice.speak(f"{greeting}{stats} {random.choice(quips)}")


# ----------------------------------------------------------------
# Confirmation helper
# ----------------------------------------------------------------

def ask_confirmation(question: str) -> str:
    voice.speak(question)
    reply = voice.listen_once(timeout=6, phrase_time_limit=5)
    return reply or ""


# ----------------------------------------------------------------
# Wake word detection
# ----------------------------------------------------------------
#
# CRITICAL PROBLEM: Whisper (especially with Indian accents) mishears
# "Jarvis" as many different words ("dennis", "davis", "travis", etc.).
# This list + fuzzy matching catches every variant.
#
# HOW TO ADD MORE: If you see "[heard] XYZ" in the terminal but Jarvis
# doesn't respond, add "xyz" to _WAKE_VARIANTS below.

_WAKE_VARIANTS = {
    # Real wake words
    "jarvis", "hey jarvis", "hey j", "hi jarvis", "hello jarvis",
    # ---- CONFIRMED WHISPER MISHEARINGS FROM YOUR SESSION ----
    "dennis",   # Whisper logged: "Good afternoon, Dennis" = "Jarvis"
    "davis", "travis", "jervis", "garvis", "jarvish",
    "jarves", "jarvi", "jarvas", "jarviz", "javis",
    "jarwis", "dervis", "servis", "service",
    "hey dennis", "hey davis", "hey travis",
    # Extra loose variants
    "jar", "jarv", "jars", "jarbs",
    "darn", "darvis", "darns",
    # ---- "no Jarvis" pattern — Whisper prefixes with "no" when activating ----
    "no jarvis", "no jarv", "no dennis", "no davis",
    # ---- Additional phonetic variants ----
    "java", "jarby", "jabis", "jalvis", "jabvis",
    "yes jarvis", "ok jarvis", "okay jarvis",
}


def _wake_word_found(text_lower: str):
    """
    Returns (True, command_after_wake) or (False, None).

    Three-pass detection:
      Pass 1 — exact substring match (fastest)
      Pass 2 — difflib fuzzy on first 1-2 words (threshold: 0.70)
      Pass 3 — very liberal single-word check for short variants
    """
    words = text_lower.split()

    # --- Pass 1: exact substring ---
    for variant in sorted(_WAKE_VARIANTS, key=len, reverse=True):
        if variant in text_lower:
            before, after = text_lower.split(variant, 1)
            before = before.strip(" ,.!?")
            rest = after.strip(" ,.!?")
            # strip double wake word ("hey jarvis open…")
            for v2 in sorted(_WAKE_VARIANTS, key=len, reverse=True):
                if rest.startswith(v2):
                    rest = rest[len(v2):].strip(" ,.")
                    break
            # Remove the wake word without discarding either side. This keeps
            # commands such as "scroll down, Jarvis, do it" intact.
            return True, " ".join(part for part in (before, rest) if part).strip()

    # --- Pass 2: fuzzy on first word and first two words ---
    candidates = []
    if words:
        candidates.append((words[0], 1))
    if len(words) >= 2:
        candidates.append((f"{words[0]} {words[1]}", 2))

    for cand, nw in candidates:
        matches = get_close_matches(cand, _WAKE_VARIANTS, n=1, cutoff=0.70)
        if matches:
            rest = " ".join(words[nw:]).strip(" ,.")
            print(f"[wake] Fuzzy: '{cand}' ~ '{matches[0]}'")
            return True, rest

    # --- Pass 3: pure similarity ratio for first word (catches heavy accents) ---
    if words:
        first = words[0]
        for variant in _WAKE_VARIANTS:
            if len(variant) < 3:
                continue
            ratio = SequenceMatcher(None, first, variant).ratio()
            if ratio >= 0.68:
                rest = " ".join(words[1:]).strip(" ,.")
                print(f"[wake] Ratio match: '{first}' ~ '{variant}' ({ratio:.0%})")
                return True, rest

    return False, None


def _extract_command(text_lower: str):
    found, command = _wake_word_found(text_lower)
    return command if found else None


def _normalize_command(text: str) -> str:
    """Remove conversational filler/preamble before a direct desktop command.

    Handles patterns like:
      "Good job. Now, on WhatsApp, text Raghav saying hello"
      "Okay now open Chrome"
      "Alright, now text Raghav saying hello"
      "Perfect. Now on WhatsApp text Raghav"
      "Nice one. Now, on WhatsApp, text Raghav saying hello"
    """
    result = text
    # Apply repeatedly to peel off multi-layer preambles
    for _ in range(5):
        prev = result
        # Strip leading conversational reactions + connectors
        result = re.sub(
            r"^(?:good\s+job|good\s+one|nice\s+one|nice\s+job|well\s+done|"
            r"great|perfect|awesome|cool|nice|alright|okay|ok|sure|right|"
            r"good|fine|yeah|yep|yes|brilliant|excellent|wonderful|"
            r"that's\s+(?:good|great|nice|cool|perfect|awesome)|"
            r"you know what|just shut up(?: and)?|"
            r"now what i want you to do is|what i want you to do is|"
            r"i want you to|can you|could you|would you|"
            r"go ahead and|and then|also|then|now)\s*[.,!?;:]*\s*",
            "",
            result,
            flags=re.IGNORECASE,
        ).strip()
        if result == prev:
            break
    return result


# ----------------------------------------------------------------
# Interview mode launcher
# ----------------------------------------------------------------

def _launch_interview(brain: Brain, text: str = ""):
    if not config.INTERVIEW_MODE_ENABLED:
        voice.speak("Interview mode is currently disabled.")
        return

    from jarvis_core.interview import InterviewSession, _parse_company_role

    company, role = _parse_company_role(text)

    InterviewSession(
        brain=brain,
        speak_fn=voice.speak,
        listen_fn=voice.listen_for_conversation,
    ).run(company=company, role=role)


# ----------------------------------------------------------------
# Continuous mode — conversation-aware
# ----------------------------------------------------------------

def run_continuous_mode(brain: Brain):
    _startup_greeting()
    print("\n" + "="*55)
    print("  JARVIS is listening. Say 'Jarvis' to activate.")
    print("  Watch this terminal to see what Whisper hears.")
    print("  If you see [heard] but no response -> no wake word.")
    print("="*55 + "\n")

    in_conversation = False
    last_spoken_time = 0.0
    no_wake_count = 0     # track consecutive misses so we can hint the user

    while True:
        if in_conversation:
            text = voice.listen_for_conversation()
        else:
            text = voice.listen_once(timeout=None, phrase_time_limit=12)

        if not text:
            if in_conversation:
                if time.time() - last_spoken_time > config.CONVERSATION_TIMEOUT_SECONDS:
                    print("[JARVIS] Conversation timeout -> passive listening.")
                    in_conversation = False
            continue

        low = text.lower().strip()

        # Exit check
        if any(ep in low for ep in EXIT_PHRASES):
            voice.speak("Powering down. It's been a pleasure, as always.")
            break

        if not in_conversation:
            command = _extract_command(low)

            if command is None:
                # ---- THIS IS THE KEY DEBUG LINE ----
                # You now see EXACTLY why Jarvis didn't respond
                no_wake_count += 1
                print(f"[sleep] No wake word in: '{text}' — say 'Jarvis' first")

                # After 4 missed phrases, give a gentle audio reminder
                if no_wake_count >= 4:
                    voice.speak("Say 'Jarvis' to wake me up.")
                    no_wake_count = 0
                continue

            # Wake word found
            no_wake_count = 0
            in_conversation = True
            last_spoken_time = time.time()

            if not command:
                voice.speak("Yes?")
                continue

            low = command   # command = everything AFTER "Jarvis"
        else:
            command = low

        # Interview trigger
        if any(t in low for t in INTERVIEW_TRIGGERS):
            in_conversation = False
            _launch_interview(brain, low)
            continue

        low = _normalize_command(low)

        # Normal command / chat
        reply = brain.respond(low, ask_confirmation)
        if reply:
            voice.speak(reply)
            last_spoken_time = time.time()

        if any(ep in low for ep in EXIT_PHRASES):
            voice.speak("Powering down. Goodbye.")
            break


# ----------------------------------------------------------------
# Hotkey (push-to-talk) mode
# ----------------------------------------------------------------

def run_hotkey_mode(brain: Brain):
    _startup_greeting()
    in_conversation = False
    last_spoken_time = 0.0

    while True:
        if in_conversation:
            text = voice.listen_for_conversation()
            if not text:
                if time.time() - last_spoken_time > config.CONVERSATION_TIMEOUT_SECONDS:
                    print("[JARVIS] Conversation timeout -> press the hotkey to start again.")
                    in_conversation = False
                continue
        else:
            voice.wait_for_push_to_talk()
            text = voice.listen_once()

        if not text:
            continue

        if not in_conversation:
            voice.reset_push_to_talk_prompt()

        low = text.lower().strip()

        if not in_conversation:
            command = _extract_command(low)
            if command is None:
                print(f"[sleep] Ignored without wake word: '{text}'")
                continue

            greeting_commands = {
                "hi", "hello", "hey", "good morning", "good afternoon",
                "good evening", "how are you",
            }
            if low in {
                "hi jarvis", "hello jarvis", "hey jarvis", "jarvis",
                "good morning jarvis", "good afternoon jarvis",
                "good evening jarvis",
            } or command in greeting_commands:
                in_conversation = True
                last_spoken_time = time.time()
                voice.speak("Yes, Miss Aarushi?")
                continue

            low = command

            if not low:
                in_conversation = True
                last_spoken_time = time.time()
                voice.speak("Yes, Miss Aarushi?")
                continue
        else:
            # Keep wake-word prefixes out of commands during follow-ups too.
            # Otherwise "Okay Jarvis, open WhatsApp" is sent to the LLM
            # instead of the local app command handler.
            found, command = _wake_word_found(low)
            if found and command:
                low = command

        low = _normalize_command(low)

        if any(ep in low for ep in EXIT_PHRASES):
            voice.speak("Powering down. Goodbye.")
            break

        if any(t in low for t in INTERVIEW_TRIGGERS):
            _launch_interview(brain, low)
            in_conversation = False
            continue

        in_conversation = True
        last_spoken_time = time.time()
        reply = brain.respond(low, ask_confirmation)
        if reply:
            voice.speak(reply)
            last_spoken_time = time.time()


# ----------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------

def main():
    voice.calibrate_mic()
    voice.preload_stt()   # load Whisper model now, not on your first command
    brain = Brain()
    if config.LISTEN_MODE == "continuous":
        run_continuous_mode(brain)
    else:
        run_hotkey_mode(brain)


if __name__ == "__main__":
    main()