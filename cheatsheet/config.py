"""Paths, settings and the games library."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys

from . import APP_NAME

IS_WIN = sys.platform == "win32"


# ---------------------------------------------------------------- paths ---

def _app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resource_dir() -> str:
    # PyInstaller unpacks bundled data here; otherwise use the repo folder.
    return getattr(sys, "_MEIPASS", _app_dir())


def _data_dir() -> str:
    override = os.environ.get("CHEATSHEET_DATA")
    if override:
        return override
    if os.path.exists(os.path.join(_app_dir(), "portable.txt")):
        return _app_dir()
    if IS_WIN:
        return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
    return os.path.join(os.path.expanduser("~"), ".config", "cheat-sheet")


APP_DIR = _app_dir()
RES_DIR = _resource_dir()
ASSETS = os.path.join(RES_DIR, "assets")
FONTS = os.path.join(ASSETS, "fonts")
DATA_DIR = _data_dir()
GAMES_DIR = os.path.join(DATA_DIR, "games")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")


def asset(*parts) -> str:
    return os.path.join(ASSETS, *parts)


# ------------------------------------------------------------- settings ---

POSITIONS = ["top-left", "top-center", "top-right",
             "bottom-left", "bottom-center", "bottom-right"]
HOTKEY_ACTIONS = ["toggle", "next_page", "next_game", "manager"]
HOTKEY_LABELS = {
    "toggle": "Show overlay",
    "next_page": "Next page",
    "next_game": "Next game",
    "manager": "Open window",
}
DEFAULT_SETTINGS = {
    "active_game": "",
    "opacity": 1.0,          # whole overlay
    "backdrop": 0.55,        # strength of the faint panel behind the text
    "font_size": 11,
    "columns": 3,
    "position": "top-right",
    "margin": 24,
    "mode": "hold",          # "hold" = only while held, "toggle" = press to open/close
    "start_hidden": False,
    "show_hints": False,
    "hotkeys": {
        "toggle": "F8",
        "next_page": "Ctrl+F8",
        "next_game": "Ctrl+Shift+F8",
        "manager": "Ctrl+Alt+F8",
    },
}


def _num(value, default, lo, hi, cast=float):
    try:
        v = cast(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def load_settings() -> dict:
    s = json.loads(json.dumps(DEFAULT_SETTINGS))
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if k == "hotkeys" and isinstance(v, dict):
                for a, b in v.items():
                    if a in s["hotkeys"] and isinstance(b, str):
                        s["hotkeys"][a] = b
            elif k in s and k != "hotkeys":
                s[k] = v
    d = DEFAULT_SETTINGS
    s["opacity"] = _num(s["opacity"], d["opacity"], 0.3, 1.0)
    s["backdrop"] = _num(s["backdrop"], d["backdrop"], 0.0, 1.0)
    s["font_size"] = _num(s["font_size"], d["font_size"], 8, 24, int)
    s["columns"] = _num(s["columns"], d["columns"], 1, 6, int)
    s["margin"] = _num(s["margin"], d["margin"], 0, 400, int)
    if s["position"] not in POSITIONS:
        s["position"] = d["position"]
    if s["mode"] not in ("hold", "toggle"):
        s["mode"] = d["mode"]
    s["active_game"] = str(s["active_game"] or "")
    s["start_hidden"] = bool(s["start_hidden"])
    s["show_hints"] = bool(s["show_hints"])
    return s


def save_settings(s: dict) -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------- games ---

TEMPLATE = """\
// One file = one game. Lines starting with // are ignored.
//
//   # Title             starts a new page (flip with the Next page hotkey)
//   ## Title            starts a section
//   Key | Action        one row
//   Key | A | B         extra columns, great for side-by-side menus
//   > | Col A | Col B   column headings for the rows below
//   Any other line      shows as a small note

# Basics
## Movement
W A S D | Move
Space | Jump
Shift | Sprint

## Combat
LMB | Attack
R | Reload
G | Grenade
"""

_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def clean_name(name: str) -> str:
    return _BAD_CHARS.sub("", name or "").strip().strip(".")[:60]


# SHA-256 of bundled sheets shipped in earlier versions (\r stripped). A user copy that
# still matches one of these was never edited, so it is safe to refresh on upgrade.
_STOCK_SHEETS = {
    "fe78ac74ce3db46a8a33ed3210f7913b5a45d38730931400c5bddac81eb31f10",  # AoE2, v1.0.0
}


def _sheet_hash(path: str) -> str:
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return ""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return hashlib.sha256(data.replace(b"\r", b"")).hexdigest()


def _refresh_stock_sheets(bundled: str) -> None:
    """Replace unedited copies of old bundled sheets with the current ones."""
    if not os.path.isdir(bundled):
        return
    for f in os.listdir(bundled):
        mine = os.path.join(GAMES_DIR, f)
        if f.lower().endswith(".txt") and os.path.isfile(mine) \
                and _sheet_hash(mine) in _STOCK_SHEETS:
            try:
                shutil.copy2(os.path.join(bundled, f), mine)
            except OSError:
                pass


def ensure_library() -> None:
    """Create the games folder; seed it with the bundled sheets on first run."""
    os.makedirs(GAMES_DIR, exist_ok=True)
    if list_games():
        _refresh_stock_sheets(os.path.join(RES_DIR, "games"))
        return
    bundled = os.path.join(RES_DIR, "games")
    if os.path.isdir(bundled):
        for f in os.listdir(bundled):
            if f.lower().endswith(".txt"):
                shutil.copy2(os.path.join(bundled, f), os.path.join(GAMES_DIR, f))
    if not list_games():
        write_game("Example game", TEMPLATE)


def list_games() -> list:
    try:
        names = [f[:-4] for f in os.listdir(GAMES_DIR)
                 if f.lower().endswith(".txt") and not f.startswith(".")]
    except OSError:
        return []
    return sorted(names, key=str.lower)


def game_path(name: str) -> str:
    return os.path.join(GAMES_DIR, name + ".txt")


def read_game(name: str) -> str:
    try:
        with open(game_path(name), encoding="utf-8-sig", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def write_game(name: str, text: str) -> None:
    with open(game_path(name), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
