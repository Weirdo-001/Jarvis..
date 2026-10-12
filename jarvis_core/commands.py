"""
commands.py — JARVIS's hands. All actual system control lives here.

Every function returns a short string that JARVIS will speak back,
so the brain layer stays simple: match intent -> call function -> speak result.
"""
import datetime
import os
import subprocess
import webbrowser

from . import config

DANGEROUS = {"shutdown", "restart", "sleep", "run_script"}


def confirm(action_name: str, ask_fn) -> bool:
    """ask_fn() should return the user's spoken/typed reply as a string."""
    if not config.CONFIRM_DANGEROUS_ACTIONS:
        return True
    reply = ask_fn(f"Are you sure you want me to {action_name}? Say yes to confirm.")
    return bool(reply) and reply.strip().lower() in (
        "yes", "yes sir", "yes ma'am", "confirm", "do it", "go ahead", "yeah", "yep"
    )


# ---------- Apps ----------

def _fuzzy_app_match(key: str):
    """
    Fuzzy-match a spoken app name against APP_MAP.
    Handles Whisper mishearings: 'crow'->chrome, 'spo'->spotify, etc.
    Returns matched APP_MAP key or None.
    """
    from difflib import get_close_matches

    # 1. Substring match — "chrom" inside "chrome"
    for app_key in config.APP_MAP:
        if key in app_key or app_key in key:
            return app_key

    # 2. difflib closest match
    matches = get_close_matches(key, config.APP_MAP.keys(), n=1, cutoff=0.6)
    if matches:
        print(f"[app] Fuzzy: '{key}' -> '{matches[0]}'")
        return matches[0]

    # 3. Hard-coded phonetic fallbacks for common Whisper mishearings
    _PHONETIC = {
        "crow": "chrome", "crone": "chrome", "crom": "chrome", "crumb": "chrome",
        "spo": "spotify", "spotty": "spotify",
        "disc": "discord", "disco": "discord",
        "cod": "vs code",
        "zum": "zoom", "zoo": "zoom",
        "what": "whatsapp", "whats": "whatsapp",
        "tele": "telegram",
        "power": "powerpoint",
        "calc": "calculator",
        "explore": "file explorer",
    }
    for mishear, correct in _PHONETIC.items():
        if mishear in key or key in mishear:
            print(f"[app] Phonetic: '{key}' -> '{correct}'")
            return correct

    return None


def open_app(name: str) -> str:
    key = name.lower().strip()

    if key in config.APP_MAP:
        target = config.APP_MAP[key]
        matched_name = name
    else:
        fuzzy_key = _fuzzy_app_match(key)
        if fuzzy_key:
            target = config.APP_MAP[fuzzy_key]
            matched_name = fuzzy_key
        else:
            target = key
            matched_name = name

    try:
        if target.startswith(("ms-settings:", "ms-", "outlookcal:", "com.epicgames", "ms-windows-store:")):
            # Windows URI scheme — use os.startfile or powershell start
            subprocess.Popen(f'start "" "{target}"', shell=True)

        elif target.startswith("explorer shell:"):
            # UWP/Store apps via explorer shell — needs shell=True
            subprocess.Popen(target, shell=True)

        elif os.path.isfile(target):
            # Full absolute path to an exe
            subprocess.Popen(f'"{target}"', shell=True)

        elif " --" in target or (target.count(" ") > 0 and target.count(".exe") > 0):
            # Command with CLI flags: split exe from flags
            if " --" in target:
                parts = target.split(" --", 1)
                exe = parts[0].strip().strip('"')
                flags = "--" + parts[1]
            else:
                parts = target.split(" -", 1)
                exe = parts[0].strip().strip('"')
                flags = "-" + parts[1]
            subprocess.Popen(f'"{exe}" {flags}', shell=True)

        else:
            # Short executable name like: chrome, code, spotify, notepad, calc
            # Use 'start' for GUI apps — avoids window hijacking
            subprocess.Popen(f'start "" {target}', shell=True)

        return f"Opening {matched_name}."
    except Exception as e:
        return f"I couldn't open {matched_name}: {e}"


def close_app(name: str) -> str:
    key = name.lower().strip()
    exe = config.APP_MAP.get(key, key)
    if not exe.endswith(".exe"):
        exe += ".exe"
    result = subprocess.run(["taskkill", "/IM", exe, "/F"], capture_output=True, text=True)
    if result.returncode == 0:
        return f"Closed {name}."
    return f"{name} doesn't appear to be running."


# ---------- Web ----------

def web_search(query: str) -> str:
    webbrowser.open(f"https://www.google.com/search?q={query.replace(' ', '+')}")
    return f"Searching the web for {query}."


def open_site(url: str) -> str:
    if not url.startswith("http"):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opening {url}."


# ---------- System info / utility ----------

def tell_time() -> str:
    now = datetime.datetime.now()
    # 12-hour clock, no leading zero, e.g. "6:03 PM"
    return f"It's {now.strftime('%I:%M %p').lstrip('0')}."


def tell_date() -> str:
    now = datetime.datetime.now()
    return f"Today is {now.strftime('%A, %B %d, %Y')}."


def take_screenshot() -> str:
    import pyautogui
    folder = os.path.join(os.path.expanduser("~"), "Pictures", "Jarvis_Screenshots")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"screenshot_{datetime.datetime.now():%Y%m%d_%H%M%S}.png")
    pyautogui.screenshot().save(path)
    return f"Screenshot saved to {path}."


def set_volume(level: int) -> str:
    """level: 0-100"""
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        volume.SetMasterVolumeLevelScalar(max(0, min(100, level)) / 100, None)
        return f"Volume set to {level} percent."
    except Exception as e:
        return f"I couldn't change the volume: {e}"


def mute_volume() -> str:
    """Toggle mute."""
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        current = volume.GetMute()
        volume.SetMute(not current, None)
        return "Muted." if not current else "Unmuted."
    except Exception as e:
        return f"Couldn't toggle mute: {e}"


# ---------- System stats ----------

def system_stats() -> str:
    """CPU, RAM, battery — quick health check."""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        battery = psutil.sensors_battery()
        reply = f"CPU at {cpu}%, RAM {ram.percent}% used ({ram.used // (1024**3)} of {ram.total // (1024**3)} GB)"
        if battery:
            status = "charging" if battery.power_plugged else "on battery"
            reply += f", battery {battery.percent}% and {status}"
        return reply + "."
    except ImportError:
        return "I need psutil installed to check system stats. Run pip install psutil."


def battery_status() -> str:
    try:
        import psutil
        b = psutil.sensors_battery()
        if b is None:
            return "No battery detected — are you on a desktop?"
        status = "charging" if b.power_plugged else "on battery"
        return f"Battery is at {b.percent}%, currently {status}."
    except ImportError:
        return "I need psutil to check the battery."


# ---------- Clipboard ----------

def read_clipboard() -> str:
    """Read the current clipboard text content."""
    try:
        import pyperclip
        content = pyperclip.paste()
        if not content:
            return "The clipboard is empty."
        # Truncate for speech
        if len(content) > 200:
            return f"Clipboard contains: {content[:200]}... and more."
        return f"Clipboard contains: {content}"
    except ImportError:
        return "I need pyperclip installed to access the clipboard."


def copy_to_clipboard(text: str) -> str:
    try:
        import pyperclip
        pyperclip.copy(text)
        return "Copied to clipboard."
    except ImportError:
        return "I need pyperclip installed."


# ---------- Brightness ----------

def set_brightness(level: int) -> str:
    """Set screen brightness (0-100). Works on laptops with WMI."""
    try:
        import subprocess
        subprocess.run([
            "powershell", "-Command",
            f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{max(0, min(100, level))})"
        ], capture_output=True)
        return f"Brightness set to {level}%."
    except Exception as e:
        return f"Couldn't set brightness: {e}"


# ---------- Power (dangerous — always gated by confirm()) ----------

def shutdown() -> str:
    subprocess.run(["shutdown", "/s", "/t", "5"])
    return "Shutting down in five seconds."


def restart() -> str:
    subprocess.run(["shutdown", "/r", "/t", "5"])
    return "Restarting in five seconds."


def sleep_pc() -> str:
    subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
    return "Going to sleep."


def cancel_shutdown() -> str:
    subprocess.run(["shutdown", "/a"])
    return "Shutdown cancelled."


# ---------- Lock screen ----------

def lock_screen() -> str:
    subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"])
    return "Locking the screen."


# ---------- Scripts ----------

def run_script(path: str) -> str:
    """Runs a .py or .ps1 script the user points to. Gated by confirm() in brain.py."""
    if not os.path.exists(path):
        return f"I can't find a script at {path}."
    try:
        if path.endswith(".py"):
            subprocess.Popen(["python", path])
        elif path.endswith(".ps1"):
            subprocess.Popen(["powershell", "-ExecutionPolicy", "Bypass", "-File", path])
        else:
            subprocess.Popen(path, shell=True)
        return f"Running {os.path.basename(path)}."
    except Exception as e:
        return f"Script failed to run: {e}"


# ============================================================
# ---------- Process Management (Full Access) ----------
# ============================================================

def get_top_processes(n: int = 5) -> str:
    """
    Return the top N processes by memory usage, plus top CPU hog.
    Speaks them back in a natural sentence.
    """
    try:
        import psutil
        procs = []
        for proc in psutil.process_iter(["pid", "name", "memory_percent", "cpu_percent"]):
            try:
                info = proc.info
                if info["memory_percent"] is None:
                    continue
                procs.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Top by memory
        top_mem = sorted(procs, key=lambda p: p["memory_percent"] or 0, reverse=True)[:n]
        # Top by CPU (sample cpu_percent needs a brief interval — use cached)
        top_cpu = sorted(procs, key=lambda p: p["cpu_percent"] or 0, reverse=True)[:1]

        lines = []
        for i, p in enumerate(top_mem, 1):
            lines.append(
                f"{i}. {p['name']} — {p['memory_percent']:.1f}% RAM"
            )

        reply = "Top memory processes: " + ", ".join(
            f"{p['name']} at {p['memory_percent']:.1f} percent"
            for p in top_mem[:3]
        )
        if top_cpu and top_cpu[0]["cpu_percent"] and top_cpu[0]["cpu_percent"] > 5:
            reply += f". Highest CPU: {top_cpu[0]['name']} at {top_cpu[0]['cpu_percent']:.0f} percent."
        else:
            reply += "."

        # Also print the full table to terminal
        print("\n[Processes — Top by RAM]")
        for line in lines:
            print(f"  {line}")

        return reply
    except ImportError:
        return "I need psutil installed to check processes."
    except Exception as e:
        return f"Process check failed: {e}"


def kill_process(name: str) -> str:
    """Kill a process by name. Gated by confirm() in brain.py."""
    try:
        import psutil
        killed = []
        for proc in psutil.process_iter(["name", "pid"]):
            try:
                if name.lower() in proc.info["name"].lower():
                    proc.kill()
                    killed.append(proc.info["name"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if killed:
            return f"Terminated: {', '.join(set(killed))}."
        return f"No process matching '{name}' found."
    except ImportError:
        return "I need psutil to kill processes."
    except Exception as e:
        return f"Could not terminate {name}: {e}"


# ============================================================
# ---------- Window Management (Full Access) ----------
# ============================================================

def _find_window_by_name(name: str):
    """
    Find a window handle by partial title or app name match.
    Returns hwnd or None.
    """
    try:
        import win32gui
        name_lower = name.lower()
        results = []

        def _cb(hwnd, _):
            try:
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd).lower()
                    if name_lower in title or title in name_lower:
                        results.append((hwnd, win32gui.GetWindowText(hwnd)))
            except Exception:
                pass
            return True

        win32gui.EnumWindows(_cb, None)

        # Prefer exact/closer match
        results.sort(key=lambda r: len(r[1]))
        return results[0][0] if results else None
    except ImportError:
        return None


def maximize_window(name: str) -> str:
    """Maximize a window by title/app name."""
    try:
        import win32gui
        import win32con
        hwnd = _find_window_by_name(name)
        if hwnd is None:
            return f"I couldn't find a window for '{name}'. Make sure it's open."
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        win32gui.SetForegroundWindow(hwnd)
        return f"Maximized {name}."
    except ImportError:
        return "I need pywin32 installed to manage windows. Run: pip install pywin32"
    except Exception as e:
        return f"Couldn't maximize {name}: {e}"


def minimize_window(name: str) -> str:
    """Minimize a window by title/app name."""
    try:
        import win32gui
        import win32con
        hwnd = _find_window_by_name(name)
        if hwnd is None:
            return f"I couldn't find a window for '{name}'."
        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        return f"Minimized {name}."
    except ImportError:
        return "I need pywin32 installed to manage windows."
    except Exception as e:
        return f"Couldn't minimize {name}: {e}"


def focus_window(name: str) -> str:
    """Bring a window to the foreground by title/app name."""
    try:
        import win32gui
        import win32con
        hwnd = _find_window_by_name(name)
        if hwnd is None:
            return f"I couldn't find a window for '{name}'."
        # Restore if minimized
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return f"Focused {name}."
    except ImportError:
        return "I need pywin32 to manage windows."
    except Exception as e:
        return f"Couldn't focus {name}: {e}"


def get_open_windows() -> str:
    """List all visible windows — useful for JARVIS to report what's open."""
    try:
        import win32gui
        titles = []

        def _cb(hwnd, _):
            try:
                if win32gui.IsWindowVisible(hwnd):
                    t = win32gui.GetWindowText(hwnd).strip()
                    if t and len(t) > 2:
                        titles.append(t)
            except Exception:
                pass
            return True

        win32gui.EnumWindows(_cb, None)
        if not titles:
            return "No windows are currently open."
        # Deduplicate and limit
        seen = set()
        unique = []
        for t in titles:
            if t.lower() not in seen:
                seen.add(t.lower())
                unique.append(t)
        short = unique[:8]
        return "Open windows: " + ", ".join(short) + ("." if len(unique) <= 8 else f", and {len(unique)-8} more.")
    except ImportError:
        return "I need pywin32 to list windows."
    except Exception as e:
        return f"Window listing failed: {e}"

