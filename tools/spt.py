"""Parse / rebuild .SPT dialogue scripts (filelist.fbe inner blobs)."""
from __future__ import annotations

import struct


def parse_spt(data: bytes) -> dict:
    if data[:4] != b".SPT":
        raise ValueError(f"not .SPT: {data[:4]!r}")
    pool = struct.unpack_from("<I", data, 4)[0]
    if pool < 8 or pool > len(data):
        raise ValueError(f"bad string pool {pool}")
    strings: list[tuple[int, str]] = []
    off = pool
    while off < len(data):
        if data[off] == 0:
            off += 1
            continue
        end = data.find(0, off)
        if end < 0:
            raise ValueError(f"unterminated SPT string at {off}")
        strings.append((off, data[off:end].decode("utf-8")))
        off = end + 1
    refs: dict[int, int] = {}
    for pos in range(0, pool - 1, 2):
        val = struct.unpack_from("<H", data, pos)[0]
        if any(val == s_off for s_off, _ in strings):
            if val in refs:
                raise ValueError(f"duplicate ptr to {val:#x} at {pos} and {refs[val]}")
            refs[val] = pos
    missing = [s_off for s_off, _ in strings if s_off not in refs]
    if missing:
        raise ValueError(f"SPT strings without ptrs: {missing}")
    return {
        "pool": pool,
        "cmds": data[:pool],
        "strings": strings,
        "refs": refs,
        "raw": data,
    }


def rebuild_spt(original: bytes, new_texts: list[str]) -> bytes:
    info = parse_spt(original)
    if len(new_texts) != len(info["strings"]):
        raise ValueError(f"string count {len(new_texts)} != {len(info['strings'])}")
    pool = info["pool"]
    first = info["strings"][0][0] if info["strings"] else pool
    out = bytearray(original[:pool])
    out.extend(b"\x00" * (first - pool))
    for (old_off, _old), text in zip(info["strings"], new_texts, strict=True):
        new_off = len(out)
        if new_off > 0xFFFF:
            raise ValueError("SPT grew past 16-bit pointer")
        struct.pack_into("<H", out, info["refs"][old_off], new_off)
        raw = text.encode("utf-8")
        if 0 in raw:
            raise ValueError("NUL in SPT string")
        out.extend(raw)
        out.append(0)
    return bytes(out)


def patch_spt(data: bytes, mapping: dict[str, str]) -> tuple[bytes, int]:
    info = parse_spt(data)
    n = 0
    texts = []
    for _off, old in info["strings"]:
        new = mapping.get(old, old)
        if new != old:
            n += 1
        texts.append(new)
    if n == 0:
        return data, 0
    return rebuild_spt(data, texts), n
