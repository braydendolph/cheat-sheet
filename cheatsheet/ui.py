"""The Cheat Sheet manager window."""
from __future__ import annotations

import ctypes
import os
import queue
import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, simpledialog, ttk

from PIL import Image, ImageTk

from . import APP_NAME, __version__
from . import config as cfg
from .hotkeys import HotkeyListener, hotkey_to_tk, key_is_down, parse_hotkey
from .overlay import Overlay, screen_scale
from .render import render_overlay
from .sheet import parse_sheet

IS_WIN = sys.platform == "win32"
if IS_WIN:
    from ctypes import wintypes

# ------------------------------------------------------------------ theme ---

C = {
    "bg": "#0b0e13",
    "surface": "#10151c",
    "surface2": "#161c25",
    "raised": "#1c232d",
    "border": "#1f2731",
    "text": "#e8ecf1",
    "muted": "#8c95a4",
    "faint": "#566070",
    "accent": "#f0c04f",
    "accent_hi": "#f6cf6d",
    "accent_dim": "#2a2415",
    "ink": "#15110a",
    "key": "#9ecbff",
    "ok": "#6fd39a",
    "danger": "#ef7b6c",
    "status": "#080a0e",
}
F = {}  # font families, filled in by _setup_fonts()
UI = 1.0  # screen DPI / 96, set once the Tk root exists


def px(n: float) -> int:
    """Scale a layout size in 96-DPI pixels to this screen (fonts scale on their own)."""
    return int(round(n * UI))


def _register_bundled_fonts():
    """Make the bundled Inter / JetBrains Mono available to Tk on Windows."""
    if not IS_WIN or not os.path.isdir(cfg.FONTS):
        return
    add = ctypes.windll.gdi32.AddFontResourceExW
    for f in os.listdir(cfg.FONTS):
        if f.lower().endswith((".ttf", ".otf")):
            add(os.path.join(cfg.FONTS, f), 0x10, 0)  # FR_PRIVATE


def _setup_fonts(root):
    fams = set(tkfont.families(root))

    def pick(*names):
        for n in names:
            if n in fams:
                return n
        return names[-1]

    F["ui"] = pick("Inter", "Segoe UI", "DejaVu Sans")
    F["semi"] = pick("Inter SemiBold", "Inter Semi Bold", "Segoe UI Semibold", F["ui"])
    F["mono"] = pick("JetBrains Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono")


def font(kind="ui", size=10, bold=False):
    return (F[kind], size, "bold") if bold else (F[kind], size)


# ------------------------------------------------------------ widgets ---

class FlatButton(tk.Label):
    STYLES = {
        "primary": ("accent", "ink", "accent_hi"),
        "ghost": ("raised", "text", "border"),
        "subtle": ("surface", "muted", "surface2"),
        "danger": ("raised", "danger", "border"),
    }

    def __init__(self, parent, text, command, kind="ghost", padx=14, pady=7, size=10):
        bg, fg, hover = (C[k] for k in self.STYLES[kind])
        super().__init__(parent, text=text, bg=bg, fg=fg, cursor="hand2",
                         font=font("semi" if kind == "primary" else "ui", size),
                         padx=padx, pady=pady)
        self._bg, self._hover, self._cmd = bg, hover, command
        self.bind("<Enter>", lambda e: self.configure(bg=self._hover))
        self.bind("<Leave>", lambda e: self.configure(bg=self._bg))
        self.bind("<ButtonRelease-1>", self._click)

    def _click(self, e):
        if 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self._cmd()


class Stepper(tk.Frame):
    def __init__(self, parent, value, lo, hi, on_change):
        super().__init__(parent, bg=C["surface2"])
        self.value, self.lo, self.hi, self.on_change = value, lo, hi, on_change
        for txt, d in (("−", -1), (None, 0), ("+", 1)):
            if txt is None:
                self.lbl = tk.Label(self, text=str(value), width=3, bg=C["surface2"],
                                    fg=C["text"], font=font("mono", 10, True))
                self.lbl.pack(side="left")
                continue
            b = tk.Label(self, text=txt, bg=C["surface2"], fg=C["muted"], cursor="hand2",
                         font=font("ui", 11), padx=7, pady=1)
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, d=d: self._step(d))
            b.bind("<Enter>", lambda e, b=b: b.configure(fg=C["accent"]))
            b.bind("<Leave>", lambda e, b=b: b.configure(fg=C["muted"]))

    def _step(self, d):
        v = max(self.lo, min(self.hi, self.value + d))
        if v != self.value:
            self.value = v
            self.lbl.configure(text=str(v))
            self.on_change(v)


class Slider(tk.Frame):
    """Thin track, gold fill, round knob, value readout."""

    def __init__(self, parent, value, lo, hi, on_change, length=180, fmt="{:.0%}"):
        super().__init__(parent, bg=C["surface"])
        length = px(length)
        self.lo, self.hi, self.value, self.on_change, self.length, self.fmt = \
            lo, hi, value, on_change, length, fmt
        self.cv = tk.Canvas(self, width=length, height=px(20), bg=C["surface"],
                            highlightthickness=0, bd=0, cursor="hand2")
        self.cv.pack(side="left")
        self.out = tk.Label(self, text="", width=5, anchor="e", bg=C["surface"],
                            fg=C["text"], font=font("mono", 9, True))
        self.out.pack(side="left", padx=(6, 0))
        self.cv.bind("<Button-1>", self._drag)
        self.cv.bind("<B1-Motion>", self._drag)
        self._draw()

    def _draw(self):
        c, pad, y, r, w = self.cv, px(8), px(10), px(7), max(2, px(4))
        x = pad + (self.value - self.lo) / (self.hi - self.lo) * (self.length - 2 * pad)
        c.delete("all")
        c.create_line(pad, y, self.length - pad, y, fill=C["raised"], width=w, capstyle="round")
        c.create_line(pad, y, x, y, fill=C["accent"], width=w, capstyle="round")
        c.create_oval(x - r, y - r, x + r, y + r, fill=C["text"], outline=C["bg"], width=2)
        self.out.configure(text=self.fmt.format(self.value))

    def _drag(self, e):
        pad = px(8)
        frac = (e.x - pad) / max(1, self.length - 2 * pad)
        v = round(max(self.lo, min(self.hi, self.lo + frac * (self.hi - self.lo))), 2)
        if v != self.value:
            self.value = v
            self._draw()
            self.on_change(v)


class Segmented(tk.Frame):
    def __init__(self, parent, options, value, on_change):
        super().__init__(parent, bg=C["surface2"], padx=2, pady=2)
        self.value, self.on_change, self.btns = value, on_change, {}
        for opt, label in options:
            lbl = tk.Label(self, text=label, cursor="hand2", font=font("ui", 9), padx=10, pady=4)
            lbl.pack(side="left", padx=(0, 2))
            lbl.bind("<Button-1>", lambda e, o=opt: self.set(o, notify=True))
            self.btns[opt] = lbl
        self.set(value)

    def set(self, value, notify=False):
        self.value = value
        for opt, lbl in self.btns.items():
            on = opt == value
            lbl.configure(bg=C["accent_dim"] if on else C["surface2"],
                          fg=C["accent"] if on else C["muted"])
        if notify:
            self.on_change(value)


class PositionPicker(tk.Frame):
    """A tiny 'screen' with six spots to click."""

    SPOTS = [("top-left", 0, 0), ("top-center", 0, 1), ("top-right", 0, 2),
             ("bottom-left", 1, 0), ("bottom-center", 1, 1), ("bottom-right", 1, 2)]

    def __init__(self, parent, value, on_change):
        super().__init__(parent, bg=C["surface"])
        self.cv = tk.Canvas(self, width=px(96), height=px(56), bg=C["surface"], highlightthickness=0)
        self.cv.pack()
        self.value, self.on_change = value, on_change
        self.cv.bind("<Button-1>", self._click)
        self._draw()

    def _draw(self):
        c = self.cv
        c.delete("all")
        c.create_rectangle(1, 1, px(96) - 1, px(56) - 1, outline=C["border"], fill=C["surface2"])
        for name, r, col in self.SPOTS:
            x = px(8 + col * 30)
            y = px(7 + r * 28)
            on = name == self.value
            c.create_rectangle(x, y, x + px(20), y + px(14),
                               fill=C["accent"] if on else C["raised"], outline="")

    def _click(self, e):
        col = min(2, max(0, int((e.x / UI - 4) // 30)))
        r = 0 if e.y / UI < 28 else 1
        for name, rr, cc in self.SPOTS:
            if rr == r and cc == col and name != self.value:
                self.value = name
                self._draw()
                self.on_change(name)


class Switch(tk.Frame):
    def __init__(self, parent, text, value, on_change):
        super().__init__(parent, bg=C["surface"], cursor="hand2")
        self.value, self.on_change = value, on_change
        self.cv = tk.Canvas(self, width=px(34), height=px(18), bg=C["surface"], highlightthickness=0)
        self.cv.pack(side="left")
        self.lbl = tk.Label(self, text=text, bg=C["surface"], fg=C["muted"], font=font("ui", 9))
        self.lbl.pack(side="left", padx=(8, 0))
        for w in (self, self.cv, self.lbl):
            w.bind("<Button-1>", self._toggle)
        self._draw()

    def _draw(self):
        c = self.cv
        c.delete("all")
        on = self.value
        fill = C["accent"] if on else C["raised"]
        c.create_oval(px(1), px(1), px(17), px(17), fill=fill, outline="")
        c.create_oval(px(17), px(1), px(33), px(17), fill=fill, outline="")
        c.create_rectangle(px(9), px(1), px(25), px(17), fill=fill, outline="")
        x = px(25 if on else 9)
        c.create_oval(x - px(6), px(3), x + px(6), px(15), fill=C["ink"] if on else C["muted"],
                      outline="")

    def _toggle(self, _e=None):
        self.value = not self.value
        self._draw()
        self.on_change(self.value)


def section_label(parent, text, bg=None, pady=(14, 8)):
    bg = bg or C["surface"]
    row = tk.Frame(parent, bg=bg)
    row.pack(fill="x", pady=pady)
    tk.Label(row, text=text.upper(), bg=bg, fg=C["faint"],
             font=font("mono", 8, True)).pack(side="left")
    tk.Frame(row, bg=C["border"], height=1).pack(side="left", fill="x", expand=True, padx=(10, 0))
    return row


def field(parent, label, widget_factory):
    row = tk.Frame(parent, bg=C["surface"])
    row.pack(fill="x", pady=3)
    tk.Label(row, text=label, bg=C["surface"], fg=C["muted"], width=12, anchor="w",
             font=font("ui", 9)).pack(side="left")
    w = widget_factory(row)
    w.pack(side="left")
    return w


# ---------------------------------------------------------------- app ---

class App:
    def __init__(self):
        self.settings = cfg.load_settings()
        cfg.ensure_library()
        _register_bundled_fonts()
        self.root = tk.Tk()
        global UI
        try:
            UI = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        except tk.TclError:
            UI = 1.0
        _setup_fonts(self.root)
        self.root.title(APP_NAME)
        self.root.configure(bg=C["bg"])
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = min(px(1280), int(sw * 0.92)), min(px(860), int(sh * 0.88))
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(min(px(1100), w), min(px(820), h))
        self.root.protocol("WM_DELETE_WINDOW", self.hide_manager)
        self._window_icon()
        self._dark_titlebar()

        self.events: queue.Queue = queue.Queue()
        self.overlay = Overlay(self.root)
        self.page = 0
        self.preview_page = 0
        self.editor_game = None
        self.saved_text = ""
        self.listener = None
        self.failed_hotkeys = []
        self._tk_bound = []
        self.toggle_vk = 0
        self._holding = False
        self._preview_job = None
        try:
            self.preview_bg = Image.open(cfg.asset("preview_bg.jpg")).convert("RGBA")
        except OSError:
            self.preview_bg = Image.new("RGBA", (1920, 1080), (52, 74, 48, 255))

        games = cfg.list_games()
        if self.settings["active_game"] not in games:
            self.settings["active_game"] = games[0] if games else ""

        self._build()
        self._refresh_games(select=self.settings["active_game"])
        self.apply_hotkeys(quiet=True)
        self.root.after(40, self._pump)
        self.root.after(1500, self._tick)
        if self.settings["start_hidden"]:
            self.root.withdraw()

    # ---- chrome -------------------------------------------------------------
    def _window_icon(self):
        try:
            if IS_WIN and os.path.exists(cfg.asset("icon.ico")):
                self.root.iconbitmap(default=cfg.asset("icon.ico"))
            img = Image.open(cfg.asset("logo_256.png")).resize((64, 64), Image.LANCZOS)
            self._icon = ImageTk.PhotoImage(img)
            self.root.iconphoto(True, self._icon)
        except Exception:
            pass

    def _dark_titlebar(self):
        if not IS_WIN:
            return
        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            for attr, val in ((20, 1), (35, 0x0013100B)):  # dark mode, caption colour
                v = ctypes.c_int(val)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v),
                                                           ctypes.sizeof(v))
        except Exception:
            pass

    # ---- layout ----------------------------------------------------------------
    def _build(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Dark.Vertical.TScrollbar", background=C["raised"],
                        troughcolor=C["surface"], bordercolor=C["surface"],
                        arrowcolor=C["muted"], lightcolor=C["raised"],
                        darkcolor=C["raised"], gripcount=0, arrowsize=12)
        style.map("Dark.Vertical.TScrollbar", background=[("active", C["border"])])

        r = self.root
        r.columnconfigure(1, weight=1)
        r.rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_editor()
        self._build_settings()
        self._build_statusbar()

    def _build_sidebar(self):
        side = tk.Frame(self.root, bg=C["surface"], width=px(236))
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)
        side.columnconfigure(0, weight=1)
        side.rowconfigure(2, weight=1)

        brand = tk.Frame(side, bg=C["surface"])
        brand.grid(row=0, column=0, sticky="ew", padx=20, pady=(22, 22))
        try:
            img = Image.open(cfg.asset("logo_256.png")).resize((px(34), px(34)), Image.LANCZOS)
            self._brand_img = ImageTk.PhotoImage(img)
            tk.Label(brand, image=self._brand_img, bg=C["surface"]).pack(side="left")
        except Exception:
            pass
        words = tk.Frame(brand, bg=C["surface"])
        words.pack(side="left", padx=(12, 0))
        tk.Label(words, text=APP_NAME, bg=C["surface"], fg=C["text"],
                 font=font("semi", 13)).pack(anchor="w")
        tk.Label(words, text=f"v{__version__}  ·  HOTKEY OVERLAY", bg=C["surface"], fg=C["faint"],
                 font=font("mono", 7, True)).pack(anchor="w")

        lib = tk.Frame(side, bg=C["surface"])
        lib.grid(row=1, column=0, sticky="ew", padx=20)
        section_label(lib, "Library", pady=(0, 6))

        self.game_list = tk.Listbox(
            side, bg=C["surface"], fg=C["text"], bd=0, highlightthickness=0,
            selectbackground=C["raised"], selectforeground=C["text"],
            activestyle="none", font=font("ui", 11), exportselection=False)
        self.game_list.grid(row=2, column=0, sticky="nsew", padx=12, pady=(2, 8))
        self.game_list.bind("<<ListboxSelect>>", self._on_select_game)
        self.game_list.bind("<Double-Button-1>", lambda e: self.use_selected_game())

        actions = tk.Frame(side, bg=C["surface"])
        actions.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 18))
        FlatButton(actions, "Use on overlay", self.use_selected_game, kind="primary").pack(fill="x")
        row = tk.Frame(actions, bg=C["surface"])
        row.pack(fill="x", pady=(8, 0))
        for i, (txt, cmd, kind) in enumerate((("New", self.new_game, "ghost"),
                                              ("Rename", self.rename_game, "ghost"),
                                              ("Delete", self.delete_game, "danger"))):
            FlatButton(row, txt, cmd, kind=kind, padx=4, size=9).pack(
                side="left", expand=True, fill="x", padx=(0 if i == 0 else 4, 0))
        FlatButton(actions, "Open games folder", self.open_folder, kind="subtle", size=9).pack(
            fill="x", pady=(8, 0))

    def _build_editor(self):
        main = tk.Frame(self.root, bg=C["bg"])
        main.grid(row=0, column=1, sticky="nsew", padx=26, pady=(22, 16))
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        top = tk.Frame(main, bg=C["bg"])
        top.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        titles = tk.Frame(top, bg=C["bg"])
        titles.pack(side="left")
        self.editor_title = tk.Label(titles, text="", bg=C["bg"], fg=C["text"], font=font("semi", 18))
        self.editor_title.pack(anchor="w")
        self.editor_meta = tk.Label(titles, text="", bg=C["bg"], fg=C["faint"],
                                    font=font("mono", 8, True))
        self.editor_meta.pack(anchor="w", pady=(2, 0))
        FlatButton(top, "Save", self.save_game, kind="primary").pack(side="right")
        FlatButton(top, "Revert", self.revert, kind="subtle").pack(side="right", padx=(0, 8))

        card = tk.Frame(main, bg=C["border"])
        card.grid(row=1, column=0, sticky="nsew")
        inner = tk.Frame(card, bg=C["surface"])
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.gutter = tk.Text(inner, width=4, bd=0, highlightthickness=0, bg=C["surface"],
                              fg=C["faint"], font=font("mono", 10), padx=8, pady=16,
                              spacing1=3, spacing3=3, state="disabled", cursor="arrow",
                              takefocus=0)
        self.gutter.pack(side="left", fill="y")
        self.editor = tk.Text(inner, wrap="none", undo=True, bd=0, highlightthickness=0,
                              bg=C["surface"], fg=C["text"], insertbackground=C["accent"],
                              selectbackground="#2b3442", font=font("mono", 10),
                              padx=10, pady=16, spacing1=3, spacing3=3)
        sb = ttk.Scrollbar(inner, orient="vertical", command=self._yview,
                           style="Dark.Vertical.TScrollbar")
        self.editor.configure(yscrollcommand=lambda a, b: (sb.set(a, b), self.gutter.yview_moveto(a)))
        sb.pack(side="right", fill="y")
        self.editor.pack(side="left", fill="both", expand=True)
        t = self.editor
        t.tag_configure("page", foreground=C["accent"], font=font("mono", 11, True))
        t.tag_configure("section", foreground="#d4dae3", font=font("mono", 10, True))
        t.tag_configure("key", foreground=C["key"])
        t.tag_configure("pipe", foreground=C["faint"])
        t.tag_configure("comment", foreground=C["faint"])
        t.bind("<KeyRelease>", lambda e: self._after_edit())
        t.bind("<Control-s>", lambda e: (self.save_game(), "break")[1])

        hint = tk.Frame(main, bg=C["bg"])
        hint.grid(row=2, column=0, sticky="w", pady=(10, 0))
        for sym, desc in (("#", "page"), ("##", "section"), ("Key | Action", "row"),
                          ("| B", "extra column"), (">", "headings"), ("//", "comment")):
            tk.Label(hint, text=sym, bg=C["bg"], fg=C["accent"], font=font("mono", 8, True)).pack(side="left")
            tk.Label(hint, text=desc, bg=C["bg"], fg=C["faint"], font=font("mono", 8)).pack(side="left", padx=(5, 12))

    def _yview(self, *args):
        self.editor.yview(*args)
        self.gutter.yview(*args)

    def _build_settings(self):
        panel = tk.Frame(self.root, bg=C["surface"], width=px(380))
        panel.grid(row=0, column=2, sticky="nse")
        panel.pack_propagate(False)
        body = tk.Frame(panel, bg=C["surface"])
        body.pack(fill="both", expand=True, padx=22, pady=(20, 14))

        # Live preview ------------------------------------------------------------
        head = section_label(body, "Live preview", pady=(0, 10))
        nav = tk.Frame(head, bg=C["surface"])
        nav.pack(side="right", padx=(10, 0))
        for txt, d in (("‹", -1), (None, 0), ("›", 1)):
            if txt is None:
                self.preview_lbl = tk.Label(nav, text="", bg=C["surface"], fg=C["muted"],
                                            font=font("mono", 8, True))
                self.preview_lbl.pack(side="left", padx=4)
                continue
            b = tk.Label(nav, text=txt, bg=C["surface"], fg=C["muted"], cursor="hand2",
                         font=font("ui", 12))
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, d=d: self._preview_step(d))
        self.preview = tk.Label(body, bg=C["surface2"], bd=0, width=px(336), height=px(212))
        self.preview.pack(fill="x")
        self.preview_note = tk.Label(body, text="Exactly what you'll see in game",
                                     bg=C["surface"], fg=C["faint"], font=font("ui", 8))
        self.preview_note.pack(anchor="w", pady=(6, 0))

        # Display -----------------------------------------------------------------
        section_label(body, "Display")
        field(body, "Show", lambda p: Segmented(
            p, [("hold", "Hold key"), ("toggle", "Press to toggle")],
            self.settings["mode"], lambda v: self._set("mode", v)))
        pos_row = tk.Frame(body, bg=C["surface"])
        pos_row.pack(fill="x", pady=4)
        tk.Label(pos_row, text="Position", bg=C["surface"], fg=C["muted"], width=12, anchor="nw",
                 font=font("ui", 9)).pack(side="left", anchor="n")
        PositionPicker(pos_row, self.settings["position"],
                       lambda v: self._set("position", v)).pack(side="left")
        steppers = tk.Frame(pos_row, bg=C["surface"])
        steppers.pack(side="left", padx=(12, 0), anchor="n")
        for label, key, lo, hi in (("Columns", "columns", 1, 6), ("Text", "font_size", 8, 24)):
            r = tk.Frame(steppers, bg=C["surface"])
            r.pack(anchor="w", pady=(0, 6))
            tk.Label(r, text=label, bg=C["surface"], fg=C["muted"], width=6, anchor="w",
                     font=font("ui", 9)).pack(side="left")
            Stepper(r, self.settings[key], lo, hi,
                    lambda v, k=key: self._set(k, v)).pack(side="left")

        # Appearance ----------------------------------------------------------------
        section_label(body, "Appearance")
        field(body, "Backdrop", lambda p: Slider(p, self.settings["backdrop"], 0.0, 1.0,
                                                 lambda v: self._set("backdrop", v), length=170))
        field(body, "Opacity", lambda p: Slider(p, self.settings["opacity"], 0.3, 1.0,
                                                lambda v: self._set("opacity", v), length=170))

        # Hotkeys -------------------------------------------------------------------
        section_label(body, "Hotkeys")
        self.hk_vars = {}
        for action in cfg.HOTKEY_ACTIONS:
            var = tk.StringVar(value=self.settings["hotkeys"][action])
            self.hk_vars[action] = var

            def make(p, var=var):
                e = tk.Entry(p, textvariable=var, bd=0, width=18, bg=C["surface2"], fg=C["text"],
                             insertbackground=C["accent"], highlightthickness=1,
                             highlightbackground=C["surface2"], highlightcolor=C["accent"],
                             font=font("mono", 9), relief="flat")
                e.bind("<Return>", lambda ev: self.apply_hotkeys())
                return e
            ent = field(body, cfg.HOTKEY_LABELS[action], make)
            ent.pack_configure(ipady=3)
        foot = tk.Frame(body, bg=C["surface"])
        foot.pack(fill="x", pady=(10, 0))
        FlatButton(foot, "Apply hotkeys", self.apply_hotkeys, size=9).pack(side="right")

        # Behaviour -------------------------------------------------------------------
        section_label(body, "Behavior")
        sw = tk.Frame(body, bg=C["surface"])
        sw.pack(fill="x")
        Switch(sw, "Start hidden", self.settings["start_hidden"],
               lambda v: self._set("start_hidden", v)).pack(side="left")
        Switch(sw, "Show hints", self.settings["show_hints"],
               lambda v: self._set("show_hints", v)).pack(side="left", padx=(22, 0))

    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=C["status"], height=px(30))
        bar.grid(row=1, column=0, columnspan=3, sticky="ew")
        bar.pack_propagate(False)
        self.status_dot = tk.Label(bar, text="●", bg=C["status"], fg=C["ok"], font=font("ui", 8))
        self.status_dot.pack(side="left", padx=(18, 6))
        self.status_left = tk.Label(bar, text="", bg=C["status"], fg=C["muted"],
                                    font=font("mono", 8, True))
        self.status_left.pack(side="left")
        FlatButton(bar, "Quit", self.quit, kind="subtle", padx=10, pady=3, size=8).pack(side="right", padx=(0, 12))
        FlatButton(bar, "Hide window", self.hide_manager, kind="subtle", padx=10, pady=3, size=8).pack(side="right")
        self.status_right = tk.Label(bar, text="", bg=C["status"], fg=C["muted"],
                                     font=font("mono", 8))
        self.status_right.pack(side="right", padx=(0, 14))

    # ---- status ---------------------------------------------------------------
    def _update_status(self):
        hk = self.settings["hotkeys"].get("toggle") or "—"
        verb = "HOLD" if self.settings["mode"] == "hold" else "PRESS"
        active = self.settings["active_game"] or "no game selected"
        ok = not self.failed_hotkeys
        self.status_dot.configure(fg=C["ok"] if ok else C["danger"])
        self.status_left.configure(
            text=f"{'RUNNING' if ok else 'HOTKEY CONFLICT'}   ·   {verb} {hk.upper()} IN GAME"
                 f"   ·   ON OVERLAY: {active.upper()}")

    def message(self, text, kind="muted"):
        self.status_right.configure(text=text, fg=C.get(kind, C["muted"]))
        if getattr(self, "_msg_job", None):
            self.root.after_cancel(self._msg_job)
        self._msg_job = self.root.after(6000, lambda: self.status_right.configure(text=""))

    # ---- settings ---------------------------------------------------------------
    def _set(self, key, value):
        self.settings[key] = value
        cfg.save_settings(self.settings)
        if key in ("mode",):
            self._update_status()
        if self.overlay.visible:
            self.render_overlay()
        self._schedule_preview()

    def _hint(self):
        hk = self.settings["hotkeys"]
        parts = []
        if hk.get("next_page"):
            parts.append(f"{hk['next_page']} next page")
        if hk.get("next_game"):
            parts.append(f"{hk['next_game']} next game")
        return "   ·   ".join(parts)

    # ---- library ------------------------------------------------------------------
    def _refresh_games(self, select=None):
        games = cfg.list_games()
        self._games = games
        lb = self.game_list
        lb.delete(0, "end")
        for i, g in enumerate(games):
            active = g == self.settings["active_game"]
            lb.insert("end", f"  {g}" + ("   ●" if active else ""))
            lb.itemconfig(i, foreground=C["accent"] if active else C["text"],
                          selectforeground=C["accent"] if active else C["text"])
        idx = games.index(select) if select in games else (0 if games else None)
        if idx is not None:
            lb.selection_clear(0, "end")
            lb.selection_set(idx)
            lb.see(idx)
            if games[idx] != self.editor_game:
                self._load_editor(games[idx])
        else:
            self._load_editor(None)
        self._update_status()

    def _selected(self):
        sel = self.game_list.curselection()
        return self._games[sel[0]] if sel else None

    def _dirty(self):
        return self.editor_game is not None and self.editor.get("1.0", "end-1c") != self.saved_text

    def _confirm_discard(self):
        if not self._dirty():
            return True
        ans = messagebox.askyesnocancel(APP_NAME, f'Save changes to "{self.editor_game}"?',
                                        parent=self.root)
        if ans is None:
            return False
        if ans:
            self.save_game()
        return True

    def _on_select_game(self, _e=None):
        name = self._selected()
        if name == self.editor_game:
            return
        if not self._confirm_discard():
            self._refresh_games(select=self.editor_game)
            return
        self._load_editor(name)

    def _load_editor(self, name):
        self.editor_game = name
        text = cfg.read_game(name) if name else ""
        self.editor.configure(state="normal")
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)
        self.editor.edit_reset()
        self.saved_text = text
        self.editor_title.configure(text=name or "No games yet")
        if not name:
            self.editor.configure(state="disabled")
        self.preview_page = 0
        self._after_edit()

    def _after_edit(self):
        text = self.editor.get("1.0", "end-1c")
        pages = parse_sheet(text)
        rows = sum(1 for p in pages for s in p["sections"] for r in s["rows"] if r[0] == "row")
        state = "UNSAVED" if self._dirty() else "SAVED"
        self.editor_meta.configure(
            text=f"{len(pages)} PAGE{'S' if len(pages) != 1 else ''}  ·  {rows} HOTKEYS  ·  {state}",
            fg=C["accent"] if self._dirty() else C["faint"])
        self._highlight()
        self._update_gutter()
        self._schedule_preview()

    def _update_gutter(self):
        n = int(self.editor.index("end-1c").split(".")[0])
        g = self.gutter
        g.configure(state="normal")
        g.delete("1.0", "end")
        g.insert("1.0", "\n".join(str(i) for i in range(1, n + 1)))
        g.configure(state="disabled")
        g.yview_moveto(self.editor.yview()[0])

    def _highlight(self):
        t = self.editor
        for tag in ("page", "section", "key", "pipe", "comment"):
            t.tag_remove(tag, "1.0", "end")
        for i, line in enumerate(t.get("1.0", "end-1c").split("\n"), start=1):
            s = line.lstrip()
            off = len(line) - len(s)
            if s.startswith("//") or s.startswith(">"):
                t.tag_add("comment", f"{i}.0", f"{i}.end")
            elif s.startswith("## "):
                t.tag_add("section", f"{i}.0", f"{i}.end")
            elif s.startswith("# "):
                t.tag_add("page", f"{i}.0", f"{i}.end")
            elif "|" in line:
                p = line.index("|")
                t.tag_add("key", f"{i}.{off}", f"{i}.{p}")
                for j, ch in enumerate(line):
                    if ch == "|":
                        t.tag_add("pipe", f"{i}.{j}", f"{i}.{j + 1}")

    # ---- preview --------------------------------------------------------------------
    def _schedule_preview(self):
        if self._preview_job:
            self.root.after_cancel(self._preview_job)
        self._preview_job = self.root.after(120, self._draw_preview)

    def _preview_step(self, d):
        self.preview_page += d
        self._draw_preview()

    def _draw_preview(self):
        self._preview_job = None
        pages = parse_sheet(self.editor.get("1.0", "end-1c")) if self.editor_game else []
        if pages:
            self.preview_page %= len(pages)
        img = render_overlay(self.editor_game or "", pages, self.preview_page, self.settings, 1.0)
        bw, bh = px(336), px(212)
        pad = 26
        cw, ch = img.width + 2 * pad, img.height + 2 * pad
        ratio = max(cw / bw, ch / bh, 1.0)
        cw, ch = int(bw * ratio), int(bh * ratio)
        bg = self.preview_bg
        crop = bg.crop((bg.width - cw, 0, bg.width, ch)) if cw <= bg.width and ch <= bg.height \
            else bg.resize((cw, ch))
        frame = crop.copy()
        frame.alpha_composite(img, (cw - img.width - pad + 8, pad - 8))
        frame = frame.resize((bw, bh), Image.LANCZOS)
        self._preview_img = ImageTk.PhotoImage(frame)
        self.preview.configure(image=self._preview_img, width=bw, height=bh)
        n = len(pages)
        self.preview_lbl.configure(text=f"{self.preview_page + 1:02d}/{n:02d}" if n else "—")

    # ---- game actions -------------------------------------------------------------
    def use_selected_game(self):
        name = self._selected()
        if not name:
            return
        self.settings["active_game"] = name
        cfg.save_settings(self.settings)
        self.page = 0
        self._refresh_games(select=name)
        verb = "Hold" if self.settings["mode"] == "hold" else "Press"
        self.message(f"{name} is on the overlay. {verb} {self.settings['hotkeys']['toggle']} in game.", "ok")
        if self.overlay.visible:
            self.render_overlay()

    def save_game(self):
        if not self.editor_game:
            return
        text = self.editor.get("1.0", "end-1c")
        try:
            cfg.write_game(self.editor_game, text)
        except OSError as e:
            self.message(f"Couldn't save: {e}", "danger")
            return
        self.saved_text = text
        self._after_edit()
        self.message(f"Saved {self.editor_game}", "ok")
        if self.overlay.visible:
            self.render_overlay()

    def revert(self):
        if self.editor_game and self._dirty():
            self._load_editor(self.editor_game)
            self.message("Changes discarded")

    def open_folder(self):
        if IS_WIN:
            os.startfile(cfg.GAMES_DIR)
        else:
            self.message(cfg.GAMES_DIR)

    def new_game(self):
        if not self._confirm_discard():
            return
        name = cfg.clean_name(simpledialog.askstring(APP_NAME, "Game name:", parent=self.root) or "")
        if not name:
            return
        if name.lower() in (g.lower() for g in cfg.list_games()):
            messagebox.showinfo(APP_NAME, f'"{name}" already exists.', parent=self.root)
            return
        cfg.write_game(name, cfg.TEMPLATE)
        self.editor_game = None
        self._refresh_games(select=name)
        self.message(f"Created {name}. Replace the example rows with your hotkeys.", "ok")

    def rename_game(self):
        old = self._selected()
        if not old or not self._confirm_discard():
            return
        name = cfg.clean_name(simpledialog.askstring(APP_NAME, "New name:", initialvalue=old,
                                                     parent=self.root) or "")
        if not name or name == old:
            return
        if name.lower() in (g.lower() for g in cfg.list_games() if g != old):
            messagebox.showinfo(APP_NAME, f'"{name}" already exists.', parent=self.root)
            return
        try:
            os.rename(cfg.game_path(old), cfg.game_path(name))
        except OSError as e:
            self.message(f"Couldn't rename: {e}", "danger")
            return
        if self.settings["active_game"] == old:
            self.settings["active_game"] = name
            cfg.save_settings(self.settings)
        self.editor_game = None
        self._refresh_games(select=name)

    def delete_game(self):
        name = self._selected()
        if not name:
            return
        if not messagebox.askyesno(APP_NAME, f'Delete "{name}"? This can\'t be undone.',
                                   icon="warning", parent=self.root):
            return
        try:
            os.remove(cfg.game_path(name))
        except OSError as e:
            self.message(f"Couldn't delete: {e}", "danger")
            return
        if self.settings["active_game"] == name:
            games = cfg.list_games()
            self.settings["active_game"] = games[0] if games else ""
            cfg.save_settings(self.settings)
        self.editor_game = None
        self._refresh_games(select=self.settings["active_game"])
        if self.overlay.visible:
            self.render_overlay()

    # ---- overlay control --------------------------------------------------------
    def _active_text(self):
        name = self.settings["active_game"]
        if not name:
            return ""
        if name == self.editor_game:
            return self.editor.get("1.0", "end-1c")
        return cfg.read_game(name)

    def render_overlay(self):
        pages = parse_sheet(self._active_text())
        if pages:
            self.page %= len(pages)
        warn = ""
        if self.failed_hotkeys:
            warn = "Hotkey in use by another app: " + ", ".join(
                self.settings["hotkeys"][a] for a in self.failed_hotkeys)
        hint = self._hint() if self.settings.get("show_hints") else ""
        img = render_overlay(self.settings["active_game"], pages, self.page, self.settings,
                             screen_scale(), hint, warn)
        self.overlay.set_image(img, self.settings["position"], self.settings["margin"])

    def show_overlay(self):
        self.render_overlay()
        self.overlay.show()

    def handle(self, action):
        if action == "toggle":
            if self.overlay.visible:
                self._holding = False
                self.overlay.hide()
            else:
                self.show_overlay()
                if self.settings["mode"] == "hold" and IS_WIN and self.toggle_vk:
                    self._holding = True
                    self.root.after(30, self._poll_hold)
        elif action == "next_page":
            if self.overlay.visible:
                self.page += 1
            self.show_overlay()
        elif action == "next_game":
            games = cfg.list_games()
            if games:
                cur = self.settings["active_game"]
                i = games.index(cur) if cur in games else -1
                self.settings["active_game"] = games[(i + 1) % len(games)]
                cfg.save_settings(self.settings)
                self.page = 0
                self._refresh_games(select=self.editor_game)
                self.show_overlay()
        elif action == "manager":
            self.show_manager()

    def _poll_hold(self):
        if not self._holding:
            return
        if key_is_down(self.toggle_vk):
            self.root.after(30, self._poll_hold)
        else:
            self._holding = False
            self.overlay.hide()

    def _pump(self):
        try:
            while True:
                self.handle(self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(40, self._pump)

    def _tick(self):
        self.overlay.keep_on_top()
        self.root.after(1500, self._tick)

    # ---- hotkeys ------------------------------------------------------------------
    def apply_hotkeys(self, quiet=False):
        wanted = {a: self.hk_vars[a].get().strip() for a in cfg.HOTKEY_ACTIONS}
        parsed, errors = {}, []
        for a, txt in wanted.items():
            if not txt:
                continue
            try:
                parsed[a] = parse_hotkey(txt)
            except ValueError as e:
                errors.append(f"{cfg.HOTKEY_LABELS[a]}: {e}")
        if not errors and len(set(parsed.values())) < len(parsed):
            errors.append("two actions share the same hotkey")
        if errors:
            self.message("Not applied. " + "; ".join(errors), "danger")
            return
        self.settings["hotkeys"] = wanted
        cfg.save_settings(self.settings)
        self.toggle_vk = parsed["toggle"][1] if "toggle" in parsed else 0

        if IS_WIN:
            if self.listener:
                self.listener.stop()
            self.listener = HotkeyListener(parsed, self.events)
            self.listener.start()
            self.listener.ready.wait(2.0)
            self.failed_hotkeys = list(self.listener.failed)
        else:
            for seq in self._tk_bound:
                self.root.unbind_all(seq)
            self._tk_bound = []
            for a, txt in wanted.items():
                seq = hotkey_to_tk(txt) if txt else None
                if seq:
                    self.root.bind_all(seq, lambda e, act=a: self.events.put(act))
                    self._tk_bound.append(seq)
            self.failed_hotkeys = []

        self._update_status()
        if self.failed_hotkeys:
            names = ", ".join(wanted[a] for a in self.failed_hotkeys)
            self.message(f"Another app already uses {names}. Pick a different key.", "danger")
        elif not quiet:
            self.message("Hotkeys applied", "ok")
        if self.overlay.visible:
            self.render_overlay()
        self._schedule_preview()

    # ---- window -------------------------------------------------------------------
    def show_manager(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_manager(self):
        self.root.withdraw()

    def quit(self):
        if not self._confirm_discard():
            return
        if self.listener:
            self.listener.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ----------------------------------------------------------------- main ---

_MUTEX = None


def _already_running() -> bool:
    global _MUTEX
    if not IS_WIN:
        return False
    k = ctypes.windll.kernel32
    k.CreateMutexW.restype = wintypes.HANDLE
    _MUTEX = k.CreateMutexW(None, False, "CheatSheet.SingleInstance")
    return k.GetLastError() == 183  # ERROR_ALREADY_EXISTS


def main():
    if IS_WIN:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor DPI aware
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CheatSheet.App")
        except Exception:
            pass
    if _already_running():
        r = tk.Tk()
        r.withdraw()
        messagebox.showinfo(APP_NAME, "Cheat Sheet is already running.\n\n"
                            "Press Ctrl+Alt+F8 (or your Open hotkey) to bring it up.")
        r.destroy()
        return
    App().run()
