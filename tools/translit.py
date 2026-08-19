"""Compact Latin translit for the title bitmap font (no Cyrillic glyphs).

Keep the Russian source in translation/ui.py. Only GameText strings that
render with fpack slot 00 need Latin. Autosave/save dialogs use a different
font that already has real А–Я — those stay Cyrillic.
"""
from __future__ import annotations

# Longer digraphs first.
_DIGRAPHS = (
    ("ый", "y"),
    ("ЫЙ", "Y"),
    ("Ый", "Y"),
)

_MAP = {
    "А": "A",
    "Б": "B",
    "В": "V",
    "Г": "G",
    "Д": "D",
    "Е": "E",
    "Ё": "E",
    "З": "Z",
    "И": "I",
    "Й": "Y",
    "К": "K",
    "Л": "L",
    "М": "M",
    "Н": "N",
    "О": "O",
    "П": "P",
    "Р": "R",
    "С": "S",
    "Т": "T",
    "У": "U",
    "Ф": "F",
    "Ъ": "",
    "Ы": "Y",
    "Ь": "",
    "Э": "E",
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}

# Uppercase letters that expand to 2+ Latin chars. Title-case if the next char is lower.
_MULTI_UPPER = {
    "Ж": "ZH",
    "Х": "H",
    "Ц": "TS",
    "Ч": "CH",
    "Ш": "SH",
    "Щ": "SCH",
    "Ю": "YU",
    "Я": "YA",
}

# Manual fits when compact translit still exceeds the English wchar budget.
FIT = {
    "Next": "Eshe",
    "Mutation": "Mutatsia",
    "Food Chain": "Pisch tsep",
    "Max. HP: 20": "Max HP: 20",
    "Max. HP: [F]": "Max HP: [F]",
    "Mana Drain": "Krazha man",
    "Barrel Bomb": "Bochka-bomb",
    "Dungeonquake": "Danzhtryas.",
    "Skill Snooper": "Shpion navyk",
    "Warp This Way": "Teleport syud",
    "Story": "Syuzh",
    "Wandering Mana": "Brodyacha mana",
    "Earth": "Zemly",
    "Badman & Badmella": "Badman i Badmella",
}

# Proven sceFont path (autosave already showed real Cyrillic).
KEEP_CYRILLIC = {
    "This game has an autosave feature.",
    "Please do not turn off the power \nwhile the game is autosaving.",
    "Continue from restore point.",
    "There is no story mode data on the\nstorage media.",
    "Delete restore point and continue?",
    "No storage media inserted.",
    "The story mode save data\nis corrupted.",
    "Please create new save data.",
    "Saving data to storage media.",
    "Overwriting data on storage media.",
    "Overwriting data.",
    "To save at least\n800KB is required.",
    "Delete unwanted data?",
    "Save completed.",
    "Save almanac data to storage media.",
    "Saving...",
    "Checking...",
    "Save replay data?",
    "Delete unwanted replay data?",
    "To save replay data at least\n544KB is required.",
    "Load replay data?",
    "Restarting from resume point...",
    "To create save data at least 800KB\nis required. Delete unwanted data?",
    "Load data from storage media?",
    "Loading almanac data.",
    "Save failed.",
    "Load failed.",
    "The save data file size is incorrect.",
    "The storage media has been removed.",
    "The storage media is locked.",
    "Cannot access storage media.",
    "Operation was cancelled by the system entering sleep mode.",
    "The save data is corrupted.",
    "The chosen save file doesn't exist.",
    "Not enough space on storage media.",
    "At least 800KB is required to create save data.",
    "An error occurred while trying to save.",
    "The almanac save data has become corrupted.",
    "No almanac save data exists.",
    "An error occurred while trying to load.",
    "There is no \"Badman's Chamber\" data.",
    "Please try loading another file",
    "that contains \"Badman's Chamber\" data.",
}


def to_latin(text: str) -> str:
    for src, dst in _DIGRAPHS:
        text = text.replace(src, dst)
    out: list[str] = []
    for i, ch in enumerate(text):
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if ch in _MULTI_UPPER:
            chunk = _MULTI_UPPER[ch]
            prev = text[i - 1] if i else ""
            if nxt.islower() or not prev.isupper():
                chunk = chunk[0] + chunk[1:].lower()
            out.append(chunk)
        else:
            out.append(_MAP.get(ch, ch))
    return "".join(out)


def gametext_display(en: str, ru: str) -> str:
    """Russian source → what actually goes into GameText.bin."""
    if en in KEEP_CYRILLIC or "\n" in en:
        return ru
    if en in FIT:
        return FIT[en]
    return to_latin(ru)
