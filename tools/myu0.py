#!/usr/bin/env python3
"""Dump / rebuild MYU0 .tbin tables (No Heroes Allowed!)."""
from __future__ import annotations

import argparse
import struct
from pathlib import Path


def parse_myu0(data: bytes) -> dict:
    if data[:4] != b"MYU0":
        raise ValueError("not MYU0")
    header_size, row_count, field3 = struct.unpack_from("<III", data, 4)
    if header_size != 16:
        raise ValueError(f"unexpected header_size {header_size}")
    first_ptr = struct.unpack_from("<I", data, header_size)[0]
    n_ptrs = first_ptr // 4
    if n_ptrs * 4 != first_ptr or row_count == 0 or n_ptrs % row_count:
        raise ValueError(
            f"bad pointer table: first_ptr={first_ptr} rows={row_count} n_ptrs={n_ptrs}"
        )
    cols = n_ptrs // row_count
    ptrs = list(struct.unpack_from(f"<{n_ptrs}I", data, header_size))
    cells = []
    for off in ptrs:
        abs_off = header_size + off
        end = data.find(b"\x00", abs_off)
        if end < 0:
            raise ValueError(f"unterminated string at {abs_off}")
        raw = data[abs_off:end]
        cells.append(raw)
    return {
        "header_size": header_size,
        "row_count": row_count,
        "field3": field3,
        "cols": cols,
        "cells": cells,
        "raw": data,
    }


def decode_cell(raw: bytes) -> tuple[str, str]:
    for enc in ("ascii", "cp1251", "utf-8", "shift_jis", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1"


def dump_tbin(path: Path, out_path: Path) -> dict:
    info = parse_myu0(path.read_bytes())
    lines = [
        f"# MYU0 {path.name}",
        f"# rows={info['row_count']} cols={info['cols']} field3=0x{info['field3']:X}",
        "# row\tcol\tenc\ttext",
    ]
    cols = info["cols"]
    for i, raw in enumerate(info["cells"]):
        text, enc = decode_cell(raw)
        safe = (
            text.replace("\\", "\\\\")
            .replace("\r", "\\r")
            .replace("\n", "\\n")
            .replace("\t", "\\t")
        )
        lines.append(f"{i // cols}\t{i % cols}\t{enc}\t{safe}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return info


def unescape(text: str) -> str:
    return (
        text.replace("\\t", "\t")
        .replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\\\\", "\\")
    )


def build_tbin(rows: list[list[bytes]], field3: int) -> bytes:
    if not rows:
        raise ValueError("no rows")
    cols = len(rows[0])
    if any(len(r) != cols for r in rows):
        raise ValueError("ragged rows")
    cells = [cell for row in rows for cell in row]
    header_size = 16
    n_ptrs = len(cells)
    # pointers are relative to start of pointer table (offset 0x10)
    ptrs = []
    blob = bytearray()
    for cell in cells:
        ptrs.append(n_ptrs * 4 + len(blob))
        blob.extend(cell)
        blob.append(0)
    out = bytearray()
    out += b"MYU0"
    out += struct.pack("<III", header_size, len(rows), field3)
    out += struct.pack(f"<{n_ptrs}I", *ptrs)
    out += blob
    return bytes(out)


def load_dump(path: Path) -> tuple[int, list[list[bytes]], str]:
    rows: dict[int, dict[int, bytes]] = {}
    field3 = 0
    max_col = 0
    encoding = "utf-8"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# rows="):
            # "# rows=13 cols=2 field3=0x1F"
            for part in line.split():
                if part.startswith("field3="):
                    field3 = int(part.split("=", 1)[1], 0)
        if not line or line.startswith("#"):
            continue
        row_s, col_s, enc, text = line.split("\t", 3)
        row, col = int(row_s), int(col_s)
        max_col = max(max_col, col)
        raw = unescape(text).encode(enc if enc != "ascii" else "ascii")
        rows.setdefault(row, {})[col] = raw
        encoding = enc
    n_rows = max(rows) + 1
    n_cols = max_col + 1
    table = []
    for r in range(n_rows):
        table.append([rows.get(r, {}).get(c, b"") for c in range(n_cols)])
    return field3, table, encoding


def roundtrip_ok(path: Path) -> bool:
    original = path.read_bytes()
    info = parse_myu0(original)
    cols = info["cols"]
    cells = info["cells"]
    table = [cells[i : i + cols] for i in range(0, len(cells), cols)]
    rebuilt = build_tbin(table, info["field3"])
    return rebuilt == original


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("src")
    d.add_argument("dst")
    b = sub.add_parser("build")
    b.add_argument("src")
    b.add_argument("dst")
    b.add_argument("--encoding", default=None, help="override cell encoding")
    r = sub.add_parser("roundtrip")
    r.add_argument("src")
    args = ap.parse_args()
    if args.cmd == "dump":
        info = dump_tbin(Path(args.src), Path(args.dst))
        print(f"dumped {args.src} rows={info['row_count']} cols={info['cols']}")
    elif args.cmd == "build":
        field3, table, enc = load_dump(Path(args.src))
        if args.encoding:
            # re-encode from the dump file as unicode then to requested encoding
            text_table = []
            for row in table:
                text_table.append(
                    [cell.decode(enc) if enc != "ascii" else cell.decode("ascii") for cell in row]
                )
            table = [[t.encode(args.encoding) for t in row] for row in text_table]
        Path(args.dst).write_bytes(build_tbin(table, field3))
        print(f"wrote {args.dst}")
    elif args.cmd == "roundtrip":
        src = Path(args.src)
        files = [src] if src.is_file() else list(src.rglob("*.tbin"))
        bad = 0
        for f in files:
            ok = roundtrip_ok(f)
            print(("OK " if ok else "FAIL"), f)
            bad += not ok
        if bad:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
