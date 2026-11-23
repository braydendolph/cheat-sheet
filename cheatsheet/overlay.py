"""The in-game overlay window.

On Windows the rendered RGBA image is pushed straight to a layered window
with UpdateLayeredWindow, so transparency is per pixel. The window is
click-through, never takes focus and stays out of Alt+Tab.
"""
from __future__ import annotations

import ctypes
import sys
import tkinter as tk

from PIL import Image, ImageChops, ImageTk

IS_WIN = sys.platform == "win32"
if IS_WIN:
    from ctypes import wintypes


if IS_WIN:
    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                    ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    _u32 = ctypes.windll.user32
    _gdi = ctypes.windll.gdi32
    _u32.GetParent.restype = wintypes.HWND
    _u32.GetParent.argtypes = [wintypes.HWND]
    _u32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _u32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    _u32.GetDC.restype = wintypes.HDC
    _u32.GetDC.argtypes = [wintypes.HWND]
    _u32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _u32.UpdateLayeredWindow.argtypes = [
        wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
        ctypes.POINTER(wintypes.SIZE), wintypes.HDC, ctypes.POINTER(wintypes.POINT),
        wintypes.COLORREF, ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
    _u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _gdi.CreateCompatibleDC.restype = wintypes.HDC
    _gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _gdi.CreateDIBSection.restype = wintypes.HBITMAP
    _gdi.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
                                      ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE,
                                      wintypes.DWORD]
    _gdi.SelectObject.restype = wintypes.HGDIOBJ
    _gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    _gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi.DeleteDC.argtypes = [wintypes.HDC]


def screen_scale() -> float:
    """Display scaling (1.0 = 100%)."""
    if IS_WIN:
        try:
            return ctypes.windll.user32.GetDpiForSystem() / 96.0
        except Exception:
            pass
    return 1.0


def _premultiplied_bgra(img: Image.Image) -> bytes:
    r, g, b, a = img.split()
    r, g, b = (ImageChops.multiply(c, a) for c in (r, g, b))
    return Image.merge("RGBA", (b, g, r, a)).tobytes()


class Overlay:
    GWL_EXSTYLE = -20
    WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x00080000, 0x00000020
    WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, WS_EX_TOPMOST = 0x80, 0x08000000, 0x8

    def __init__(self, root: tk.Tk):
        self.root = root
        self.visible = False
        self.image = None
        self.pos = (0, 0)
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.hwnd = None
        if IS_WIN:
            self.win.geometry("1x1+-4000+-4000")
            self.win.deiconify()
            self.win.update_idletasks()
            self.hwnd = _u32.GetParent(self.win.winfo_id())
            style = _u32.GetWindowLongW(self.hwnd, self.GWL_EXSTYLE)
            style |= (self.WS_EX_LAYERED | self.WS_EX_TRANSPARENT | self.WS_EX_TOOLWINDOW
                      | self.WS_EX_NOACTIVATE | self.WS_EX_TOPMOST)
            _u32.SetWindowLongW(self.hwnd, self.GWL_EXSTYLE, style)
        else:  # preview fallback for development on other systems
            self.label = tk.Label(self.win, bd=0, bg="#2b3a2c")
            self.label.pack()

    # ------------------------------------------------------------------
    def _push(self, alpha: int):
        img, (x, y) = self.image, self.pos
        if img is None:
            return
        w, h = img.size
        data = _premultiplied_bgra(img)
        screen = _u32.GetDC(None)
        mem = _gdi.CreateCompatibleDC(screen)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h          # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bits = ctypes.c_void_p()
        hbmp = _gdi.CreateDIBSection(mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        try:
            ctypes.memmove(bits, data, len(data))
            old = _gdi.SelectObject(mem, hbmp)
            blend = BLENDFUNCTION(0, 0, alpha, 1)   # AC_SRC_OVER, AC_SRC_ALPHA
            _u32.UpdateLayeredWindow(self.hwnd, screen, ctypes.byref(wintypes.POINT(x, y)),
                                     ctypes.byref(wintypes.SIZE(w, h)), mem,
                                     ctypes.byref(wintypes.POINT(0, 0)), 0,
                                     ctypes.byref(blend), 2)  # ULW_ALPHA
            _gdi.SelectObject(mem, old)
        finally:
            _gdi.DeleteObject(hbmp)
            _gdi.DeleteDC(mem)
            _u32.ReleaseDC(None, screen)

    def set_image(self, img: Image.Image, position: str, margin: int):
        """Place a freshly rendered overlay image (keeps current visibility)."""
        self.image = img
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = img.size
        m = int(margin)
        x = m if position.endswith("left") else sw - w - m if position.endswith("right") \
            else (sw - w) // 2
        y = m if position.startswith("top") else sh - h - m
        self.pos = (max(0, x), max(0, y))
        if IS_WIN:
            if self.visible:
                self._push(255)
        else:
            self._photo = ImageTk.PhotoImage(img)
            self.label.configure(image=self._photo)
            self.win.geometry(f"+{self.pos[0]}+{self.pos[1]}")

    def show(self):
        self.visible = True
        if IS_WIN:
            self._push(255)
            self.keep_on_top()
        else:
            self.win.deiconify()
            self.win.lift()

    def hide(self):
        self.visible = False
        if IS_WIN:
            self._push(0)
        else:
            self.win.withdraw()

    def keep_on_top(self):
        if IS_WIN and self.hwnd and self.visible:
            # HWND_TOPMOST; no move / size / activate
            _u32.SetWindowPos(self.hwnd, wintypes.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
