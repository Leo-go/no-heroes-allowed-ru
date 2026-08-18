#!/usr/bin/env python3
"""Extract FBE10 packs used by No Heroes Allowed!"""
from __future__ import annotations

import struct
from pathlib import Path


def parse_fbe(data: bytes) -> list[tuple[int, int, bytes]]:
    if data[:3] != b"FBE":
        raise ValueError(f"not FBE: {data[:8]!r}")
    filesize, unk, count = struct.unpack_from("<III", data, 4)
    entries = []
    for i in range(count):
        off, size = struct.unpack_from("<II", data, 16 + i * 8)
        entries.append((off, size, data[off : off + size]))
    return entries


def guess_ext(blob: bytes) -> str:
    mag = blob[:8]
    if mag[:4] in (b"PGF\x00", b"PGF0"):
        return "pgf"
    if mag[:3] == b"PGF":
        return "pgf"
    if mag[:4] == b"MYU0":
        return "tbin"
    if mag[:4] == b"DPPK":
        return "dppk"
    if mag[:4] == b"FBE\x10":
        return "fbe"
    if mag[:4] == b"TIM2":
        return "tm2"
    if mag[:3] == b"GMO":
        return "gmo"
    if mag[:4] == b"\x7fELF":
        return "prx"
    return "bin"


def build_fbe(blobs: list[bytes], unk: int = 4, align: int = 2) -> bytes:
    """Rebuild FBE10. fpack uses 2-byte file alignment; filelist inner packs use 4."""
    count = len(blobs)
    toc_size = 16 + count * 8
    offset = toc_size
    entries: list[tuple[int, int]] = []
    payload = bytearray()
    for blob in blobs:
        while offset % align:
            payload.append(0)
            offset += 1
        entries.append((offset, len(blob)))
        payload.extend(blob)
        offset += len(blob)
    while (toc_size + len(payload)) % align:
        payload.append(0)
    filesize = toc_size + len(payload)
    header = b"FBE\x10" + struct.pack("<III", filesize, unk, count)
    toc = b"".join(struct.pack("<II", off, size) for off, size in entries)
    out = header + toc + bytes(payload)
    if len(out) != filesize:
        raise ValueError(f"FBE size mismatch {len(out)} != {filesize}")
    return out


def extract_fbe(path: Path, out_dir: Path) -> None:
    data = path.read_bytes()
    entries = parse_fbe(data)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"{path.name}: {len(entries)} files, size={len(data)}")
    for i, (off, size, blob) in enumerate(entries):
        ext = guess_ext(blob)
        dest = out_dir / f"{i:02d}_{off:06X}.{ext}"
        dest.write_bytes(blob)
        mag = blob[:16]
        print(f"  [{i:02d}] {dest.name:28} {size:7} magic={mag!r}")


if __name__ == "__main__":
    import sys

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(src.stem + "_extracted")
    extract_fbe(src, dst)
