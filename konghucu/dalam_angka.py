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

PARSER_VERSION = "2026-10-18b"  # bump when a parsing change should invalidate dalam-angka-extract's per-book cache

RELS = ["islam", "kristen", "protestan", "katolik", "katholik", "hindu", "budha", "buddha", "konghucu", "khonghucu"]
TOC = re.compile(r"(?i)daftar tabel|list of tables|daftar isi|table of contents|daftar gambar")
STRONG = re.compile(r"(?i)agama yang dianut|menurut (kecamatan|distrik)[^\n]*agama|by (sub)?district and religion")
NOT_THIS = re.compile(r"(?i)rumah ibadah|tempat ibadah|penyuluh|jemaah|haji|nikah|sekolah|madrasah|guru|murid")


def page_score(text: str) -> int:
    """Religion names present plus a bonus for the table title; a table of contents
    (which lists the title too) and places-of-worship tables are penalised."""
    t = text.lower()
    s = sum(r in t for r in RELS) + (4 if STRONG.search(t) else 0)
    if "agama" in t and "penduduk" in t and not STRONG.search(t):
        s += 2  # Jombang: the column group is just headed 'Agama/Religion' under a population table
    head = "\n".join(t.split("\n")[:8])
    if NOT_THIS.search(head):
        s -= 4
    if TOC.search(head) or len(re.findall(r"\.{4,}\s*\d+\s*$", t, flags=re.M)) > 5:
        s -= 10  # a table of contents: dotted leaders with page numbers
    return s


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


PERCENT_CELL = re.compile(r"^[^\d]*\d{1,3}\s*,\s*\d{1,4}[^\d]*$")


def is_percent_table(rows: List[List[object]], cols: List[Tuple[int, str]], hdr: int) -> bool:
    """True when most numeric cells are decimals with a comma ('6,4390', '22,09'): a
    'Persentase Penduduk Menurut Agama' table, not counts."""
    cells = [str(r[j]) for r in rows[hdr + 1:] for j, _ in cols if j < len(r) and r[j] and re.search(r"\d", str(r[j]))]
    if len(cells) < 4:
        return False
    return sum(bool(PERCENT_CELL.match(c.strip())) for c in cells) >= len(cells) / 2


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


def total_row_index(rows: List[List[object]], cols: List[Tuple[int, str]], hdr: int,
                    unit_hint: Optional[str] = None) -> Optional[int]:
    """The kabupaten/kota total row: the data row whose values equal the sum of all the
    other data rows (within 2%) on the largest column; else a trailing row labelled
    Kabupaten/Kota/Kab.; else None. Needed because kecamatan are often named 'Kota X'
    ('Kota Soe', 'Kota Lama', 'Kotamobagu Barat') and some books print the total row
    without a prefix ('Kotawaringin Timur')."""
    data = [(i, r) for i, r in enumerate(rows) if i > hdr and r and clean_label(r[0])
            and not re.fullmatch(r"\(?\d\)?", clean_label(r[0]))]
    if len(data) < 2:
        return None
    for i, r in data:  # an explicit 'Jumlah / Total' row needs no arithmetic
        if re.fullmatch(r"(?i)(jumlah|total)(\s*/?\s*(jumlah|total))?", clean_label(r[0])):
            return i
    j = max(cols, key=lambda c: sum(clean_number(r[c[0]]) or 0 for _, r in data if c[0] < len(r)))[0]
    vals = [(i, clean_number(r[j]) if j < len(r) else None) for i, r in data]
    biggest = max((v for _, v in vals if v), default=0)
    for i, v in vals:
        if not v or v < biggest:
            continue  # the total is the largest value of the column
        rest = sum(w for k, w in vals if k != i and w)
        if rest and abs(v - rest) / v <= 0.01:
            return i
    for i, r in reversed(data):
        if re.match(r"(?i)^(kabupaten|kota|kab\.?)\s", clean_label(r[0])):
            return i
    if unit_hint:  # a trailing row named like the book ('Pasaman Barat' in 'Kabupaten Pasaman Barat Dalam Angka')
        key = norm_label(unit_hint).replace(" ", "")
        for i, r in reversed(data):
            if key and key in norm_label(clean_unit_name(clean_label(r[0]))).replace(" ", ""):
                return i
    return None


def parse_rows(rows: List[List[object]], text: str, ref: str, province_code: str, unit_code: Optional[str],
               book_year: Optional[int], unit_hint: Optional[str] = None) -> pd.DataFrame:
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
    percent = is_percent_table(rows, cols, hdr)
    year = year_from_title(text, book_year - 1 if book_year else None)
    # a yearbook reports the previous year (sometimes the one before); any other year read
    # from the page is a stray number (a census reference, the book's own year)
    if book_year and year not in (book_year - 1, book_year - 2):
        year = book_year - 1
    tot_i = total_row_index(rows, cols, hdr, unit_hint) if not percent else _percent_total_row(rows, cols, hdr)
    out = []
    for i, r in enumerate(rows):
        if i <= hdr:
            continue
        name = clean_label(r[0] if r else "")
        if not name or re.fullmatch(r"\(?\d\)?", name):
            continue
        num = percent_number if percent else clean_number
        vals = [(rel, num(r[j]) if j < len(r) else None) for j, rel in cols]
        if all(v is None for _, v in vals):
            continue
        if i == tot_i:
            name = clean_unit_name(name)
            if re.fullmatch(r"(?i)(jumlah|total)(\s*/?\s*(jumlah|total))?", name):
                name = unit_hint or (unit_code or "total")
            lvl = unit_level(name)
            if lvl == "unknown":
                lvl = "kota" if unit_code and unit_code[2] == "7" else "kabupaten"
        else:
            lvl = "kecamatan"
        for rel, v in vals:
            out.append({"source": "pdf_da_pct" if percent else "pdf_da", "province_code": province_code,
                        "unit_code": unit_code if lvl != "kecamatan" else None, "unit_name": name,
                        "year": year, "semester": None, "religion": rel, "count": v, "ref": ref, "level": lvl})
    df = pd.DataFrame(out, columns=LONG_COLUMNS + ["level"])
    if tot_i is not None and not percent and not any(v is not None for _, v in
                                                      [(rel, clean_number(rows[tot_i][j]) if j < len(rows[tot_i]) else None) for j, rel in cols]):
        # the total row is printed but empty (Pasuruan): sum the kecamatan under its name
        unit_hint = unit_hint or clean_unit_name(clean_label(rows[tot_i][0]))
        tot_i = None
    if tot_i is None and not percent and unit_hint and len(df) and not _nested_numbering(rows, hdr):
        # no total row printed (Kota Bengkulu): the kabupaten is the sum of its kecamatan,
        # marked as such in the source
        kec = df[df["level"] == "kecamatan"]
        if kec["unit_name"].nunique() >= 3:
            tot = kec.groupby("religion", as_index=False)["count"].sum(min_count=1)
            lvl = "kota" if unit_code and unit_code[2] == "7" else "kabupaten"
            tot = tot.assign(source="pdf_da_sum", province_code=province_code, unit_code=unit_code,
                             unit_name=unit_hint or unit_code or "total", year=year, semester=None, ref=ref, level=lvl)
            df = pd.concat([df, tot[LONG_COLUMNS + ["level"]]], ignore_index=True)
    df["unit_name_norm"] = df["unit_name"].map(norm_unit_name)
    df.attrs["percent"] = percent
    return df


def _nested_numbering(rows: List[List[object]], hdr: int) -> bool:
    """True when row labels carry two numbering levels ('01. GUGUK PANJANG' kecamatan with
    '1. Tarok Dipo' kelurahan under it): summing the rows would double count."""
    labels = [str(r[0] or "").strip() for r in rows[hdr + 1:] if r]
    two = any(re.match(r"^\d{2}\.", x) for x in labels)
    one = any(re.match(r"^\d\.", x) for x in labels)
    return two and one


def percent_number(cell: object) -> Optional[float]:
    """'6,4390' -> 6.439; '0 ,0021' -> 0.0021; '_' / '-' -> 0; watermark letters dropped."""
    if cell is None:
        return None
    s = re.sub(r"[^\d,.\-–_]", "", str(cell))
    if not s:
        return None
    if re.fullmatch(r"[\-–_.]+", s):
        return 0.0
    m = re.search(r"(\d{1,3})\s*,\s*(\d{1,4})", s)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    digits = re.sub(r"\D", "", s)
    return float(digits) if digits else None


def _percent_total_row(rows: List[List[object]], cols: List[Tuple[int, str]], hdr: int) -> Optional[int]:
    """In a percentage table the total row is the first row (not a numbered kecamatan)
    whose religions add up to about 100; a table printed with several year rows
    (Sijunjung: 2023, 2022, ...) yields the current year's."""
    data = [(i, r) for i, r in enumerate(rows) if i > hdr and r and clean_label(r[0])
            and not re.fullmatch(r"\(?\d\)?", clean_label(r[0]))]
    for i, r in data:
        vals = [percent_number(r[j]) for j, _ in cols if j < len(r)]
        tot = sum(v for v in vals if v)
        if 95 <= tot <= 105 and not re.match(r"(?i)^\d+\.?\s", str(r[0] or "")):
            return i
    return None


def _group_lines(words: List[dict], tol: float = 3.0) -> List[List[dict]]:
    lines, cur, top = [], [], None
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if top is None or abs(w["top"] - top) <= tol:
            cur.append(w)
            top = w["top"] if top is None else top
        else:
            lines.append(sorted(cur, key=lambda w: w["x0"]))
            cur, top = [w], w["top"]
    if cur:
        lines.append(sorted(cur, key=lambda w: w["x0"]))
    return lines


def rows_from_words(page) -> List[List[str]]:
    """Fallback for borderless tables that pdfplumber's table finder misses: locate the
    header line with >= 3 religion names, then assign every word below it to the nearest
    religion column by x position; words left of the first column form the row label."""
    words = page.extract_words()
    lines = _group_lines(words)
    best, hdr_i = 0, None
    for i, ln in enumerate(lines):
        rels = {canonical_religion(w["text"]) for w in ln if len(w["text"]) >= 4} - {None, "total"}
        if len(rels) > best:
            best, hdr_i = len(rels), i
    if hdr_i is None or best < 3:
        return []
    cols = []
    for w in lines[hdr_i]:
        rel = canonical_religion(w["text"]) if len(w["text"]) >= 4 else None
        if rel and rel != "total" and rel not in [r for _, r in cols]:
            cols.append(((w["x0"] + w["x1"]) / 2, rel))
    cols.sort()
    centers = [c for c, _ in cols]
    left_bound = centers[0] - (centers[1] - centers[0]) / 2
    rows = [["Kecamatan"] + [r for _, r in cols]]
    for ln in lines[hdr_i + 1:]:
        label, cells = [], [[] for _ in cols]
        for w in ln:
            xc = (w["x0"] + w["x1"]) / 2
            if xc < left_bound:
                label.append(w["text"])
            else:
                j = min(range(len(centers)), key=lambda k: abs(centers[k] - xc))
                cells[j].append(w["text"])
        if not label or not any(cells):
            continue
        rows.append([" ".join(label)] + [" ".join(c) for c in cells])
    return rows


def religion_tables(page) -> List[List[List[object]]]:
    """Tables on a page that carry a religion header, from the table finder first and
    from word positions when it finds none."""
    found = [tb for tb in (page.extract_tables() or []) if any(len(header_map(r)) >= 3 for r in tb)]
    if found:
        return found
    rows = rows_from_words(page)
    return [rows] if len(rows) > 1 else []


def _data_rows(tb: List[List[object]]) -> List[List[object]]:
    """Rows after the header row (and the '(1) (2)' numbering row)."""
    for i, r in enumerate(tb):
        if len(header_map(r)) >= 3:
            return [x for x in tb[i + 1:] if x and not re.fullmatch(r"\(?\d\)?", clean_label(x[0]))
                    and not all(re.fullmatch(r"\s*(\(\d{1,2}\))?\s*", str(c or "")) for c in x)]
    return []


def continuation_rows(page, hdr: List[object]) -> List[List[object]]:
    """Data rows of a table continued on `page`: a table there with the same religion
    header, or, when the continuation is printed without a header, a table with the same
    number of columns whose rows carry a label and figures."""
    want = [r for _, r in header_map(hdr)]
    with_header = [t for t in religion_tables(page)
                   if [r for _, r in header_map(next(x for x in t if len(header_map(x)) >= 3))] == want]
    if with_header:
        return _data_rows(max(with_header, key=len))
    same_width = []
    for t in page.extract_tables() or []:
        if not t or max(len(r) for r in t) != len(hdr):
            continue
        rows = [r for r in t if r and clean_label(r[0]) and any(re.search(r"\d", str(c or "")) for c in r[1:])
                and not any(canonical_religion(str(c or "")) for c in r[1:])]
        same_width += rows
    return same_width


def column_continuation(page, hdr: List[object], rows: List[List[object]]) -> Optional[Tuple[List[object], List[List[object]]]]:
    """A wide table printed on two pages by columns (Jombang: Islam/Kristen/Katolik on one
    page, Hindu/Budha/Konghucu/Lainnya on the next): when `page` has a religion header with
    religions not in `hdr` and the same row labels, return the header and rows extended
    with the new columns."""
    have = {r for _, r in header_map(hdr)}
    for t in religion_tables(page):
        h2 = next(x for x in t if len(header_map(x)) >= 3) if any(len(header_map(x)) >= 3 for x in t) else None
        if h2 is None:
            h2 = next((x for x in t if header_map(x)), None)
        if h2 is None:
            continue
        new_cols = [(j, r) for j, r in header_map(h2) if r not in have]
        if not new_cols:
            continue
        data2 = _data_rows(t) if any(len(header_map(x)) >= 3 for x in t) else [x for x in t if x is not h2]
        by_label = {norm_label(clean_label(x[0])): x for x in data2 if x and clean_label(x[0])}
        matched = sum(norm_label(clean_label(r[0])) in by_label for r in rows[1:] if r and clean_label(r[0]))
        if matched < max(3, 0.6 * (len(rows) - 1)):
            continue
        ext_hdr = list(hdr) + [h2[j] for j, _ in new_cols]
        ext_rows = []
        for r in rows[1:]:
            x = by_label.get(norm_label(clean_label(r[0]))) if r and clean_label(r[0]) else None
            ext_rows.append(list(r) + [x[j] if x is not None and j < len(x) else None for j, _ in new_cols])
        return ext_hdr, ext_rows
    return None


def extract_book(path: str | Path, domain: Optional[str] = None, pub_id: Optional[str] = None,
                 book_year: Optional[int] = None, log=print, debug: bool = False,
                 title: Optional[str] = None) -> pd.DataFrame:
    """Find the religion table in one Dalam Angka PDF and return long rows. The domain
    (BPS 4-digit code) and pub_id default to the file name '<domain>_<pub_id>.pdf'.
    A table continued on the following page(s) is joined before the total row is
    looked for. The result's .attrs['status'] says what happened."""
    import pdfplumber
    path = Path(path)
    m = re.match(r"^(\d{4})_([0-9a-f]+)", path.stem)
    domain = domain or (m.group(1) if m else None)
    pub_id = pub_id or (m.group(2) if m else path.stem)
    ref = f"da:{domain}:{pub_id}"
    empty = pd.DataFrame(columns=LONG_COLUMNS + ["level"])

    def done(df, status, msg):
        df.attrs["status"] = status
        log(f"  {path.name}: {msg}")
        return df

    with open(path, "rb") as fh:
        magic = fh.read(5)
    if not magic.startswith(b"%PDF"):
        return done(empty, "not_pdf", "file is not a PDF (an HTML error page from the download?); delete and re-download")
    try:
        pdf_cm = pdfplumber.open(str(path))
    except Exception as e:  # noqa: BLE001  truncated download: pdfminer 'No /Root object'
        return done(empty, "corrupt", f"cannot be opened ({type(e).__name__}: {str(e)[:60]}); delete and re-download")
    with pdf_cm as pdf:
        head = " ".join((pdf.pages[i].extract_text() or "") for i in range(min(3, len(pdf.pages))))
        if book_year is None:
            ym = re.search(r"(?i)dalam angka\s*(20[0-3]\d)", head) or re.search(r"\b(20[0-3]\d)\b", head)
            book_year = int(ym.group(1)) if ym else None  # 2084 is a page count, not a year
        hm = re.search(r"(?i)\b(kecamatan|distrik|kapanewon|kemantren)\s+[A-Za-z' ]{2,40}?\s+dalam angka", head)
        if hm:
            return done(empty, "booklet", f"per-{hm.group(1).lower()} booklet, skipped")
        um = re.search(r"(?i)\b(kabupaten|kota|kab\.?)\s+([A-Za-z' ]{2,40}?)\s+dalam angka", head or "")
        if um is None and title:
            um = re.search(r"(?i)\b(kabupaten|kota|kab\.?)\s+([A-Za-z' ]{2,40}?)\s+dalam angka", title)
        unit_hint = um.group(2).strip() if um else None
        scored, texts, any_text = [], {}, False
        for i, page in enumerate(pdf.pages):
            t = page.extract_text() or ""
            any_text = any_text or len(t) > 200
            if "agama" not in t.lower() and "religion" not in t.lower():
                continue
            texts[i] = t
            scored.append((page_score(t), i))
        if not any_text:
            return done(empty, "scanned", "no text layer (scanned PDF); needs OCR")
        candidates = [i for sc, i in sorted(scored, key=lambda x: (-x[0], x[1])) if sc >= 4][:6]
        if not candidates:
            best = max((sc for sc, _ in scored), default=-99)
            return done(empty, "no_table", f"no population-by-religion table found (best score {best})")
        # several pages can look like the table (a places-of-worship table, a Kemenag count,
        # a list of tables): take them in score order and keep the first that yields a usable one
        tried = []
        for best_i in candidates:
            try:
                df, status, msg = _read_candidate(pdf, best_i, texts[best_i], ref, domain, book_year, unit_hint, log, debug)
            except Exception as e:  # noqa: BLE001  one odd page must not sink the book
                status, msg = "error", f"page {best_i}: {type(e).__name__}: {str(e)[:80]}"
            if debug:
                log(f"  [debug] candidate page {best_i}: {status}")
            if status in ("ok", "ok_percent"):
                df.attrs["status"] = status
                log(f"  {path.name}: {msg}")
                return df
            tried.append((status, msg))
    # report the most informative failure: numbers missing beats an unparsed page beats no total
    order = {"no_numbers": 0, "no_total": 1, "unparsed": 2, "error": 3}
    status, msg = sorted(tried, key=lambda x: order.get(x[0], 9))[0]
    return done(empty, status, msg + f" (candidate pages tried: {[m.split(':')[0].replace('page ', '').replace('pages ', '') for _, m in tried]})")


def _read_candidate(pdf, best_i, text, ref, domain, book_year, unit_hint, log, debug):
    """Read the religion table starting on page best_i. Returns (df, status, message)."""
    empty = pd.DataFrame(columns=LONG_COLUMNS + ["level"])
    tables = religion_tables(pdf.pages[best_i])
    if not tables:
        return empty, "unparsed", f"page {best_i} looks right but no table parsed"
    tb = max(tables, key=len)
    hdr = next(r for r in tb if len(header_map(r)) >= 3)
    rows = [hdr] + _data_rows(tb)
    pages_used = [best_i]
    # continued on the next page(s): no total row yet, and the next page has the same columns
    for nxt in (best_i + 1, best_i + 2):
        if total_row_index(rows, header_map(hdr), 0, unit_hint) is not None or nxt >= len(pdf.pages):
            break
        more = continuation_rows(pdf.pages[nxt], hdr)
        if not more:
            break
        rows += more
        pages_used.append(nxt)
    if best_i + 1 < len(pdf.pages):  # the remaining religion columns on the facing page
        ext = column_continuation(pdf.pages[best_i + 1], hdr, rows)
        if ext is not None:
            hdr, data = ext
            rows = [hdr] + data
            pages_used.append(best_i + 1)
    if debug:
        log(f"  [debug] page {best_i} tables={len(tables)} header={[r for _, r in header_map(hdr)]} "
            f"rows={len(rows) - 1} total_row={total_row_index(rows, header_map(hdr), 0, unit_hint)} "
            f"hint={unit_hint!r} pages={pages_used}")
        for r in rows[:6] + rows[-3:]:
            log("    " + " | ".join(str(c).replace(chr(10), " ")[:16] for c in r))
    cells = [str(c or "").strip() for r in rows[1:] for c in r[1:]]
    if cells and sum(bool(re.fullmatch(r"[.…]{2,}", c)) for c in cells) >= len(cells) / 2:
        return empty, "no_data", f"page {best_i}: the table is printed with '...' (data not available)"
    if not any(re.search(r"\d", c) for c in cells):
        return empty, "no_numbers", f"page {best_i}: table found but its figures are not in the text layer"
    df = parse_rows(rows, text, ref, domain[:2] if domain else "", domain, book_year, unit_hint)
    if df.empty:
        return empty, "unparsed", f"page {best_i} looks right but no table parsed"
    tot = df[df["level"] != "kecamatan"]
    if df.attrs.get("percent"):
        if tot.empty:
            return empty, "no_total", f"page {best_i}: percentage table without a row adding to 100"
        k = tot[tot["religion"] == "konghucu"]["count"]
        return df, "ok_percent", (f"page {best_i} year={df['year'].iloc[0]} {tot['unit_name'].iloc[0]} PERCENT table "
                                  f"(converted with the population in harmonize) konghucu={k.iloc[0] if len(k) else 'in Lainnya'}%")
    if tot.empty:
        return empty, "no_total", (f"pages {pages_used}: no total row equal to the sum of the "
                                   f"{df['unit_name'].nunique()} rows (a kecamatan book, or a split table)")
    k = tot[tot["religion"] == "konghucu"]["count"]
    return df, "ok", (f"pages {pages_used} year={df['year'].iloc[0]} {tot['unit_name'].iloc[0]} "
                      f"total={tot['count'].sum():,.0f} konghucu={k.iloc[0] if len(k) else 'in Lainnya'}")
