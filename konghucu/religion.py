"""Label normalisation shared by all sources."""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

LONG_COLUMNS = ["source", "province_code", "unit_code", "unit_name", "year", "semester",
                "religion", "count", "ref"]

# canonical religion -> regex over a lowercased, de-accented label
RELIGION_PATTERNS = [
    ("konghucu", r"k?h?ong\s*hu\s*ch?u|k?h?ong\s*hu\s*tju|kong\s*fu\s*(cu|tse)|confuc|konfusian|\bkhong\b"),
    ("kepercayaan", r"kepercayaan|penghayat|aliran"),
    ("islam", r"\bislam\b|muslim"),
    ("kristen", r"kristen|protestan"),
    ("katolik", r"katolik|katholik|catholic"),
    ("hindu", r"\bhindu\b"),
    ("buddha", r"bud+h?a|buddhis"),
    ("lainnya", r"lain|other"),
    ("total", r"jumlah|total"),
]

PROVINCES = {
    "11": "Aceh", "12": "Sumatera Utara", "13": "Sumatera Barat", "14": "Riau", "15": "Jambi",
    "16": "Sumatera Selatan", "17": "Bengkulu", "18": "Lampung", "19": "Kepulauan Bangka Belitung",
    "21": "Kepulauan Riau", "31": "DKI Jakarta", "32": "Jawa Barat", "33": "Jawa Tengah",
    "34": "DI Yogyakarta", "35": "Jawa Timur", "36": "Banten", "51": "Bali", "52": "Nusa Tenggara Barat",
    "53": "Nusa Tenggara Timur", "61": "Kalimantan Barat", "62": "Kalimantan Tengah",
    "63": "Kalimantan Selatan", "64": "Kalimantan Timur", "65": "Kalimantan Utara",
    "71": "Sulawesi Utara", "72": "Sulawesi Tengah", "73": "Sulawesi Selatan", "74": "Sulawesi Tenggara",
    "75": "Gorontalo", "76": "Sulawesi Barat", "81": "Maluku", "82": "Maluku Utara", "91": "Papua",
    "92": "Papua Barat", "93": "Papua Selatan", "94": "Papua Tengah", "95": "Papua Pegunungan",
    "96": "Papua Barat Daya",
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm_label(s: object) -> str:
    s = strip_accents(str(s)).lower()
    s = re.sub(r"[\s_\-\.]+", " ", s)
    return s.strip()


def canonical_religion(label: object) -> Optional[str]:
    """Map a column header or row label to a canonical religion, else None."""
    s = norm_label(label)
    for name, pat in RELIGION_PATTERNS:
        if re.search(pat, s):
            return name
    return None


def parse_count(x: object) -> Optional[float]:
    """Indonesian number formatting: '1.234.567' thousands, '12,5' decimal. '-' and '' -> None."""
    if x is None:
        return None
    s = str(x).strip()
    if s in {"", "-", "–", "—", "nan", "None", "n.a.", "na", "NA", "..."}:
        return None
    s = re.sub(r"[^\d,\.\-]", "", s)
    if s in {"", "-"}:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if all(len(p) == 3 for p in parts[1:]):
            s = s.replace(".", "")
    elif "," in s:
        parts = s.split(",")
        s = s.replace(",", "") if all(len(p) == 3 for p in parts[1:]) else s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


_UNIT_PREFIX = re.compile(r"^(kabupaten|kab\.?|kota adm\.?|kota administrasi|kota|kotamadya)\s+", re.I)


UNIT_ALIASES = {  # table spelling -> BPS domain spelling (both normalised, spaces removed)
    "pali": "penukalabablematangilir",
    "labuanbatuutara": "labuhanbatuutara",
    "labuanbatuselatan": "labuhanbatuselatan",
    "labuanbatu": "labuhanbatu",
    "kepseribu": "kepulauanseribu",
    "kepulauantanimbar": "malukutenggarabarat",  # renamed 2019; the BPS code table keeps the old name
    "pasir": "paser",
    "sidrap": "sidenrengrappang",
    "sinderengrappang": "sidenrengrappang",
    "kepulauansitaro": "siautagulandangbiaro",
    "sitaro": "siautagulandangbiaro",
    "kepulauanyapen": "kepulauanyapen",
    "mamujuutara": "pasangkayu",
    "toli toli": "tolitoli",
    "tolitoli": "tolitoli",
    "pangkep": "pangkajenedankepulauan",
    "pangkajenekepulauan": "pangkajenedankepulauan",
    "tanjungjabungtimur": "tanjungjabungtimur",
    "tanjabbarat": "tanjungjabungbarat",
    "tanjabtimur": "tanjungjabungtimur",
    "kepulauanseribu": "kepulauanseribu",
    "jakartapusat": "jakartapusat",
    "sawahlunto": "sawahlunto",
    "pematangsiantar": "pematangsiantar",
    "batam": "batam",
    "dumai": "dumai",
    "siak": "siak",
}


def norm_unit_name(name: object) -> str:
    """'Kab. Deli Serdang' -> 'deli serdang'; 'KOTA MEDAN' -> 'medan'; '2. Bulungan *)' -> 'bulungan'.
    Keeps 'kota ' when needed to separate Kota X from Kabupaten X: callers compare on (level, name)."""
    s = norm_label(strip_tags(name))
    s = re.sub(r"^\d+\s*", "", s)  # leading row numbers / BPS codes
    s = _UNIT_PREFIX.sub("", s)
    s = re.sub(r"\s*[\*\)\(\]\[/]+\s*$", "", s)  # trailing footnote marks '*)'
    s = re.sub(r"\s+(kab|kabupaten|kota|regency|municipality)$", "", s)
    return s.strip()


def squash_unit_name(name: object) -> str:
    """Space-free key for matching: 'labuhan batu' == 'labuhanbatu'; aliases applied."""
    k = norm_unit_name(name).replace(" ", "")
    return UNIT_ALIASES.get(k, k)


def is_unit_name(name: object) -> bool:
    """False for footnotes, sources, dashes and sentence-length titles that slipped into the name column."""
    s = norm_label(strip_tags(name))
    if not re.search(r"[a-z]", s) or len(s) > 45:
        return False
    if re.fullmatch(r"(sp|sensus|supas|susenas)\s?\d{4}", s):  # census vintage labels used as row names
        return False
    return not re.search(r"sumber|source|catatan|note|keterangan|population by|penduduk .* menurut|jumlah penduduk", s)


def strip_tags(s: object) -> str:
    return re.sub(r"<[^>]+>", "", str(s)) if s is not None else ""


def unit_level(name: object) -> str:
    s = re.sub(r"^\d+\s*", "", norm_label(strip_tags(name)))  # '3308 Kabupaten Magelang' -> 'kabupaten magelang'
    if re.match(r"^(kota|kotamadya|kota adm)", s):
        return "kota"
    if re.match(r"^(kabupaten|kab\b|kab\.)", s):
        return "kabupaten"
    return "unknown"


def year_from_text(text: object) -> Optional[int]:
    m = re.findall(r"\b(19[89]\d|20[0-4]\d)\b", str(text))
    return int(m[-1]) if m else None


def semester_from_text(text: object) -> Optional[int]:
    s = norm_label(text)
    m = re.search(r"semester\s*(i{1,2}|1|2)\b", s)
    if not m:
        return None
    return {"i": 1, "1": 1, "ii": 2, "2": 2}[m.group(1)]
