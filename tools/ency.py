#!/usr/bin/env python3
"""Dump / patch Ency.pack (almanac) UTF-16LE string pool."""
from __future__ import annotations

import re
import struct
from pathlib import Path

POOL_START = 0x2108


def _u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def gim_offset(data: bytes) -> int:
    off = data.find(b"MIG.00.1PSP")
    if off < 0:
        raise ValueError("GIM/MIG not found in Ency.pack")
    return off


def is_text(s: str) -> bool:
    if not s:
        return False
    if any(0xD800 <= ord(c) <= 0xDFFF for c in s):
        return False
    t = s.lstrip("\uffff")
    if not t:
        return False
    printable = sum(1 for c in t if c.isprintable() or c in "\n\t")
    if printable * 10 < len(t) * 9:
        return False
    letters = [c for c in t if c.isalpha()]
    if not letters:
        return True
    latin = sum(1 for c in letters if c.isascii())
    return latin * 4 >= len(letters) * 3 or "key" in t


def extract_cstrs(data: bytes, start: int | None = None, end: int | None = None) -> list[tuple[int, str]]:
    """Null-terminated UTF-16LE strings in the almanac pool (before GIM art)."""
    if start is None:
        start = POOL_START
    if end is None:
        end = gim_offset(data)
    out: list[tuple[int, str]] = []
    i = start if start % 2 == 0 else start + 1
    while i + 2 <= end:
        if _u16(data, i) == 0:
            i += 2
            continue
        chars: list[str] = []
        j = i
        while j + 2 <= end:
            c = _u16(data, j)
            if c == 0:
                break
            chars.append(chr(c))
            j += 2
            if len(chars) > 12000:
                break
        text = "".join(chars)
        if is_text(text):
            out.append((i, text))
        i = j + 2
    return out


_STAT_START = re.compile(r"(Diet:|Taxonomy:|Dislikes:|Predator)")


def split_prefix(raw: str) -> tuple[str, str]:
    """Leftover buffer junk before the real English (e.g. 'wnedThe...')."""
    if raw.startswith("\uffff"):
        stripped = raw.lstrip("\uffff")
        return raw[: len(raw) - len(stripped)], stripped
    pref = ""
    rest = raw
    while rest:
        if rest.startswith('"') and len(rest) > 1 and rest[1].isupper() and rest.count('"') == 1:
            pref += '"'
            rest = rest[1:]
            continue
        m = re.match(r"^(\d+)([A-Z].*)$", rest)
        if m:
            pref += m.group(1)
            rest = m.group(2)
            continue
        m = re.match(r"^([a-z]{1,8}[.,:;\"'\s]+)([A-Z].*)$", rest)
        if m:
            pref += m.group(1)
            rest = m.group(2)
            continue
        m = re.match(r"^((?:\d+\s+)?[a-z]{1,8})([A-Z].*)$", rest)
        if m:
            pref += m.group(1)
            rest = m.group(2)
            continue
        m = re.match(r"^([A-Z])([A-Z][a-z].+)$", rest)
        if m:
            pref += m.group(1)
            rest = m.group(2)
            continue
        m = re.match(r"^([A-Z][a-z]{2,5})([A-Z][a-z].+)$", rest)
        if m and " " not in m.group(1):
            pref += m.group(1)
            rest = m.group(2)
            continue
        m = _STAT_START.search(rest)
        if m and m.start() and m.start() <= 12:
            pref += rest[: m.start()]
            rest = rest[m.start() :]
            continue
        break
    stripped = rest.lstrip(" ")
    if stripped != rest:
        pref += rest[: len(rest) - len(stripped)]
        rest = stripped
    return pref, rest


def lookup_ency(clean: str, mapping: dict[str, str]) -> tuple[str | None, int]:
    """Return (ru, extra_prefix_len) so leftover junk before the EN key is kept."""
    ru = mapping.get(clean)
    if ru is not None:
        return ru, 0
    if len(clean) >= 2 and clean[0] == clean[-1] == '"':
        ru = mapping.get(clean[1:-1])
        if ru is not None:
            return ru, 0
    limit = min(20, len(clean))
    for i in range(1, limit):
        rest = clean[i:]
        ru = mapping.get(rest)
        if ru is None:
            continue
        if len(rest) >= 40 or i <= 6:
            return ru, i
    return None, 0


def patch_pool(data: bytes, mapping: dict[str, str], fit) -> tuple[bytes, int]:
    """Replace clean English in each C-string; keep leftover prefix; same wchar length."""
    end = gim_offset(data)
    out = bytearray(data)
    n = 0
    for off, raw in extract_cstrs(data, POOL_START, end):
        pref, clean = split_prefix(raw)
        ru, extra = lookup_ency(clean, mapping)
        if ru is None:
            continue
        if extra:
            pref += clean[:extra]
            clean = clean[extra:]
        shown = fit(clean, ru)
        if len(shown) > len(clean):
            shown = shown[: len(clean)]
        new_body = pref + shown
        pad = len(raw) - len(new_body)
        if pad < 0:
            new_body = new_body[: len(raw)]
            pad = 0
        new_raw = new_body + ("\0" * pad)
        encoded = new_raw.encode("utf-16le")
        old = raw.encode("utf-16le")
        if len(encoded) != len(old):
            raise SystemExit(f"ency wchar size {len(old)} -> {len(encoded)} at 0x{off:X}")
        out[off : off + len(old)] = encoded
        if shown != clean:
            n += 1
    return bytes(out), n


_LABEL_MARKERS = (
    "Diet:",
    "Taxonomy:",
    "Dislikes:",
    "Predators:",
    "Predator:",
    "Mutations:",
    "Special Abilit",
    "Max. HP:",
    "HP:",
    "Skill:",
    "Sex:",
    "Height:",
    "Dream Job:",
    "Likes:",
    "Hates:",
    "Attributes:",
    "Wants:",
    "Nickname:",
    "Personality:",
    "Hair ",
    "Title:",
    "Hobby:",
    "Hobbies:",
    "Equipment:",
    "Interests:",
    "Languages:",
    "Era:",
    "Purpose:",
    "Craves:",
    "Favorite ",
    "Hated ",
    "In A Word:",
    "Brain:",
    "Face:",
    "Type:",
    "Nerves:",
    "Weapon:",
    "AI:",
    "OS:",
    "Head:",
    "Belly:",
    "Special Move:",
    "Special Skill:",
    "Nutrient Capacity:",
    "Effect:",
    "Tap to break",
    "Get all 44",
    "Overwrite Save",
)


def apply_labeled(text: str, labels: list[tuple[str, str]], terms: list[tuple[str, str]]) -> str:
    out = text
    for en, ru in labels:
        out = out.replace(en, ru)
    for en, ru in terms:
        out = out.replace(en, ru)
    return out


_COMPACT_REPL = (
    ("Slizlepestok", "Slizlept"),
    ("slizlepestok", "slizlept"),
    ("gigantomoh", "gigamoh"),
    ("Gigantomoh", "Gigamoh"),
    ("ameba", "ameb"),
    ("Ameba", "Ameb"),
    ("tsista", "tsist"),
    ("Tsista", "Tsist"),
    ("tsvetok", "tsvet"),
    ("Tsvetok", "Tsvet"),
    ("vonyuchka", "vonyuch"),
    ("Vonyuchka", "Vonyuch"),
    ("aromat", "arom"),
    ("Aromat", "Arom"),
    ("oglushala", "ogl"),
    ("Oglushala", "Ogl"),
    ("zhuzhzh", "zhzh"),
    ("Zhuzhzh", "Zhzh"),
    ("pyanzh", "pyan"),
    ("Pyanzh", "Pyan"),
    ("redkiy", "redk"),
    ("Redkiy", "Redk"),
    ("velikiy", "vel"),
    ("Velikiy", "Vel"),
    ("rytsar", "ryts"),
    ("Rytsar", "Ryts"),
    ("geysha", "geish"),
    ("Geysha", "Geish"),
    ("dremo", "drem"),
    ("Dremo", "Drem"),
    ("tumanny", "tuman"),
    ("Tumanny", "Tuman"),
    ("drakona", "drak"),
    ("Drakona", "Drak"),
    ("haosa", "haos"),
    ("Haosa", "Haos"),
    ("shina", "shin"),
    ("Shina", "Shin"),
    ("ledyanoy", "led"),
    ("Ledyanoy", "Led"),
    ("zharkiy", "zhar"),
    ("Zharkiy", "Zhar"),
    ("holodny", "hol"),
    ("Holodny", "Hol"),
    ("bolshaya", "bol"),
    ("Bolshaya", "Bol"),
    ("bolshoy", "bol"),
    ("Bolshoy", "Bol"),
    ("bolshoe", "bol"),
    ("Bolshoe", "Bol"),
    ("boytsovskaya", "bout"),
    ("Boytsovskaya", "Bout"),
    ("sonnaya", "son"),
    ("Sonnaya", "Son"),
    ("pyshnaya", "pysh"),
    ("Pyshnaya", "Pysh"),
    ("zdorovennaya", "burly"),
    ("Zdorovennaya", "Burly"),
    ("mladshaya", "less"),
    ("Mladshaya", "Less"),
    ("sladosti", "sweet"),
    ("Sladosti", "Sweet"),
    ("kokon", "kok"),
    ("Kokon", "Kok"),
    ("rostok", "rost"),
    ("Rostok", "Rost"),
    ("sazhenets", "sazh"),
    ("Sazhenets", "Sazh"),
    ("kuvshinki", "kuvsh"),
    ("Kuvshinki", "Kuvsh"),
    ("mandry", "mandr"),
    ("Mandry", "Mandr"),
    ("pepelnaya", "ash"),
    ("Pepelnaya", "Ash"),
    ("strashnaya", "scar"),
    ("Strashnaya", "Scar"),
    ("lenivaya", "idle"),
    ("Lenivaya", "Idle"),
    ("muravinaya", "mur"),
    ("Muravinaya", "Mur"),
    ("kucha", "kuch"),
    ("Kucha", "Kuch"),
    ("Kukolka-", "Kuk-"),
    ("kukolka-", "kuk-"),
    ("Yaytso ", "Ya "),
    ("yaytso ", "ya "),
    ("Yaytso-", "Ya-"),
    ("yaytso-", "ya-"),
    ("Muha-", "M-"),
    ("muhа-", "m-"),
    ("Buton ", "Btn "),
    ("buton ", "btn "),
    ("Buton-", "Btn-"),
    ("buton-", "btn-"),
    ("Rostok ", "Rst "),
    ("rostok ", "rst "),
    ("Sazhenets ", "Sazh "),
    ("sazhenets ", "sazh "),
    ("Sazhenets-", "Sazh-"),
    ("sazhenets-", "sazh-"),
    ("Runa ", "R "),
    ("runa ", "r "),
    ("Kristaln", "Krist."),
    ("kristaln", "krist."),
    ("Vorotnichkov", "Vorotn."),
    ("vorotnichkov", "vorotn."),
    ("Draznilka-", "Drazn-"),
    ("draznilka-", "drazn-"),
    ("Tyazhely", "Tyazh."),
    ("tyazhely", "tyazh."),
    ("Tyazheloe", "Tyazh."),
    ("tyazheloe", "tyazh."),
    ("Dlinny", "Dlin."),
    ("dlinny", "dlin."),
    ("Chernoe", "Chern."),
    ("chernoe", "chern."),
    ("Tenevoe", "Ten."),
    ("tenevoe", "ten."),
    ("Zolotomnom", "Zlat."),
    ("zlatomnom", "zlat."),
    ("omnomnom", "omnmnm"),
    ("Omnomnom", "Omnmnm"),
    ("omnom", "omn"),
    ("Omnom", "Omn"),
    ("shipastika", "ship."),
    ("Shipastika", "Ship."),
    ("pantsir", "pants"),
    ("Pantsir", "Pants"),
    ("mandragora", "mandra"),
    ("Mandragora", "Mandra"),
    ("mandragory", "mandry"),
    ("Mandragory", "Mandry"),
    ("lilii", "lil"),
    ("Lilii", "Lil"),
    ("liliya", "lil"),
    ("Liliya", "Lil"),
    ("sirena", "siren"),
    ("Sirena", "Siren"),
    ("vedma", "ved."),
    ("Vedma", "Ved."),
    ("ledi", "lady"),
    ("Ledi", "Lady"),
    ("zhenschina", "zhen."),
    ("Zhenschina", "Zhen."),
    ("yash.", "ysh."),
    ("Yash.", "Ysh."),
    ("Magicheskaya", "Mag."),
    ("magicheskaya", "mag."),
    ("Imperator", "Imper."),
    ("imperator", "imper."),
    ("Zamorskaya", "Zamor."),
    ("zamorskaya", "zamor."),
    ("Blestyaschaya", "Blesch."),
    ("blestyaschaya", "blesch."),
    ("Kristalnaya", "Krist."),
    ("kristalnaya", "krist."),
    ("Fioletovaya", "Fiolet."),
    ("fioletovaya", "fiolet."),
    ("Bezmyatezhnaya", "Spok."),
    ("bezmyatezhnaya", "spok."),
    ("Brodyachiy", "Brod."),
    ("brodyachiy", "brod."),
    ("Obayatelny", "Obayat."),
    ("obayatelny", "obayat."),
    ("Letuchaya", "Let."),
    ("letuchaya", "let."),
    ("Mrachnaya", "Mrach."),
    ("mrachnaya", "mrach."),
    ("Pepelnaya", "Pepel."),
    ("pepelnaya", "pepel."),
    ("Strashnaya", "Strash."),
    ("strashnaya", "strash."),
    ("Peschernaya", "Pesch."),
    ("peschernaya", "pesch."),
    ("Vodyanaya", "Vod."),
    ("vodyanaya", "vod."),
    ("Ledyanoy", "Led."),
    ("ledyanoy", "led."),
    ("Ledyanoi", "Led."),
    ("ledyanoi", "led."),
    ("Bolshoy", "Bolsh."),
    ("bolshoy", "bolsh."),
    ("Bolshoe", "Bolsh."),
    ("bolshoe", "bolsh."),
    ("Cherny", "Chern."),
    ("cherny", "chern."),
    ("Tenevoy", "Ten."),
    ("tenevoy", "ten."),
    ("Grozovaya", "Groz."),
    ("grozovaya", "groz."),
    ("Krutyaschiysya", "Krut."),
    ("krutyaschiysya", "krut."),
    ("Gorohovy", "Goroh."),
    ("gorohovy", "goroh."),
    ("shipastik", "ship."),
    ("Shipastik", "Ship."),
    ("yascher", "yash."),
    ("Yascher", "Yash."),
    ("Muha-", "Muh-"),
    ("mra", "mra"),
    ("Maks.", "Max"),
    ("Vozrast", "Vozr."),
    ("Lyubimaya", "Lyub."),
    ("Nenavidit", "Nenav."),
    ("Obozhaet", "Obozh."),
    ("Lyubit", "Lyub."),
    ("Interesy", "Inter."),
    ("Interes", "Inter."),
    ("Harakter", "Har."),
    ("Prozvische", "Prozv."),
    ("Pozitsiya", "Poz."),
    ("Politika", "Pol."),
    ("Rodina", "Rod."),
    ("Mechta-rabota", "Mechta"),
    ("Teloslozhenie", "Tel."),
    ("Tsvet litsa", "Litso"),
    ("Tsvet volos", "Volosy"),
    ("Nastroyki", "Nastr."),
    ("Ozhidaniya", "Ozhid."),
    ("Professiya", "Prof."),
    ("Umeniya", "Skilly"),
    ("Ambitsii", "Amb."),
    ("Klimat", "Klim."),
    ("Pogoda", "Pog."),
    ("Osoby", "Osob."),
    ("Soderzhimoe", "Soderzh."),
    ("Krizis srednego vozrasta", "Krizis 40+"),
    ("glazovynosyaschim", "krupnym"),
)


def compact_latin(text: str, limit: int) -> str:
    out = text
    for src, dst in _COMPACT_REPL:
        if len(out) <= limit:
            break
        out = out.replace(src, dst)
    return out


def is_labeled(text: str) -> bool:
    return any(m in text for m in _LABEL_MARKERS)


def load_ency_map(root: Path) -> dict[str, str]:
    """EN → RU for almanac strings. TSV overrides win."""
    import sys

    sys.path.insert(0, str(root))
    from translation.ency_glossary import KEY_EXTRA, LABELS, TERMS, TITLES  # noqa: E402
    from translation.ui import GAMETEXT  # noqa: E402

    mapping: dict[str, str] = {}
    mapping.update(GAMETEXT)
    mapping.update(TITLES)
    mapping.update(KEY_EXTRA)

    en_names = (root / "translation" / "ency_monsters_en.txt").read_text(encoding="utf-8").splitlines()
    ru_names = [
        ln
        for ln in (root / "translation" / "monsters.txt").read_text(encoding="utf-8").splitlines()
        if ln.strip() != ""
    ]
    if len(en_names) != len(ru_names):
        raise SystemExit(f"monster name count {len(en_names)} vs {len(ru_names)}")
    for en, ru in zip(en_names, ru_names):
        mapping[en] = ru

    return mapping, LABELS, TERMS


def load_ency_tsv(root: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    tsv = root / "translation" / "ency_ru.tsv"
    if not tsv.exists():
        return mapping
    for line in tsv.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "\t" not in line:
            continue
        en, ru = line.split("\t", 1)
        en = en.replace("\\n", "\n")
        ru = ru.replace("\\n", "\n")
        mapping[en] = ru
        collapsed = en.replace('""', '"')
        mapping[collapsed] = ru
        if len(en) >= 2 and en[0] == en[-1] == '"':
            mapping[en[1:-1]] = ru
            mapping[en[1:-1].replace('""', '"')] = ru
    return mapping


def complete_ency_map(data: bytes, mapping: dict[str, str], labels, terms) -> dict[str, str]:
    """Fill Diet/hero-stat blocks from glossary; leave long flavor for the TSV."""
    out = dict(mapping)
    for _off, raw in extract_cstrs(data):
        _pref, clean = split_prefix(raw)
        if not clean or clean in out:
            continue
        if is_labeled(clean):
            ru = apply_labeled(clean, labels, terms)
            if ru != clean:
                out[clean] = ru
    return out
