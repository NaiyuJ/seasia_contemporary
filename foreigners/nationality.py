"""Nationality, permit-type and header-role normalisation."""
from __future__ import annotations

import re
from typing import Optional, Tuple

from konghucu.religion import norm_label, year_from_text  # noqa: F401  (re-exported helpers)

LONG_COLUMNS = ["source", "province_code", "region_name", "region_level", "nationality", "permit_type",
                "year", "count", "ref"]

# canonical nationality -> regex on normalised label. Order matters: Taiwan / Hong Kong
# before China so "China (Taiwan)" is not swallowed by the China pattern.
NATIONALITY_PATTERNS = [
    ("TWN", r"\btaiwan\b|republik china|china taipei"),
    ("HKG", r"hong\s*kong|hongkong"),
    ("CHN", r"tiongkok|\bchina\b|\bcina\b|\brrt\b|rep(ublik)? rakyat|\bprc\b|chinese|中国"),
    ("JPN", r"jepang|japan"), ("KOR", r"korea sel|korea selatan|south korea|\bkorea\b(?! utara)"),
    ("IND", r"\bindia\b"), ("MYS", r"malaysia"), ("SGP", r"singapura|singapore"),
    ("AUS", r"australia"), ("USA", r"amerika serikat|united states|\busa\b|\bas\b"),
    ("GBR", r"inggris|united kingdom|britain"), ("PHL", r"filipina|philippin"),
    ("THA", r"thailand"), ("VNM", r"vietnam"), ("DEU", r"jerman|german"), ("NLD", r"belanda|netherland"),
    ("FRA", r"pran?cis|france|french"), ("RUS", r"rusia|russia"), ("CAN", r"kanada|canada"),
    ("ITA", r"italia"), ("ESP", r"spanyol|spain"), ("PAK", r"pakistan"), ("BGD", r"bangladesh"),
    ("LKA", r"sri ?lanka"), ("TLS", r"timor"), ("PNG", r"papua nugini|papua new guinea"),
    ("SAU", r"arab saudi|saudi"), ("EGY", r"mesir|egypt"), ("NGA", r"nigeria"), ("ZAF", r"afrika selatan|south africa"),
    ("NZL", r"selandia baru|new zealand"), ("CHE", r"swiss|switzerland"), ("SWE", r"swedia|sweden"),
    ("BEL", r"belgia|belgium"), ("MMR", r"myanmar"), ("KHM", r"kamboja|cambodia"), ("LAO", r"\blaos?\b"),
    ("BRN", r"brunei"), ("TUR", r"turki|turkey"), ("IRN", r"\biran\b"), ("IRQ", r"\birak\b|\biraq\b"),
    ("YEM", r"yaman|yemen"), ("PRK", r"korea utara|north korea"),
    ("OTHER", r"lain|other|negara lainnya"),
    ("TOTAL", r"^jumlah|^total|^seluruh"),
]
PERMIT_PATTERNS = [
    ("ITAS", r"\bitas\b|kitas|terbatas|limited stay"),
    ("ITAP", r"\bitap\b|kitap|\btetap\b|permanent"),
    ("ITK", r"\bitk\b|kunjungan|visit"),
    ("TKA", r"\btka\b|tenaga kerja asing|foreign worker|imta|rptka"),
    ("TOTAL", r"^jumlah|^total"),
]
WNA_RE = re.compile(r"\bwna\b|warga negara asing|orang asing|foreign", re.I)
WNI_RE = re.compile(r"\bwni\b|warga negara indonesia", re.I)
KANIM_RE = re.compile(r"kantor imigrasi|kanim\b|kelas [i]+ ", re.I)


def canonical_nationality(label: object) -> Optional[str]:
    s = norm_label(label)
    if not s:
        return None
    for code, pat in NATIONALITY_PATTERNS:
        if re.search(pat, s):
            return code
    return None


def canonical_permit(label: object) -> Optional[str]:
    s = norm_label(label)
    for code, pat in PERMIT_PATTERNS:
        if re.search(pat, s):
            return code
    return None


def header_role(label: object) -> Tuple[str, Optional[str]]:
    """Classify a header/row label: ('nationality', code) | ('permit', code) |
    ('year', '2021') | ('kanim', name) | ('total', 'TOTAL') | ('other', None).
    'total' is resolved by the caller: nationality TOTAL on the nationality axis,
    permit TOTAL on the other axis."""
    s = norm_label(label)
    nat = canonical_nationality(s)
    if nat == "TOTAL":
        return "total", "TOTAL"
    if nat and nat != "OTHER":
        return "nationality", nat
    y = year_from_text(s)
    if y and re.fullmatch(r"(tahun\s*)?\d{4}(\s*\(\w+\))?", s):
        return "year", str(y)
    if KANIM_RE.search(s):
        return "kanim", s
    p = canonical_permit(s)
    if p:
        return "permit", p
    if nat == "OTHER":
        return "nationality", nat
    return "other", None


def norm_kanim(name: object) -> str:
    """'Kantor Imigrasi Kelas I TPI Medan' -> 'medan'."""
    s = norm_label(name)
    s = re.sub(r"kantor imigrasi|kanim|kelas i+\b|khusus|tpi|non tpi", " ", s)
    return re.sub(r"\s+", " ", s).strip()
