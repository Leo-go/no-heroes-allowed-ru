#!/usr/bin/env python3
"""Build stage-1 Russian files (UTF-8 tbin + padded UTF-16 GameText) and patch an ISO copy."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from paths import EXTRACT, ORIGINALS, RELEASE_ISO, ROOT, require_orig_iso  # noqa: E402

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from fbe import build_fbe, parse_fbe  # noqa: E402
from myu0 import build_tbin, decode_cell, parse_myu0  # noqa: E402
from patch_font import patch_fpack  # noqa: E402
from spt import patch_spt  # noqa: E402
from translit import FIT, gametext_display, to_latin  # noqa: E402
from translation.dialogs import DIALOG  # noqa: E402
from translation.ui import DGN, GAMETEXT, LOADING, PICKS, STAGES, SYS  # noqa: E402

ORIG_ISO = require_orig_iso()
OUT_ISO = RELEASE_ISO
SECTOR = 2048


def write_dump(path: Path, name: str, field3: int, rows: list[list[str]]) -> None:
    cols = len(rows[0])
    lines = [
        f"# MYU0 {name} RUS utf-8",
        f"# rows={len(rows)} cols={cols} field3=0x{field3:X}",
        "# row\tcol\tenc\ttext",
    ]
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            safe = (
                text.replace("\\", "\\\\")
                .replace("\r", "\\r")
                .replace("\n", "\\n")
                .replace("\t", "\\t")
            )
            lines.append(f"{r}\t{c}\tutf-8\t{safe}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fit_cell_bytes(raw: bytes, text: str) -> bytes:
    """Encode text as UTF-8, never longer than the original cell payload."""
    encoded = text.encode("utf-8")
    if len(encoded) <= len(raw):
        return encoded
    return encoded[: len(raw)].rstrip()


def build_named(src_rel: str, rows: list[list[str]], dump_name: str) -> tuple[Path, bytes, bytes]:
    src = EXTRACT / src_rel
    original = backup(src, Path(src_rel).name, rel=src_rel).read_bytes()
    info = parse_myu0(original)
    if len(rows) != info["row_count"]:
        raise SystemExit(f"{src.name}: rows {len(rows)} != {info['row_count']}")
    if any(len(r) != info["cols"] for r in rows):
        raise SystemExit(f"{src.name}: col mismatch")
    # Keep each cell within the original byte budget so the tbin fits in-place.
    flat_raw = info["cells"]
    table: list[list[bytes]] = []
    i = 0
    for row in rows:
        out_row: list[bytes] = []
        for cell in row:
            out_row.append(fit_cell_bytes(flat_raw[i], bitmap_ru(cell)))
            i += 1
        table.append(out_row)
    rebuilt = build_tbin(table, info["field3"])
    if len(rebuilt) > len(original):
        raise SystemExit(
            f"{src.name}: rebuilt {len(rebuilt)} > original {len(original)} after cell fit"
        )
    if len(rebuilt) < len(original):
        rebuilt = rebuilt + b"\x00" * (len(original) - len(rebuilt))
    write_dump(ROOT / "translation" / "built" / dump_name, src.name, info["field3"], rows)
    return src, original, rebuilt


def fit_ru(en: str, ru: str) -> str:
    if len(ru) <= len(en):
        return ru
    cut = ru[: len(en)].rstrip()
    print(f"  TRIM {len(ru)}>{len(en)} {en!r} -> {cut!r}")
    return cut


def patch_gametext(original: bytes) -> bytes:
    data = bytearray(original)
    missing = []
    applied = 0
    items = sorted(GAMETEXT.items(), key=lambda kv: len(kv[0]), reverse=True)
    latin = 0
    kept = 0
    for en, ru in items:
        shown = gametext_display(en, ru)
        if shown != ru:
            latin += 1
        else:
            kept += 1
        ru = fit_ru(en, shown)
        old = en.encode("utf-16le")
        new = ru.encode("utf-16le")
        if len(new) > len(old):
            new = new[: len(old)]
        count = data.count(old)
        if count == 0:
            missing.append(en)
            continue
        padded = new + b"\x00" * (len(old) - len(new))
        data = data.replace(old, padded)
        applied += count
    if missing:
        print("MISSING in GameText (left English):")
        for en in missing:
            print(f"  {en!r}")
    print(f"GameText replacements applied: {applied} (latin menu {latin}, cyrillic dialogs {kept})")
    if len(data) != len(original):
        raise SystemExit(f"GameText size changed {len(original)} -> {len(data)}")
    return bytes(data)


def load_tsv(path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not path.exists():
        return mapping
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "\t" not in line:
            continue
        en, ru = line.split("\t", 1)
        mapping[en.replace("\\n", "\n")] = ru.replace("\\n", "\n")
    return mapping


def load_spt_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    mapping.update(load_tsv(ROOT / "translation" / "spt_ru.tsv"))
    mapping.update(load_tsv(ROOT / "translation" / "script_ru.tsv"))
    mapping.update(DIALOG)
    return mapping


def bitmap_ru(text: str) -> str:
    """Russian meaning, Latin letters — the title/dialogue atlas has no А–Я pixels."""
    return to_latin(text)


def patch_spt_pack(inner_blob: bytes, mapping: dict[str, str]) -> tuple[bytes, int, int]:
    inner = parse_fbe(inner_blob)
    blobs = [blob for _off, _size, blob in inner]
    n_str = n_spt = 0
    for i, blob in enumerate(blobs):
        if blob[:4] != b".SPT":
            continue
        new, n = patch_spt(blob, mapping)
        if n:
            blobs[i] = new
            n_str += n
            n_spt += 1
    return build_fbe(blobs, unk=4, align=4), n_str, n_spt


def pad_fbe(blob: bytes, target: int) -> bytes:
    """Keep FBE header filesize in sync with the retail ISO allocation."""
    if len(blob) > target:
        raise SystemExit(f"FBE {len(blob)} > retail slot {target}")
    if len(blob) == target:
        return blob
    out = bytearray(blob + b"\x00" * (target - len(blob)))
    struct.pack_into("<I", out, 4, target)
    return bytes(out)


def patch_filelist(original: bytes) -> bytes:
    mapping = {en: bitmap_ru(ru) for en, ru in load_spt_map().items()}
    outer = parse_fbe(original)
    new_inner0, n_str, n_spt = patch_spt_pack(outer[0][2], mapping)
    print(f"filelist.fbe  patched {n_str} strings in {n_spt} scripts")

    quests: dict[int, str] = {}
    qpath = ROOT / "translation" / "quests_ru.tsv"
    if qpath.exists():
        for line in qpath.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#") or "\t" not in line:
                continue
            idx_s, text = line.split("\t", 1)
            quests[int(idx_s)] = text.replace("\\n", "\n")
    inner1 = parse_fbe(outer[1][2])
    blobs1 = []
    nq = 0
    for i, (_off, _size, blob) in enumerate(inner1):
        if i not in quests:
            blobs1.append(blob)
            continue
        nl = "\r\n" if blob.count(b"\r\n") else "\n"
        new = quests[i].replace("\r\n", "\n").replace("\n", nl).encode("utf-8")
        if new != blob:
            nq += 1
        blobs1.append(new)
    print(f"filelist.fbe  patched {nq} quest blobs")
    new_inner1 = build_fbe(blobs1, unk=4, align=4)
    rebuilt = build_fbe([new_inner0, new_inner1], unk=4, align=4)
    return pad_fbe(rebuilt, len(original))


def patch_script(original: bytes) -> bytes:
    mapping = {en: bitmap_ru(ru) for en, ru in load_spt_map().items()}
    outer = parse_fbe(original)
    new_inner, n_str, n_spt = patch_spt_pack(outer[0][2], mapping)
    print(f"script.fbe    patched {n_str} strings in {n_spt} scripts")
    return pad_fbe(build_fbe([new_inner], unk=4, align=4), len(original))


def patch_tbin_map(original: bytes, mapping: dict[str, str]) -> tuple[bytes, int]:
    info = parse_myu0(original)
    cols = info["cols"]
    n = 0
    cells: list[bytes] = []
    for raw in info["cells"]:
        text, _enc = decode_cell(raw)
        ru = mapping.get(text)
        if ru is not None:
            text = bitmap_ru(ru)
            n += 1
            cells.append(fit_cell_bytes(raw, text))
        else:
            cells.append(raw)
    table = [cells[i : i + cols] for i in range(0, len(cells), cols)]
    rebuilt = build_tbin(table, info["field3"])
    if len(rebuilt) > len(original):
        raise SystemExit(
            f"tbin grew {len(original)} -> {len(rebuilt)} after per-cell fit"
        )
    if len(rebuilt) < len(original):
        rebuilt = rebuilt + b"\x00" * (len(original) - len(rebuilt))
    return rebuilt, n


def patch_mainichi(original: bytes) -> bytes:
    mapping = {en: ru for en, ru in load_tsv(ROOT / "translation" / "mainichi_ru.tsv").items()}
    outer = parse_fbe(original)
    blobs = []
    total = 0
    for _off, _size, blob in outer:
        new, n = patch_tbin_map(blob, mapping)
        total += n
        blobs.append(new)
    print(f"MainichiText  patched {total} strings")
    rebuilt = build_fbe(blobs, unk=4, align=4)
    return pad_fbe(rebuilt, len(original))


def load_retail_file(rel: str) -> bytes:
    """Read a file from the untouched kohryu ISO (source of truth for originals/)."""
    import io

    from pycdlib import PyCdlib

    iso_path = "/" + rel.replace("\\", "/").lstrip("/")
    cd = PyCdlib()
    cd.open(str(ORIG_ISO))
    bio = io.BytesIO()
    try:
        cd.get_file_from_iso_fp(bio, iso_path=iso_path)
    finally:
        cd.close()
    return bio.getvalue()


def backup(src: Path, name: str, rel: str | None = None) -> Path:
    """Ensure originals/name matches the retail ISO (never trust a patched extract)."""
    ORIGINALS.mkdir(parents=True, exist_ok=True)
    dest = ORIGINALS / name
    if rel is not None:
        retail = load_retail_file(rel)
        if not dest.exists() or dest.read_bytes() != retail:
            dest.write_bytes(retail)
            print(f"backed up originals/{name} from retail ISO")
        return dest
    if not dest.exists():
        dest.write_bytes(src.read_bytes())
        print(f"backed up originals/{name}")
    return dest


def patch_iso(iso_bytes: bytearray, old: bytes, new: bytes, label: str) -> None:
    """Replace one file blob in a raw ISO image without rewriting the UMD layout.

    New content must be exactly the retail size so directory records stay
    untouched (real PSP loaders are picky about TOC/size changes).
    """
    if len(new) != len(old):
        raise SystemExit(
            f"{label}: size {len(new)} != retail {len(old)} — refuse ISO inject"
        )
    idx = iso_bytes.find(old)
    if idx < 0:
        raise SystemExit(f"{label}: original blob not found in ISO")
    if iso_bytes.find(old, idx + 1) >= 0:
        raise SystemExit(f"{label}: original blob found more than once")
    iso_bytes[idx : idx + len(old)] = new
    print(f"ISO patched {label} at 0x{idx:X} size={len(old)}")


def write_iso_inplace(built: list[tuple[str, bytes, bytes]]) -> Path:
    """Copy the retail ISO and patch files in-place (same image size, same LBAs)."""
    raw = bytearray(ORIG_ISO.read_bytes())
    orig_size = len(raw)
    for rel, old, new in built:
        patch_iso(raw, old, new, Path(rel).name)
    if len(raw) != orig_size:
        raise SystemExit(f"ISO size changed {orig_size} -> {len(raw)}")

    out = OUT_ISO
    if out.exists():
        try:
            out.unlink()
        except PermissionError:
            out = OUT_ISO.with_name(OUT_ISO.stem + "_new.iso")
            if out.exists():
                try:
                    out.unlink()
                except PermissionError:
                    out = OUT_ISO.with_name(OUT_ISO.stem + "_new2.iso")
            print(f"{OUT_ISO.name} is locked, writing {out.name} instead")
    out.write_bytes(raw)
    print(f"wrote {out} size {out.stat().st_size} (retail {orig_size})")
    return out


def main() -> None:
    monsters = [
        ln
        for ln in (ROOT / "translation" / "monsters.txt").read_text(encoding="utf-8").splitlines()
        if ln.strip() != ""
    ]
    if len(SYS) != 222 or any(s is None for s in SYS):
        raise SystemExit(f"SYS incomplete: {sum(1 for s in SYS if s is None)} missing")
    if len(STAGES) != 97:
        raise SystemExit(f"STAGES {len(STAGES)} != 97")
    if len(PICKS) != 10:
        raise SystemExit("PICKS")
    if len(LOADING) != 13:
        raise SystemExit("LOADING")
    if len(DGN) != 16:
        raise SystemExit("DGN")
    if len(monsters) != 368:
        raise SystemExit(f"monsters {len(monsters)}")

    jobs = [
        (
            "PSP_GAME/USRDIR/data/csvtables/LoadingText_EN.tbin",
            [[a, b] for a, b in LOADING],
            "LoadingText_RU.txt",
        ),
        (
            "PSP_GAME/USRDIR/data/csvtables/PickName_EN.tbin",
            [[p] for p in PICKS],
            "PickName_RU.txt",
        ),
        (
            "PSP_GAME/USRDIR/data/csvtables/StgTitleNameList_EN.tbin",
            [[s] for s in STAGES],
            "StgTitleNameList_RU.txt",
        ),
        (
            "PSP_GAME/USRDIR/data/csvtables/DgnComment_EN.tbin",
            [[a, b] for a, b in DGN],
            "DgnComment_RU.txt",
        ),
        (
            "PSP_GAME/USRDIR/data/text/SystemMessage_EN.tbin",
            [[s] for s in SYS],
            "SystemMessage_RU.txt",
        ),
        (
            "PSP_GAME/USRDIR/data/csvtables/MonsterName_EN.tbin",
            [[m] for m in monsters],
            "MonsterName_RU.txt",
        ),
    ]

    built = []
    for rel, rows, dump_name in jobs:
        src, original, rebuilt = build_named(rel, rows, dump_name)
        delta = len(rebuilt) - len(original)
        print(f"{src.name:28} {len(original):6} -> {len(rebuilt):6}  ({delta:+d})")
        src.write_bytes(rebuilt)
        built.append((rel, original, rebuilt))

    gt_rel = "PSP_GAME/USRDIR/data/text/GameText.bin"
    gt_orig_path = backup(EXTRACT / gt_rel, "GameText.bin", rel=gt_rel)
    gt_orig = gt_orig_path.read_bytes()
    gt_new = patch_gametext(gt_orig)
    (EXTRACT / gt_rel).write_bytes(gt_new)
    print(f"GameText.bin                  {len(gt_orig):6} -> {len(gt_new):6}")
    built.append((gt_rel, gt_orig, gt_new))

    fpack_rel = "PSP_GAME/USRDIR/data/font/fpack.fbe"
    fpack_orig_path = backup(EXTRACT / fpack_rel, "fpack.fbe", rel=fpack_rel)
    fpack_new = patch_fpack(fpack_orig_path.read_bytes())
    (EXTRACT / fpack_rel).write_bytes(fpack_new)
    print(f"fpack.fbe                    {fpack_orig_path.stat().st_size:6} -> {len(fpack_new):6}")
    built.append((fpack_rel, fpack_orig_path.read_bytes(), fpack_new))

    fl_rel = "PSP_GAME/USRDIR/data/text/filelist.fbe"
    fl_orig_path = backup(EXTRACT / fl_rel, "filelist.fbe", rel=fl_rel)
    fl_new = patch_filelist(fl_orig_path.read_bytes())
    (EXTRACT / fl_rel).write_bytes(fl_new)
    print(f"filelist.fbe                 {fl_orig_path.stat().st_size:6} -> {len(fl_new):6}")
    built.append((fl_rel, fl_orig_path.read_bytes(), fl_new))

    hero_rel = "PSP_GAME/USRDIR/data/csvtables/HeroTextData_EN.tbin"
    hero_orig = backup(EXTRACT / hero_rel, "HeroTextData_EN.tbin", rel=hero_rel)
    hero_map = load_tsv(ROOT / "translation" / "hero_ru.tsv")
    hero_new, hero_n = patch_tbin_map(hero_orig.read_bytes(), hero_map)
    (EXTRACT / hero_rel).write_bytes(hero_new)
    print(f"HeroTextData_EN.tbin         {hero_orig.stat().st_size:6} -> {len(hero_new):6}  ({hero_n} cells)")
    built.append((hero_rel, hero_orig.read_bytes(), hero_new))

    sc_rel = "PSP_GAME/USRDIR/data/script/script.fbe"
    sc_orig = backup(EXTRACT / sc_rel, "script.fbe", rel=sc_rel)
    sc_new = patch_script(sc_orig.read_bytes())
    (EXTRACT / sc_rel).write_bytes(sc_new)
    print(f"script.fbe                   {sc_orig.stat().st_size:6} -> {len(sc_new):6}")
    built.append((sc_rel, sc_orig.read_bytes(), sc_new))

    mt_rel = "PSP_GAME/USRDIR/data/csvtables/MainichiText_EN.fbe"
    mt_orig = backup(EXTRACT / mt_rel, "MainichiText_EN.fbe", rel=mt_rel)
    mt_new = patch_mainichi(mt_orig.read_bytes())
    (EXTRACT / mt_rel).write_bytes(mt_new)
    print(f"MainichiText_EN.fbe          {mt_orig.stat().st_size:6} -> {len(mt_new):6}")
    built.append((mt_rel, mt_orig.read_bytes(), mt_new))

    from ency import (  # noqa: E402
        compact_latin,
        complete_ency_map,
        load_ency_map,
        load_ency_tsv,
        patch_pool,
    )

    ency_rel = "PSP_GAME/USRDIR/data/zukan/Ency.pack"
    ency_orig = backup(EXTRACT / ency_rel, "Ency.pack", rel=ency_rel)
    ency_blob = ency_orig.read_bytes()
    ency_map, ency_labels, ency_terms = load_ency_map(ROOT)
    ency_map = complete_ency_map(ency_blob, ency_map, ency_labels, ency_terms)
    ency_map.update(load_ency_tsv(ROOT))

    def fit_ency(en: str, ru: str) -> str:
        if en in FIT:
            return fit_ru(en, FIT[en])
        shown = bitmap_ru(ru)
        if len(shown) > len(en):
            shown = compact_latin(shown, len(en))
        return fit_ru(en, shown)

    ency_new, ency_n = patch_pool(ency_blob, ency_map, fit_ency)
    (EXTRACT / ency_rel).write_bytes(ency_new)
    print(f"Ency.pack                    {len(ency_blob):6} -> {len(ency_new):6}  ({ency_n} strings)")
    built.append((ency_rel, ency_blob, ency_new))

    print("patch ISO in-place (keep retail size/LBAs for real PSP)")
    write_iso_inplace(built)


if __name__ == "__main__":
    main()
