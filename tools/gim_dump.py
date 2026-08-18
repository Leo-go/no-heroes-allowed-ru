#!/usr/bin/env python3
"""Minimal PSP GIM (MIG.00.1PSP) → PNG dumper."""
from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image


def _u16(data: bytes, pos: int) -> int:
    return struct.unpack_from("<H", data, pos)[0]


def _u32(data: bytes, pos: int) -> int:
    return struct.unpack_from("<I", data, pos)[0]


def overscan(value: int, tile: int) -> int:
    if tile <= 0 or value % tile == 0:
        return value
    return value + (tile - value % tile)


def unswizzle(pixels: list[list[int]], w: int, h: int, tile_w: int, tile_h: int) -> list[list[int]]:
    ow, oh = overscan(w, tile_w), overscan(h, tile_h)
    out = [[0] * w for _ in range(h)]
    tile_origin_x = 0
    tile_origin_y = 0
    tile_pos = 0
    for y in range(oh):
        row = pixels[y] if y < len(pixels) else [0] * ow
        for x in range(ow):
            dx = tile_origin_x + (tile_pos % tile_w)
            dy = tile_origin_y + (tile_pos // tile_w)
            if dx < w and dy < h and x < len(row):
                out[dy][dx] = row[x]
            tile_pos += 1
            if tile_pos == tile_w * tile_h:
                tile_pos = 0
                tile_origin_x += tile_w
                if tile_origin_x >= ow:
                    tile_origin_x = 0
                    tile_origin_y += tile_h
    return out


def take_pixel(data: bytes, pos: int, partial: tuple[int, int], bpp: int) -> tuple[int, int, tuple[int, int]]:
    nbytes = (bpp + 7) // 8
    last_bits = bpp % 8
    if pos + nbytes > len(data):
        return 0, pos, partial
    pixel = int.from_bytes(data[pos : pos + nbytes], "little")
    pos += nbytes
    if last_bits > 0:
        bits_in_partial, _ = partial
        if bits_in_partial == 0:
            bits_in_partial = 8
        pixel >>= bits_in_partial - last_bits
        pixel &= 0xFF >> last_bits
        leftover = bits_in_partial - last_bits
        partial = (leftover, 0)
        if leftover > 0:
            pos -= 1
    return pixel, pos, partial


def rgba_from_format(fmt: int, px: int) -> tuple[int, int, int, int]:
    if fmt == 3:  # RGBA8888
        r = px & 0xFF
        g = (px >> 8) & 0xFF
        b = (px >> 16) & 0xFF
        a = (px >> 24) & 0xFF
        return r, g, b, a
    if fmt == 1:  # RGBA5551
        r = (px & 0x1F) * 8
        g = ((px >> 5) & 0x1F) * 8
        b = ((px >> 10) & 0x1F) * 8
        a = 255 if (px >> 15) else 0
        return r, g, b, a
    if fmt == 2:  # RGBA4444
        r = (px & 0xF) * 17
        g = ((px >> 4) & 0xF) * 17
        b = ((px >> 8) & 0xF) * 17
        a = ((px >> 12) & 0xF) * 17
        return r, g, b, a
    if fmt == 0:  # RGBA5650
        r = (px & 0x1F) * 8
        g = ((px >> 5) & 0x3F) * 4
        b = ((px >> 11) & 0x1F) * 8
        return r, g, b, 255
    return px & 0xFF, (px >> 8) & 0xFF, (px >> 16) & 0xFF, 255


def decode_gim(data: bytes) -> tuple[Image.Image, dict]:
    if not data.startswith(b"MIG.00.1PSP") and not data.startswith(b"GIM.00.1PSP"):
        raise ValueError(f"not GIM: {data[:16]!r}")
    pos = 16
    info: dict = {}
    image_pixels = None
    image_fmt = None
    palette = None
    pal_fmt = None
    width = height = 0
    while pos + 16 <= len(data):
        block_start = pos
        btype = _u16(data, pos)
        bsize = _u32(data, pos + 4)
        next_off = _u32(data, pos + 8)
        data_off = _u32(data, pos + 12)
        content = block_start + data_off
        if btype in (4, 5):
            structsz = _u16(data, content)
            fmt = _u16(data, content + 4)
            order = _u16(data, content + 6)
            w = _u16(data, content + 8)
            h = _u16(data, content + 10)
            bpp = _u16(data, content + 12)
            pitch_align = _u16(data, content + 14)
            idx_off = _u32(data, content + 24)
            frame_start = _u32(data, content + 28)
            frame_end = _u32(data, content + 32)
            info[btype] = {
                "fmt": fmt,
                "order": order,
                "w": w,
                "h": h,
                "bpp": bpp,
                "pitch": pitch_align,
            }
            frame = data[content + frame_start : content + frame_end]
            tile_w = max(1, 0x80 // max(bpp, 1))
            tile_h = 8
            rw, rh = w, h
            if order == 1:
                rw, rh = overscan(w, tile_w), overscan(h, tile_h)
            pixels: list[list[int]] = []
            fpos = 0
            partial = (0, 0)
            for y in range(rh):
                row = []
                for x in range(rw):
                    px, fpos, partial = take_pixel(frame, fpos, partial, bpp)
                    row.append(px)
                pixels.append(row)
                if pitch_align and fpos % pitch_align:
                    fpos += pitch_align - (fpos % pitch_align)
            if order == 1:
                pixels = unswizzle(pixels, w, h, tile_w, tile_h)
            if btype == 4:
                image_pixels, image_fmt, width, height = pixels, fmt, w, h
            else:
                palette, pal_fmt = pixels, fmt
        if next_off == 0 or bsize < 16:
            break
        pos = block_start + next_off
        if pos <= block_start:
            break

    if image_pixels is None:
        raise ValueError("no image block")
    if palette is not None:
        pal_row = palette[0]
        rgba = []
        for y in range(height):
            for x in range(width):
                idx = image_pixels[y][x]
                if idx < len(pal_row):
                    rgba.append(rgba_from_format(pal_fmt, pal_row[idx]))
                else:
                    rgba.append((0, 0, 0, 0))
    else:
        rgba = [
            rgba_from_format(image_fmt, image_pixels[y][x])
            for y in range(height)
            for x in range(width)
        ]
    im = Image.new("RGBA", (width, height))
    im.putdata(rgba)
    info["size"] = (width, height)
    info["image_fmt"] = image_fmt
    return im, info


def main() -> None:
    import sys

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".png")
    im, info = decode_gim(src.read_bytes())
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst)
    print(src.name, info["size"], "fmt", info.get("image_fmt"), "->", dst)


if __name__ == "__main__":
    main()
