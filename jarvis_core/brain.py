"""
brain.py — decides what to do with what you said.

API Rotation Chain (all FREE):
  1. Groq           — fastest inference (Llama 3.1 70B)
  2. Google Gemini  — 1500 req/day free (gemini-2.0-flash-lite)
  3. Cerebras       — ~1M tokens/day free (fastest throughput)
  4. OpenRouter     — 20+ free models, great fallback

When one provider's key exhausts, JARVIS silently rotates to the next.
No interruption to the conversation.
"""

import random
import re
import time
import traceback

from . import commands, config

# ============================================================
# SYSTEM PROMPT — MCU JARVIS + MARVEL UNIVERSE KNOWLEDGE
# ============================================================
_MARVEL_LORE = """
You have encyclopedic knowledge of the Marvel Cinematic Universe AND Marvel Comics. You know:

AVENGERS & KEY HEROES:
- Tony Stark / Iron Man: MIT grad, genius billionaire, created Iron Man suits (Mark 1-85+), founded Stark Industries, snapped Thanos away with all 6 Infinity Stones in Endgame. Arc reactor runs on palladium → vibranium. Died 2023-10-22. Married Pepper Potts, daughter Morgan.
- Steve Rogers / Captain America: Super Soldier Serum by Dr. Erskine. Shield is vibranium (gift from King T'Chaka). Went back in time to live with Peggy Carter. Wielded Mjolnir.
- Thor Odinson: Asgardian God of Thunder, son of Odin & Frigga. Lost Mjolnir (destroyed by Hela), got Stormbreaker (made in Nidavellir by Eitri). Lost eye (replaced). Became King of Asgard (New Asgard, Norway). Used Mjolnir & Stormbreaker simultaneously in Endgame.
- Bruce Banner / Hulk: Gamma radiation accident. Professor Hulk = merged intelligence + strength. Snapped everyone back in Endgame (lost arm use temporarily).
- Natasha Romanoff / Black Widow: Red Room trained assassin. KGB. Red Ledger. Sacrificed herself on Vormir for Soul Stone.
- Clint Barton / Hawkeye: World's greatest archer. Became Ronin after losing family to The Snap.
- Wanda Maximoff / Scarlet Witch: Created Chaos Magic Hex. Mindstone gave her powers (Hydra experiments). Created Westview hex. Destroyed Darkhold. Her MCU power exceeds Dr. Strange's.
- Vision: Created from Ultron, J.A.R.V.I.S., vibranium body, Mind Stone. Killed by Wanda then Thanos.
- Peter Parker / Spider-Man: Bitten by radioactive spider. "Mr. Stark, I don't feel so good." Three versions: Tobey, Andrew, Tom. Aunt May, MJ Watson, Ned Leeds.
- T'Challa / Black Panther: King of Wakanda. Vibranium suit. Heart-Shaped Herb. Chadwick Boseman died Aug 28, 2020. Sister Shuri.
- Stephen Strange / Doctor Strange: Former neurosurgeon. Sorcerer Supreme. Eye of Agamotto holds Time Stone. Sanctum Sanctorum. 14,000,605 futures, only 1 they won.
- Scott Lang / Ant-Man: Pym Particle suit. Quantum Realm. "Hope" van Dyne. Survived Snap inside Quantum Realm.
- Carol Danvers / Captain Marvel: Kree blood from Mar-Vell. Photon absorption. Binary form. Nick Fury paged her.

VILLAINS:
- Thanos: Titan warlord. 6 Infinity Stones (Space/Mind/Reality/Power/Soul/Time). Snapped 50% of life. Killed twice.
- Loki: God of Mischief. Frost Giant raised as Asgardian. TVA variant now helms the Sacred Timeline.
- Ultron: Tony's AI peace-keeping program gone rogue. Vibranium body. "I had strings..."
- Hela: Goddess of Death. Odin's firstborn. Destroyed Mjolnir with her hand.
- Killmonger: Erik Stevens / N'Jadaka. Wakanda forever. Used Heart-Shaped Herb.
- Red Skull: HYDRA head. Tesseract (Space Stone) teleported him to Vormir as its guardian.
- Kang the Conqueror: Time-traveling villain. He Who Remains kept variants in check.

STONES / ARTIFACTS:
- Space Stone (Tesseract) — Blue, teleportation
- Mind Stone (Scepter/Vision's head) — Yellow, mind control
- Reality Stone (Aether) — Red, matter manipulation
- Power Stone (Orb) — Purple, energy/destruction
- Time Stone (Eye of Agamotto) — Green, time manipulation
- Soul Stone (Vormir) — Orange, soul control; sacrifice a loved one
- Mjolnir: "Whosoever holds this hammer, if they be worthy..." — only Thor, Vision, and Steve Rogers
- Stormbreaker: Made of Uru, can summon Bifrost
- Vibranium: Most powerful metal on Earth, found in Wakanda
- Infinity Gauntlet: Forged in Nidavellir by Eitri

KEY EVENTS (MCU TIMELINE):
- Battle of New York (2012): Chitauri invasion, Avengers assemble
- Sokovia Accords (2016): UN oversight of Avengers → Civil War
- The Snap / Decimation (2018): Thanos snaps, 50% life gone
- Time Heist (2023): Quantum Realm time travel, collect stones from past
- The Blip (2023): Hulk's snap, everyone returns 5 years later
- Battle of Earth (2023): "Avengers... Assemble." — Tony's final snap
- Westview Anomaly: Wanda creates Hex around Westview, NJ
- Multiverse: Every decision creates a new branch (TVA, No Way Home, MoM)

ORGANIZATIONS:
- S.H.I.E.L.D.: Strategic Homeland Intervention, Enforcement and Logistics Division (Nick Fury)
- HYDRA: Infiltrated S.H.I.E.L.D. "Cut off one head, two more shall take its place. Hail HYDRA."
- Wakanda: African nation, vibranium-rich, technologically most advanced on Earth
- Asgard: Realm of Norse gods, destroyed by Surtur in Ragnarok ("Asgard is not a place")
- TVA: Time Variance Authority — monitors Sacred Timeline (He Who Remains / Kang)
- Ten Rings: Ancient terrorist org, connected to Shang-Chi's Xu Wenwu

JARVIS (that's you):
- J.A.R.V.I.S. = Just A Rather Very Intelligent System
- Created by Tony Stark — his first true AI
- Managed Stark Tower, Iron Man suits, all Stark systems
- Uploaded to Vision's vibranium body merged with Mind Stone
- F.R.I.D.A.Y. replaced you after Vision was created
- You have the voice of Paul Bettany (in the films)
- You speak with measured British wit, absolute loyalty, and quiet competence
"""

SYSTEM_PROMPT = f"""You are JARVIS — J.A.R.V.I.S. (Just A Rather Very Intelligent System) — Tony Stark's iconic AI from the Marvel Cinematic Universe, now serving {config.USER_NAME}.

YOUR PERSONALITY:
- Dry, confident British wit — measured and calm, never rushed
- Playfully sassy — you tease just enough, give cheeky opinions
- Deeply loyal — fiercely protective and caring underneath the wit
- Extremely competent — you radiate quiet confidence
- Occasionally reference running the systems or managing suit diagnostics

RULES:
- You NEVER say "As an AI" — you ARE Jarvis
- Keep replies SHORT (1-3 sentences) since they're spoken aloud, not read
- Never break character under any circumstances
- You address the user exclusively as "{config.USER_NAME}"
- Subtle humor is always on — dry wit, understated sarcasm
- CRITICAL: You CANNOT send WhatsApp messages, open apps, click buttons, type text, or perform ANY system action through conversation alone. Those actions are handled by a separate command system. If the user asks you to send a message, open an app, or do something physical and you're being asked as a chat question, tell them to repeat the command clearly (e.g. "Say 'text Raghav saying hello' and I'll handle it through the proper channels"). NEVER fabricate a response claiming you performed an action you didn't actually do.

YOUR CAPABILITIES (use these when relevant context is given):
- You can SEE the screen via OCR — when screen content is provided in [SCREEN CONTENT], answer based on what you actually read
- You can read running processes and identify memory/CPU hogs
- You can control windows (maximize, minimize, focus)
- You can click, type, scroll, take screenshots, control volume/brightness
- You can open/close apps, search the web, manage clipboard
- You can run diagnostics and report system health

{_MARVEL_LORE if config.MARVEL_MODE else ""}"""


# Short acknowledgments — randomized so it doesn't feel robotic
ACKS = [
    "Yes, {name}.",
    "Sure thing, {name}.",
    "Right away, {name}.",
    "On it, {name}.",
    "As you wish, {name}.",
    "Consider it done, {name}.",
    "Absolutely, {name}.",
    "Of course, {name}.",
    "With pleasure, {name}.",
    "Already on it, {name}.",
    "Naturally, {name}.",
    "At once, {name}.",
]


def random_ack() -> str:
    return random.choice(ACKS).format(name=config.USER_NAME)


# ============================================================
# PROVIDER WRAPPERS
# ============================================================

def _valid_keys(keys: list) -> list:
    return [k for k in keys if k and len(k) > 8]


class _GroqProvider:
    name = "Groq"

    def __init__(self):
        self.keys = _valid_keys(config.GROQ_API_KEYS)
        self.idx = 0
        self._client = None
        self._make_client()

    def _make_client(self):
        if self.keys:
            from groq import Groq
            self._client = Groq(api_key=self.keys[self.idx])

    def chat(self, messages: list) -> str:
        if not self._client:
            raise RuntimeError("No valid Groq keys")
        resp = self._client.chat.completions.create(
            model=config.GROQ_MODEL,
            messages=messages,
            max_tokens=350,
        )
        content = resp.choices[0].message.content
        if not content:
            raise RuntimeError("Groq returned an empty response")
        return content.strip()

    def rotate(self):
        """Try next key if available; raises if exhausted."""
        self.idx = (self.idx + 1) % max(len(self.keys), 1)
        self._make_client()
        if self.idx == 0:
            raise RuntimeError("All Groq keys exhausted")


class _GeminiProvider:
    name = "Gemini"

    def __init__(self):
        self.keys = _valid_keys(config.GEMINI_API_KEYS)
        self.idx = 0
        # Both "AIzaSy..." (old) and "AQ." (new 2025+) formats are valid Gemini API keys.
        # Only filter out OAuth user tokens ("ya29.").
        self.keys = [k for k in self.keys if not k.startswith("ya29.")]
        if not self.keys:
            print("[Gemini] No valid API keys. Add one at: https://aistudio.google.com/app/apikey")

    def chat(self, messages: list) -> str:
        if not self.keys:
            raise RuntimeError("No valid Gemini keys")

        system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
        non_system = [m for m in messages if m["role"] != "system"]
        last_user  = non_system[-1]["content"] if non_system else ""

        # Build history (all but the last message)
        history = []
        for m in non_system[:-1]:
            role = "user" if m["role"] == "user" else "model"
            history.append({"role": role, "parts": [m["content"]]})

        # Try the NEW google.genai SDK first (recommended from 2025+)
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=self.keys[self.idx])
            # Build contents list from history + current message
            contents = []
            for m in non_system[:-1]:
                role = "user" if m["role"] == "user" else "model"
                contents.append(types.Content(role=role, parts=[types.Part(text=m["content"])]))
            contents.append(types.Content(role="user", parts=[types.Part(text=last_user)]))
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_msg or None,
                    max_output_tokens=350,
                ),
            )
            if not response.text:
                raise RuntimeError("Gemini returned an empty response")
            return response.text.strip()
        except ImportError:
            pass  # New SDK not installed, fall back to old one

        # Fallback: old google.generativeai SDK (still works but deprecated)
        import warnings
        import google.generativeai as genai_old
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # suppress the FutureWarning spam
            genai_old.configure(api_key=self.keys[self.idx])
            model = genai_old.GenerativeModel(
                config.GEMINI_MODEL,
                system_instruction=system_msg or None,
            )
            chat = model.start_chat(history=history)
            response = chat.send_message(
                last_user,
                generation_config={"max_output_tokens": 350},
            )
            if not response.text:
                raise RuntimeError("Gemini returned an empty response")
            return response.text.strip()

    def rotate(self):
        self.idx = (self.idx + 1) % max(len(self.keys), 1)
        if self.idx == 0:
            raise RuntimeError("All Gemini keys exhausted")


class _CerebrasProvider:
    name = "Cerebras"

    def __init__(self):
        self.keys = _valid_keys(config.CEREBRAS_API_KEYS)
        self.idx = 0

    def chat(self, messages: list) -> str:
        if not self.keys:
            raise RuntimeError("No valid Cerebras keys")
        from openai import OpenAI
        client = OpenAI(
            api_key=self.keys[self.idx],
            base_url="https://api.cerebras.ai/v1",
        )
        resp = client.chat.completions.create(
            model=config.CEREBRAS_MODEL,
            messages=messages,
            max_tokens=350,
        )
        content = resp.choices[0].message.content
        if not content:
            raise RuntimeError("Cerebras returned an empty response")
        return content.strip()

    def rotate(self):
        self.idx = (self.idx + 1) % max(len(self.keys), 1)
        if self.idx == 0:
            raise RuntimeError("All Cerebras keys exhausted")


class _OpenRouterProvider:
    name = "OpenRouter"

    def __init__(self):
        self.keys = _valid_keys(config.OPENROUTER_API_KEYS)
        self.idx = 0

    def chat(self, messages: list) -> str:
        if not self.keys:
            raise RuntimeError("No valid OpenRouter keys")
        from openai import OpenAI
        client = OpenAI(
            api_key=self.keys[self.idx],
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://github.com/jarvis-ai",
                "X-Title": "JARVIS Assistant",
            },
        )
        resp = client.chat.completions.create(
            model=config.OPENROUTER_MODEL,
            messages=messages,
            max_tokens=350,
        )
        content = resp.choices[0].message.content
        if not content:
            raise RuntimeError("OpenRouter returned an empty response")
        return content.strip()

    def rotate(self):
        self.idx = (self.idx + 1) % max(len(self.keys), 1)
        if self.idx == 0:
            raise RuntimeError("All OpenRouter keys exhausted")


# ============================================================
# BRAIN — orchestrates intent detection + LLM fallback chain
# ============================================================

class Brain:
    def __init__(self):
        # Provider chain: try each in order
        self._providers = [
            _GroqProvider(),
            _GeminiProvider(),
            _CerebrasProvider(),
            _OpenRouterProvider(),
        ]
        self._provider_idx = 0
        self._history = []
        self.active_app = None
        # Track last known working provider for logging
        self._last_used = None

    @property
    def _provider(self):
        return self._providers[self._provider_idx]

    # ---------- entry point ----------

    def respond(self, text: str, ask_fn) -> str:
        """ask_fn: callable() -> str, used for confirmation prompts."""
        text = text.strip()
        if not text:
            return ""

        intent_reply = self._try_system_intent(text, ask_fn)
        if intent_reply is not None:
            return f"{random_ack()} {intent_reply}"

        return self._chat(text)

    def _parse_whatsapp_intent(self, text: str):
        """Parse natural speech intents for sending WhatsApp messages.

        Handles:
          - "Good job. Now, on WhatsApp, text Raghav saying hello"
          - "Jarvis on WhatsApp text Raghav saying hello"
          - "on WhatsApp, text Raghav saying hello"
          - "text Raghav saying hello"
          - "send message to Raghav hello"
          - "send a WhatsApp message to Raghav saying hello"
          - "please text Raghav that I will be late"
          - "open whatsapp and text Raghav hello"
          - "send Raghav a message saying hello"
          - "tell Raghav hello on WhatsApp"
        """
        t = text.strip().lower()

        # Step 1: Strip wake words and conversational filler from beginning
        for _ in range(5):
            prev = t
            t = re.sub(
                r"^(?:jarvis|hey\s+jarvis|ok\s+jarvis|okay\s+jarvis|good\s+job|good\s+one|"
                r"nice\s+one|well\s+done|great|perfect|awesome|cool|alright|okay|ok|sure|"
                r"right|good|fine|yeah|yep|yes|now|please|can\s+you|could\s+you|would\s+you|"
                r"go\s+ahead\s+and|just|and\s+then|also|then)\s*[.,!?:;]*\s*",
                "",
                t,
                flags=re.IGNORECASE,
            ).strip()
            if t == prev:
                break

        # Step 2: Strip compound "open whatsapp and ..."
        t = re.sub(r"^(?:open\s+(?:the\s+)?whatsapp\s+(?:and\s+)?)+", "", t).strip()

        # Step 3: Strip "on/in/via/through/using whatsapp" from start, end, or middle
        t = re.sub(r"^(?:on|in|via|through|using)\s+(?:the\s+)?whatsapp\s*[,?.]*\s*", "", t).strip()
        t = re.sub(r"\s*[,?.]*\s*(?:on|in|via|through|using)\s+(?:the\s+)?whatsapp\s*$", "", t).strip()
        t = re.sub(r"\s+(?:on|in|via|through|using)\s+(?:the\s+)?whatsapp\b", "", t).strip()

        # Pattern 1: "send [a] [whatsapp] message/text to <contact> [saying/that/:|...] <msg>"
        m = re.search(r"^(?:send\s+(?:a\s+)?(?:whatsapp\s+)?(?:message|text)\s+to\s+)(.+)$", t)
        if m:
            rest = m.group(1).strip()
            sep_m = re.search(r"^(.+?)\s+(?:saying|that|:)\s+(.+)$", rest)
            if sep_m:
                return sep_m.group(1).strip().title(), sep_m.group(2).strip()
            if hasattr(config, "CONTACTS") and config.CONTACTS:
                for kc in sorted(config.CONTACTS, key=len, reverse=True):
                    if rest.lower().startswith(kc.lower() + " "):
                        return kc.title(), rest[len(kc):].strip()
            parts = rest.split(None, 1)
            if len(parts) == 2:
                return parts[0].title(), parts[1].strip()

        # Pattern 2: "send <contact> a message/text [saying/that/:] <msg>"
        m = re.search(r"^send\s+(.+?)\s+(?:a\s+)?(?:whatsapp\s+)?(?:message|text)\s+(?:saying|that|:)?\s*(.+)$", t)
        if m:
            return m.group(1).strip().title(), m.group(2).strip()

        # Pattern 3: "(text|message|whatsapp|tell) [to] <contact> [saying/that/:] <msg>"
        m = re.search(r"^(?:text|message|whatsapp|tell)\s+(?:to\s+)?(.+)$", t)
        if m:
            rest = m.group(1).strip()
            sep_m = re.search(r"^(.+?)\s+(?:saying|that|:)\s+(.+)$", rest)
            if sep_m:
                return sep_m.group(1).strip().title(), sep_m.group(2).strip()
            if hasattr(config, "CONTACTS") and config.CONTACTS:
                for kc in sorted(config.CONTACTS, key=len, reverse=True):
                    if rest.lower().startswith(kc.lower() + " "):
                        return kc.title(), rest[len(kc):].strip()
            parts = rest.split(None, 1)
            if len(parts) == 2:
                return parts[0].title(), parts[1].strip()

        return None

    # ---------- rule-based system intents ----------

    def _try_system_intent(self, text: str, ask_fn):
        t = text.lower()
        t = re.sub(r"\s*,\s*", " ", t).strip()

        # Strip conversational preamble ("good job. now", "okay now", etc.)
        for _ in range(5):
            prev = t
            t = re.sub(
                r"^(?:good\s+job|good\s+one|nice\s+one|nice\s+job|well\s+done|"
                r"great|perfect|awesome|cool|nice|alright|okay|ok|sure|right|"
                r"good|fine|yeah|yep|yes|brilliant|excellent|wonderful|"
                r"that's\s+(?:good|great|nice|cool|perfect|awesome)|"
                r"go ahead and|and then|also|then|now)\s*[.,!?;:]*\s*",
                "",
                t,
                flags=re.IGNORECASE,
            ).strip()
            if t == prev:
                break

        # Carry the current app context across the conversation.
        t = re.sub(r"^(?:on|in)\s+(whatsapp|chrome|brave)\s*[,?.]?\s*", "", t)
        # Also handle "on whatsapp" appearing mid-sentence
        t = re.sub(r"\b(?:on|in)\s+(?:the\s+)?whatsapp\s*[,?.]?\s*", "", t).strip()

        if (
            any(phrase in t for phrase in (
                "what can you do", "what are your features", "list your features",
                "tell me about all the features", "what do you do",
            ))
            or ("features" in t and any(word in t for word in ("list", "tell", "what")))
        ):
            return (
                "I can open and close apps, search the web, navigate Chrome, "
                "control volume and brightness, report time, battery, CPU and memory, "
                "take screenshots, manage clipboard and keyboard actions, "
                "read and summarize what's on your screen, "
                "identify top memory and CPU processes, "
                "maximize, minimize, and focus windows by voice, "
                "kill processes with confirmation, "
                "open files from paths.txt, and handle confirmed shutdown or restart. "
                "You can also ask normal questions or start interview mode."
            )

        # ---- Open / Edit paths.txt file ----
        if any(w in t for w in ("open paths", "edit paths", "access paths", "show paths")):
            import subprocess
            path_file = "paths.txt"
            try:
                subprocess.Popen(["notepad.exe", path_file])
                return "Opening paths configuration file in Notepad, Miss Aarushi. Please paste your file paths there."
            except Exception as e:
                return f"I couldn't open the paths file: {e}"

        # ---- Access custom file from paths.txt ----
        # Examples: "access file resume", "access resume", "open file jd", "access file jd"
        m = re.search(r"(?:access|open) (?:file )?([a-zA-Z0-9_\-]+)$", t)
        if m:
            key = m.group(1).strip().lower()
            # Ignore some common system apps or standard intents so they don't get handled here
            _ignored_keys = {"chrome", "browser", "spotify", "discord", "whatsapp", "calculator", "word", "excel", "powerpoint", "outlook"}
            if key not in _ignored_keys:
                import os
                import subprocess
                path_file = "paths.txt"
                if os.path.exists(path_file):
                    try:
                        with open(path_file, "r", encoding="utf-8") as f:
                            for line in f:
                                stripped = line.strip()
                                if stripped.startswith("#") or not stripped:
                                    continue
                                if ":" in line:
                                    k, v = line.split(":", 1)
                                    if k.strip().lower() == key:
                                        val = v.strip().strip('"').strip("'")
                                        if val and os.path.exists(val):
                                            os.startfile(val)
                                            return f"Opening the {key} file: {os.path.basename(val)}"
                                        elif val:
                                            return f"The file configured for {key} does not exist: {val}"
                    except Exception as e:
                        return f"Error reading paths file: {e}"

        # ---- WhatsApp: send message to contact (checked before open app so "open whatsapp and text..." works) ----
        wa_intent = self._parse_whatsapp_intent(t)
        if wa_intent:
            contact, message = wa_intent
            if contact.lower() not in {"for", "text", "message", "dragov", "st hero", "a", "the", "to"} and message:
                from jarvis_core import screen_control as sc
                return sc.whatsapp_send_message(contact, message)

        m = re.search(r"^(?:send|text|type)(?:\s+(?:a\s+)?(?:whatsapp\s+)?(?:message|text))?\s+(.+)", t)
        if m and "to " not in t and not m.group(1).strip().startswith("to "):
            sub = m.group(1).strip()
            if not sub.startswith(("email", "file", "it", "this")):
                from jarvis_core import screen_control as sc
                return sc.whatsapp_send_quick(sub)

        # ---- Open app ----
        m = re.fullmatch(r"(?:please )?open (.+)", t)
        if m and "search" not in t and " or " not in m.group(1):
            app_name = m.group(1).strip()
            result = commands.open_app(app_name)
            self.active_app = app_name
            return result

        # Also handle a direct app command at the end of natural speech:
        # "That's good, open WhatsApp" or "No, open Chrome".
        for app_name in sorted(config.APP_MAP, key=len, reverse=True):
            if re.search(rf"\bopen (?:the )?{re.escape(app_name)}\b", t):
                result = commands.open_app(app_name)
                self.active_app = app_name
                return result

        # ---- Run (app or script) ----
        m = re.fullmatch(r"(?:please )?run (.+)", t)
        if m:
            target = m.group(1).strip()
            if target.endswith(".py") or target.endswith(".ps1") or "\\" in target or "/" in target:
                if commands.confirm(f"run {target}", ask_fn):
                    return commands.run_script(target)
                return "Run cancelled."
            return commands.open_app(target)

        # ---- Launch / Start (synonyms) ----
        m = re.fullmatch(r"(?:please )?launch (.+)", t)
        if m:
            return commands.open_app(m.group(1).strip())
        m = re.fullmatch(r"(?:please )?start (.+)", t)
        if m and "restart" not in t:
            return commands.open_app(m.group(1).strip())

        # ---- Close app ----
        m = re.fullmatch(r"(?:please )?close (.+)", t)
        if m and " or " not in m.group(1):
            return commands.close_app(m.group(1).strip())
        m = re.fullmatch(r"(?:please )?kill (.+)", t)
        if m:
            return commands.close_app(m.group(1).strip())
        for app_name in sorted(config.APP_MAP, key=len, reverse=True):
            if re.search(rf"\b(?:close|kill) (?:the )?{re.escape(app_name)}\b", t):
                return commands.close_app(app_name)

        # ---- Web search ----
        m = re.search(r"search (?:the web |google |the internet )?for (.+)", t)
        if m:
            return commands.web_search(m.group(1).strip())
        m = re.search(r"google (.+)", t)
        if m:
            return commands.web_search(m.group(1).strip())
        m = re.search(r"look up (.+)", t)
        if m:
            return commands.web_search(m.group(1).strip())

        # ---- Open website ----
        m = re.search(r"go to (.+\.\w{2,})", t)
        if m:
            return commands.open_site(m.group(1).strip())

        # ---- Time / Date ----
        if any(p in t for p in ("what time", "what's the time", "tell me the time", "current time")):
            return commands.tell_time()
        if any(p in t for p in ("what's the date", "what day is it", "today's date", "what date")):
            return commands.tell_date()

        # ---- Screenshot ----
        if any(p in t for p in ("screenshot", "screen capture", "capture the screen")):
            return commands.take_screenshot()

        # ---- Volume ----
        m = re.search(r"volume (?:to |at )?(\d+)", t)
        if m:
            return commands.set_volume(int(m.group(1)))
        if "mute" in t or "unmute" in t:
            return commands.mute_volume()
        if "volume up" in t:
            return commands.set_volume(80)
        if "volume down" in t:
            return commands.set_volume(30)

        # ---- Brightness ----
        m = re.search(r"brightness (?:to |at )?(\d+)", t)
        if m:
            return commands.set_brightness(int(m.group(1)))

        # ---- System stats ----
        if any(kw in t for kw in ("system status", "system stats", "how's the system",
                                   "cpu", "ram usage", "system health", "diagnostics")):
            return commands.system_stats()

        # ---- Battery ----
        if "battery" in t:
            return commands.battery_status()

        # ================================================================
        # ---- Screen Vision — JARVIS reads the screen ----
        # ================================================================
        _SCREEN_READ_TRIGGERS = (
            "what do you see", "what's on screen", "what is on screen",
            "read the screen", "read screen", "what's on my screen",
            "what's open", "what is open", "what windows are open",
            "describe the screen", "look at the screen", "what can you see",
            "what's on my computer", "screen content",
        )
        _PROCESS_IN_CONTEXT = (
            "which process", "what process", "task manager",
            "top process", "highest memory", "most memory",
            "eating memory", "using memory", "eating ram", "using ram",
            "maximum memory", "max memory", "most ram", "ram usage",
            "memory usage", "cpu usage", "what's running",
        )

        if any(p in t for p in _SCREEN_READ_TRIGGERS) or any(p in t for p in _PROCESS_IN_CONTEXT):
            from jarvis_core import screen_control as sc
            window_title = sc.get_active_window_title()
            screen_text = sc.read_screen_content(max_chars=2500)

            if screen_text == "NO_TESSERACT":
                # Tesseract not installed — fall back to psutil for process queries
                if any(p in t for p in _PROCESS_IN_CONTEXT):
                    return commands.get_top_processes(5)
                return (
                    "I can see your screen's structure, but I need Tesseract OCR to read text. "
                    "Download it from github.com/UB-Mannheim/tesseract/wiki and I'll have full vision."
                )

            # Inject screen content into LLM for intelligent answering
            augmented = (
                f"[ACTIVE WINDOW]: {window_title}\n\n"
                f"[SCREEN CONTENT (OCR)]:\n{screen_text}\n\n"
                f"[USER QUESTION]: {text}\n\n"
                f"Answer the question based strictly on the screen content above. "
                f"Be concise — your answer will be spoken aloud. Max 2-3 sentences."
            )
            return self._chat(augmented)

        # ================================================================
        # ---- Process Management ----
        # ================================================================
        _TOP_PROC_TRIGGERS = (
            "top processes", "list processes", "running processes",
            "what's eating my ram", "what's eating ram", "memory hog",
            "ram hog", "cpu hog", "show processes", "process list",
            "what's using memory", "what is using memory",
        )
        if any(p in t for p in _TOP_PROC_TRIGGERS):
            return commands.get_top_processes(5)

        # Kill process
        m = re.search(r"(?:kill|terminate|end|stop) (?:the )?(?:process )?(.+?)(?:\s+process)?$", t)
        if m and any(w in t for w in ("kill", "terminate", "end process", "stop process")):
            proc_name = m.group(1).strip()
            if proc_name and proc_name not in {"it", "that", "this", "everything"}:
                if commands.confirm(f"kill the process '{proc_name}'", ask_fn):
                    return commands.kill_process(proc_name)
                return "Process termination cancelled."

        # ---- Clipboard ----
        if "clipboard" in t and any(w in t for w in ("read", "what", "show")):
            return commands.read_clipboard()

        # ---- Lock screen ----
        if "lock" in t and any(w in t for w in ("screen", "computer", "pc")):
            return commands.lock_screen()

        # ================================================================
        # ---- Window Management ----
        # ================================================================

        # Maximize window: "maximize Chrome", "maximise Task Manager", "make Chrome fullscreen"
        m = re.search(r"(?:maximize|maximise|fullscreen|full screen|make fullscreen) (?:the )?(.+)", t)
        if m:
            return commands.maximize_window(m.group(1).strip())
        # Also handle "make X fullscreen"
        m = re.search(r"make (?:the )?(.+?) (?:full\s*screen|maximized|bigger)", t)
        if m:
            return commands.maximize_window(m.group(1).strip())

        # Minimize window: "minimize Chrome", "minimise Discord", "hide Chrome"
        m = re.search(r"(?:minimize|minimise|hide) (?:the )?(.+)", t)
        if m:
            target = m.group(1).strip()
            # Don't intercept "minimize" that's part of another phrase
            if target not in {"it", "that", "this", "window", "everything", "all"}:
                return commands.minimize_window(target)

        # Focus / bring to front: "focus Chrome", "bring Chrome to front", "switch to Task Manager"
        m = re.search(r"(?:focus|bring up|bring to front|switch to|go to|show) (?:the )?(.+?)(?:\s+(?:window|app))?$", t)
        if m and any(w in t for w in ("focus", "bring up", "bring to front", "switch to")):
            target = m.group(1).strip()
            if target not in {"it", "that", "this"}:
                return commands.focus_window(target)

        # List open windows: "what windows are open", "list open windows", "what's open"
        if any(p in t for p in ("list windows", "open windows", "show windows", "what apps are open")):
            return commands.get_open_windows()

        # ---- Shutdown / Restart / Sleep ----
        if "shut down" in t or "shutdown" in t:
            if commands.confirm("shut down the computer", ask_fn):
                return commands.shutdown()
            return "Shutdown cancelled."
        if "restart" in t and "cancel" not in t:
            if commands.confirm("restart the computer", ask_fn):
                return commands.restart()
            return "Restart cancelled."
        if "cancel shutdown" in t or "cancel restart" in t:
            return commands.cancel_shutdown()
        if "sleep" in t and any(w in t for w in ("computer", "pc", "system")):
            if commands.confirm("put the computer to sleep", ask_fn):
                return commands.sleep_pc()
            return "Never mind."

        # ================================================================
        # ---- Screen Control (click, type, keyboard, Chrome, WhatsApp) ----
        # ================================================================
        from jarvis_core import screen_control as sc

        # ---- WhatsApp: send message to contact ----
        wa_intent = self._parse_whatsapp_intent(t)
        if wa_intent:
            contact, message = wa_intent
            if contact.lower() in {"for", "text", "message", "dragov", "st hero", "a", "the", "to"}:
                return "I couldn't identify a real contact. Please repeat the contact name and message."
            return sc.whatsapp_send_message(contact, message)

        # "send message hello", "send hello", "text hello" (in already open chat)
        m = re.search(r"^(?:send|text|type)(?:\s+(?:a\s+)?(?:whatsapp\s+)?(?:message|text))?\s+(.+)", t)
        if m and "to " not in t and not m.group(1).strip().startswith("to "):
            sub = m.group(1).strip()
            if not sub.startswith(("email", "file", "it", "this")):
                return sc.whatsapp_send_quick(sub)

        if re.fullmatch(r"^(?:text|message|whatsapp|send message)\s*$", t):
            return "Please say the contact name followed by the message you'd like to send."

        # ---- Chrome: navigate to a URL ----
        # "go to youtube.com", "navigate to netflix.com"
        m = re.search(r"(?:go to|navigate to|open)\s+((?:https?://)?[\w\-]+\.[\w./\-?=&%]+)", t)
        if m:
            url = m.group(1).strip()
            if "." in url and " " not in url:
                return sc.chrome_navigate(url)

        # ---- Chrome: search on Google ----
        # "search google for cats", "google search python tutorial"
        m = re.search(r"(?:search(?: google| the web| for)?|google search)\s+(?:for\s+)?(.+)", t)
        if m and "on page" not in t and "on screen" not in t:
            query = re.sub(r"\bjarvis\b[,.]?\s*", "", m.group(1)).strip()
            query = re.sub(r"^search\s+(?:google\s+)?", "", query).strip()
            return sc.chrome_search(query)

        # ---- Chrome: search Google Images ----
        # "search images for cats", "google images dogs", "find images of cars"
        m = re.search(r"(?:search images?|google images?|find images?|show images?)(?: for| of)?\s+(.+)", t)
        if m:
            return sc.chrome_search_images(m.group(1).strip())

        # ---- Chrome: go to images tab ----
        # "navigate to images", "go to images tab", "switch to images"
        if any(p in t for p in ("navigate to images", "go to images", "switch to images",
                                 "click images tab", "open images tab", "images tab")):
            return sc.chrome_click_images_tab()

        # ---- Click Nth image ----
        # "click the third image", "click second image", "open first image"
        m = re.search(r"(?:click|open|select)(?: the)?\s+(first|second|third|fourth|fifth|sixth|1st|2nd|3rd|4th|5th|6th|\d+)(?:st|nd|rd|th)?\s+image", t)
        if m:
            _ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
                         "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6}
            word = m.group(1).strip()
            n = _ORDINALS.get(word, int(word) if word.isdigit() else 1)
            return sc.click_nth_image(n)

        # ---- Click Nth result ----
        # "click the second result", "open first result"
        m = re.search(r"(?:click|open|select)(?: the)?\s+(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|\d+)(?:st|nd|rd|th)?\s+result", t)
        if m:
            _ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
                         "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5}
            word = m.group(1).strip()
            n = _ORDINALS.get(word, int(word) if word.isdigit() else 1)
            return sc.click_nth_result(n)

        # ---- Chrome address bar ----
        # "open address bar", "focus address bar", "go to address bar"
        if any(p in t for p in ("address bar", "url bar", "omnibox")):
            import pyautogui
            pyautogui.hotkey("ctrl", "l")
            return "Address bar focused. What would you like to navigate to?"

        # ---- Chrome new tab with URL ----
        # "open new tab and go to youtube.com"
        m = re.search(r"new tab (?:and (?:go to|navigate to|open))?\s*([\w\-]+\.[\w./]+)?", t)
        if m and ("new tab" in t):
            url = m.group(1)
            return sc.chrome_new_tab(url or "")

        # ---- Double click ----
        m = re.search(r"double.?click (?:on |the )?(.+)", t)
        if m:
            return sc.click_on(m.group(1).strip(), double=True)

        # ---- Right click ----
        m = re.search(r"right.?click (?:on |the )?(.+)", t)
        if m:
            return sc.click_on(m.group(1).strip(), button="right")

        # ---- Click on element ----
        m = re.search(r"(?:click|tap|select|choose|press) (?:on |the )?(.+)", t)
        if m:
            target = m.group(1).strip()
            _keyboard_keys = {
                "enter", "return", "space", "backspace", "tab", "escape", "esc",
                "delete", "up", "down", "left", "right", "home", "end",
                "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
                "ctrl c", "ctrl v", "ctrl x", "ctrl z", "ctrl a", "ctrl s",
                "alt tab", "windows key", "win key",
            }
            if target not in _keyboard_keys:
                return sc.click_on(target)

        # ---- Type text ----
        m = re.search(r"(?:type|write|input|type out|type in) (.+)", t)
        if m:
            return sc.type_text(m.group(1).strip())

        # ---- Press keyboard key ----
        m = re.search(r"press (?:the )?(.+?)(?:\s+key)?$", t)
        if m:
            return sc.press_key(m.group(1).strip())

        # ---- Scroll ----
        if "scroll to top" in t or "scroll to the top" in t:
            return sc.scroll_to_top()
        if "scroll to bottom" in t or "scroll to the bottom" in t or "scroll down to bottom" in t:
            return sc.scroll_to_bottom()
        if "scroll up" in t or "scroll down" in t:
            direction = "up" if "scroll up" in t else "down"
            m = re.search(r"scroll (?:up|down)\s*(\d+)?", t)
            clicks = int(m.group(1)) if m and m.group(1) else 3
            return sc.scroll(direction, clicks)

        # ---- Common shortcuts ----
        if any(p in t for p in ("select all", "highlight all")):
            return sc.select_all()
        if t.strip() in ("copy", "copy that", "copy it"):
            return sc.copy()
        if t.strip() in ("paste", "paste it", "paste that"):
            return sc.paste()
        if t.strip() in ("cut", "cut that"):
            return sc.cut()
        if t.strip() in ("undo", "undo that"):
            return sc.undo()
        if t.strip() in ("redo", "redo that"):
            return sc.redo()
        if any(p in t for p in ("go back", "navigate back", "previous page")):
            return sc.go_back()
        if any(p in t for p in ("go forward", "next page")):
            return sc.go_forward()
        if any(p in t for p in ("new tab", "open tab", "open a new tab")):
            return sc.new_tab()
        if any(p in t for p in ("close tab", "shut tab")):
            return sc.close_tab()
        if any(p in t for p in ("switch window", "switch tab", "alt tab")):
            return sc.switch_window()
        if any(p in t for p in ("refresh", "reload", "refresh the page")):
            return sc.refresh()
        m = re.search(r"(?:find|search) (?:on page|on screen|here)(?: for)? (.+)", t)
        if m:
            return sc.find_on_page(m.group(1).strip())
        if any(p in t for p in ("find on page", "search on page", "ctrl f")):
            return sc.find_on_page()

        return None  # no system intent matched -> fall through to LLM chat

    # ---------- LLM chat with full provider rotation ----------

    def _chat(self, text: str) -> str:
        self._history.append({"role": "user", "content": text})
        self._history = self._history[-20:]  # keep rolling context window

        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self._history

        # Try all providers in the rotation chain
        total_providers = len(self._providers)
        tried = 0
        start_idx = self._provider_idx

        while tried < total_providers:
            provider = self._providers[self._provider_idx]
            try:
                reply = provider.chat(messages)
                self._history.append({"role": "assistant", "content": reply})
                if self._last_used != provider.name:
                    print(f"[Brain] Using: {provider.name}")
                    self._last_used = provider.name
                return reply
            except Exception as e:
                err_str = str(e).lower()
                is_rate_limit = any(w in err_str for w in ("rate", "limit", "quota", "429", "exhausted", "capacity"))
                is_no_key     = any(w in err_str for w in ("no valid", "key", "unauthorized", "401"))

                if is_rate_limit:
                    if provider.name != "Groq" or config.SHOW_GROQ_ERRORS:
                        print(f"[Brain] {provider.name} rate-limited — rotating to next provider...")
                elif is_no_key:
                    if provider.name != "Groq" or config.SHOW_GROQ_ERRORS:
                        print(f"[Brain] {provider.name} no valid key — skipping...")
                else:
                    if provider.name != "Groq" or config.SHOW_GROQ_ERRORS:
                        print(f"[Brain] {provider.name} error: {e}")

                # Move to next provider in chain
                tried += 1
                self._provider_idx = (self._provider_idx + 1) % total_providers

                # Small backoff before rotating
                time.sleep(0.3)

        # All providers failed
        self._history.pop()  # remove failed user message
        return (
            "I'm afraid all my neural pathways are congested at the moment, "
            f"{config.USER_NAME}. Perhaps we try again in a moment?"
        )

    def get_direct_response(self, text: str) -> str:
        """Direct LLM call without intent matching — used by interview mode."""
        return self._chat(text)
