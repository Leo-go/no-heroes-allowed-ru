#!/usr/bin/env python3
"""Launch PPSSPP with the extracted EBOOT and capture the window."""
from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PIL import Image, ImageGrab

USER32 = ctypes.windll.user32
GDI32 = ctypes.windll.gdi32
PRINT_WINDOW = 0x00000002
SRCCOPY = 0x00CC0020

PPSSPP = Path(r"B:\psp games\tools\PPSSPP\PPSSPPWindows64.exe")
EBOOT = Path(r"B:\psp games\No Heroes Allowed RUS\iso_extracted\PSP_GAME\SYSDIR\EBOOT.BIN")
OUT = Path(r"B:\psp games\No Heroes Allowed RUS\dumps\screenshots")

EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def list_windows(substr: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []

    def cb(hwnd, _lparam):
        if USER32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(512)
            USER32.GetWindowTextW(hwnd, buf, 512)
            if substr.lower() in buf.value.lower():
                found.append((int(hwnd), buf.value))
        return True

    USER32.EnumWindows(EnumWindowsProc(cb), 0)
    return found


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = RECT()
    USER32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def capture_printwindow(hwnd: int, path: Path) -> bool:
    left, top, right, bottom = window_rect(hwnd)
    w, h = right - left, bottom - top
    if w <= 0 or h <= 0:
        return False
    hwnd_dc = USER32.GetWindowDC(hwnd)
    mem_dc = GDI32.CreateCompatibleDC(hwnd_dc)
    bmp = GDI32.CreateCompatibleBitmap(hwnd_dc, w, h)
    GDI32.SelectObject(mem_dc, bmp)
    ok = USER32.PrintWindow(hwnd, mem_dc, PRINT_WINDOW)
    # BITMAPINFO
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.c_uint32),
            ("biWidth", ctypes.c_int32),
            ("biHeight", ctypes.c_int32),
            ("biPlanes", ctypes.c_uint16),
            ("biBitCount", ctypes.c_uint16),
            ("biCompression", ctypes.c_uint32),
            ("biSizeImage", ctypes.c_uint32),
            ("biXPelsPerMeter", ctypes.c_int32),
            ("biYPelsPerMeter", ctypes.c_int32),
            ("biClrUsed", ctypes.c_uint32),
            ("biClrImportant", ctypes.c_uint32),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    GDI32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    GDI32.DeleteObject(bmp)
    GDI32.DeleteDC(mem_dc)
    USER32.ReleaseDC(hwnd, hwnd_dc)
    img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
    img.save(path)
    return bool(ok)


def capture_grab(hwnd: int, path: Path) -> None:
    left, top, right, bottom = window_rect(hwnd)
    img = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
    img.save(path)


def send_space_and_z(hwnd: int) -> None:
    USER32.SetForegroundWindow(hwnd)
    time.sleep(0.15)
    # VK_SPACE=0x20, Z=0x5A, RETURN=0x0D, ESCAPE=0x1B
    for vk in (0x20, 0x5A, 0x0D, 0x58):
        USER32.PostMessageW(hwnd, 0x0100, vk, 0)  # WM_KEYDOWN
        time.sleep(0.05)
        USER32.PostMessageW(hwnd, 0x0101, vk, 0)  # WM_KEYUP
        time.sleep(0.1)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    print("windows before:", list_windows("PPSSPP"))
    proc = subprocess.Popen([str(PPSSPP), str(EBOOT)], cwd=str(PPSSPP.parent))
    print("started pid", proc.pid)
    hwnd = None
    t0 = time.time()
    shot_i = 0
    while time.time() - t0 < duration:
        wins = list_windows("PPSSPP")
        if not hwnd and wins:
            hwnd = wins[-1][0]
            print("hwnd", hwnd, wins)
        if hwnd:
            send_space_and_z(hwnd)
            shot_i += 1
            p1 = OUT / f"pw_{shot_i:02d}.png"
            p2 = OUT / f"grab_{shot_i:02d}.png"
            try:
                capture_printwindow(hwnd, p1)
            except Exception as e:
                print("printwindow fail", e)
            try:
                capture_grab(hwnd, p2)
            except Exception as e:
                print("grab fail", e)
            print(f"shot {shot_i} rect={window_rect(hwnd)}")
        time.sleep(4)
    print("done pid still", proc.poll())


if __name__ == "__main__":
    main()
