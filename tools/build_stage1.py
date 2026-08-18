#!/usr/bin/env python3
"""Build stage-1 Russian files (UTF-8 tbin + padded UTF-16 GameText) and patch an ISO copy."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from paths import EXTRACT, ORIGINALS, RELEASE_ISO, ROOT, require_orig_iso  # noqa: E402

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from fbe import build_fbe, parse_fbe  # noqa: E402
from myu0 import build_tbin, decode_cell, parse_myu0  # noqa: E402
from patch_font import patch_fpack  # noqa: E402
from spt import patch_spt  # noqa: E402
from translit import gametext_display, to_latin  # noqa: E402
from translation.dialogs import DIALOG  # noqa: E402
from translation.ui import DGN, GAMETEXT, LOADING, PICKS, STAGES, SYS  # noqa: E402

ORIG_ISO = require_orig_iso()
OUT_ISO = RELEASE_ISO


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


def build_named(src_rel: str, rows: list[list[str]], dump_name: str) -> tuple[Path, bytes, bytes]:
    src = EXTRACT / src_rel
    original = src.read_bytes()
    info = parse_myu0(original)
    if len(rows) != info["row_count"]:
        raise SystemExit(f"{src.name}: rows {len(rows)} != {info['row_count']}")
    if any(len(r) != info["cols"] for r in rows):
        raise SystemExit(f"{src.name}: col mismatch")
    table = [[bitmap_ru(cell).encode("utf-8") for cell in row] for row in rows]
    rebuilt = build_tbin(table, info["field3"])
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
    return build_fbe([new_inner0, new_inner1], unk=4, align=4)


def patch_script(original: bytes) -> bytes:
    mapping = {en: bitmap_ru(ru) for en, ru in load_spt_map().items()}
    outer = parse_fbe(original)
    new_inner, n_str, n_spt = patch_spt_pack(outer[0][2], mapping)
    print(f"script.fbe    patched {n_str} strings in {n_spt} scripts")
    return build_fbe([new_inner], unk=4, align=4)


def patch_tbin_map(original: bytes, mapping: dict[str, str]) -> tuple[bytes, int]:
    info = parse_myu0(original)
    cols = info["cols"]
    n = 0
    cells: list[str] = []
    for raw in info["cells"]:
        text, _enc = decode_cell(raw)
        ru = mapping.get(text)
        if ru is not None:
            text = bitmap_ru(ru)
            n += 1
        cells.append(text)
    table = [cells[i : i + cols] for i in range(0, len(cells), cols)]
    rebuilt = build_tbin([[c.encode("utf-8") for c in row] for row in table], info["field3"])
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
    return build_fbe(blobs, unk=4, align=4)


def backup(src: Path, name: str) -> Path:
    dest = ORIGINALS / name
    if not dest.exists():
        dest.write_bytes(src.read_bytes())
        print(f"backed up originals/{name}")
    return dest


def patch_iso(iso_bytes: bytearray, old: bytes, new: bytes, label: str) -> None:
    if len(new) < len(old):
        new = new + b"\x00" * (len(old) - len(new))
    if len(new) != len(old):
        raise SystemExit(
            f"{label}: new file {len(new)} > original {len(old)} — cannot in-place patch ISO"
        )
    idx = iso_bytes.find(old)
    if idx < 0:
        raise SystemExit(f"{label}: original blob not found in ISO")
    if iso_bytes.find(old, idx + 1) >= 0:
        raise SystemExit(f"{label}: original blob found more than once")
    iso_bytes[idx : idx + len(old)] = new
    print(f"ISO patched {label} at 0x{idx:X} size={len(old)}")


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
    overflow = []
    for rel, rows, dump_name in jobs:
        src, original, rebuilt = build_named(rel, rows, dump_name)
        delta = len(rebuilt) - len(original)
        print(f"{src.name:28} {len(original):6} -> {len(rebuilt):6}  ({delta:+d})")
        dest = src
        dest.write_bytes(rebuilt if len(rebuilt) >= len(original) else rebuilt)
        # keep extracted as exact rebuilt (not padded) so tools stay honest
        built.append((rel, original, rebuilt))
        if len(rebuilt) > len(original):
            overflow.append((rel, len(original), len(rebuilt)))

    ORIGINALS.mkdir(exist_ok=True)
    gt_orig_path = ORIGINALS / "GameText.bin"
    gt_orig = gt_orig_path.read_bytes()
    gt_new = patch_gametext(gt_orig)
    gt_dest = EXTRACT / "PSP_GAME/USRDIR/data/text/GameText.bin"
    gt_dest.write_bytes(gt_new)
    print(f"GameText.bin                  {len(gt_orig):6} -> {len(gt_new):6}")
    built.append(("PSP_GAME/USRDIR/data/text/GameText.bin", gt_orig, gt_new))

    fpack_orig_path = ORIGINALS / "fpack.fbe"
    fpack_dest = EXTRACT / "PSP_GAME/USRDIR/data/font/fpack.fbe"
    if not fpack_orig_path.exists():
        fpack_orig_path.write_bytes(fpack_dest.read_bytes())
        print("backed up originals/fpack.fbe")
    fpack_new = patch_fpack(fpack_orig_path.read_bytes())
    fpack_dest.write_bytes(fpack_new)
    print(f"fpack.fbe                    {fpack_orig_path.stat().st_size:6} -> {len(fpack_new):6}")
    built.append(("PSP_GAME/USRDIR/data/font/fpack.fbe", fpack_orig_path.read_bytes(), fpack_new))

    fl_orig_path = ORIGINALS / "filelist.fbe"
    fl_dest = EXTRACT / "PSP_GAME/USRDIR/data/text/filelist.fbe"
    if not fl_orig_path.exists():
        fl_orig_path.write_bytes(fl_dest.read_bytes())
        print("backed up originals/filelist.fbe")
    fl_new = patch_filelist(fl_orig_path.read_bytes())
    fl_dest.write_bytes(fl_new)
    print(f"filelist.fbe                 {fl_orig_path.stat().st_size:6} -> {len(fl_new):6}")
    built.append(("PSP_GAME/USRDIR/data/text/filelist.fbe", fl_orig_path.read_bytes(), fl_new))

    hero_dest = EXTRACT / "PSP_GAME/USRDIR/data/csvtables/HeroTextData_EN.tbin"
    hero_orig = backup(hero_dest, "HeroTextData_EN.tbin")
    hero_map = load_tsv(ROOT / "translation" / "hero_ru.tsv")
    hero_new, hero_n = patch_tbin_map(hero_orig.read_bytes(), hero_map)
    hero_dest.write_bytes(hero_new)
    print(f"HeroTextData_EN.tbin         {hero_orig.stat().st_size:6} -> {len(hero_new):6}  ({hero_n} cells)")
    built.append(("PSP_GAME/USRDIR/data/csvtables/HeroTextData_EN.tbin", hero_orig.read_bytes(), hero_new))

    sc_dest = EXTRACT / "PSP_GAME/USRDIR/data/script/script.fbe"
    sc_orig = backup(sc_dest, "script.fbe")
    sc_new = patch_script(sc_orig.read_bytes())
    sc_dest.write_bytes(sc_new)
    print(f"script.fbe                   {sc_orig.stat().st_size:6} -> {len(sc_new):6}")
    built.append(("PSP_GAME/USRDIR/data/script/script.fbe", sc_orig.read_bytes(), sc_new))

    mt_dest = EXTRACT / "PSP_GAME/USRDIR/data/csvtables/MainichiText_EN.fbe"
    mt_orig = backup(mt_dest, "MainichiText_EN.fbe")
    mt_new = patch_mainichi(mt_orig.read_bytes())
    mt_dest.write_bytes(mt_new)
    print(f"MainichiText_EN.fbe          {mt_orig.stat().st_size:6} -> {len(mt_new):6}")
    built.append(("PSP_GAME/USRDIR/data/csvtables/MainichiText_EN.fbe", mt_orig.read_bytes(), mt_new))

    if overflow:
        print("OVERFLOW (need ISO rebuild, not in-place):")
        for rel, a, b in overflow:
            print(f"  {rel}: {a} -> {b}")

    print("rebuild ISO from extracted tree (tbin grew vs retail)")
    rebuild_iso_from_extracted()


def rebuild_iso_from_extracted() -> None:
    """Open the retail ISO and replace patched files, preserving UMD layout."""
    try:
        from pycdlib import PyCdlib
    except ImportError:
        raise SystemExit("pip install pycdlib")

    replacements = [
        "PSP_GAME/USRDIR/data/csvtables/LoadingText_EN.tbin",
        "PSP_GAME/USRDIR/data/csvtables/PickName_EN.tbin",
        "PSP_GAME/USRDIR/data/csvtables/StgTitleNameList_EN.tbin",
        "PSP_GAME/USRDIR/data/csvtables/DgnComment_EN.tbin",
        "PSP_GAME/USRDIR/data/csvtables/MonsterName_EN.tbin",
        "PSP_GAME/USRDIR/data/text/SystemMessage_EN.tbin",
        "PSP_GAME/USRDIR/data/text/GameText.bin",
        "PSP_GAME/USRDIR/data/font/fpack.fbe",
        "PSP_GAME/USRDIR/data/text/filelist.fbe",
        "PSP_GAME/USRDIR/data/csvtables/HeroTextData_EN.tbin",
        "PSP_GAME/USRDIR/data/script/script.fbe",
        "PSP_GAME/USRDIR/data/csvtables/MainichiText_EN.fbe",
    ]
    iso = PyCdlib()
    iso.open(str(ORIG_ISO))
    for rel in replacements:
        local = EXTRACT / rel
        iso_path = "/" + rel.replace("\\", "/")
        iso.update_file_contents(str(local), iso_path=iso_path)
        print("updated", iso_path, local.stat().st_size)
    if OUT_ISO.exists():
        try:
            OUT_ISO.unlink()
        except PermissionError:
            alt = OUT_ISO.with_name(OUT_ISO.stem + "_new.iso")
            if alt.exists():
                try:
                    alt.unlink()
                except PermissionError:
                    alt = OUT_ISO.with_name(OUT_ISO.stem + "_new2.iso")
            print(f"{OUT_ISO.name} is locked, writing {alt.name} instead")
            iso.write(str(alt))
            iso.close()
            print("wrote", alt, "size", alt.stat().st_size)
            return
    iso.write(str(OUT_ISO))
    iso.close()
    print("wrote", OUT_ISO, "size", OUT_ISO.stat().st_size)


if __name__ == "__main__":
    main()
