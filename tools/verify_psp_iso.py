#!/usr/bin/env python3
"""Verify patched ISO vs retail for real-PSP safety."""
from __future__ import annotations

import io
import struct
import sys
from pathlib import Path

from pycdlib import PyCdlib

ROOT = Path(r"B:\psp games\No Heroes Allowed RUS")
ORIG = Path(r"B:\psp games\[PSP] No Heroes Allowed! [USA]_up_by_kohryu.iso")
PATCH = ROOT / "NHA_USA_RUS.iso"
SECTOR = 2048

CRITICAL = [
    "/PSP_GAME/SYSDIR/EBOOT.BIN",
    "/PSP_GAME/SYSDIR/BOOT.BIN",
    "/PSP_GAME/PARAM.SFO",
    "/UMD_DATA.BIN",
    "/PSP_GAME/SYSDIR/OPNSSMP.BIN",
]

PATCHED = [
    "/PSP_GAME/USRDIR/data/csvtables/LoadingText_EN.tbin",
    "/PSP_GAME/USRDIR/data/csvtables/PickName_EN.tbin",
    "/PSP_GAME/USRDIR/data/csvtables/StgTitleNameList_EN.tbin",
    "/PSP_GAME/USRDIR/data/csvtables/DgnComment_EN.tbin",
    "/PSP_GAME/USRDIR/data/csvtables/MonsterName_EN.tbin",
    "/PSP_GAME/USRDIR/data/text/SystemMessage_EN.tbin",
    "/PSP_GAME/USRDIR/data/text/GameText.bin",
    "/PSP_GAME/USRDIR/data/font/fpack.fbe",
    "/PSP_GAME/USRDIR/data/text/filelist.fbe",
    "/PSP_GAME/USRDIR/data/csvtables/HeroTextData_EN.tbin",
    "/PSP_GAME/USRDIR/data/script/script.fbe",
    "/PSP_GAME/USRDIR/data/csvtables/MainichiText_EN.fbe",
    "/PSP_GAME/USRDIR/data/zukan/Ency.pack",
]


def get(iso: PyCdlib, path: str) -> bytes:
    bio = io.BytesIO()
    iso.get_file_from_iso_fp(bio, iso_path=path)
    return bio.getvalue()


def pvd_info(raw: bytes) -> dict:
    off = 16 * SECTOR
    assert raw[off : off + 6] == b"\x01CD001"
    vol_space = struct.unpack_from("<I", raw, off + 80)[0]
    path_le = struct.unpack_from("<I", raw, off + 140)[0]
    path_size = struct.unpack_from("<I", raw, off + 132)[0]
    root_extent = struct.unpack_from("<I", raw, off + 158)[0]
    return {
        "vol_space_sectors": vol_space,
        "vol_bytes": vol_space * SECTOR,
        "path_table_size": path_size,
        "path_table_lba": path_le,
        "root_extent": root_extent,
        "sys_id": raw[off + 8 : off + 40].rstrip(b"\x00 ").decode("latin-1", "replace"),
        "vol_id": raw[off + 40 : off + 72].rstrip(b"\x00 ").decode("latin-1", "replace"),
    }


def find_dir_records(raw: bytes, extent_lba: int, expect_size: int | None = None) -> list[dict]:
    le = struct.pack("<I", extent_lba)
    be = struct.pack(">I", extent_lba)
    hits = []
    start = 0
    while True:
        idx = raw.find(le, start)
        if idx < 0:
            break
        rec = idx - 2
        if rec >= 0 and raw[rec + 6 : rec + 10] == be:
            reclen = raw[rec]
            if reclen >= 33 and rec + reclen <= len(raw):
                size = struct.unpack_from("<I", raw, rec + 10)[0]
                name_len = raw[rec + 32]
                name = raw[rec + 33 : rec + 33 + name_len]
                hits.append(
                    {
                        "rec_off": rec,
                        "reclen": reclen,
                        "size": size,
                        "name": name,
                        "size_match": expect_size is None or size == expect_size,
                    }
                )
        start = idx + 1
    return hits


def main() -> int:
    issues: list[str] = []
    if not PATCH.exists():
        print("MISSING patched ISO")
        return 1

    o_raw = ORIG.read_bytes()
    p_raw = PATCH.read_bytes()
    print(f"size orig={len(o_raw)} patch={len(p_raw)} match={len(o_raw)==len(p_raw)}")
    if len(o_raw) != len(p_raw):
        issues.append("ISO size mismatch")

    op = pvd_info(o_raw)
    pp = pvd_info(p_raw)
    print("PVD orig:", op)
    print("PVD patch:", pp)
    if op != pp:
        issues.append(f"PVD differs: {op} vs {pp}")
    if pp["vol_bytes"] != len(p_raw):
        issues.append(
            f"PVD vol_bytes {pp['vol_bytes']} != file size {len(p_raw)}"
        )

    # path tables identical?
    pts = op["path_table_size"]
    plba = op["path_table_lba"]
    o_pt = o_raw[plba * SECTOR : plba * SECTOR + pts]
    p_pt = p_raw[plba * SECTOR : plba * SECTOR + pts]
    print(f"path table identical: {o_pt == p_pt}")
    if o_pt != p_pt:
        issues.append("path table changed")

    o_iso = PyCdlib()
    p_iso = PyCdlib()
    o_iso.open(str(ORIG))
    p_iso.open(str(PATCH))

    print("\n=== critical identical? ===")
    for path in CRITICAL:
        try:
            a, b = get(o_iso, path), get(p_iso, path)
        except Exception as e:
            issues.append(f"{path}: read fail {e}")
            print(path, "FAIL", e)
            continue
        same = a == b
        print(f"{path}: same={same} size={len(a)}")
        if not same:
            issues.append(f"{path} changed (must stay retail)")

    print("\n=== patched files ===")
    for path in PATCHED:
        a, b = get(o_iso, path), get(p_iso, path)
        name = path.rsplit("/", 1)[-1]
        capacity = ((len(a) + SECTOR - 1) // SECTOR) * SECTOR
        changed = a != b
        print(
            f"{name:28} retail={len(a):8} patch={len(b):8} "
            f"cap={capacity:8} changed={changed} magic={b[:4]!r}"
        )
        if len(b) > capacity:
            issues.append(f"{name}: exceeds sector capacity")
        if name.endswith(".tbin") and b[:4] != b"MYU0":
            issues.append(f"{name}: bad MYU0 magic")
        if name.endswith(".fbe") and b[:4] != b"FBE\x10":
            issues.append(f"{name}: bad FBE magic")
        if name == "GameText.bin" and len(a) != len(b):
            issues.append("GameText size changed")
        if name == "Ency.pack" and len(a) != len(b):
            issues.append("Ency size changed")

        # locate content offset and dir records
        idx = p_raw.find(b if len(b) <= len(a) else b[: len(a)])
        # better: find unique prefix of patched content
        # use retail content location from orig
        oidx = o_raw.find(a)
        if oidx < 0:
            issues.append(f"{name}: retail blob not found in orig ISO")
            continue
        if oidx % SECTOR != 0:
            issues.append(f"{name}: retail offset 0x{oidx:X} not sector-aligned")
        extent = oidx // SECTOR
        # patched payload at same offset
        patch_at = p_raw[oidx : oidx + len(b)]
        if patch_at != b:
            # for shrunk+padded files, ISO still has len(a) bytes
            if len(b) < len(a):
                padded = b + b"\x00" * (len(a) - len(b))
                if p_raw[oidx : oidx + len(a)] != padded:
                    # may have non-zero pad if we only wrote new and left old tail
                    # our patcher pads with zeros to len(a) when shrinking
                    got = p_raw[oidx : oidx + len(a)]
                    if got[: len(b)] != b:
                        issues.append(f"{name}: content mismatch at 0x{oidx:X}")
                    elif got[len(b) :] != b"\x00" * (len(a) - len(b)):
                        issues.append(
                            f"{name}: non-zero pad after shrunk content "
                            f"({sum(1 for x in got[len(b):] if x)} nonzero)"
                        )
            elif len(b) > len(a):
                if p_raw[oidx : oidx + len(b)] != b:
                    issues.append(f"{name}: grown content mismatch at 0x{oidx:X}")
            else:
                issues.append(f"{name}: content mismatch at 0x{oidx:X}")

        hits = find_dir_records(p_raw, extent, expect_size=len(b) if len(b) >= len(a) else len(a))
        # For shrunk files, dir size should remain retail len(a)
        # For grown, dir size should be len(b)
        expect = len(b) if len(b) > len(a) else len(a)
        hits2 = find_dir_records(p_raw, extent)
        good = [h for h in hits2 if h["size"] == expect]
        print(f"  LBA={extent} off=0x{oidx:X} dir_hits={len(hits2)} size_ok={len(good)}")
        for h in hits2:
            print(f"    rec@0x{h['rec_off']:X} size={h['size']} name={h['name']!r}")
        if not good:
            issues.append(f"{name}: no dir record with expected size {expect}")
        if len(b) > len(a):
            # next sector must not belong to another file start that we overwrote
            end = oidx + len(b)
            next_sector = ((oidx + len(a) + SECTOR - 1) // SECTOR) * SECTOR
            if end > next_sector:
                issues.append(f"{name}: wrote past sector allocation into 0x{end:X}")

    # FBE internal size vs ISO size for fpack
    fpack = get(p_iso, "/PSP_GAME/USRDIR/data/font/fpack.fbe")
    fbe_size = struct.unpack_from("<I", fpack, 4)[0]
    print(f"\nfpack FBE header size={fbe_size} iso size={len(fpack)} match={fbe_size==len(fpack)}")
    if fbe_size != len(fpack):
        issues.append(f"fpack FBE header {fbe_size} != iso {len(fpack)}")

    # byte identity outside patched extents
    print("\n=== unchanged regions sample ===")
    # SYSDIR area roughly early in ISO — compare first difference in EBOOT region via files
    # Count how many sectors differ
    n_diff_sectors = 0
    for s in range(0, len(o_raw) // SECTOR):
        a = o_raw[s * SECTOR : (s + 1) * SECTOR]
        b = p_raw[s * SECTOR : (s + 1) * SECTOR]
        if a != b:
            n_diff_sectors += 1
    print(f"differing sectors: {n_diff_sectors} / {len(o_raw)//SECTOR}")

    o_iso.close()
    p_iso.close()

    print("\n=== ISSUES ===")
    if not issues:
        print("none found by structural checks")
        return 0
    for i in issues:
        print("!", i)
    return 1


if __name__ == "__main__":
    sys.exit(main())
