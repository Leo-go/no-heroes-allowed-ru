#!/usr/bin/env python3
"""One-shot format probe for No Heroes Allowed! text + font files."""
from __future__ import annotations

import struct
from pathlib import Path

ROOT = Path(r"B:\psp games\No Heroes Allowed RUS\iso_extracted")
OUT = Path(r"B:\psp games\No Heroes Allowed RUS\dumps")
OUT.mkdir(parents=True, exist_ok=True)


def hexdump(data: bytes, n: int = 256) -> str:
    lines = []
    for i in range(0, min(len(data), n), 16):
        chunk = data[i : i + 16]
        hx = " ".join(f"{b:02X}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{i:04X}  {hx:<48} {asc}")
    return "\n".join(lines)


def parse_myu0(data: bytes) -> dict:
    if data[:4] != b"MYU0":
        raise ValueError("not MYU0")
    header_size, row_count, field3 = struct.unpack_from("<III", data, 4)
    first_ptr = struct.unpack_from("<I", data, header_size)[0]
    n_ptrs = first_ptr // 4
    if n_ptrs == 0 or n_ptrs * 4 != first_ptr or row_count == 0 or n_ptrs % row_count:
        cols = None
    else:
        cols = n_ptrs // row_count
    ptrs = list(struct.unpack_from(f"<{n_ptrs}I", data, header_size))
    strings = []
    for i, off in enumerate(ptrs):
        abs_off = header_size + off
        end = data.find(b"\x00", abs_off)
        if end < 0:
            raw = data[abs_off:]
        else:
            raw = data[abs_off:end]
        try:
            text = raw.decode("ascii")
            enc = "ascii"
        except UnicodeDecodeError:
            try:
                text = raw.decode("shift_jis")
                enc = "shift_jis"
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
                enc = "latin-1"
        strings.append((i, abs_off, enc, text))
    return {
        "header_size": header_size,
        "row_count": row_count,
        "field3": field3,
        "n_ptrs": n_ptrs,
        "cols": cols,
        "ptrs": ptrs,
        "strings": strings,
        "size": len(data),
    }


def dump_tbin(path: Path, out_txt: Path) -> None:
    info = parse_myu0(path.read_bytes())
    lines = [
        f"# file: {path.name}",
        f"# size={info['size']} header={info['header_size']} rows={info['row_count']} "
        f"field3=0x{info['field3']:X} ptrs={info['n_ptrs']} cols={info['cols']}",
        "# idx\tptr\tenc\ttext",
    ]
    for i, abs_off, enc, text in info["strings"]:
        safe = text.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")
        lines.append(f"{i}\t{abs_off:04X}\t{enc}\t{safe}")
    out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"tbin {path.name:28} rows={info['row_count']:4} cols={info['cols']} "
        f"field3=0x{info['field3']:02X} strings={len(info['strings'])}"
    )


def parse_gametext(data: bytes) -> None:
    # Probe header
    print("\n=== GameText.bin header ===")
    print(hexdump(data, 64))
    u0, u1 = struct.unpack_from("<II", data, 0)
    print(f"u32[0]={u0} (0x{u0:X})  u32[1]={u1} (0x{u1:X})")

    # Find UTF-16LE strings
    needle = "New Game".encode("utf-16le")
    idx = data.find(needle)
    print(f"'New Game' utf-16le at {idx} (0x{idx:X})" if idx >= 0 else "New Game NOT FOUND as utf-16le")
    for enc_name, enc in [
        ("utf-16le", "utf-16le"),
        ("ascii", "ascii"),
        ("utf-8", "utf-8"),
    ]:
        n = "New Game".encode(enc)
        i = data.find(n)
        print(f"  {enc_name}: {i}")

    # Dump utf-16le cstrings from a guessed string region
    # Many tables: count, then pointer table, then UTF-16 strings.
    count = u0
    # try: pointers start at offset 8, count pointers
    print("\nTrying pointer table at +8, count=u32[0]:")
    if 8 + count * 4 < len(data):
        ptrs = list(struct.unpack_from(f"<{min(count, 20)}I", data, 8))
        print(" first 20 ptrs:", [f"{p:04X}" for p in ptrs])
        for p in ptrs[:8]:
            if 0 <= p < len(data) - 2:
                chunk = data[p : p + 64]
                # utf-16le until 0000
                end = 0
                while end + 2 <= len(chunk) and chunk[end : end + 2] != b"\x00\x00":
                    end += 2
                try:
                    s = chunk[:end].decode("utf-16le")
                except Exception:
                    s = repr(chunk[:32])
                print(f"  -> 0x{p:04X}: {s!r}")

    print("\nTrying u32[1] as pointer-table start, u32[0] as count:")
    off = u1
    if off + 4 < len(data):
        ptrs = list(struct.unpack_from(f"<{min(count, 12)}I", data, off))
        print(" first ptrs:", [f"{p:04X}" for p in ptrs])

    # brute: scan utf-16le readable strings
    strings = []
    i = 0
    while i + 4 < len(data):
        if data[i : i + 2] == b"\x00\x00":
            i += 2
            continue
        # must start with ASCII-range utf16
        if data[i + 1] != 0 or not (32 <= data[i] < 127):
            i += 2 if i % 2 == 0 else 1
            continue
        j = i
        chars = []
        ok = True
        while j + 2 <= len(data):
            lo, hi = data[j], data[j + 1]
            if lo == 0 and hi == 0:
                break
            if hi != 0:
                ok = False
                break
            if lo < 32 and lo not in (9, 10, 13):
                ok = False
                break
            chars.append(chr(lo))
            j += 2
        if ok and len(chars) >= 3:
            strings.append((i, "".join(chars)))
            i = j + 2
        else:
            i += 2
    print(f"\nUTF-16LE ascii-range strings found: {len(strings)}")
    out = OUT / "GameText_strings_probe.txt"
    out.write_text("\n".join(f"{off:04X}\t{s}" for off, s in strings), encoding="utf-8")
    for off, s in strings[:40]:
        print(f"  {off:04X}  {s}")


def parse_fbe(path: Path, extract_dir: Path) -> list[tuple[int, int, bytes]]:
    data = path.read_bytes()
    magic = data[:4]
    print(f"\n=== FBE {path.name} magic={magic!r} size={len(data)} ===")
    print(hexdump(data, 96))
    if magic[:3] != b"FBE":
        print(" not FBE")
        return []
    filesize, unk, count = struct.unpack_from("<III", data, 4)
    toc0 = struct.unpack_from("<I", data, 16)[0]
    print(f"filesize={filesize} unk={unk} count={count} first_off={toc0:X}")
    entries = []
    # pairs (offset, size) starting at 16
    for i in range(count):
        off, size = struct.unpack_from("<II", data, 16 + i * 8)
        blob = data[off : off + size]
        entries.append((off, size, blob))
        mag = blob[:8]
        print(f"  [{i}] off=0x{off:06X} size={size:6} magic={mag!r}")
    extract_dir.mkdir(parents=True, exist_ok=True)
    for i, (off, size, blob) in enumerate(entries):
        ext = "bin"
        if blob[:4] == b"PGF\x00" or blob[:3] == b"PGF":
            ext = "pgf"
        elif blob[:4] == b"MYU0":
            ext = "tbin"
        elif blob[:4] == b"DPPK":
            ext = "dppk"
        elif blob[:4] == b"TIM2":
            ext = "tm2"
        elif blob[:3] == b"GMO":
            ext = "gmo"
        (extract_dir / f"{i:02d}_{off:06X}.{ext}").write_bytes(blob)
    return entries


def parse_blockfont(path: Path) -> None:
    data = path.read_bytes()
    print(f"\n=== BlockFont.bin size={len(data)} ===")
    print(hexdump(data, 80))
    # UTF-16LE char list until something else
    chars = []
    i = 0
    while i + 2 <= min(len(data), 200):
        cp = struct.unpack_from("<H", data, i)[0]
        if cp == 0:
            break
        chars.append(cp)
        i += 2
        if len(chars) > 80:
            break
    print("first codepoints:", " ".join(f"U+{c:04X}({chr(c) if c >= 32 else '?'})" for c in chars[:40]))
    print("n chars guessed from leading utf16:", len(chars), "stop at", i)


def main() -> None:
    usr = ROOT / "PSP_GAME" / "USRDIR" / "data"
    print("=== MYU0 EN/JP tbins ===")
    for p in sorted(usr.rglob("*.tbin")):
        dump_tbin(p, OUT / f"{p.stem}.txt")

    parse_gametext((usr / "text" / "GameText.bin").read_bytes())
    parse_blockfont(usr / "font" / "BlockFont.bin")
    parse_fbe(usr / "font" / "fpack.fbe", OUT / "fpack_extracted")
    parse_fbe(usr / "csvtables" / "MainichiText_EN.fbe", OUT / "MainichiText_EN_extracted")
    parse_fbe(usr / "text" / "filelist.fbe", OUT / "filelist_extracted")
    parse_fbe(usr / "graph" / "SkillName.fbe", OUT / "SkillName_extracted")

    ency = usr / "zukan" / "Ency.pack"
    print(f"\n=== Ency.pack size={ency.stat().st_size} ===")
    blob = ency.read_bytes()[:128]
    print(hexdump(blob, 128))
    print("MYU0 in Ency:", blob.find(b"MYU0"), "FBE:", blob.find(b"FBE"), "PGF:", blob.find(b"PGF"))
    whole = ency.read_bytes()
    print("MYU0 count", whole.count(b"MYU0"), "FBE count", whole.count(b"FBE\x10"))


if __name__ == "__main__":
    main()
