"""System-wide hotkeys (Windows) and hotkey-string parsing."""
from __future__ import annotations

import ctypes
import queue
import re
import sys
import threading

IS_WIN = sys.platform == "win32"
if IS_WIN:
    from ctypes import wintypes

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
_MODS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT,
         "shift": MOD_SHIFT, "win": MOD_WIN}
_SPECIAL = {
    "space": 0x20, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "esc": 0x1B, "escape": 0x1B, "backspace": 0x08,
    "insert": 0x2D, "ins": 0x2D, "delete": 0x2E, "del": 0x2E,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pgup": 0x21,
    "pagedown": 0x22, "pgdn": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "`": 0xC0, "backtick": 0xC0, "tilde": 0xC0,
    "pause": 0x13, "scrolllock": 0x91, "capslock": 0x14,
    "-": 0xBD, "minus": 0xBD, "=": 0xBB, "equals": 0xBB,
    "[": 0xDB, "]": 0xDD, ";": 0xBA, "'": 0xDE, ",": 0xBC, "comma": 0xBC,
    ".": 0xBE, "period": 0xBE, "/": 0xBF, "\\": 0xDC,
    "numplus": 0x6B, "numminus": 0x6D, "nummultiply": 0x6A, "numdivide": 0x6F,
    "mouse4": 0x05, "xbutton1": 0x05, "mouse5": 0x06, "xbutton2": 0x06,
}


def _vk(key: str) -> int:
    m = re.fullmatch(r"f(\d{1,2})", key)
    if m and 1 <= int(m.group(1)) <= 24:
        return 0x6F + int(m.group(1))
    if len(key) == 1 and ("a" <= key <= "z" or "0" <= key <= "9"):
        return ord(key.upper())
    m = re.fullmatch(r"(?:num|numpad)(\d)", key)
    if m:
        return 0x60 + int(m.group(1))
    if key in _SPECIAL:
        return _SPECIAL[key]
    raise ValueError(f'unknown key "{key}"')


def parse_hotkey(text: str):
    """``'Ctrl+Shift+F8'`` -> ``(modifiers, virtual_key_code)``."""
    parts = [p.strip().lower() for p in str(text).split("+") if p.strip()]
    if not parts:
        raise ValueError("empty")
    mods, key = 0, None
    for p in parts:
        if p in _MODS:
            mods |= _MODS[p]
        elif key is None:
            key = p
        else:
            raise ValueError("use one main key plus Ctrl / Alt / Shift / Win")
    if key is None:
        raise ValueError("add a main key, e.g. F8")
    vk = _vk(key)
    if vk in (0x05, 0x06):
        raise ValueError("mouse buttons can't be global hotkeys; map them to a key in your mouse software")
    return mods, vk


def hotkey_to_tk(text: str):
    """Best-effort Tk binding, used only for previews on non-Windows systems."""
    parts = [p.strip() for p in text.split("+") if p.strip()]
    if not parts:
        return None
    names = {"ctrl": "Control", "control": "Control", "alt": "Alt", "shift": "Shift"}
    mods = [names[p.lower()] for p in parts[:-1] if p.lower() in names]
    key = parts[-1]
    if re.fullmatch(r"[Ff]\d{1,2}", key):
        key = key.upper()
    elif len(key) == 1 and key.isalnum():
        key = key.lower()
    else:
        return None
    return "<" + "-".join(mods + [key]) + ">"


def key_is_down(vk: int) -> bool:
    return bool(IS_WIN and ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


class HotkeyListener(threading.Thread):
    """Registers system-wide hotkeys with Windows and reports presses."""

    WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

    def __init__(self, bindings: dict, out: queue.Queue):
        super().__init__(daemon=True)
        self.bindings = bindings
        self.out = out
        self.failed = []
        self.thread_id = None
        self.ready = threading.Event()

    def run(self):
        user32 = ctypes.windll.user32
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        # Create this thread's message queue before anyone posts to it.
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        ids = {}
        for i, (action, (mods, vk)) in enumerate(self.bindings.items(), start=1):
            if user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk):
                ids[i] = action
            else:
                self.failed.append(action)
        self.ready.set()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == self.WM_HOTKEY and msg.wParam in ids:
                self.out.put(ids[msg.wParam])
        for i in ids:
            user32.UnregisterHotKey(None, i)

    def stop(self):
        if self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, self.WM_QUIT, 0, 0)
        self.join(timeout=1.0)
