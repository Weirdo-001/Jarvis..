import os
import warnings
# Suppress HuggingFace symlink warning on Windows (harmless — just uses more disk space)
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
# Suppress unauthenticated HF Hub warning (model still downloads fine without a token)
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
warnings.filterwarnings("ignore", category=UserWarning, module="huggingface_hub")

"""
voice.py — ears and mouth of JARVIS.

PRODUCTION PIPELINE (as recommended by modern voice assistant research):

  Mic Audio
    -> WebRTC VAD  (filters silence/noise before transcription)
    -> faster-whisper large-v3-turbo  (4x faster than openai-whisper, better accuracy)
    -> LLM transcript correction  (fixes "crow" -> "chrome", "arushi" -> "Aarushi")
    -> Intent engine

WHY THIS IS BETTER:
  - VAD: stops Whisper from processing silence (which causes hallucinations)
  - faster-whisper: same model weights, CTranslate2 backend = 4x speed, INT8 quantization
  - LLM correction: catches context-aware mishearings openai-whisper gets wrong
  - en-IN language hint: tuned for Indian English accent

INSTALL (one time):
  pip install faster-whisper webrtcvad

STT fallback order: faster-whisper -> openai-whisper -> Google

PERFORMANCE NOTES (read this if listening feels slow):
  - Model now loads with device="auto" / compute_type="auto" — if you have an
    NVIDIA GPU + CUDA available, faster-whisper will use it automatically and
    transcription drops from tens-of-seconds to ~1-2s. On CPU-only machines it
    now also uses all your CPU cores instead of a single thread.
  - Call preload_stt() once at startup (e.g. right after calibrate_mic()) so
    the model is already loaded in memory before the user's first command —
    otherwise the FIRST listen eats the entire model-load time (can be 30-90s+
    for large-v3 on a cold CPU load).
  - Watch the console: every transcription now prints "[faster-whisper] N.NNs"
    so you can see exactly where time is going. If mic capture itself is the
    slow part (not transcription), that's a listen_once() timeout/threshold
    issue, not a model issue.
"""
import asyncio
import collections
import os
import re
import struct
import tempfile
import time
import threading
import keyboard
import speech_recognition as sr

from . import config

# ----------------------------------------------------------------
# Recognizer — used only for Google fallback + audio capture
# ----------------------------------------------------------------
_recognizer = sr.Recognizer()
_recognizer.pause_threshold = getattr(config, "MIC_PAUSE_THRESHOLD", 1.2)
_recognizer.energy_threshold = getattr(config, "MIC_ENERGY_THRESHOLD", 200)
_recognizer.dynamic_energy_threshold = False
_recognizer.phrase_threshold = 0.05   # was 0.3 — start capturing almost immediately, don't clip first word
_recognizer.non_speaking_duration = 0.45  # was 0.3 — a bit more breathing room so trailing words aren't clipped mid-phrase

_mic_calibrated = False
_mic_device_index = None
_mic_fallback_reported = False
_ptt_prompt_shown = False


def _get_mic_device_index():
    """
    Resolve the configured microphone once, preferring an explicit name or index.
    If neither is set, auto-detects realme / OnePlus / Bluetooth headset mic by name.
    """
    global _mic_device_index
    if _mic_device_index is not None:
        return _mic_device_index

    configured_name = getattr(config, "MIC_DEVICE_NAME", "").strip().lower()
    configured_index = str(getattr(config, "MIC_DEVICE_INDEX", "")).strip()
    names = sr.Microphone.list_microphone_names()

    if configured_name:
        for index, name in enumerate(names):
            if configured_name in name.lower():
                _mic_device_index = index
                print(f"[Mic] Auto-selected by name '{configured_name}': [{index}] {name}")
                break
        else:
            raise OSError(
                f"Microphone matching '{configured_name}' was not found. "
                "Set JARVIS_MIC_DEVICE_INDEX instead."
            )
    elif configured_index:
        try:
            _mic_device_index = int(configured_index)
        except ValueError as exc:
            raise OSError("JARVIS_MIC_DEVICE_INDEX must be a number") from exc
    else:
        # ---- Auto-detect: prefer realme / OnePlus / Bluetooth headset mic ----
        _PREFER_KEYWORDS = ["realme", "oneplus", "hands-free", "headset", "bluetooth"]
        for kw in _PREFER_KEYWORDS:
            for index, name in enumerate(names):
                if kw in name.lower():
                    _mic_device_index = index
                    print(f"[Mic] Auto-detected headset mic: [{index}] {name}")
                    return _mic_device_index
        # Fall back to Windows default
        _mic_device_index = None

    return _mic_device_index


def print_microphones():
    """Print available recording devices so the correct headset mic can be selected."""
    print("[Mic] Available recording devices:")
    for index, name in enumerate(sr.Microphone.list_microphone_names()):
        print(f"  [{index}] {name}")


def _microphone():
    return sr.Microphone(device_index=_get_mic_device_index())


def calibrate_mic():
    """Calibrate microphone once at startup."""
    global _mic_calibrated
    if _mic_calibrated:
        return
    print("[Mic] Calibrating for ambient noise (1.5 seconds)...")
    print_microphones()

    # Bluetooth hands-free endpoints can open successfully but never return
    # frames while Windows is changing audio profiles. Avoid blocking startup.
    if str(getattr(config, "MIC_DEVICE_INDEX", "")).strip():
        _recognizer.energy_threshold = getattr(config, "MIC_ENERGY_THRESHOLD", 200)
        print(f"[Mic] Skipping Bluetooth calibration. Using threshold: {_recognizer.energy_threshold:.0f}")
        _mic_calibrated = True
        return

    calibrated = False
    try:
        with _microphone() as source:
            _recognizer.adjust_for_ambient_noise(source, duration=1.5)
            calibrated = True
    except (OSError, AssertionError, AttributeError) as e:
        print(f"[Mic] Cannot open the selected microphone: {e}")
        print("[Mic] Try another OnePlus device index, usually 2, 8, 15, or 35.")
        _recognizer.energy_threshold = getattr(config, "MIC_ENERGY_THRESHOLD", 200)
    # Hard cap — don't let calibration make us deaf
    _recognizer.energy_threshold = max(50, min(350, _recognizer.energy_threshold))
    if calibrated:
        print(f"[Mic] Calibrated. Energy threshold: {_recognizer.energy_threshold:.0f}")
    else:
        print(f"[Mic] Using configured threshold: {_recognizer.energy_threshold:.0f}")
    _mic_calibrated = True


# ----------------------------------------------------------------
# Faster-Whisper (primary STT — 4x faster, better accuracy)
# ----------------------------------------------------------------
_fw_model = None
_fw_lock = threading.Lock()


def _get_faster_whisper():
    global _fw_model
    if _fw_model is None:
        with _fw_lock:
            if _fw_model is None:
                try:
                    from faster_whisper import WhisperModel
                    # Default is "large-v3" — the most accurate Whisper checkpoint
                    # there is. On an 8GB CPU-only laptop this is genuinely heavy:
                    # ~3GB RAM while loaded and several-to-many seconds per utterance
                    # (you said you don't care — this is the "don't care" setting).
                    # Close other heavy apps (browser with many tabs, IDE, etc.) so
                    # it doesn't start swapping to disk, which would be far slower
                    # than the model itself. If your machine can't handle it (crashes,
                    # extreme slowdown, "out of memory" errors), drop WHISPER_MODEL
                    # to "medium" in config.py — still noticeably better than "small".
                    model_size = getattr(config, "WHISPER_MODEL", "large-v3")
                    # Map openai-whisper model names to faster-whisper equivalents
                    _size_map = {
                        "tiny":   "tiny",
                        "base":   "base",
                        "small":  "small",
                        "medium": "medium",
                        "large":  "large-v3",
                        "large-v3": "large-v3",
                        "turbo":  "large-v3-turbo",
                    }
                    fw_size = _size_map.get(model_size, "small")

                    # ---- Device / compute type: pinned to CPU/int8 by default ----
                    # No dedicated GPU on an 8GB laptop = "auto" just wastes a CUDA
                    # probe on every load. CPU + int8 is the fastest, lowest-RAM,
                    # numerically-stable path and matches what you were already
                    # running (same hallucination/accuracy behavior, just threaded).
                    device = getattr(config, "WHISPER_DEVICE", "cpu")
                    compute_type = getattr(config, "WHISPER_COMPUTE_TYPE", "int8")
                    # No thread cap — speed isn't the priority here, so let large-v3
                    # use every core you've got to chew through the model faster.
                    cpu_threads = getattr(config, "WHISPER_CPU_THREADS", os.cpu_count() or 4)

                    t0 = time.time()
                    print(f"[faster-whisper] Loading '{fw_size}' (device={device}, compute_type={compute_type}, cpu_threads={cpu_threads})...")
                    try:
                        _fw_model = WhisperModel(
                            fw_size,
                            device=device,
                            compute_type=compute_type,
                            cpu_threads=cpu_threads,
                            num_workers=getattr(config, "WHISPER_NUM_WORKERS", 1),
                        )
                    except Exception as gpu_err:
                        # Older CTranslate2 builds / no CUDA runtime installed — fall back to plain CPU/int8.
                        print(f"[faster-whisper] device='{device}' failed ({gpu_err}); falling back to CPU/int8.")
                        _fw_model = WhisperModel(
                            fw_size,
                            device="cpu",
                            compute_type="int8",
                            cpu_threads=cpu_threads,
                            num_workers=1,
                        )
                    print(f"[faster-whisper] Model ready in {time.time() - t0:.2f}s.")
                except ImportError:
                    print("[faster-whisper] Not installed. Run: pip install faster-whisper")
                    _fw_model = "UNAVAILABLE"
    return None if _fw_model == "UNAVAILABLE" else _fw_model


def preload_stt():
    """
    Warm up the faster-whisper model ahead of time (call once at startup,
    e.g. right after calibrate_mic()) so the first real listen_once() call
    isn't the one that pays the model-load cost. Safe to call multiple times.
    """
    _get_faster_whisper()


# ----------------------------------------------------------------
# Openai-Whisper fallback
# ----------------------------------------------------------------
_ow_model = None
_ow_lock = threading.Lock()


def _get_openai_whisper():
    global _ow_model
    if _ow_model is None:
        with _ow_lock:
            if _ow_model is None:
                try:
                    import whisper
                    model_size = getattr(config, "WHISPER_MODEL", "base")
                    print(f"[whisper] Loading '{model_size}'...")
                    _ow_model = whisper.load_model(model_size)
                    print("[whisper] Model ready.")
                except ImportError:
                    _ow_model = "UNAVAILABLE"
    return None if _ow_model == "UNAVAILABLE" else _ow_model


# ----------------------------------------------------------------
# Public API
# ----------------------------------------------------------------

def listen_once(timeout=8, phrase_time_limit=25):
    """Listen from mic and return transcribed text, or None."""
    global _mic_fallback_reported
    configured_index = _get_mic_device_index()
    device_indices = [configured_index]
    if configured_index is not None:
        # If Bluetooth disappears, immediately try the Windows default input.
        device_indices.append(None)

    for device_index in device_indices:
        try:
            with sr.Microphone(device_index=device_index) as source:
                listen_start = time.time()
                audio = _recognizer.listen(
                    source,
                    timeout=min(timeout, getattr(config, "MIC_RETRY_TIMEOUT", 3)) if timeout is not None else None,
                    phrase_time_limit=phrase_time_limit,
                )
            print(f"[Mic] Captured audio in {time.time() - listen_start:.2f}s")
            return _transcribe(audio)
        except sr.WaitTimeoutError:
            return None
        except (OSError, AssertionError, AttributeError) as e:
            # Bluetooth devices can vanish while a conversation is active.
            # Try the next input instead of killing or pausing the session.
            if device_index == configured_index and len(device_indices) > 1:
                _mic_fallback_reported = True
            continue

    return None


def listen_for_conversation(phrase_time_limit=40):
    """Longer listen for conversation follow-ups."""
    return listen_once(
        timeout=getattr(config, "MIC_RETRY_TIMEOUT", 3),
        phrase_time_limit=phrase_time_limit,
    )


def wait_for_push_to_talk():
    global _ptt_prompt_shown
    if not _ptt_prompt_shown:
        print(f"[ready] Hold '{config.PUSH_TO_TALK_KEY}' and speak...")
        _ptt_prompt_shown = True
    keyboard.wait(config.PUSH_TO_TALK_KEY)


def reset_push_to_talk_prompt():
    global _ptt_prompt_shown
    _ptt_prompt_shown = False


def speak(text: str):
    """Speak text aloud."""
    print(f"\n[JARVIS] {text}\n")
    if config.TTS_ENGINE == "edge":
        try:
            _speak_edge(text)
            return
        except Exception as e:
            print(f"[edge-tts error: {e}] -> falling back to pyttsx3")
    _speak_pyttsx3(text)


# ----------------------------------------------------------------
# STT dispatch
# ----------------------------------------------------------------

def _transcribe(audio):
    engine = getattr(config, "STT_ENGINE", "whisper")
    if engine == "whisper":
        result = _transcribe_faster_whisper(audio)
        if result:
            return result
        # Google emergency fallback (silence filtered by VAD = expected, don't spam)
        return _transcribe_google(audio)
    return _transcribe_google(audio)


# ----------------------------------------------------------------
# faster-whisper (primary)
# ----------------------------------------------------------------

def _transcribe_faster_whisper(audio):
    """
    faster-whisper: CTranslate2 backend, auto device/compute type.
    Uses GPU automatically when available, otherwise multi-threaded CPU int8.
    """
    model = _get_faster_whisper()
    if model is None:
        return None

    t0 = time.time()
    try:
        import numpy as np
        raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
        audio_np = (
            np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        )

        lang = getattr(config, "WHISPER_LANGUAGE", "en")

        # Dynamic Vocabulary hints — prevents technical terms from polluting normal conversations.
        #
        # IMPORTANT: initial_prompt must be a bare list of NOUNS/NAMES only — never
        # full example sentences. Whisper treats initial_prompt as "recent context"
        # and will literally echo it back verbatim whenever the mic picks up silence,
        # background hum, or anything that isn't clear speech. Sentences like
        # "text Ashna saying hello" or "system status, rage bait" used to be in here
        # as *examples* — the model was hallucinating them back as if you'd said them.
        # Comma-separated proper nouns don't have this problem; Whisper uses them to
        # bias spelling/recognition without having a "sentence" to fall back on.
        is_interview = getattr(config, "INTERVIEW_ACTIVE", False)
        if is_interview:
            vocab = getattr(config, "WHISPER_VOCAB", "")
            _default_vocab = (
                "Jarvis, Aarushi Sharma, Chitkara University, Tekion, "
                "OWASP, SQL injection, RDBMS, Flask, Django, Python, Java, "
                "bcrypt, JWT, AES, OTP, CSRF, DSA, Chrome, VS Code."
            )
            prompt = f"{_default_vocab} {vocab}" if vocab else _default_vocab
        else:
            # IMPORTANT: list all contact names here so Whisper doesn't map unknown
            # names to the closest thing it knows (e.g. Ashna → Aarushi).
            extra_vocab = getattr(config, "WHISPER_VOCAB", "")
            contacts = ", ".join(getattr(config, "CONTACTS", []))
            prompt = (
                f"Jarvis, Aarushi, {contacts}, Chrome, WhatsApp, Raghav, Ashna."
                + (f" {extra_vocab}" if extra_vocab else "")
            )

        segments, info = model.transcribe(
            audio_np,
            language=lang,
            beam_size=8,            # was 5 — even wider search; max accuracy, we've stopped caring about speed
            best_of=3,              # was 2 — more candidates considered per segment
            patience=2.0,           # extra beam-search patience — keeps exploring instead of settling early
            temperature=0.0,
            initial_prompt=prompt,
            condition_on_previous_text=False,
            vad_filter=True,
            vad_parameters={
                "min_silence_duration_ms": 400,
                "speech_pad_ms": 400,   # was 600 — less padding = less non-speech fed to the model
            },
            no_speech_threshold=0.65,      # was 0.5 — stricter: reject more as "not speech"
            log_prob_threshold=-0.6,       # was -0.7 — even stricter: reject more low-confidence segments
            compression_ratio_threshold=2.2,  # was 2.4 — catches repetitive hallucinated text sooner
            word_timestamps=False,
        )

        # Hard guard: if VAD found essentially no real speech in the clip, don't
        # even bother joining segments — this is exactly what was producing the
        # "text Ashna saying hello" loops on ambient noise.
        speech_secs = getattr(info, "duration_after_vad", None)
        if speech_secs is not None and speech_secs < 0.35:
            print(f"[faster-whisper] VAD found {speech_secs:.2f}s of speech — treating as silence.")
            print(f"[faster-whisper] Transcribed in {time.time() - t0:.2f}s")
            return None

        text = " ".join(
            seg.text.strip()
            for seg in segments
            if getattr(seg, "no_speech_prob", 0.0) < 0.5   # was 0.6 — stricter join filter
        ).strip()
        text = _clean_transcript(text)
        elapsed = time.time() - t0
        if text:
            print(f"[heard] {text}")
        print(f"[faster-whisper] Transcribed in {elapsed:.2f}s")
        return text or None

    except Exception as e:
        print(f"[faster-whisper error] {e} (after {time.time() - t0:.2f}s)")
        return None


# ----------------------------------------------------------------
# openai-whisper (secondary fallback)
# ----------------------------------------------------------------

def _transcribe_openai_whisper(audio):
    model = _get_openai_whisper()
    if model is None:
        return None
    try:
        import numpy as np
        raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
        audio_np = (
            np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        )
        result = model.transcribe(
            audio_np,
            language=getattr(config, "WHISPER_LANGUAGE", "en"),
            fp16=False,
            no_speech_threshold=0.3,
            condition_on_previous_text=False,
            temperature=0.0,
            beam_size=5,
        )
        text = _clean_transcript(result["text"].strip())
        if text:
            print(f"[heard] {text}")
        return text or None
    except Exception as e:
        print(f"[openai-whisper error] {e}")
        return None


# ----------------------------------------------------------------
# Google fallback
# ----------------------------------------------------------------

def _transcribe_google(audio):
    try:
        # en-IN = Indian English — better accent match
        text = _recognizer.recognize_google(audio, language="en-IN")
        if text:
            print(f"[heard] {text}")
        return text or None
    except sr.UnknownValueError:
        return None
    except Exception as e:
        print(f"[Google STT] {e}")
        return None


# ----------------------------------------------------------------
# Transcript cleanup
# ----------------------------------------------------------------

_HALLUCINATIONS = {
    "", ".", "..", "...", "you", "thank you", "thanks",
    "thanks for watching", "bye", "bye bye", "okay", "hmm",
    "[silence]", "[music]", "[applause]", "subtitle", "subtitles",
    "the end", "thank you for watching",
}


def _clean_transcript(text: str) -> str:
    """
    Remove Whisper hallucinations and normalise the transcript.
    Also removes adjacent repeated word/phrase loops (common in Whisper).
    """
    if not text:
        return ""
    cleaned = text.strip().strip(".,!?")
    if cleaned.lower() in _HALLUCINATIONS:
        return ""

    words = cleaned.split()
    n = len(words)

    # ---- Guard 1: Single-word frequency cap ----
    # If ANY single content word appears 8+ times, it's a Whisper loop hallucination.
    # (e.g. "good afternoon good afternoon ..." x39 → drop entirely)
    _STOP_WORDS = {"a", "an", "the", "and", "or", "but", "is", "are", "was", "were", "i", "you"}
    from collections import Counter
    word_counts = Counter(w.lower().strip(".,!?'\"") for w in words)
    for word, count in word_counts.items():
        if count >= 8 and word not in _STOP_WORDS and len(word) > 2:
            print(f"[clean] Hallucination loop ('{word}' x{count}) — dropping transcript.")
            return ""

    # ---- Guard 2: Phrase-cycle detection ----
    # If a phrase of 2–6 words repeats 3+ times consecutively → hallucination loop.
    for chunk_size in range(2, 7):
        if n < chunk_size * 3:
            continue
        for i in range(n - chunk_size * 3 + 1):
            chunk = words[i : i + chunk_size]
            repeat_count = 1
            j = i + chunk_size
            while j + chunk_size <= n and words[j : j + chunk_size] == chunk:
                repeat_count += 1
                j += chunk_size
            if repeat_count >= 3:
                phrase = " ".join(chunk)
                print(f"[clean] Phrase loop ('{phrase}' x{repeat_count}) — dropping transcript.")
                return ""

    # ---- Remove adjacent duplicate chunks (e.g. "Fintech SQL Fintech SQL") ----
    changed = True
    while changed:
        changed = False
        # Look for repeated phrases of size 1 to 8 words
        for chunk_size in range(1, min(8, n // 2 + 1)):
            i = 0
            while i <= n - 2 * chunk_size:
                chunk1 = words[i : i + chunk_size]
                chunk2 = words[i + chunk_size : i + 2 * chunk_size]
                if chunk1 == chunk2:
                    # Remove the repeating second chunk
                    del words[i + chunk_size : i + 2 * chunk_size]
                    n = len(words)
                    changed = True
                else:
                    i += 1

    # ---- "text Raghav" mishearing corrections ----
    # Whisper mangles BOTH words. "text" → let's / lets / next / test / texts / tech / tell
    # "Raghav" → struggle / straggle / rag / raga / ragav / rahav / ra have etc.
    # Fix the full phrase first (highest specificity):
    cleaned = re.sub(
        r"\b(?:let'?s|lets|next|texts?|tech|tell|text)\s+"
        r"(?:struggle|straggle|rag(?:av|hab?|a)?|ra\s*h?av|rahav|ragav|ra\s*have|tobacco|raghab)\b",
        "text Raghav",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Fix "fix tobacco" legacy pattern
    cleaned = re.sub(
        r"\bfix\s+tobacco\b",
        "text Raghav",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Fix "text" being misheard — handles comma between name and "saying" e.g. "next Ashna, saying"
    cleaned = re.sub(
        r"\b(?:let'?s|lets|next|tech|tell)\s+([a-z]{3,12})[\s,.]*(?:saying|that|saying that)\b",
        r"text \1 saying",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Fix "Raghav" mishearings after the word "text" is already correct
    cleaned = re.sub(
        r"\btext\s+(?:struggle|straggle|rag(?:av|hab?|a)?|ra\s*h?av|rahav|ragav|ra\s*have|tobacco|raghab)\b",
        "text Raghav",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Fix other Raghav variants after text
    cleaned = re.sub(
        r"\btext\s+(?:ra\s*have|ragav|rahav|rag\s*have)\b",
        "text Raghav",
        cleaned,
        flags=re.IGNORECASE,
    )
    # "saying" often misheard as "say" or "says"
    cleaned = re.sub(
        r"\b(text\s+\w+)\s+(?:say|says|saying that)\b",
        r"\1 saying",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Common Indian-English Whisper error: "rage bait" → "raise weight"
    cleaned = re.sub(r"\braise\s+weight\s+me\b", "rage bait me", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\braise\s+weight\b", "rage bait", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\b(?:disturb|testing?)\s+(?:patients?|people)\b",
        "test your patience",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\bsecond(?:ly)?\s+people\b", "secondly", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\btest\s+([a-z]+)\s+(saying|that)\b",
        r"text \1 \2",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^(?:what(?:'s| is) up[,.]?\s*){2,}$",
        "open WhatsApp",
        cleaned,
        flags=re.IGNORECASE,
    )
    if re.search(
        r"(?:thanks?|thank you)\s+(?:for watching|to .*?)(?:.*?see you in the next video)?"
        r"|see you in the next video|like and subscribe|in the next video",
        cleaned,
        re.IGNORECASE,
    ):
        return ""
    return cleaned


# ----------------------------------------------------------------
# TTS — edge-tts (primary) with pygame + pyttsx3 fallback
# ----------------------------------------------------------------

def _speak_edge(text: str):
    import edge_tts

    async def _run():
        communicate = edge_tts.Communicate(
            text,
            config.EDGE_VOICE,
            pitch=config.EDGE_PITCH,
            rate=config.EDGE_RATE,
        )
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            path = f.name
        await communicate.save(path)
        return path

    path = asyncio.run(_run())
    _play_audio(path)


def _play_audio(path: str):
    """Play audio file — tries pygame, then playsound, then Windows PowerShell."""
    played = False
    try:
        import pygame
        pygame.mixer.init()
        time.sleep(getattr(config, "TTS_START_DELAY", 0.0))
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)
        pygame.mixer.quit()
        played = True
    except Exception:
        pass

    if not played:
        try:
            from playsound import playsound
            playsound(path)
            played = True
        except Exception:
            pass

    if not played:
        try:
            import subprocess
            subprocess.run(
                ["powershell", "-c", f'(New-Object Media.SoundPlayer "{path}").PlaySync()'],
                capture_output=True,
            )
        except Exception as e:
            print(f"[TTS audio] All playback methods failed: {e}")

    try:
        os.remove(path)
    except Exception:
        pass


def _speak_pyttsx3(text: str):
    path = None
    padded_path = None
    try:
        import pyttsx3
        import wave
        import winsound

        engine = pyttsx3.init()
        engine.setProperty("rate", config.PYTTSX3_RATE)
        voices = engine.getProperty("voices")
        for v in voices:
            if "male" in v.name.lower() or "david" in v.name.lower():
                engine.setProperty("voice", v.id)
                break

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        engine.save_to_file(text, path)
        engine.runAndWait()

        # Put real silence before the speech. Blank pyttsx3 utterances are
        # discarded by SAPI, but silence in the WAV reliably wakes Bluetooth.
        with wave.open(path, "rb") as source:
            params = source.getparams()
            frames = source.readframes(source.getnframes())
        silence_frames = int(
            params.framerate
            * getattr(config, "TTS_START_DELAY", 0.8)
            * params.nchannels
            * params.sampwidth
        )
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            padded_path = f.name
        with wave.open(padded_path, "wb") as output:
            output.setparams(params)
            output.writeframes(b"\x00" * silence_frames)
            output.writeframes(frames)
        winsound.PlaySound(padded_path, winsound.SND_FILENAME)
    except Exception as e:
        print(f"[pyttsx3] {e}")
        if path is not None:
            try:
                engine.say(text)
                engine.runAndWait()
            except Exception as fallback_error:
                print(f"[pyttsx3 fallback] {fallback_error}")
    finally:
        for audio_path in (path, padded_path):
            if audio_path:
                try:
                    os.remove(audio_path)
                except OSError:
                    pass