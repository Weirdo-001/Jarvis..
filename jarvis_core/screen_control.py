"""
screen_control.py — JARVIS's hands on the screen.

Full voice-driven screen control:
  "click on Aarushi Sharma"        -> OCR finds text, clicks it
  "type hello world"               -> types text at cursor
  "press enter"                    -> keyboard key
  "scroll up 3"                    -> scroll 3 clicks
  "scroll to bottom"               -> scrolls to page bottom
  "go to chrome address bar"       -> Ctrl+L, focuses address bar
  "search google for cats"         -> opens Google search
  "navigate to images"             -> clicks Images tab in Google
  "click the third image"          -> clicks Nth image on screen
  "click the second result"        -> clicks Nth search result
  "open whatsapp and text Priya"   -> handled in brain.py
  "send message hello"             -> types and sends in WhatsApp

Requires: pip install pyautogui pytesseract Pillow pyperclip
Also requires: Tesseract OCR -> https://github.com/UB-Mannheim/tesseract/wiki
"""
import os
import re
import time
import subprocess
from typing import Optional

try:
    import ctypes
    # Make process DPI aware on Windows so physical coordinates match pyautogui and screenshots
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import pyautogui
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.2


# ---------------------------------------------------------------
# Tesseract path resolver (once)
# ---------------------------------------------------------------

_TESS_CMD = None

def _get_tesseract():
    global _TESS_CMD
    if _TESS_CMD:
        return _TESS_CMD
    for tp in [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]:
        if os.path.exists(tp):
            _TESS_CMD = tp
            return tp
    return None


# ---------------------------------------------------------------
# OCR engine
# ---------------------------------------------------------------

def _ocr_screenshot():
    """Returns (words, lefts, tops, widths, heights, confs) from current screen."""
    try:
        import pytesseract
        from PIL import Image

        tp = _get_tesseract()
        if tp:
            pytesseract.pytesseract.tesseract_cmd = tp

        screenshot = pyautogui.screenshot()
        data = pytesseract.image_to_data(
            screenshot,
            output_type=pytesseract.Output.DICT,
            config="--psm 11",
        )
        return data
    except ImportError:
        return None
    except Exception as e:
        print(f"[Screen OCR] {e}")
        return None


def _find_text_on_screen(text: str):
    """
    Find text on screen. Returns (x, y) center or None or 'NO_TESSERACT'.
    """
    data = _ocr_screenshot()
    if data is None:
        return "NO_TESSERACT"

    target = text.lower().strip()
    words   = [w.lower() for w in data["text"]]
    lefts   = data["left"]
    tops    = data["top"]
    widths  = data["width"]
    heights = data["height"]
    confs   = data["conf"]

    # Single-word match
    for i, word in enumerate(words):
        if not word.strip() or int(confs[i]) < 30:
            continue
        if target in word or word in target:
            return lefts[i] + widths[i] // 2, tops[i] + heights[i] // 2

    # Multi-word phrase (2-4 words)
    for window in range(2, 5):
        for i in range(len(words) - window + 1):
            phrase = " ".join(words[i:i+window]).strip()
            if not phrase:
                continue
            if target in phrase or phrase in target:
                x1 = lefts[i]
                y1 = min(tops[i:i+window])
                x2 = lefts[i+window-1] + widths[i+window-1]
                y2 = max(tops[j] + heights[j] for j in range(i, i+window))
                return (x1 + x2) // 2, (y1 + y2) // 2

    return None


def _find_nth_image_on_screen(n: int):
    """
    Find the Nth image thumbnail on screen using pyautogui's locateAll or
    a screenshot-based detection approach.
    Falls back to evenly dividing the screen into image grid slots.
    """
    try:
        from PIL import ImageGrab
        import pyautogui

        sw, sh = pyautogui.size()

        # Heuristic: images in Google Image search appear in a grid.
        # Approximate positions by sampling NxM grid cells starting from
        # the search results area (roughly top 20% is header/search bar).
        # Each image is ~200x150 pixels in standard Chrome at 100% zoom.
        cols = 6
        start_y = int(sh * 0.25)  # skip top nav
        cell_w  = sw // cols
        cell_h  = 170

        col = (n - 1) % cols
        row = (n - 1) // cols
        cx  = cell_w * col + cell_w // 2
        cy  = start_y + row * cell_h + cell_h // 2

        return cx, cy
    except Exception as e:
        print(f"[Screen] Nth image error: {e}")
        return None


# ---------------------------------------------------------------
# Click commands
# ---------------------------------------------------------------

def click_on(target_text: str, button: str = "left", double: bool = False) -> str:
    print(f"[Screen] Looking for '{target_text}'...")
    result = _find_text_on_screen(target_text)

    if result == "NO_TESSERACT":
        return "I need Tesseract OCR installed to click on screen elements."

    if result is None:
        return f"I couldn't find '{target_text}' on screen. Make sure it's visible."

    x, y = result
    if double:
        pyautogui.doubleClick(x, y)
        action = "Double-clicked"
    elif button == "right":
        pyautogui.rightClick(x, y)
        action = "Right-clicked"
    else:
        pyautogui.click(x, y)
        action = "Clicked"

    print(f"[Screen] {action} '{target_text}' at ({x}, {y})")
    return f"{action} on {target_text}."


def click_at(x: int, y: int) -> str:
    pyautogui.click(x, y)
    return f"Clicked at ({x}, {y})."


def click_nth_image(n: int) -> str:
    """Click the Nth image in a Google Images-style grid."""
    pos = _find_nth_image_on_screen(n)
    if pos is None:
        return f"Couldn't locate image number {n} on screen."
    x, y = pos
    pyautogui.click(x, y)
    return f"Clicked the {_ordinal(n)} image."


def click_nth_result(n: int) -> str:
    """Click the Nth search result link on screen (Google/Bing style)."""
    data = _ocr_screenshot()
    if data is None:
        return "OCR unavailable."

    # Find all blue-link-style text (hard to OCR colour, so just find Nth non-empty line)
    words   = data["text"]
    lefts   = data["left"]
    tops    = data["top"]
    widths  = data["width"]
    heights = data["height"]
    confs   = data["conf"]

    # Group into lines by Y proximity
    lines = {}
    for i, word in enumerate(words):
        if not word.strip() or int(confs[i]) < 40:
            continue
        # bucket by rounded Y
        bucket = (tops[i] // 30) * 30
        if bucket not in lines:
            lines[bucket] = []
        lines[bucket].append((lefts[i], tops[i], widths[i], heights[i], word))

    sorted_lines = sorted(lines.items())
    # Filter lines that look like result headings (longer than 2 words)
    result_lines = [(y, items) for y, items in sorted_lines if len(items) >= 2]

    if n > len(result_lines):
        return f"I can only see {len(result_lines)} results on screen."

    y_key, items = result_lines[n - 1]
    cx = sum(it[0] + it[2] // 2 for it in items) // len(items)
    cy = y_key + 15
    pyautogui.click(cx, cy)
    return f"Clicked the {_ordinal(n)} result."


def _ordinal(n: int) -> str:
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n if n < 20 else n % 10, "th")
    return f"{n}{suffix}"


# ---------------------------------------------------------------
# Keyboard commands
# ---------------------------------------------------------------

def type_text(text: str) -> str:
    """Type text using clipboard paste (handles Unicode, Indian names, etc.)."""
    try:
        import pyperclip
        pyperclip.copy(text)
        time.sleep(0.15)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.1)
    except Exception:
        pyautogui.write(text, interval=0.03)
    return f"Typed: {text}"


def press_key(key: str) -> str:
    key = key.lower().strip()
    _KEY_MAP = {
        "enter": "enter", "return": "enter",
        "space": "space", "spacebar": "space",
        "backspace": "backspace", "delete": "delete",
        "tab": "tab",
        "escape": "escape", "esc": "escape",
        "up": "up", "down": "down", "left": "left", "right": "right",
        "home": "home", "end": "end",
        "page up": "pageup", "page down": "pagedown",
        "windows": "win", "win": "win",
        "caps lock": "capslock",
        "print screen": "printscreen",
    }
    parts  = key.replace("+", " ").split()
    mapped = [_KEY_MAP.get(p, p) for p in parts]
    if len(mapped) == 1:
        pyautogui.press(mapped[0])
    else:
        pyautogui.hotkey(*mapped)
    return f"Pressed {key}."


# ---------------------------------------------------------------
# Chrome-specific helpers
# ---------------------------------------------------------------

def chrome_navigate(url: str) -> str:
    """Focus Chrome address bar and navigate to a URL."""
    pyautogui.hotkey("ctrl", "l")
    time.sleep(0.3)
    type_text(url)
    time.sleep(0.1)
    pyautogui.press("enter")
    return f"Navigating to {url}."


def chrome_search(query: str) -> str:
    """Search Google for a query in Chrome."""
    url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
    return chrome_navigate(url)


def chrome_search_images(query: str) -> str:
    """Search Google Images for a query."""
    url = f"https://www.google.com/search?tbm=isch&q={query.replace(' ', '+')}"
    return chrome_navigate(url)


def chrome_click_images_tab() -> str:
    """Click the 'Images' tab on a Google search page."""
    result = click_on("Images")
    if "couldn't find" in result.lower():
        # Fallback: Ctrl+L and append &tbm=isch
        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.1)
        pyautogui.hotkey("ctrl", "c")
        import pyperclip
        url = pyperclip.paste()
        if "google.com/search" in url and "tbm=isch" not in url:
            url = url + "&tbm=isch"
            type_text(url)
            pyautogui.press("enter")
            return "Switched to Images tab."
    return result


def chrome_new_tab(url: str = "") -> str:
    pyautogui.hotkey("ctrl", "t")
    time.sleep(0.4)
    if url:
        return chrome_navigate(url)
    return "Opened new tab."


# ---------------------------------------------------------------
# WhatsApp helpers
# ---------------------------------------------------------------

def _get_whatsapp_window():
    """Find the WhatsApp window object via pygetwindow."""
    try:
        import pygetwindow as gw
        for w in gw.getAllWindows():
            if w.title and "whatsapp" in w.title.lower():
                if w.width > 200 and w.height > 200:
                    return w
    except Exception as e:
        print(f"[Screen] _get_whatsapp_window error: {e}")
    return None


def _find_whatsapp_hwnd() -> Optional[int]:
    """Find the top-level HWND for WhatsApp Desktop."""
    win = _get_whatsapp_window()
    if win:
        return getattr(win, "_hWnd", None)
    return None


def _focus_whatsapp() -> bool:
    """
    Launch or bring WhatsApp Desktop window to the front and maximize it.
    """
    win = _get_whatsapp_window()
    if not win:
        try:
            from jarvis_core import config
            wa_cmd = config.APP_MAP.get("whatsapp", r"explorer shell:AppsFolder\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App")
            subprocess.Popen(wa_cmd, shell=True)
        except Exception as e:
            print(f"[Screen] Launch WhatsApp error: {e}")
            try:
                os.startfile("whatsapp:")
            except Exception:
                pass

        # Poll up to 3 seconds for WhatsApp window to appear
        for _ in range(15):
            time.sleep(0.2)
            win = _get_whatsapp_window()
            if win:
                break

    if win:
        try:
            if getattr(win, "isMinimized", False):
                win.restore()
            win.activate()
        except Exception:
            try:
                pyautogui.press("alt")
                win.activate()
            except Exception:
                pass

        time.sleep(0.3)
        try:
            if not getattr(win, "isMaximized", False):
                win.maximize()
        except Exception:
            pass

    # Windows 11 fix: Win+Up can snap to top-half instead of maximizing.
    # Alt+Space then 'x' is the standard Windows command to fully maximize.
    time.sleep(0.3)
    try:
        cur_win = _get_whatsapp_window()
        sw, sh = pyautogui.size()
        if cur_win and cur_win.height < (sh - 120):
            print("[Screen] WhatsApp not maximized, applying Alt+Space -> x...")
            pyautogui.hotkey("alt", "space")
            time.sleep(0.15)
            pyautogui.press("x")
            time.sleep(0.4)
    except Exception:
        pass

    return True


def whatsapp_open_chat(contact: str) -> str:
    """
    Focus WhatsApp, search for a contact in the search bar, and open their chat.
    """
    # Step 1: Bring WhatsApp to front and maximize
    _focus_whatsapp()

    win = _get_whatsapp_window()
    if win:
        # Calculate search position relative to WhatsApp window
        search_x = win.left + min(int(win.width * 0.16), 300)
        search_y = win.top + 75
    else:
        sw, sh = pyautogui.size()
        search_x = int(sw * 0.16)
        search_y = int(sh * 0.11)

    print(f"[Screen] Clicking WhatsApp search bar at ({search_x}, {search_y})...")
    pyautogui.click(search_x, search_y)
    time.sleep(0.3)

    # Also trigger search shortcut as backup
    pyautogui.hotkey("ctrl", "f")
    time.sleep(0.2)

    # Step 3: Clear any existing search query
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.1)
    pyautogui.press("backspace")
    time.sleep(0.2)

    # Step 4: Type the contact name into the search bar
    print(f"[Screen] Typing contact: {contact}")
    type_text(contact)
    time.sleep(1.3)  # Wait for search results to appear

    # Step 5: Select first contact and open chat
    # In WhatsApp Desktop, Down arrow highlights the top search result, Enter opens the chat
    print(f"[Screen] Selecting '{contact}' from search results...")
    pyautogui.press("down")
    time.sleep(0.3)
    pyautogui.press("enter")
    time.sleep(0.8)

    return f"Opened chat with {contact}."


def _click_whatsapp_input() -> None:
    """
    Focus the WhatsApp message input box at the bottom of the active chat.
    Uses window-relative coordinates so it always hits the input box regardless
    of window size or monitor scaling.
    """
    win = _get_whatsapp_window()
    if win:
        input_x = win.left + int(win.width * 0.60)
        input_y = win.top + win.height - 35
        print(f"[Screen] WhatsApp window at ({win.left}, {win.top}, {win.width}, {win.height})")
    else:
        sw, sh = pyautogui.size()
        input_x = int(sw * 0.60)
        input_y = int(sh * 0.95)

    print(f"[Screen] Clicking message input box at ({input_x}, {input_y})...")
    pyautogui.click(input_x, input_y)
    time.sleep(0.2)


def whatsapp_send_message(contact: str, message: str) -> str:
    """
    Open WhatsApp, search for contact, open chat, type message, and send it.
    """
    print(f"[Screen] WhatsApp: sending '{message}' to '{contact}'...")
    whatsapp_open_chat(contact)
    time.sleep(0.5)

    # Ensure message input box is focused
    _click_whatsapp_input()
    time.sleep(0.3)

    # Type the message and send
    print(f"[Screen] Typing message: '{message}'...")
    type_text(message)
    time.sleep(0.3)
    pyautogui.press("enter")
    print(f"[Screen] Message successfully sent to {contact}!")
    return f"Message sent to {contact}."


def whatsapp_send_quick(message: str) -> str:
    """Type and send a message in the currently open WhatsApp chat."""
    _focus_whatsapp()
    _click_whatsapp_input()
    time.sleep(0.3)
    type_text(message)
    time.sleep(0.2)
    pyautogui.press("enter")
    return f"Sent: {message}"


# ---------------------------------------------------------------
# Common shortcuts
# ---------------------------------------------------------------

def select_all() -> str:
    pyautogui.hotkey("ctrl", "a"); return "Selected all."

def copy() -> str:
    pyautogui.hotkey("ctrl", "c"); return "Copied."

def paste() -> str:
    pyautogui.hotkey("ctrl", "v"); return "Pasted."

def cut() -> str:
    pyautogui.hotkey("ctrl", "x"); return "Cut."

def undo() -> str:
    pyautogui.hotkey("ctrl", "z"); return "Undone."

def redo() -> str:
    pyautogui.hotkey("ctrl", "y"); return "Redone."

def go_back() -> str:
    pyautogui.hotkey("alt", "left"); return "Going back."

def go_forward() -> str:
    pyautogui.hotkey("alt", "right"); return "Going forward."

def new_tab() -> str:
    pyautogui.hotkey("ctrl", "t"); return "New tab opened."

def close_tab() -> str:
    pyautogui.hotkey("ctrl", "w"); return "Tab closed."

def switch_window() -> str:
    pyautogui.hotkey("alt", "tab"); return "Switching window."

def refresh() -> str:
    pyautogui.press("f5"); return "Refreshed."

def find_on_page(term: str = "") -> str:
    pyautogui.hotkey("ctrl", "f")
    if term:
        time.sleep(0.3)
        type_text(term)
    return f"Opened find bar{' for: ' + term if term else ''}."


# ---------------------------------------------------------------
# Scroll commands
# ---------------------------------------------------------------

def scroll(direction: str = "down", clicks: int = 3) -> str:
    amount = clicks if direction == "up" else -clicks
    pyautogui.scroll(amount)
    return f"Scrolled {direction} {clicks} times."


def scroll_to_top() -> str:
    pyautogui.hotkey("ctrl", "home")
    return "Scrolled to the top."


def scroll_to_bottom() -> str:
    pyautogui.hotkey("ctrl", "end")
    return "Scrolled to the bottom."


# ---------------------------------------------------------------
# Mouse move (hover)
# ---------------------------------------------------------------

def move_mouse_to(target_text: str) -> str:
    result = _find_text_on_screen(target_text)
    if result and result != "NO_TESSERACT":
        x, y = result
        pyautogui.moveTo(x, y, duration=0.3)
        return f"Mouse moved to '{target_text}'."
    return f"Could not find '{target_text}' on screen."


# ---------------------------------------------------------------
# Screen Vision — Read and Summarize Screen Content
# ---------------------------------------------------------------

def read_screen_content(max_chars: int = 3000) -> str:
    """
    OCR the entire screen and return the visible text, capped at max_chars.
    Used by brain.py to give JARVIS genuine screen vision.

    Returns a string with the text content, or an error message.
    """
    data = _ocr_screenshot()
    if data is None:
        return "NO_TESSERACT"

    words  = data["text"]
    lefts  = data["left"]
    tops   = data["top"]
    confs  = data["conf"]
    widths = data["width"]
    heights= data["height"]

    # Group tokens into lines by Y-bucket (30px rows)
    lines_dict = {}
    for i, word in enumerate(words):
        word = word.strip()
        if not word or int(confs[i]) < 30:
            continue
        bucket = (tops[i] // 25) * 25
        if bucket not in lines_dict:
            lines_dict[bucket] = []
        lines_dict[bucket].append((lefts[i], word))

    # Sort buckets (top→bottom), then words within each line (left→right)
    output_lines = []
    for bucket in sorted(lines_dict):
        line_words = sorted(lines_dict[bucket], key=lambda x: x[0])
        output_lines.append(" ".join(w for _, w in line_words))

    # Join and cap
    full_text = "\n".join(output_lines).strip()
    if len(full_text) > max_chars:
        full_text = full_text[:max_chars] + "\n...[truncated]"

    return full_text if full_text else "The screen appears to be blank or text could not be extracted."


def get_active_window_title() -> str:
    """Return the title bar text of the currently focused window."""
    try:
        import win32gui
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd).strip()
        return title if title else "Unknown window"
    except ImportError:
        try:
            # Fallback via pyautogui (less reliable)
            import subprocess
            result = subprocess.run(
                ["powershell", "-c",
                 "(Get-Process | Where-Object {$_.MainWindowHandle -ne 0} | Sort-Object CPU -Descending | Select-Object -First 1).MainWindowTitle"],
                capture_output=True, text=True, timeout=3,
            )
            return result.stdout.strip() or "Unknown window"
        except Exception:
            return "Unknown window"
    except Exception as e:
        return f"Could not get window title: {e}"

