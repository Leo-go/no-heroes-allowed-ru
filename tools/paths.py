#!/usr/bin/env python3
"""Repo / original-ISO / release-ISO locations for Windows and WSL."""
from __future__ import annotations

from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
ROOT = TOOLS_DIR.parent


def _first_existing(*candidates: Path) -> Path | None:
    for path in candidates:
        if path.exists():
            return path
    return None


PSP_GAMES = _first_existing(
    Path("/mnt/b/psp games"),
    Path(r"B:\psp games"),
)

ORIG_ISO = _first_existing(
    *(
        base / "[PSP] No Heroes Allowed! [USA]_up_by_kohryu.iso"
        for base in (PSP_GAMES, ROOT.parent)
        if base is not None
    )
)

# Playable drop on the Windows PSP folder, even when the repo lives in WSL.
RELEASE_DIR = (PSP_GAMES / "No Heroes Allowed RUS") if PSP_GAMES is not None else ROOT
RELEASE_ISO = RELEASE_DIR / "NHA_USA_RUS.iso"

EXTRACT = ROOT / "iso_extracted"
ORIGINALS = ROOT / "originals"

FONT_FILES = [
    Path(r"C:\Windows\Fonts\tahomabd.ttf"),
    Path(r"C:\Windows\Fonts\tahoma.ttf"),
    Path(r"C:\Windows\Fonts\arialbd.ttf"),
    Path("/mnt/c/Windows/Fonts/tahomabd.ttf"),
    Path("/mnt/c/Windows/Fonts/tahoma.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]


def require_orig_iso() -> Path:
    if ORIG_ISO is None:
        raise SystemExit("original kohryu ISO not found (looked under B:\\psp games and /mnt/b/psp games)")
    return ORIG_ISO
