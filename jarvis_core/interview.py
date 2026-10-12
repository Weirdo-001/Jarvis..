"""
interview.py — JARVIS Interview Mode (Zara-style)

Flow:
  1. Ask company + role → CONFIRM back
  2. Ask for resume path → CONFIRM file found
  3. Ask for JD path → CONFIRM file found
  4. Silently fetch context via LLM (NO browser windows)
  5. Ask permission for camera + screen monitoring
  6. Behavioral round → Technical round → Coding round
  7. Wrap-up + feedback + transcript saved

Rules:
  - Violations are QUEUED and spoken BETWEEN questions, never overlapping
  - Every input is CONFIRMED before proceeding
  - Coding round opens VS Code with an actual file to write in
"""

import os
import re
import time
import datetime
import threading
import subprocess

from . import config


# ----------------------------------------------------------------
# File helpers
# ----------------------------------------------------------------

def _extract_text(path: str) -> str:
    if not path or not os.path.exists(path):
        return ""
    if path.lower().endswith(".pdf"):
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                return "\n".join(page.extract_text() or "" for page in pdf.pages)
        except ImportError:
            return ""
    elif path.lower().endswith((".txt", ".md", ".docx")):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    return ""


def _clean_spoken_name(val: str) -> str:
    """Correct common Whisper speech-to-text mishearings for companies and roles."""
    low = val.strip().lower()
    # Remove trailing/leading punctuation
    low = re.sub(r"^[.,\/#!$%\^&\*;:{}=\-_`~()]+|[.,\/#!$%\^&\*;:{}=\-_`~()]+$", "", low).strip()

    # Map mishearings
    if low in ("tekintern", "tek intern", "techintern", "tech intern", "techintone"):
        return "Tech Intern"
    if low in ("techloin", "tech loin", "tekion", "techion", "tekion,"):
        return "Tekion"
    if "chitgara" in low:
        return "Chitkara"
    
    # Default to title case
    return val.strip().title()


def _parse_company_role(text: str) -> tuple[str, str]:
    """Parse company and role from natural speech."""
    t = text.strip()
    c, r = "", ""

    # "company is X and/,/ role is Y"
    m = re.search(
        r"company\s+(?:name\s+)?(?:is\s+)?(.+?)"
        r"(?:\s+and\s+|\s*,\s*)"
        r"(?:the\s+)?role\s+(?:is\s+)?(.+?)(?:\.|$)",
        t, re.IGNORECASE,
    )
    if m:
        c, r = m.group(1), m.group(2)
    else:
        # "role is X at Y"
        m = re.search(r"role\s+(?:is\s+)?(.+?)\s+(?:at|in|for)\s+(.+?)(?:\.|$)", t, re.IGNORECASE)
        if m:
            c, r = m.group(2), m.group(1)
        else:
            # "X at Y"
            m = re.search(r"(.+?)\s+(?:at|in|for|with)\s+(.+?)(?:\.|$)", t, re.IGNORECASE)
            if m:
                company = re.split(r"\s+(?:and|from)\s+", m.group(2).strip())[0].strip()
                c, r = company, m.group(1)
            else:
                words = t.split()
                if len(words) >= 2:
                    c, r = words[0], " ".join(words[1:])
                else:
                    c, r = (words[0] if words else ""), ""

    return _clean_spoken_name(c), _clean_spoken_name(r)


def _find_file_by_keyword(folder: str, keyword: str, exts=(".pdf", ".txt", ".md", ".docx")):
    """Find most recent file matching keyword in folder."""
    if not os.path.isdir(folder):
        return ""
    matches = [
        os.path.join(folder, f) for f in os.listdir(folder)
        if f.lower().endswith(exts) and keyword.lower() in f.lower()
    ]
    if not matches:
        matches = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(exts)]
    return max(matches, key=os.path.getmtime) if matches else ""


def _resolve_path(text: str) -> str:
    """Resolve spoken folder/file names to real paths."""
    t = text.strip().strip('"').strip("'").lower()
    home = os.path.expanduser("~")
    if "download" in t:
        return os.path.join(home, "Downloads")
    if "document" in t:
        return os.path.join(home, "Documents")
    if "desktop" in t:
        return os.path.join(home, "Desktop")
    # If it looks like a path
    raw = text.strip().strip('"').strip("'")
    if os.path.sep in raw or "/" in raw or ":" in raw:
        return raw
    # Try common locations
    for base in [home, os.path.join(home, "Downloads"),
                 os.path.join(home, "Documents"), os.path.join(home, "Desktop")]:
        cand = os.path.join(base, raw)
        if os.path.exists(cand):
            return cand
    return raw


def _get_path_from_txt(key: str) -> str:
    """Read a specific key (like 'resume' or 'jd') from paths.txt in workspace root."""
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
                        if k.strip().lower() == key.lower():
                            val = v.strip().strip('"').strip("'")
                            if val:
                                return val
        except Exception as e:
            print(f"[Paths File] Error reading paths.txt: {e}")
    return ""


# ----------------------------------------------------------------
# Proctors (violations are just COLLECTED, never spoken directly)
# ----------------------------------------------------------------

class _CameraProctor:
    def __init__(self):
        self._running = False
        self._thread = None
        self.violations = []

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self):
        try:
            import cv2
            cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            )
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                return
            absent_since = None
            while self._running:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.1)
                    continue
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = cascade.detectMultiScale(gray, 1.1, 5)
                if len(faces) == 0:
                    if absent_since is None:
                        absent_since = time.time()
                    elif time.time() - absent_since > 4.0:
                        self.violations.append({"time": datetime.datetime.now().isoformat(), "type": "face_absent"})
                        absent_since = time.time()
                else:
                    absent_since = None
                time.sleep(0.3)
            cap.release()
        except Exception:
            pass


class _ScreenProctor:
    def __init__(self):
        self._running = False
        self._thread = None
        self.violations = []

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self):
        try:
            import win32gui
            last = win32gui.GetForegroundWindow()
            while self._running:
                cur = win32gui.GetForegroundWindow()
                if cur != last:
                    title = win32gui.GetWindowText(cur)
                    self.violations.append({"time": datetime.datetime.now().isoformat(), "type": f"switch:{title}"})
                    last = cur
                time.sleep(0.5)
        except Exception:
            pass


# ----------------------------------------------------------------
# INTERVIEW SESSION
# ----------------------------------------------------------------

class InterviewSession:
    def __init__(self, brain, speak_fn, listen_fn):
        self.brain = brain
        self.speak = speak_fn
        self.listen = listen_fn
        self.qa_log = []
        self.cam = _CameraProctor()
        self.scr = _ScreenProctor()
        self._last_cam = 0
        self._last_scr = 0
        os.makedirs(config.INTERVIEW_DATA_DIR, exist_ok=True)

    # ---- helpers ----

    def _confirm(self, question: str, retries: int = 2) -> bool:
        """Ask yes/no confirmation. Returns True if confirmed."""
        self.speak(question)
        for _ in range(retries):
            resp = self.listen(phrase_time_limit=8)
            if not resp:
                self.speak("I didn't catch that. Yes or no?")
                continue
            low = resp.lower()
            if any(w in low for w in ("yes", "yeah", "yep", "correct", "right", "sure", "go ahead", "confirm")):
                return True
            if any(w in low for w in ("no", "nope", "wrong", "incorrect", "change", "not")):
                return False
            self.speak("Sorry, I need a yes or no.")
        return False

    def _ask_llm(self, prompt: str) -> str:
        try:
            return self.brain.get_direct_response(prompt)
        except Exception:
            return ""

    def _speak_violations_between_questions(self):
        """Speak queued violations BETWEEN questions only. Never overlaps."""
        cam_new = len(self.cam.violations) - self._last_cam
        scr_new = len(self.scr.violations) - self._last_scr
        self._last_cam = len(self.cam.violations)
        self._last_scr = len(self.scr.violations)
        parts = []
        if cam_new > 0:
            parts.append(f"You looked away {cam_new} time{'s' if cam_new > 1 else ''}.")
        if scr_new > 0:
            parts.append(f"You switched windows {scr_new} time{'s' if scr_new > 1 else ''}.")
        if parts:
            self.speak(" ".join(parts) + " Please stay focused. This is recorded.")
            self.qa_log.append({"role": "proctor", "content": " ".join(parts)})

    def _detect_role_type(self, role: str, jd_text: str) -> str:
        combined = f"{role} {jd_text}".lower()
        if any(k in combined for k in ("data analyst", "data science", "analytics", "bi ")):
            return "data_analyst"
        if any(k in combined for k in ("data engineer", "etl", "pipeline", "spark")):
            return "data_engineer"
        if any(k in combined for k in ("frontend", "react", "angular", "vue")):
            return "frontend"
        if any(k in combined for k in ("backend", "api", "microservice", "django", "flask", "spring")):
            return "backend"
        if any(k in combined for k in ("full stack", "fullstack", "mern")):
            return "fullstack"
        if any(k in combined for k in ("machine learning", "ml ", "deep learning")):
            return "ml_engineer"
        if any(k in combined for k in ("software", "sde", "developer", "engineer", "intern", "trainee")):
            return "sde"
        return "general"

    def _detect_coding_lang(self, jd_text: str, role_type: str) -> str:
        """Detect primary coding language from JD. Defaults to Java + SQL."""
        jd = jd_text.lower()
        has_java = any(k in jd for k in ("java", "oop", "object oriented", "spring", "jvm", "collections"))
        has_sql = any(k in jd for k in ("sql", "rdbms", "database", "mysql", "postgres", "oracle", "queries"))
        has_python = any(k in jd for k in ("python", "django", "flask", "pandas", "numpy"))
        has_js = any(k in jd for k in ("javascript", "typescript", "react", "node", "angular"))

        if has_java and has_sql:
            return "java_sql"
        if has_java:
            return "java"
        if has_sql:
            return "sql"
        if has_python:
            return "python"
        if has_js:
            return "javascript"
        # Default based on role
        if role_type in ("data_analyst", "data_engineer"):
            return "sql"
        return "java_sql"   # default: Java + SQL (most common for Indian tech interviews)

    def _build_prompt(self, company, role, role_type, resume_text, jd_text, context):
        coding_lang = self._detect_coding_lang(jd_text, role_type)
        lang_desc = {
            "java_sql": "Java (OOP, DSA, collections) AND SQL (joins, GROUP BY, HAVING, window functions, CTEs)",
            "java": "Java (OOP, DSA: arrays, trees, graphs, DP, collections framework)",
            "sql": "SQL (advanced joins, GROUP BY, HAVING, window functions, CTEs, subqueries)",
            "python": "Python (DSA, OOP, data structures)",
            "javascript": "JavaScript/TypeScript (DOM, async, React patterns)",
        }
        langs = lang_desc.get(coding_lang, lang_desc["java_sql"])
        self._coding_lang = coding_lang  # store for file creation later

        return f"""You are a STRICT senior technical interviewer at {company} for {role}.

CANDIDATE RESUME:
{resume_text[:3000] if resume_text else "Not provided."}

JOB DESCRIPTION:
{jd_text[:2000] if jd_text else "Not provided."}

COMPANY CONTEXT:
{context[:800] if context else "N/A"}

RULES (FOLLOW EXACTLY):
1. Ask ONE question at a time. WAIT for answer. Never ask multiple questions.
2. Keep responses SHORT — max 3 sentences. You are SPEAKING aloud, not writing.
3. Be strict but professional. Probe deeper if answers are vague.
4. Brief acknowledgments only: "I see", "Interesting", "Go on".
5. If wrong, note it silently, move on. Don't correct them (real interviewer behavior).
6. Do NOT repeat what the candidate said back to them at length.

STRUCTURE:
- PHASE 1 (2-3 Qs): Intro + behavioral ("Tell me about yourself", "Why {company}?", STAR)
- PHASE 2 (4-5 Qs): Technical deep-dive on resume skills. Ask about SPECIFIC projects/tech listed.
- PHASE 3: Coding. Say EXACTLY: "Let's move to coding. I've opened a file in VS Code. Here's your problem:" Then give ONE specific problem with input/output/constraints. Languages: {langs}. After they solve it, ask approach + time/space complexity.
- PHASE 4 (1-2 Qs): System design or situational (senior roles)
- WRAP UP: 2-3 sentences of honest feedback. End with "That concludes our interview."

Start: "Thank you for joining, {config.USER_NAME}. Let's begin. Tell me about yourself briefly."
"""

    # ================================================================
    # MAIN FLOW
    # ================================================================

    def run(self, company: str = "", role: str = ""):
        config.INTERVIEW_ACTIVE = True

        # ---- Step 1: Company + Role with CONFIRMATION ----
        for attempt in range(3):
            if not company or not role:
                self.speak("What company and role is this interview for?")
                resp = self.listen(phrase_time_limit=15)
                if resp:
                    company, role = _parse_company_role(resp)

            if company and role:
                confirmed = self._confirm(f"Company: {company}. Role: {role}. Is that correct?")
                if confirmed:
                    break
                else:
                    self.speak("Let me try again. Please say the company name, then the role.")
                    company, role = "", ""
            else:
                self.speak("I didn't catch that. Please say something like: Tekion, Software Engineer.")

        if not company:
            company = "the company"
        if not role:
            role = "the position"

        # ---- Step 2: Resume with CONFIRMATION ----
        resume_text = ""
        txt_path = _get_path_from_txt("resume")
        if txt_path and os.path.exists(txt_path):
            fname = os.path.basename(txt_path)
            if self._confirm(f"I found {fname} in your paths file. Should I use it as your resume?"):
                resume_text = _extract_text(txt_path)
                if resume_text:
                    self.speak("Resume loaded.")
        
        if not resume_text:
            self.speak("Where is your resume? Say the folder name like 'Downloads', or the full file name.")
            for attempt in range(2):
                resp = self.listen(phrase_time_limit=12)
                if not resp:
                    self.speak("I didn't hear that. Where's the resume?")
                    continue

                path = _resolve_path(resp)
                if os.path.isdir(path):
                    fpath = _find_file_by_keyword(path, "resume") or _find_file_by_keyword(path, "cv") or _find_file_by_keyword(path, "aarushi")
                    if fpath:
                        fname = os.path.basename(fpath)
                        if self._confirm(f"I found {fname}. Is this your resume?"):
                            resume_text = _extract_text(fpath)
                            self.speak("Resume loaded.")
                            break
                        else:
                            self.speak("Which file then? Say the exact name.")
                    else:
                        self.speak("No resume found in that folder. Try another location or say the file name.")
                elif os.path.isfile(path):
                    fname = os.path.basename(path)
                    resume_text = _extract_text(path)
                    self.speak(f"Loaded {fname}.")
                    break
                else:
                    self.speak("Couldn't find that. Try saying 'Downloads' or the file name.")

        if not resume_text:
            self.speak("Proceeding without resume.")

        # ---- Step 3: JD with CONFIRMATION ----
        jd_text = ""
        txt_jd_path = _get_path_from_txt("jd")
        if txt_jd_path and os.path.exists(txt_jd_path):
            fname = os.path.basename(txt_jd_path)
            if self._confirm(f"I found {fname} in your paths file. Should I use it as the job description?"):
                jd_text = _extract_text(txt_jd_path)
                if jd_text:
                    self.speak("JD loaded.")

        if not jd_text:
            self.speak("And the job description? Same format — folder or file name.")
            for attempt in range(2):
                resp = self.listen(phrase_time_limit=12)
                if not resp:
                    self.speak("Didn't catch that. Where's the JD?")
                    continue

                path = _resolve_path(resp)
                if os.path.isdir(path):
                    fpath = _find_file_by_keyword(path, "jd") or _find_file_by_keyword(path, "job") or _find_file_by_keyword(path, "description")
                    if fpath:
                        fname = os.path.basename(fpath)
                        if self._confirm(f"I found {fname}. Is this the JD?"):
                            jd_text = _extract_text(fpath)
                            self.speak("JD loaded.")
                            break
                        else:
                            self.speak("Which file then?")
                    else:
                        self.speak("No JD found there. Try another location.")
                elif os.path.isfile(path):
                    jd_text = _extract_text(path)
                    self.speak(f"Loaded {os.path.basename(path)}.")
                    break
                else:
                    self.speak("Couldn't find that. Try again.")

        if not jd_text:
            self.speak("Proceeding without JD.")

        # ---- Step 4: Silent research (NO browser) ----
        self.speak("Give me a moment. I'm researching the company silently.")
        context = self._ask_llm(
            f"Brief summary of {company}: what they do, tech stack, culture, "
            f"and what they look for in a {role}. Under 200 words. Factual only."
        )

        role_type = self._detect_role_type(role, jd_text)
        print(f"[Interview] Role type: {role_type}")

        # ---- Step 5: Proctoring permission ----
        enable_proctoring = self._confirm(
            "Shall I enable camera and screen monitoring for this interview?"
        )
        if enable_proctoring:
            self.cam.start()
            self.scr.start()
            self.speak("Proctoring active.")
        else:
            self.speak("Proctoring off.")

        # ---- Step 6: Start interview ----
        from . import brain as brain_module
        original_prompt = getattr(brain_module, "SYSTEM_PROMPT", None)
        brain_module.SYSTEM_PROMPT = self._build_prompt(
            company, role, role_type, resume_text, jd_text, context
        )

        self.speak(f"Interview for {role} at {company} starts now. Good luck.")
        time.sleep(0.5)

        first_q = self._ask_llm("Begin the interview. Ask your first question.")
        self.speak(first_q)
        self.qa_log.append({"role": "interviewer", "content": first_q})

        # ---- Interview loop ----
        q_count = 1
        coding_opened = False
        no_answer = 0

        while True:
            answer = self.listen(phrase_time_limit=90)

            if not answer:
                no_answer += 1
                if no_answer >= 3:
                    self.speak("No response for a while. Continue or end?")
                    r = self.listen(phrase_time_limit=8)
                    if r and any(w in r.lower() for w in ("end", "stop", "done", "exit")):
                        break
                    no_answer = 0
                continue

            no_answer = 0

            if any(w in answer.lower() for w in ("end interview", "stop interview", "exit interview")):
                break

            self.qa_log.append({"role": "candidate", "content": answer})

            # Violations BETWEEN questions (never overlap)
            if enable_proctoring:
                self._speak_violations_between_questions()

            # Open IDE for coding round (around question 6-7)
            if not coding_opened and q_count >= 6 and role_type in (
                "data_analyst", "data_engineer", "sde", "backend", "fullstack", "ml_engineer", "general"
            ):
                coding_opened = True
                coding_lang = getattr(self, "_coding_lang", "java_sql")
                coding_dir = config.INTERVIEW_DATA_DIR

                # Create the right file type based on JD
                files_to_open = []
                if "sql" in coding_lang:
                    sql_file = os.path.join(coding_dir, "coding_round.sql")
                    with open(sql_file, "w", encoding="utf-8") as f:
                        f.write("-- Write your SQL solution below\n\n")
                    files_to_open.append(sql_file)
                if "java" in coding_lang:
                    java_file = os.path.join(coding_dir, "CodingRound.java")
                    with open(java_file, "w", encoding="utf-8") as f:
                        f.write("// Write your Java solution below\n\npublic class CodingRound {\n    public static void main(String[] args) {\n        \n    }\n}\n")
                    files_to_open.append(java_file)
                if coding_lang == "python":
                    py_file = os.path.join(coding_dir, "coding_round.py")
                    with open(py_file, "w", encoding="utf-8") as f:
                        f.write("# Write your Python solution below\n\n")
                    files_to_open.append(py_file)
                if coding_lang == "javascript":
                    js_file = os.path.join(coding_dir, "coding_round.js")
                    with open(js_file, "w", encoding="utf-8") as f:
                        f.write("// Write your JavaScript solution below\n\n")
                    files_to_open.append(js_file)

                for fpath in files_to_open:
                    try:
                        subprocess.Popen(["code", fpath], shell=True)
                        print(f"[Interview] Opened {fpath} in VS Code")
                    except Exception:
                        pass

            # Get next question
            next_q = self._ask_llm(answer)
            self.speak(next_q)
            self.qa_log.append({"role": "interviewer", "content": next_q})
            q_count += 1

            if any(p in next_q.lower() for p in (
                "that concludes", "thank you for your time", "best of luck",
                "end of the interview", "we'll be in touch",
            )):
                break

        # ---- Cleanup ----
        config.INTERVIEW_ACTIVE = False
        self.cam.stop()
        self.scr.stop()
        if original_prompt is not None:
            brain_module.SYSTEM_PROMPT = original_prompt

        self._save_report(company, role)

        total_q = len([e for e in self.qa_log if e["role"] == "interviewer"])
        total_v = len(self.cam.violations) + len(self.scr.violations)
        msg = f"Interview done. {total_q} questions. "
        msg += f"{total_v} violations." if total_v else "No violations."
        msg += f" Transcript saved to {config.INTERVIEW_DATA_DIR}."
        self.speak(msg)
        return self.qa_log

    def _save_report(self, company, role):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = os.path.join(
            config.INTERVIEW_DATA_DIR,
            f"interview_{company.replace(' ', '_')}_{role.replace(' ', '_')}_{ts}.txt",
        )
        with open(fname, "w", encoding="utf-8") as f:
            f.write(f"JARVIS INTERVIEW REPORT\n{'='*50}\n")
            f.write(f"Candidate: {config.USER_NAME}\nRole: {role} at {company}\n")
            f.write(f"Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n{'='*50}\n\n")
            for e in self.qa_log:
                label = {"interviewer": "JARVIS", "candidate": config.USER_NAME.upper(), "proctor": "PROCTOR"}.get(e["role"], "?")
                f.write(f"[{label}]: {e['content']}\n\n")
            all_v = self.cam.violations + self.scr.violations
            if all_v:
                f.write(f"\n{'='*50}\nVIOLATIONS:\n")
                for v in all_v:
                    f.write(f"  [{v['time']}] {v['type']}\n")
        print(f"[Interview] Saved: {fname}")
