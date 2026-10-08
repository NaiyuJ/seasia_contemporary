"""Population by religion from BPS 'Kabupaten X Dalam Angka' PDF yearbooks.

Every kabupaten/kota book has a table 'Jumlah Penduduk Menurut Kecamatan dan Agama yang
Dianut, <year>' (chapter 4.3) sourced from the local Dukcapil office: one row per
kecamatan and a total row named after the kabupaten/kota. This is the Dukcapil
definition the research wants, for kabupaten whose religion table is not in the API
(Sambas, Bengkayang, Singkawang in Kalimantan Barat).

The PDFs carry a diagonal watermark (the BPS site URL) whose letters leak into the
extracted cells: '4i1' is 41, '30b.040' is 30 040, '5.01.4' is 5 014, 'a s Sebawi' is
Sebawi. Numbers are therefore read as their digits only; a dash is zero.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

from .religion import LONG_COLUMNS, canonical_religion, norm_label, norm_unit_name, unit_level

logging.getLogger("pdfminer").setLevel(logging.ERROR)

RELS = ["islam", "kristen", "protestan", "katolik", "hindu", "budha", "buddha", "konghucu", "khonghucu"]
STRONG = re.compile(r"(?i)agama yang dianut|menurut (kecamatan|distrik)[^\n]*agama|by (sub)?district and religion")
NOT_THIS = re.compile(r"(?i)rumah ibadah|tempat ibadah|penyuluh|jemaah|haji|nikah|sekolah|madrasah|guru|murid")


def page_score(text: str) -> int:
    t = text.lower()
    s = sum(r in t for r in RELS) + (4 if STRONG.search(t) else 0)
    return s - (4 if NOT_THIS.search(t.split("\n", 8)[0] if t else "") else 0)


def clean_number(cell: object) -> Optional[float]:
    """Digits only, watermark letters and stray dots removed; '-' / '–' is zero."""
    if cell is None:
        return None
    s = str(cell).strip()
    if not s:
        return None
    if re.fullmatch(r"[\s\-–—.a-zA-Z/:]*[\-–—][\s\-–—.a-zA-Z/:]*", s):
        return 0.0
    digits = re.sub(r"\D", "", s)
    return float(digits) if digits else None


def clean_label(cell: object) -> str:
    """'a s Sebawi' -> 'Sebawi'; '1. Sungai Raya' -> 'Sungai Raya'; drop lone watermark letters."""
    s = re.sub(r"\s+", " ", str(cell or "").replace("\n", " ")).strip()
    s = re.sub(r"^\d+\.\s*", "", s)
    toks = [t for t in s.split(" ") if len(t) >= 2 and re.search(r"[A-Za-z]", t)]
    return " ".join(toks)


def header_map(row: List[object]) -> List[Tuple[int, str]]:
    """Column -> religion from a header cell such as 'Protestan\nProtestant' or, with
    watermark letters, 'd\nHindu\ni' / 'dHindu i': the first line that names a
    religion wins, after dropping lone letters."""
    out = []
    for j, c in enumerate(row):
        rel = None
        for line in str(c or "").split("\n"):
            line = " ".join(t for t in line.split() if len(t) >= 2)
            line = re.sub(r"^[a-z](?=[A-Z])", "", line)  # 'dHindu' -> 'Hindu'
            rel = canonical_religion(line)
            if rel:
                break
        if rel and rel != "total":
            out.append((j, rel))
    return out


def year_from_title(text: str, fallback: Optional[int]) -> Optional[int]:
    m = re.search(r"(?i)agama\s*yang\s*dianut[^\n]*?,?\s*(20\d\d)", text.replace("\n", " "))
    if m:
        return int(m.group(1))
    m = re.search(r"(?i)religion[^\n]{0,60}?(20\d\d)", text.replace("\n", " "))
    return int(m.group(1)) if m else fallback


def clean_unit_name(name: str) -> str:
    """'Kota Kupang Kupang Municipality' / 'Kota Bitung/ Bitung Municipality' -> 'Kota Kupang'."""
    s = name.split("/")[0].strip()
    toks = re.sub(r"(?i)\s+(regency|municipality|city|district)$", "", s).split()
    # the English rendering repeats the name: 'Kabupaten Rote Ndao Rote Ndao' -> drop the echo
    while len(toks) > 2 and toks[-1].lower() in [t.lower() for t in toks[:-1]]:
        toks.pop()
    return " ".join(toks)


def total_row_index(rows: List[List[object]], cols: List[Tuple[int, str]], hdr: int) -> Optional[int]:
    """The kabupaten/kota total row: the data row whose values equal the sum of all the
    other data rows (within 2%) on the largest column; else a trailing row labelled
    Kabupaten/Kota/Kab.; else None. Needed because kecamatan are often named 'Kota X'
    ('Kota Soe', 'Kota Lama', 'Kotamobagu Barat') and some books print the total row
    without a prefix ('Kotawaringin Timur')."""
    data = [(i, r) for i, r in enumerate(rows) if i > hdr and r and clean_label(r[0])
            and not re.fullmatch(r"\(?\d\)?", clean_label(r[0]))]
    if len(data) < 2:
        return None
    j = max(cols, key=lambda c: sum(clean_number(r[c[0]]) or 0 for _, r in data if c[0] < len(r)))[0]
    vals = [(i, clean_number(r[j]) if j < len(r) else None) for i, r in data]
    for i, v in vals:
        if not v:
            continue
        rest = sum(w for k, w in vals if k != i and w)
        if rest and abs(v - rest) / v <= 0.02:
            return i
    for i, r in reversed(data):
        if re.match(r"(?i)^(kabupaten|kota|kab\.?)\s", clean_label(r[0])):
            return i
    return None


def parse_rows(rows: List[List[object]], text: str, ref: str, province_code: str, unit_code: Optional[str],
               book_year: Optional[int]) -> pd.DataFrame:
    """One extracted table (list of rows) -> long rows. Needs a header row with >= 3
    religions; the total row (see total_row_index) becomes the kabupaten/kota, every
    other row a kecamatan."""
    hdr = None
    for i, r in enumerate(rows):
        if len(header_map(r)) >= 3:
            hdr, cols = i, header_map(r)
            break
    if hdr is None:
        return pd.DataFrame(columns=LONG_COLUMNS + ["level"])
    year = year_from_title(text, book_year - 1 if book_year else None)
    tot_i = total_row_index(rows, cols, hdr)
    out = []
    for i, r in enumerate(rows):
        if i <= hdr:
            continue
        name = clean_label(r[0] if r else "")
        if not name or re.fullmatch(r"\(?\d\)?", name):
            continue
        vals = [(rel, clean_number(r[j]) if j < len(r) else None) for j, rel in cols]
        if all(v is None for _, v in vals):
            continue
        if i == tot_i:
            name = clean_unit_name(name)
            lvl = unit_level(name)
            if lvl == "unknown":
                lvl = "kota" if unit_code and unit_code[2] == "7" else "kabupaten"
        else:
            lvl = "kecamatan"
        for rel, v in vals:
            out.append({"source": "pdf_da", "province_code": province_code,
                        "unit_code": unit_code if lvl != "kecamatan" else None, "unit_name": name,
                        "year": year, "semester": None, "religion": rel, "count": v, "ref": ref, "level": lvl})
    df = pd.DataFrame(out, columns=LONG_COLUMNS + ["level"])
    df["unit_name_norm"] = df["unit_name"].map(norm_unit_name)
    return df


def extract_book(path: str | Path, domain: Optional[str] = None, pub_id: Optional[str] = None,
                 book_year: Optional[int] = None, log=print) -> pd.DataFrame:
    """Find the religion table in one Dalam Angka PDF and return long rows. The domain
    (BPS 4-digit code) and pub_id default to the file name '<domain>_<pub_id>.pdf'."""
    import pdfplumber
    path = Path(path)
    m = re.match(r"^(\d{4})_([0-9a-f]+)", path.stem)
    domain = domain or (m.group(1) if m else None)
    pub_id = pub_id or (m.group(2) if m else path.stem)
    ref = f"da:{domain}:{pub_id}"
    with pdfplumber.open(str(path)) as pdf:
        head = " ".join((pdf.pages[i].extract_text() or "") for i in range(min(3, len(pdf.pages))))
        if book_year is None:
            ym = re.search(r"(?i)dalam angka\s*(20\d\d)", head) or re.search(r"\b(20\d\d)\b", head)
            book_year = int(ym.group(1)) if ym else None
        best, best_i = -99, None
        texts = {}
        for i, page in enumerate(pdf.pages):
            t = page.extract_text() or ""
            if "agama" not in t.lower() and "religion" not in t.lower():
                continue
            sc = page_score(t)
            texts[i] = t
            if sc > best:
                best, best_i = sc, i
        if best_i is None or best < 5:
            log(f"  {path.name}: no population-by-religion table found (best score {best})")
            return pd.DataFrame(columns=LONG_COLUMNS + ["level"])
        frames = []
        for tb in pdf.pages[best_i].extract_tables() or []:
            d = parse_rows(tb, texts[best_i], ref, domain[:2] if domain else "", domain, book_year)
            if len(d):
                frames.append(d)
    if not frames:
        log(f"  {path.name}: page {best_i} looks right but no table parsed")
        return pd.DataFrame(columns=LONG_COLUMNS + ["level"])
    df = pd.concat(frames, ignore_index=True)
    tot = df[df["level"] != "kecamatan"]
    if tot.empty:
        log(f"  {path.name}: page {best_i}: table has no Kabupaten/Kota total row (a kecamatan book?); "
            f"{df['unit_name'].nunique()} rows skipped")
        return pd.DataFrame(columns=LONG_COLUMNS + ["level"])
    k = tot[tot["religion"] == "konghucu"]["count"]
    log(f"  {path.name}: page {best_i} year={df['year'].iloc[0]} {tot['unit_name'].iloc[0]} "
        f"total={tot['count'].sum():,.0f} konghucu={k.iloc[0] if len(k) else 'in Lainnya'}")
    return df
