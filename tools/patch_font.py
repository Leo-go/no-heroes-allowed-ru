#!/usr/bin/env python3
"""Inject real Cyrillic pixels into the title bitmap font (fpack slots 00+01).

Slot 00 is a Unicode UV directory. Slot 01 is a Mu.1001 4bpp atlas:
240px wide, 120 bytes of pixels + 8 bytes pad per row, pixels start at 0x110.
Missing U+04xx used to draw '?'; empty unique UVs vanished because those
cells had no ink. This paints glyphs into free cells, then points UVs there.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from paths import FONT_FILES, ROOT  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))

from dppk import decompress_dppk, method5_dictionary, parse_dppk, wrap_dppk  # noqa: E402
from fbe import build_fbe, parse_fbe  # noqa: E402

# Fallback for cmap 03 (other text paths). Title menu uses slot 00 UVs.
CYR_TO_LATIN = {
    "А": "A",
    "Б": "B",
    "В": "B",
    "Г": "R",
    "Д": "A",
    "Е": "E",
    "Ё": "E",
    "Ж": "X",
    "З": "3",
    "И": "N",
    "Й": "N",
    "К": "K",
    "Л": "L",
    "М": "M",
    "Н": "H",
    "О": "O",
    "П": "N",
    "Р": "P",
    "С": "C",
    "Т": "T",
    "У": "Y",
    "Ф": "O",
    "Х": "X",
    "Ц": "U",
    "Ч": "4",
    "Ш": "W",
    "Щ": "W",
    "Ъ": "b",
    "Ы": "b",
    "Ь": "b",
    "Э": "3",
    "Ю": "U",
    "Я": "R",
    "а": "a",
    "б": "b",
    "в": "b",
    "г": "r",
    "д": "a",
    "е": "e",
    "ё": "e",
    "ж": "x",
    "з": "3",
    "и": "n",
    "й": "n",
    "к": "k",
    "л": "n",
    "м": "m",
    "н": "h",
    "о": "o",
    "п": "n",
    "р": "p",
    "с": "c",
    "т": "t",
    "у": "y",
    "ф": "o",
    "х": "x",
    "ц": "u",
    "ч": "4",
    "ш": "w",
    "щ": "w",
    "ъ": "b",
    "ы": "b",
    "ь": "b",
    "э": "3",
    "ю": "u",
    "я": "r",
}

CYRILLIC_CPS = [0x0401, *range(0x0410, 0x0450), 0x0451]
WIDE_LOWER = set("жмшщъыью")
# 61 leftover 10x12 holes; overwrite these rare kana for the extra 5 letters.
STEAL_CPS = (0x3090, 0x3091, 0x3092, 0x3093, 0x308F)  # ゐゑをんわ

ATLAS_W = 240
ATLAS_H = 348
PIXEL_START = 0x110
ROW_STRIDE = 128
ROW_BYTES = 120

FONT_PATHS = FONT_FILES


def parse_slot00(data: bytes) -> tuple[int, list[tuple[int, int, int, int, int, int, int]]]:
    count = struct.unpack_from("<I", data, 0)[0]
    recs = []
    off = 4
    for _ in range(count):
        typ, code, sett = data[off], data[off + 1], data[off + 2]
        x, y, w, h = struct.unpack_from("<HHHH", data, off + 3)
        recs.append((typ, code, sett, x, y, w, h))
        off += 11
    if off != len(data):
        raise ValueError(f"slot00 leftover {len(data) - off} after {count} recs")
    return count, recs


def build_slot00(recs: list[tuple[int, int, int, int, int, int, int]]) -> bytes:
    out = bytearray(struct.pack("<I", len(recs)))
    for typ, code, sett, x, y, w, h in recs:
        out.append(typ)
        out.append(code)
        out.append(sett)
        out += struct.pack("<HHHH", x, y, w, h)
    return bytes(out)


def rec_cp(rec: tuple[int, int, int, int, int, int, int]) -> int:
    return rec[2] << 8 | rec[1]


def _overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def glyph_cell_size(ch: str) -> tuple[int, int]:
    # One size so 66 letters pack into the leftover 10x12 holes.
    return 10, 12


def _occupancy(used: list[tuple[int, int, int, int]]) -> list[list[bool]]:
    grid = [[False] * ATLAS_W for _ in range(ATLAS_H)]
    for x, y, w, h in used:
        for yy in range(max(0, y), min(ATLAS_H, y + h)):
            row = grid[yy]
            for xx in range(max(0, x), min(ATLAS_W, x + w)):
                row[xx] = True
    return grid


def find_cell(grid: list[list[bool]], w: int, h: int) -> tuple[int, int, int]:
    # Stay inside 240x348. Prefer the original 10x12 packing grid.
    for try_h in (h, h - 1 if h > 8 else h):
        if try_h < 8:
            continue
        for step_y, step_x in ((12, 10), (1, 2)):
            for y in range(0, ATLAS_H - try_h + 1, step_y):
                for x in range(0, ATLAS_W - w + 1, step_x):
                    ok = True
                    for yy in range(y, y + try_h):
                        row = grid[yy]
                        if any(row[xx] for xx in range(x, x + w)):
                            ok = False
                            break
                    if not ok:
                        continue
                    for yy in range(y, y + try_h):
                        row = grid[yy]
                        for xx in range(x, x + w):
                            row[xx] = True
                    return x, y, try_h
    raise RuntimeError(f"no free {w}x{h} cell in atlas")


def get_nibble(data: bytearray, x: int, y: int) -> int:
    pos = PIXEL_START + y * ROW_STRIDE + x // 2
    b = data[pos]
    return (b >> 4) if x % 2 == 0 else (b & 0xF)


def set_nibble(data: bytearray, x: int, y: int, v: int) -> None:
    pos = PIXEL_START + y * ROW_STRIDE + x // 2
    b = data[pos]
    if x % 2 == 0:
        b = (b & 0x0F) | ((v & 0xF) << 4)
    else:
        b = (b & 0xF0) | (v & 0xF)
    data[pos] = b


def load_font() -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS:
        if path.exists():
            return ImageFont.truetype(str(path), 11)
    raise SystemExit("no TrueType font with Cyrillic (tahoma/arial)")


def render_glyph(ch: str, w: int, h: int, font: ImageFont.FreeTypeFont) -> Image.Image:
    canvas = Image.new("L", (w + 4, h + 4), 0)
    draw = ImageDraw.Draw(canvas)
    draw.text((1, -1), ch, font=font, fill=255)
    bbox = canvas.getbbox()
    if bbox is None:
        return Image.new("L", (w, h), 0)
    cropped = canvas.crop(bbox)
    out = Image.new("L", (w, h), 0)
    ox = 0
    oy = max(0, h - cropped.height - (0 if ch.isupper() or ch in "Ё" else 1))
    if oy + cropped.height > h:
        oy = 0
    if cropped.width > w or cropped.height > h:
        cropped = cropped.crop((0, 0, min(w, cropped.width), min(h, cropped.height)))
    out.paste(cropped, (ox, oy))
    return out


def clear_cell(atlas: bytearray, x: int, y: int, w: int, h: int) -> None:
    for gy in range(h):
        for gx in range(w):
            set_nibble(atlas, x + gx, y + gy, 1)


def blit_glyph(atlas: bytearray, x: int, y: int, glyph: Image.Image) -> None:
    pix = glyph.load()
    gw, gh = glyph.size
    for gy in range(gh):
        for gx in range(gw):
            lum = pix[gx, gy]
            if lum < 48:
                continue
            # Only nibbles that already appear in retail glyphs (1/2 bg, 6/7/9 ink).
            nibble = 7 if lum >= 160 else 6
            set_nibble(atlas, x + gx, y + gy, nibble)


def snap_atlas_to_dict(atlas: bytearray, dictionary: list[int]) -> int:
    """Replace any new u16 with the closest retail dictionary word."""
    allowed = set(dictionary)
    words = list(dictionary)
    snapped = 0
    for y in range(360):
        row = PIXEL_START + y * ROW_STRIDE
        for off in range(0, ROW_BYTES, 2):
            pos = row + off
            val = atlas[pos] | (atlas[pos + 1] << 8)
            if val in allowed:
                continue
            best = words[0]
            best_d = 99
            a0, a1, a2, a3 = val & 0xF, (val >> 4) & 0xF, (val >> 8) & 0xF, (val >> 12) & 0xF
            for word in words:
                d = (
                    abs((word & 0xF) - a0)
                    + abs(((word >> 4) & 0xF) - a1)
                    + abs(((word >> 8) & 0xF) - a2)
                    + abs(((word >> 12) & 0xF) - a3)
                )
                if d < best_d:
                    best_d = d
                    best = word
                    if d == 0:
                        break
            atlas[pos] = best & 0xFF
            atlas[pos + 1] = (best >> 8) & 0xFF
            snapped += 1
    return snapped


def atlas_preview(atlas: bytes, recs: list[tuple[int, int, int, int, int, int, int]], dest: Path) -> None:
    height = max(ATLAS_H, max((r[4] + r[6] for r in recs), default=ATLAS_H))
    height = min(height, 360)
    img = Image.new("L", (ATLAS_W, height))
    px = img.load()
    buf = bytearray(atlas)
    for y in range(height):
        for x in range(ATLAS_W):
            px[x, y] = get_nibble(buf, x, y) * 17
    rgb = img.convert("RGB")
    draw = ImageDraw.Draw(rgb)
    for rec in recs:
        cp = rec_cp(rec)
        if cp < 0x0400 or cp > 0x0451:
            continue
        x, y, w, h = rec[3], rec[4], rec[5], rec[6]
        draw.rectangle((x, y, x + w - 1, y + h - 1), outline=(255, 64, 64))
    dest.parent.mkdir(parents=True, exist_ok=True)
    rgb.save(dest)
    sheet = Image.new("RGB", (33 * 12, 28), (0, 0, 0))
    buf_img = img.convert("RGB")
    i_up = i_lo = 0
    for rec in recs:
        cp = rec_cp(rec)
        if cp < 0x0400 or cp > 0x0451:
            continue
        x, y, w, h = rec[3], rec[4], rec[5], rec[6]
        g = buf_img.crop((x, y, x + w, y + h))
        if chr(cp).isupper() or cp == 0x0401:
            sheet.paste(g, (i_up * 12, 0))
            i_up += 1
        else:
            sheet.paste(g, (i_lo * 12, 14))
            i_lo += 1
    sheet.resize((sheet.width * 4, sheet.height * 4), Image.NEAREST).save(dest.with_name("cyrillic_glyphs.png"))


def paint_cyrillic(slot00: bytes, slot01: bytes, dictionary: list[int]) -> tuple[bytes, bytes]:
    _, recs = parse_slot00(slot00)
    existing = {rec_cp(r) for r in recs}
    by_cp = {rec_cp(r): r for r in recs}
    grid = _occupancy([(r[3], r[4], r[5], r[6]) for r in recs])
    atlas = bytearray(slot01)
    font = load_font()
    holes: list[tuple[int, int, int, int]] = []
    while True:
        try:
            x, y, h = find_cell(grid, 10, 12)
        except RuntimeError:
            break
        holes.append((x, y, 10, h))
    steal = []
    for cp in STEAL_CPS:
        r = by_cp[cp]
        steal.append((r[3], r[4], r[5], r[6]))
    cells = holes + steal
    need = [cp for cp in CYRILLIC_CPS if cp not in existing]
    if len(cells) < len(need):
        raise RuntimeError(f"only {len(cells)} cells for {len(need)} letters")
    print(f"  cells: {len(holes)} free + {len(steal)} stolen kana")
    added = 0
    for cp, (x, y, w, h) in zip(need, cells):
        ch = chr(cp)
        clear_cell(atlas, x, y, w, h)
        glyph = render_glyph(ch, w, h, font)
        blit_glyph(atlas, x, y, glyph)
        recs.append((2, cp & 0xFF, cp >> 8, x, y, w, h))
        existing.add(cp)
        added += 1
    snapped = snap_atlas_to_dict(atlas, dictionary)
    print(f"  slot00 +{added} real cyrillic UVs, total {len(recs)}, snapped {snapped} u16s to retail dict")
    preview = ROOT / "dumps" / "font_probe" / "atlas_cyrillic.png"
    atlas_preview(bytes(atlas), recs, preview)
    print(f"  preview {preview}")
    return build_slot00(recs), bytes(atlas)


def add_cyrillic_aliases(slot00: bytes) -> bytes:
    """Point Cyrillic letters at Latin cells without growing slot00.

    Appends would inflate fpack past the retail ISO allocation (breaks real PSP
    when the directory size has to change). Instead, reuse rare kana UV rows.
    """
    _, recs = parse_slot00(slot00)
    by_cp = {rec_cp(r): i for i, r in enumerate(recs)}
    need: list[tuple[int, tuple[int, int, int, int, int, int, int]]] = []
    missing_src: list[str] = []
    for cyr, lat in CYR_TO_LATIN.items():
        cp = ord(cyr)
        if cp in by_cp:
            continue
        if ord(lat) not in by_cp:
            missing_src.append(f"{cyr}->{lat}")
            continue
        need.append((cp, recs[by_cp[ord(lat)]]))
    steal_order = [c for c in STEAL_CPS if c in by_cp]
    steal_order += sorted(
        cp for cp in by_cp if 0x3040 <= cp <= 0x30FF and cp not in set(STEAL_CPS)
    )
    if len(steal_order) < len(need):
        raise SystemExit(
            f"slot00: need {len(need)} steal slots, only {len(steal_order)} kana"
        )
    new_recs = list(recs)
    for steal_cp, (new_cp, src) in zip(steal_order, need):
        idx = by_cp[steal_cp]
        new_recs[idx] = (2, new_cp & 0xFF, new_cp >> 8, src[3], src[4], src[5], src[6])
    out = build_slot00(new_recs)
    if len(out) != len(slot00):
        raise SystemExit(f"slot00 size changed {len(slot00)} -> {len(out)}")
    if missing_src:
        print("  missing latin sources:", ", ".join(missing_src))
    print(
        f"  slot00 reused {len(need)} kana rows as cyrillic aliases "
        f"(latin UVs), total {len(new_recs)}"
    )
    return out


def patch_cmap_lookalikes(cmap: bytes) -> bytes:
    n = len(cmap) // 2
    vals = list(struct.unpack(f"<{n}H", cmap))
    patched = 0
    for cyr, lat in CYR_TO_LATIN.items():
        cp = ord(cyr)
        src_id = vals[ord(lat)]
        if src_id == 0:
            continue
        if vals[cp] != src_id:
            vals[cp] = src_id
            patched += 1
    print(f"  cmap lookalike entries written: {patched}")
    return struct.pack(f"<{n}H", *vals)


def patch_fpack(fpack: bytes) -> bytes:
    """Safe title font patch: Cyrillic UV aliases only (no slot 01 rewrite).

    Rewriting slot 01 pixels + method 5 (even with a frozen 129-word dict)
    black-screens on boot. Unique UVs without pixels vanish the menu.
    Lookalike Latin cells at least boot and show text.

    Patches slot00 in-place inside the retail FBE so the file size stays
    exactly retail (required for real-PSP ISO in-place injection). Cmap slot
    03 lookalikes are skipped when recompression would grow the pack.
    """
    entries = parse_fbe(fpack)
    if len(entries) != 9:
        raise SystemExit(f"fpack expected 9 slots, got {len(entries)}")

    off0, size0, blob0 = entries[0]
    info0 = parse_dppk(blob0)
    slot00 = add_cyrillic_aliases(decompress_dppk(blob0))
    new0 = wrap_dppk(
        slot00, method=0, type_ch=info0["type"].encode("ascii"), unk=info0["unk"]
    )
    if len(new0) != size0:
        raise SystemExit(f"fpack slot0 size {size0} -> {len(new0)}")

    out = bytearray(fpack)
    out[off0 : off0 + size0] = new0

    # Optional cmap lookalikes — only if they fit the retail slot.
    off3, size3, blob3 = entries[3]
    info3 = parse_dppk(blob3)
    cmap3 = patch_cmap_lookalikes(decompress_dppk(blob3))
    new3 = wrap_dppk(
        cmap3, method=2, type_ch=info3["type"].encode("ascii"), unk=info3["unk"]
    )
    if len(new3) <= size3:
        out[off3 : off3 + len(new3)] = new3
        if len(new3) < size3:
            out[off3 + len(new3) : off3 + size3] = b"\x00" * (size3 - len(new3))
        print(f"  cmap lookalikes fitted in slot3 ({len(new3)}/{size3})")
    else:
        print(
            f"  cmap lookalikes skipped (would be {len(new3)} > slot3 {size3}); "
            "title uses slot00 aliases"
        )

    if len(out) != len(fpack):
        raise SystemExit(f"fpack size changed {len(fpack)} -> {len(out)}")
    return bytes(out)


def main() -> None:
    src = ROOT / "originals" / "fpack.fbe"
    extracted = ROOT / "iso_extracted" / "PSP_GAME" / "USRDIR" / "data" / "font" / "fpack.fbe"
    if not src.exists():
        src.write_bytes(extracted.read_bytes())
        print("backed up originals/fpack.fbe")
    patched = patch_fpack(src.read_bytes())
    extracted.write_bytes(patched)
    print(f"wrote {extracted} ({len(patched)} bytes, was {src.stat().st_size})")


if __name__ == "__main__":
    main()
