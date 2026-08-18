#!/usr/bin/env python3
"""Decompress DPPK blobs from fpack.fbe (No Heroes Allowed! font pack)."""
from __future__ import annotations

import struct
from pathlib import Path


def rle_u8(data: bytes, uncompressed: int) -> bytes:
    out = bytearray()
    i = 0
    while len(out) < uncompressed:
        if i + 2 > len(data):
            raise ValueError(f"RLE u8 truncated at {i}, have {len(out)}/{uncompressed}")
        value = data[i]
        count = data[i + 1]
        i += 2
        if count == 0:
            raise ValueError(f"RLE u8 count=0 at {i-2}")
        out.extend([value] * count)
    return bytes(out[:uncompressed])


def rle_u16(data: bytes, uncompressed: int) -> bytes:
    out = bytearray()
    i = 0
    while len(out) < uncompressed:
        if i + 4 > len(data):
            raise ValueError(f"RLE u16 truncated at {i}, have {len(out)}/{uncompressed}")
        value, count = struct.unpack_from("<HH", data, i)
        i += 4
        if count == 0:
            raise ValueError(f"RLE u16 count=0 at {i-4}")
        out.extend(struct.pack("<H", value) * count)
    return bytes(out[:uncompressed])


def parse_dppk(data: bytes) -> dict:
    if data[:4] != b"DPPK":
        raise ValueError(f"not DPPK: {data[:4]!r}")
    type_ch = data[4]
    unk = data[5]
    method = struct.unpack_from("<H", data, 6)[0]
    uncomp, comp = struct.unpack_from("<II", data, 8)
    payload = data[16:]
    return {
        "type": chr(type_ch) if 32 <= type_ch < 127 else type_ch,
        "unk": unk,
        "method": method,
        "uncompressed": uncomp,
        "compressed": comp,
        "payload": payload,
        "raw": data,
    }


def decompress_method5(payload: bytes, uncompressed: int) -> bytes:
    """Dictionary + (count*2 << 8 | index) stream. count is in 16-bit units."""
    dict_count = struct.unpack_from("<I", payload, 0)[0]
    dictionary = list(struct.unpack_from(f"<{dict_count}H", payload, 4))
    body = payload[4 + dict_count * 2 :]
    n = len(body) // 2
    cmds = struct.unpack(f"<{n}H", body[: n * 2])
    out = bytearray()
    for cmd in cmds:
        count = (cmd >> 8) // 2
        index = cmd & 0xFF
        if count == 0:
            continue
        out.extend(struct.pack("<H", dictionary[index]) * count)
    if len(out) != uncompressed:
        raise ValueError(f"method 5 size {len(out)} != {uncompressed}")
    return bytes(out)


def compress_method5(data: bytes, dictionary: list[int] | None = None) -> bytes:
    """Inverse of decompress_method5.

    Retail streams start with a dummy command 0 (count=0). Without it the game
    hangs on boot. Dictionary order is preserved when provided so unmodified
    slot 01 round-trips byte-for-byte.
    """
    if len(data) % 2:
        raise ValueError("method 5 needs even length")
    n = len(data) // 2
    vals = struct.unpack(f"<{n}H", data)
    if dictionary is None:
        order: list[int] = []
        index_of: dict[int, int] = {}
        for value in vals:
            if value not in index_of:
                if len(order) >= 256:
                    raise ValueError(f"method 5 dict overflow ({len(set(vals))} unique u16s)")
                index_of[value] = len(order)
                order.append(value)
    else:
        # Frozen retail dictionary. New words here crashed the game (OOB write
        # into a ~129-entry table). Callers must snap pixels first.
        order = list(dictionary)
        index_of = {value: i for i, value in enumerate(order)}
        missing = {v for v in vals if v not in index_of}
        if missing:
            raise ValueError(f"method 5 frozen dict missing {len(missing)} u16s (e.g. {next(iter(missing)):04X})")
    max_run = 60
    cmds = [0]
    i = 0
    while i < n:
        value = vals[i]
        j = i + 1
        while j < n and vals[j] == value and (j - i) < max_run:
            j += 1
        count = j - i
        cmds.append((count * 2) << 8 | index_of[value])
        i = j
    header = struct.pack("<I", len(order)) + struct.pack(f"<{len(order)}H", *order)
    return header + struct.pack(f"<{len(cmds)}H", *cmds)


def decompress_dppk(data: bytes) -> bytes:
    info = parse_dppk(data)
    payload = info["payload"]
    uncomp = info["uncompressed"]
    method = info["method"]
    if method == 0:
        return payload[:uncomp]
    if method == 1:
        return rle_u8(payload, uncomp)
    if method == 2:
        return rle_u16(payload, uncomp)
    if method == 5:
        return decompress_method5(payload, uncomp)
    raise ValueError(f"unsupported DPPK method {method}")


def rle_u16_compress(data: bytes) -> bytes:
    n = len(data) // 2
    vals = struct.unpack(f"<{n}H", data[: n * 2])
    out = bytearray()
    i = 0
    while i < n:
        value = vals[i]
        j = i + 1
        while j < n and vals[j] == value and (j - i) < 65535:
            j += 1
        out += struct.pack("<HH", value, j - i)
        i = j
    return bytes(out)


def wrap_dppk(
    body: bytes,
    *,
    method: int,
    type_ch: bytes | str = b"d",
    unk: int = 0,
    dictionary: list[int] | None = None,
) -> bytes:
    if isinstance(type_ch, str):
        type_ch = type_ch.encode("ascii")
    if method == 0:
        payload = body
    elif method == 2:
        payload = rle_u16_compress(body)
    elif method == 5:
        payload = compress_method5(body, dictionary=dictionary)
    else:
        raise ValueError(f"wrap_dppk: method {method} not implemented")
    header = b"DPPK" + type_ch + bytes([unk]) + struct.pack("<HII", method, len(body), len(payload))
    return header + payload


def method5_dictionary(payload: bytes) -> list[int]:
    count = struct.unpack_from("<I", payload, 0)[0]
    return list(struct.unpack_from(f"<{count}H", payload, 4))


def main() -> None:
    import sys

    src = Path(sys.argv[1])
    dst_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else src.parent / (src.stem + "_dec")
    dst_dir.mkdir(parents=True, exist_ok=True)
    files = [src] if src.is_file() else sorted(src.glob("*.dppk"))
    for f in files:
        blob = f.read_bytes()
        info = parse_dppk(blob)
        print(
            f"{f.name}: type={info['type']!r} method={info['method']} "
            f"uncomp={info['uncompressed']} comp={info['compressed']} payload={len(info['payload'])}"
        )
        try:
            dec = decompress_dppk(blob)
        except Exception as e:
            print(f"  FAIL {e}")
            continue
        out = dst_dir / (f.stem + ".dec")
        out.write_bytes(dec)
        mag = dec[:16]
        print(f"  -> {out.name} {len(dec)} magic={mag!r}")


if __name__ == "__main__":
    main()
