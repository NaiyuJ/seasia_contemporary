"""BPS Web API client for static tables ("penduduk menurut agama").

Register for a free key at https://webapi.bps.go.id and export BPS_API_KEY.
Domains: '0000' national, '1200' a province (2-digit code + '00'), '1201' a kabupaten.
"""
from __future__ import annotations

import os
import re
import time
from typing import Iterable, List, Optional, Sequence

import pandas as pd

from .htmltable import grid_tables, read_html_tables, unescape_if_needed
from .religion import (LONG_COLUMNS, PROVINCES, canonical_religion, is_unit_name, norm_label, parse_count, strip_tags,
                       unit_level, norm_unit_name, year_from_text)

BASE = "https://webapi.bps.go.id/v1/api"


def get_key(key: Optional[str] = None) -> str:
    from .envfile import load_dotenv
    info = load_dotenv()
    key = key or os.environ.get("BPS_API_KEY")
    if not key:
        raise RuntimeError("BPS_API_KEY is not set. Put BPS_API_KEY=<App ID> in the environment or in "
                           f"{info['path']} (.env found: {info['found']}, keys loaded: {info['keys']}). "
                           "Free at https://webapi.bps.go.id; never paste it into chat.")
    return key


def _get_json(session, url: str, retries: int = 4) -> dict:
    import requests as _rq
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=60)
        except _rq.RequestException as e:  # timeouts, resets: back off and retry
            if attempt == retries - 1:
                raise RuntimeError(f"network error after {retries} tries: {type(e).__name__}") from e
            time.sleep(3 * 2 ** attempt)
            continue
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                raise RuntimeError(f"non-JSON response for {url}")
        if r.status_code in (429, 500, 502, 503):
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 404:  # domain not served by the API (e.g. some new provinces): no data
            return {"status": "NOT_FOUND", "data-availability": "not-available", "data": []}
        raise RuntimeError(f"HTTP {r.status_code} for {url}")
    raise RuntimeError(f"gave up on {url}")


def list_static_tables(session, domain: str, keyword: str, key: str, lang: str = "ind") -> List[dict]:
    """All static tables in `domain` whose title matches `keyword` (paginated)."""
    out, page = [], 1
    while True:
        url = f"{BASE}/list/model/statictable/lang/{lang}/domain/{domain}/keyword/{keyword}/page/{page}/key/{key}"
        js = _get_json(session, url)
        if js.get("data-availability") != "available" or not js.get("data"):
            break
        meta, rows = js["data"][0], js["data"][1]
        for r in rows:
            r["domain"] = domain
        out.extend(rows)
        if page >= int(meta.get("pages", 1)):
            break
        page += 1
    return out


def view_static_table_raw(session, domain: str, table_id: str | int, key: str, lang: str = "ind") -> dict:
    url = f"{BASE}/view/model/statictable/lang/{lang}/domain/{domain}/id/{table_id}/key/{key}"
    return _get_json(session, url)


def view_static_table(session, domain: str, table_id: str | int, key: str, lang: str = "ind") -> dict:
    js = view_static_table_raw(session, domain, table_id, key, lang)
    return js.get("data") if isinstance(js.get("data"), dict) else {}


RELIGION_POP_RE = r"(penduduk|umat|pemeluk|penganut)[^|]*agama|agama[^|]*(penduduk|umat|pemeluk|penganut)|agama yang dianut"
NOT_RELIGION_RE = (r"kementerian agama|kementrian agama|departemen agama|pengadilan|sekolah|madrasah|perguruan|mahasiswa|"
                   r"guru|murid|penyuluh|pemuka|peribadatan|pemakaman|dprd|desa|nikah|perkara|kegiatan keagamaan|orang rimba|jemaah|haji|"
                   r"organisasi|lembaga|yayasan|rohaniwan|tokoh")
KEYWORDS = ("agama", "pemeluk", "umat", "penganut")


def classify_title(title: object) -> dict:
    t = norm_label(title)
    about = bool(re.search(RELIGION_POP_RE, t)) and not re.search(NOT_RELIGION_RE, t)
    return {"about_religion": about,
            "by_unit": about and bool(re.search(r"kabupaten|kota|kab/kota|kecamatan", t)),
            "is_percent": "persentase" in t or "persen" in t,
            "is_sub_kecamatan": bool(re.search(r"jenis kelamin kecamatan|kelurahan|desa|per kelurahan|\bkec\.? \w+$|di kecamatan \w+", t))}


def list_domains(session, key: str, prov_code: Optional[str] = None, lang: str = "ind") -> List[dict]:
    """BPS domains: provinces ('prov') or the kabupaten/kota of one province ('kabbyprov')."""
    url = (f"{BASE}/domain/type/kabbyprov/prov/{prov_code}00/key/{key}" if prov_code
           else f"{BASE}/domain/type/prov/key/{key}")
    js = _get_json(session, url)
    data = js.get("data") or []
    rows = data[1] if len(data) > 1 and isinstance(data[1], list) else []
    return [{"domain_id": str(r.get("domain_id")), "domain_name": r.get("domain_name"), "domain_url": r.get("domain_url")}
            for r in rows]


def _domains_to_scan(session, key: str, level: str, provinces: Optional[List[str]], log) -> List[tuple]:
    out = [(f"{c}00", c, n) for c, n in PROVINCES.items() if not provinces or c in provinces]
    if level == "kabupaten":
        kab = []
        for code, name in [(c, n) for c, n in PROVINCES.items() if not provinces or c in provinces]:
            try:
                for d in list_domains(session, key, code):
                    kab.append((d["domain_id"], code, d["domain_name"]))
            except RuntimeError as e:
                log(f"  {code} {name}: cannot list kabupaten domains: {e}")
        log(f"  {len(kab)} kabupaten/kota domains")
        out = kab
    return out


def search_all_provinces(session, key: str, keyword: str = "agama", sleep_s: float = 0.2, log=print,
                         level: str = "province", provinces: Optional[List[str]] = None,
                         keywords: Optional[Sequence[str]] = None, skip_domains: Optional[set] = None,
                         on_domain=None) -> pd.DataFrame:
    """Catalogue static tables about religion. level='province' scans the 38 provincial
    domains; level='kabupaten' scans every kabupaten/kota domain (slow: ~500 x keywords).
    `skip_domains` are left out (resume); `on_domain(domain, rows)` is called after each
    domain so the caller can checkpoint."""
    keywords = list(keywords or ([keyword] if keyword != "agama" else KEYWORDS))
    rows, seen = [], set()
    for domain, prov, name in _domains_to_scan(session, key, level, provinces, log):
        if skip_domains and domain in skip_domains:
            continue
        n, start = 0, len(rows)
        for kw in keywords:
            try:
                found = list_static_tables(session, domain, kw, key)
            except RuntimeError as e:  # keep going; one domain must not kill the catalogue
                log(f"  {domain} {name}: {e}")
                continue
            for r in found:
                k = (domain, str(r.get("table_id")))
                if k in seen:
                    continue
                seen.add(k)
                n += 1
                rows.append({"domain": domain, "province_code": prov, "domain_name": name, "table_id": r.get("table_id"),
                             "title": r.get("title"), "subj": r.get("subj"), "updt_date": r.get("updt_date"),
                             "excel": r.get("excel"), **classify_title(r.get("title"))})
            time.sleep(sleep_s)
        log(f"  {domain} {name}: {n} tables")
        if on_domain:
            on_domain(domain, rows[start:])
    cols = ["domain", "province_code", "domain_name", "table_id", "title", "subj", "updt_date", "excel",
            "about_religion", "by_unit", "is_percent"]
    return pd.DataFrame(rows, columns=cols)


def _flatten_columns(cols) -> List[str]:
    out = []
    for c in cols:
        if isinstance(c, tuple):
            parts = [str(p) for p in c if not str(p).startswith("Unnamed")]
            out.append(" | ".join(dict.fromkeys(parts)))
        else:
            out.append(str(c))
    return out


SEX_TOTAL_RE = r"jumlah|total|l\s*\+\s*p|laki.*perempuan|male.*female|both"
SEX_PART_RE = r"laki|perempuan|\bmale|female|\bpria|wanita|l/p|\bl\b|\bp\b"


def split_header_blocks(rel_cols):
    """[(col, religion, year)] -> list of blocks, a block being a run of columns in which
    no religion repeats. A table 'by religion and sex' has three blocks (male, female,
    total); a multi-year table has one block per year."""
    blocks, cur, seen = [], [], set()
    for j, rel, yr in rel_cols:
        if rel in seen:
            blocks.append(cur)
            cur, seen = [], set()
        cur.append((j, rel, yr))
        seen.add(rel)
    if cur:
        blocks.append(cur)
    return blocks


def choose_sex_blocks(grid, h, rel_cols):
    """When the header repeats the religions without distinct years, the blocks are
    sex groups. Return (columns to keep, columns to add up): the 'Jumlah/Total' block
    when the rows above the header label one, else all blocks summed (Laki-laki +
    Perempuan), else when there is no label at all the last block (BPS prints the
    total last). Multi-year blocks are returned unchanged."""
    blocks = split_header_blocks(rel_cols)
    if len(blocks) < 2:
        return rel_cols, None
    years = [{yr for _, _, yr in blk} for blk in blocks]
    if len({tuple(sorted(str(y) for y in ys)) for ys in years}) > 1:
        return rel_cols, None  # one block per year: keep every column
    labels = []
    for blk in blocks:
        cols = [j for j, _, _ in blk]
        txt = " ".join(norm_label(grid[i][j]) for i in range(max(0, h - 3), h)
                       for j in cols if j < len(grid[i]) and grid[i][j])
        labels.append(txt)
    total = [i for i, lab in enumerate(labels) if re.search(SEX_TOTAL_RE, lab)]
    if total:
        return blocks[total[-1]], None
    parts = [i for i, lab in enumerate(labels) if re.search(SEX_PART_RE, lab)]
    if parts and len(parts) == len(blocks):
        return None, blocks  # male and female only: add them up
    return blocks[-1], None


def _block_level(label: str):
    """'Kabupaten/ Regency' -> 'kabupaten', 'Kota/ Municipality' -> 'kota', else None."""
    nm = norm_label(label)
    if re.fullmatch(r"(kabupaten|kab|regency)(\s*/\s*regency)?", nm):
        return "kabupaten"
    if re.fullmatch(r"(kota|municipality|kota adm(inistrasi)?)(\s*/\s*municipality)?", nm):
        return "kota"
    return None


def _is_number_like(cell: str) -> bool:
    """A count/number cell. Any letter disqualifies: BPS letter-spaces some names
    ('M e d a n', 'N i a s') and those must stay names."""
    c = (cell or "").strip()
    return bool(c) and parse_count(c) is not None and not re.search(r"[A-Za-z]", c)


def parse_religion_html(html: str, province_code: str, year: Optional[int], ref: str,
                        source: str = "bps") -> pd.DataFrame:
    """BPS 'penduduk menurut kabupaten/kota dan agama' tables (Excel-exported HTML,
    entity-escaped, title rows above, no <th>) to long form.

    Header = the row with the most religion-name cells (at least 2). Rows below it
    are data; the unit name is the first non-numeric, non-empty cell. Rows above the
    header are ignored. A religion column header may also carry a year."""
    frames = []
    for grid in grid_tables(html):
        if len(grid) < 2:
            continue
        # header = row with the most DISTINCT named religions (not 'total': a title
        # cell like 'Jumlah Penduduk ...' spans every column and would win otherwise)
        scores = [len({canonical_religion(c) for c in row} - {None, "total"}) for row in grid]
        width = max(len(r) for r in grid)
        col_scores = [len({canonical_religion(r[j]) for r in grid if j < len(r)} - {None, "total"}) for j in range(width)]
        if max(col_scores, default=0) > max(scores, default=0):
            # religions run down a column (e.g. 'Agama x Jenis Kelamin' tables): transpose
            grid = [[r[j] if j < len(r) else "" for r in grid] for j in range(width)]
            scores = [len({canonical_religion(c) for c in row} - {None, "total"}) for row in grid]
        h = max(range(len(grid)), key=lambda i: scores[i])
        if scores[h] < 2:
            continue
        header = grid[h]
        # a second header row (e.g. years under religion names, or religion names under
        # a 'Agama' super-header) is merged when it adds information
        header2 = grid[h + 1] if h + 1 < len(grid) else None
        rel_cols = []
        for j, cell in enumerate(header):
            rel = canonical_religion(cell)
            yr = year_from_text(cell)
            if rel is None and header2 is not None:
                rel = canonical_religion(header2[j]) if j < len(header2) else None
            if rel is None:
                continue
            if yr is None and header2 is not None and j < len(header2):
                yr = year_from_text(header2[j]) if canonical_religion(header2[j]) is None else None
            for i in (h - 1, h - 2):  # a year super-header above the religions ('2019' spanning a block)
                if yr is None and i >= 0 and j < len(grid[i]) and grid[i][j] and len(grid[i][j].strip()) <= 12 \
                        and canonical_religion(grid[i][j]) is None:
                    yr = year_from_text(grid[i][j])
            rel_cols.append((j, rel, yr))
        if not rel_cols:
            continue
        rel_cols, sum_blocks = choose_sex_blocks(grid, h, rel_cols)
        if sum_blocks is not None:
            rel_cols = sum_blocks[0]
        data_start = h + 1
        if header2 is not None and any(_block_level(c) for c in header2 if c):
            header2 = None  # a 'Kabupaten / Regency' block label, handled as data below
        if header2 is not None:
            nonempty = [c.strip() for c in header2 if c and c.strip()]
            is_year = lambda c: bool(re.fullmatch(r"(19|20)\d{2}(/\d{2,4})?", c))
            years_or_text = bool(nonempty) and any(is_year(c) for c in nonempty) and \
                all(is_year(c) or not _is_number_like(c) for c in nonempty)
            if years_or_text or not any(_is_number_like(c) for c in header2):
                data_start = h + 2  # header2 was a header row (years, possibly beside rowspan labels), not data
        width = len(header)
        first_rel_col = min(j for j, _, _ in rel_cols)
        block_level = None  # 'kabupaten' / 'kota' sub-header rows in province tables
        for row in grid[data_start:]:
            # a short row whose label sits where a code column is (e.g. 'Jumlah / Total' under
            # 'Kode Wil.') has its values shifted left: right-align it to the header
            eff = len(row)
            while eff > 0 and not (row[eff - 1] or "").strip():
                eff -= 1  # grids are right-padded with empty cells
            if eff < width and first_rel_col >= 2 and eff >= 2 \
                    and row[0] and not _is_number_like(row[0]) and _is_number_like(row[1]):
                row = [""] * (width - eff) + list(row[:eff])
            name = next((c.strip() for c in row if c and c.strip() and not _is_number_like(c)), None)
            if not name:
                continue
            nm = norm_label(name)
            if _block_level(name):
                block_level = _block_level(name)
                continue
            if not is_unit_name(name):
                continue
            if nm in {"kabupaten/kota", "kabupaten", "kota", "wilayah", "daerah", "kecamatan", "no", "no."} \
                    or canonical_religion(nm) not in (None, "total"):
                continue  # a religion name as a row label: header leftover, not a unit
            if re.search(r"persen|%|rasio|rata rata|proporsi|share", nm):
                continue  # a percentage / ratio row, not a count
            row_year = year_from_text(nm)
            if row_year and year and row_year != year and re.search(r"jumlah|total", nm):
                continue  # a previous year's total row ('Jumlah 2018' in a 2019 table)
            vals = [(j, rel, yr, parse_count(row[j]) if j < len(row) else None) for j, rel, yr in rel_cols]
            if sum_blocks is not None:  # male + female blocks: add the same religion across blocks
                summed = []
                for k, (j, rel, yr, v) in enumerate(vals):
                    parts = [parse_count(row[blk[k][0]]) if blk[k][0] < len(row) else None for blk in sum_blocks]
                    summed.append((j, rel, yr, sum(p for p in parts if p is not None) if any(p is not None for p in parts) else None))
                vals = summed
            if all(v is None for *_, v in vals):
                continue
            if all(v is None or (1990 <= v <= 2035 and float(v).is_integer()) for *_, v in vals) \
                    and sum(v is not None for *_, v in vals) >= 2:
                continue  # a row of years
            prov_nm = norm_label(PROVINCES.get(province_code, "")).replace(" ", "")
            is_prov_total = nm.replace(" ", "") == prov_nm or nm.startswith("provinsi") \
                or nm.startswith("jumlah") or nm.startswith("total")
            lvl = unit_level(name)
            if lvl == "unknown" and block_level:
                lvl = block_level
            for j, rel, yr, v in vals:
                frames.append({"source": source, "province_code": province_code, "unit_code": None,
                               "unit_name": "__PROVINCE__" if is_prov_total else name,
                               "year": yr or year, "semester": None, "religion": rel, "count": v, "ref": ref,
                               "level": lvl})
    df = pd.DataFrame(frames, columns=LONG_COLUMNS + ["level"])
    df["unit_name_norm"] = df["unit_name"].map(norm_unit_name)
    return df


def fetch_tables(session, catalogue: pd.DataFrame, key: str, sleep_s: float = 0.3,
                 raw_dir: Optional[str] = None, log=print) -> pd.DataFrame:
    """Download and parse every row of `catalogue`. One line per table is logged; a table
    that is empty, unreachable or unparseable is skipped, never fatal. Raw HTML already
    in `raw_dir` is reused instead of re-downloaded."""
    import json
    from pathlib import Path
    parts, status = [], {"ok": 0, "empty": 0, "no_religion_rows": 0, "error": 0}
    for i, rec in enumerate(catalogue.itertuples(index=False), 1):
        ref = f"bps:{rec.domain}:{rec.table_id}"
        raw = Path(raw_dir) / f"bps_{rec.domain}_{rec.table_id}.html" if raw_dir else None
        meta = Path(raw_dir) / f"bps_{rec.domain}_{rec.table_id}.json" if raw_dir else None
        try:
            if raw is not None and raw.exists() and raw.stat().st_size > 0:
                html = unescape_if_needed(raw.read_text(encoding="utf-8"))
                title = json.loads(meta.read_text()).get("title") if meta and meta.exists() else rec.title
            else:
                full = view_static_table_raw(session, rec.domain, rec.table_id, key)
                data = full.get("data") if isinstance(full.get("data"), dict) else {}
                html, title = unescape_if_needed(data.get("table") or ""), data.get("title") or rec.title
                if raw is not None:
                    raw.parent.mkdir(parents=True, exist_ok=True)
                    raw.write_text(html, encoding="utf-8")
                    meta.write_text(json.dumps({"title": title, "response_keys": list(full.keys()),
                                                "status": full.get("status"), "message": full.get("message"),
                                                "data_type": type(full.get("data")).__name__,
                                                "data_keys": list(data.keys())}, ensure_ascii=False))
                time.sleep(sleep_s)
            if not html or "<table" not in html.lower():
                status["empty"] += 1
                why = ""
                if meta is not None and meta.exists():
                    m = json.loads(meta.read_text())
                    why = f" status={m.get('status')} msg={str(m.get('message'))[:60]} data_keys={m.get('data_keys')}"
                log(f"  [{i}/{len(catalogue)}] {ref} EMPTY{why}  {str(rec.title)[:50]}")
                continue
            d = parse_religion_html(html, str(rec.province_code), year_from_text(title), ref)
            d = rollup_kabupaten_domain(d, str(rec.domain), getattr(rec, "domain_name", None))
            if d.empty:
                status["no_religion_rows"] += 1
                log(f"  [{i}/{len(catalogue)}] {ref} NO RELIGION COLUMNS  {str(rec.title)[:70]}")
                continue
            parts.append(d)
            status["ok"] += 1
            yrs = sorted(set(d["year"].dropna().astype(int)))
            log(f"  [{i}/{len(catalogue)}] {ref} ok rows={len(d)} years={yrs[:1]}..{yrs[-1:]}  {str(rec.title)[:60]}")
        except Exception as e:  # noqa: BLE001
            status["error"] += 1
            log(f"  [{i}/{len(catalogue)}] {ref} ERROR {type(e).__name__}: {str(e)[:80]}")
    log(f"static tables: {status}")
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=LONG_COLUMNS)


# ---------------------------------------------------------------------------
# Dynamic tables ("Tabel Dinamis"): variables with region x category x year cells.
# Many provinces publish "Penduduk menurut Agama" only here, not as static tables.
# ---------------------------------------------------------------------------

def list_vars(session, domain: str, keyword: str, key: str, lang: str = "ind") -> List[dict]:
    out, page = [], 1
    while True:
        url = f"{BASE}/list/model/var/lang/{lang}/domain/{domain}/keyword/{keyword}/page/{page}/key/{key}"
        js = _get_json(session, url)
        if js.get("data-availability") != "available" or not js.get("data"):
            break
        meta, rows = js["data"][0], js["data"][1]
        for r in rows:
            r["domain"] = domain
        out.extend(rows)
        if page >= int(meta.get("pages", 1)):
            break
        page += 1
    return out


def search_vars_all_provinces(session, key: str, keyword: str = "agama", sleep_s: float = 0.2, log=print,
                              level: str = "province", provinces: Optional[List[str]] = None,
                              keywords: Optional[Sequence[str]] = None, skip_domains: Optional[set] = None,
                              on_domain=None) -> pd.DataFrame:
    keywords = list(keywords or ([keyword] if keyword != "agama" else KEYWORDS))
    rows, seen = [], set()
    for domain, prov, name in _domains_to_scan(session, key, level, provinces, log):
        if skip_domains and domain in skip_domains:
            continue
        n, start = 0, len(rows)
        for kw in keywords:
            try:
                found = list_vars(session, domain, kw, key)
            except RuntimeError as e:
                log(f"  {domain} {name}: {e}")
                continue
            for r in found:
                k = (domain, str(r.get("var_id")))
                if k in seen:
                    continue
                seen.add(k)
                n += 1
                rows.append({"domain": domain, "province_code": prov, "domain_name": name, "var_id": r.get("var_id"),
                             "title": r.get("title"), "subj": r.get("subj"), "vertical": r.get("vertical"),
                             "unit": r.get("unit"), "notes": r.get("notes"), **classify_title(r.get("title"))})
            time.sleep(sleep_s)
        log(f"  {domain} {name}: {n} variables")
        if on_domain:
            on_domain(domain, rows[start:])
    cols = ["domain", "province_code", "domain_name", "var_id", "title", "subj", "vertical", "unit", "notes",
            "about_religion", "by_unit", "is_percent"]
    return pd.DataFrame(rows, columns=cols)


DEFAULT_TH = "125;124"  # BPS year ids are year - 1900; the data endpoint accepts at most 2 per call


def list_years(session, domain: str, var_id: str | int, key: str, lang: str = "ind") -> List[dict]:
    """Years available for a variable: [{th_id, th}]. Empty if the endpoint fails."""
    url = f"{BASE}/list/model/th/lang/{lang}/domain/{domain}/var/{var_id}/key/{key}"
    try:
        js = _get_json(session, url)
    except RuntimeError:
        return []
    data = js.get("data") or []
    rows = data[1] if len(data) > 1 and isinstance(data[1], list) else []
    return [{"th_id": r.get("th_id"), "th": r.get("th")} for r in rows if isinstance(r, dict)]


def view_data(session, domain: str, var_id: str | int, key: str, lang: str = "ind",
              th: Optional[str] = None) -> dict:
    """The data endpoint requires `th`: year ids joined by ';', at most 2 per call."""
    th = th or DEFAULT_TH
    url = f"{BASE}/list/model/data/lang/{lang}/domain/{domain}/var/{var_id}/th/{th}/key/{key}"
    return _get_json(session, url)


def view_data_all_years(session, domain: str, var_id: str | int, key: str, lang: str = "ind",
                        sleep_s: float = 0.3) -> dict:
    """Fetch every available year two at a time and merge into one response dict
    (vervar/var/turvar/turtahun from the first answer, tahun and datacontent unioned)."""
    years = list_years(session, domain, var_id, key, lang)
    ids = [str(y["th_id"]) for y in years if y.get("th_id") is not None]
    if not ids:
        return view_data(session, domain, var_id, key, lang)
    merged: dict = {}
    for i in range(0, len(ids), 2):
        js = view_data(session, domain, var_id, key, lang, th=";".join(ids[i:i + 2]))
        if js.get("data-availability") != "available":
            continue
        if not merged:
            merged = {k: v for k, v in js.items() if k not in ("tahun", "datacontent")}
            merged["tahun"], merged["datacontent"] = [], {}
        seen = {t["val"] for t in merged["tahun"]}
        merged["tahun"].extend(t for t in js.get("tahun", []) if t["val"] not in seen)
        merged["datacontent"].update(js.get("datacontent") or {})
        time.sleep(sleep_s)
    return merged or {"data-availability": "not-available", "message": "no year returned data"}


def parse_dynamic(js: dict, province_code: str, ref: str, source: str = "bpsvar") -> pd.DataFrame:
    """BPS dynamic-table JSON -> long rows. datacontent keys are the concatenation of
    vervar (region) + var + turvar (category) + tahun + turtahun ids, so we rebuild
    every combination and look it up instead of splitting the key."""
    if js.get("data-availability") != "available":
        return pd.DataFrame(columns=LONG_COLUMNS)
    def _dicts(xs):
        return [x for x in (xs or []) if isinstance(x, dict)]
    vervar = _dicts(js.get("vervar"))
    var = (_dicts(js.get("var")) or [{}])[0]
    turvar = _dicts(js.get("turvar")) or [{"val": 0, "label": ""}]
    tahun = _dicts(js.get("tahun"))
    turtahun = _dicts(js.get("turtahun")) or [{"val": 0, "label": ""}]
    content = js.get("datacontent") or {}
    rows = []
    for vv in vervar:
        region = strip_tags(str(vv.get("label", ""))).strip()
        if not is_unit_name(region):
            continue
        # BPS often prefixes the label with the unit's own code: '3308 Kabupaten Magelang'
        m_code = re.match(r"^(\d{4})\s+\S", region)
        code_from_label = m_code.group(1) if m_code and not m_code.group(1).endswith("00") else None
        region_nm = re.sub(r"^\d+\s*", "", norm_label(region))
        for tv in turvar:
            rel = canonical_religion(tv.get("label", ""))
            if rel is None and len(turvar) > 1:
                continue
            if rel is None:
                rel = canonical_religion(var.get("label", "")) or "total"
            for th in tahun:
                for tt in turtahun:
                    k = f"{vv['val']}{var.get('val', '')}{tv['val']}{th['val']}{tt['val']}"
                    if k not in content:
                        continue
                    nm = region_nm
                    is_prov = nm.startswith("provinsi") or nm.replace(" ", "") == norm_label(PROVINCES.get(province_code, "")).replace(" ", "") \
                        or nm in {"jumlah", "total"} or (m_code is not None and m_code.group(1).endswith("00"))
                    rows.append({"source": source, "province_code": province_code, "unit_code": code_from_label,
                                 "unit_name": "__PROVINCE__" if is_prov else region,
                                 "year": year_from_text(th.get("label", "")), "semester": None,
                                 "religion": rel, "count": parse_count(content[k]), "ref": ref})
    df = pd.DataFrame(rows, columns=LONG_COLUMNS)
    df["level"] = df["unit_name"].map(unit_level)
    df["unit_name_norm"] = df["unit_name"].map(norm_unit_name)
    return df


def fetch_vars(session, catalogue: pd.DataFrame, key: str, sleep_s: float = 0.3,
               raw_dir: Optional[str] = None, log=print) -> pd.DataFrame:
    import json
    from pathlib import Path
    parts, status = [], {"ok": 0, "empty": 0, "error": 0}
    for i, rec in enumerate(catalogue.itertuples(index=False), 1):
        ref = f"bpsvar:{rec.domain}:{rec.var_id}"
        raw = Path(raw_dir) / f"bps_var_{rec.domain}_{rec.var_id}.json" if raw_dir else None
        try:
            js = None
            if raw is not None and raw.exists() and raw.stat().st_size > 0:
                cached = json.loads(raw.read_text(encoding="utf-8"))
                if cached.get("data-availability") == "available":
                    js = cached
            if js is None:
                js = view_data_all_years(session, rec.domain, rec.var_id, key, sleep_s=sleep_s)
                if raw is not None:
                    raw.parent.mkdir(parents=True, exist_ok=True)
                    raw.write_text(json.dumps(js, ensure_ascii=False), encoding="utf-8")
                time.sleep(sleep_s)
            d = parse_dynamic(js, str(rec.province_code), ref)
            d = rollup_kabupaten_domain(d, str(rec.domain), getattr(rec, "domain_name", None))
            if d.empty:
                status["empty"] += 1
                log(f"  [{i}/{len(catalogue)}] {ref} EMPTY avail={js.get('data-availability')} status={js.get('status')} "
                    f"msg={str(js.get('message'))[:60]} keys={list(js.keys())[:8]}  {str(rec.title)[:40]}")
                continue
            parts.append(d)
            status["ok"] += 1
            yrs = sorted(set(d["year"].dropna().astype(int)))
            log(f"  [{i}/{len(catalogue)}] {ref} ok rows={len(d)} years={yrs[:1]}..{yrs[-1:]}  {str(rec.title)[:60]}")
        except Exception as e:  # noqa: BLE001
            status["error"] += 1
            log(f"  [{i}/{len(catalogue)}] {ref} ERROR {type(e).__name__}: {str(e)[:80]}")
    log(f"dynamic tables: {status}")
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=LONG_COLUMNS)


def is_kabupaten_domain(domain: str) -> bool:
    return len(str(domain)) == 4 and not str(domain).endswith("00")


def _rows_equal_to_sum_of_others(d: pd.DataFrame, tol: float = 0.01) -> pd.Series:
    """Mark unit rows whose count equals the sum of every other unit's count (within
    `tol`), checked on the religion with the largest total per year: BPS tables often
    label the total row with the kabupaten name or the year rather than 'Jumlah'."""
    flag = pd.Series(False, index=d.index)
    for yr, g in d.groupby("year", dropna=False):
        g = g.dropna(subset=["count"])
        if g.empty:
            continue
        rel = g.groupby("religion")["count"].sum().idxmax()
        gr = g[g["religion"] == rel]
        if gr["unit_name"].nunique() < 3:
            continue
        per_unit = gr.groupby("unit_name")["count"].sum().sort_values(ascending=False)
        top = per_unit.iloc[0]
        if top <= 0:
            continue
        # candidates: rows within 3% of the largest (this year's and previous years' totals);
        # they are totals if the largest equals the sum of everything else
        cands = per_unit[per_unit >= 0.97 * top]
        rest = per_unit[per_unit < 0.97 * top].sum()
        if len(cands) < len(per_unit) and abs(top - rest) <= tol * max(top, rest):
            for u in cands.index:
                flag |= (d["unit_name"] == u) & ((d["year"] == yr) | (d["year"].isna() & pd.isna(yr)))
    return flag


def rollup_kabupaten_domain(df: pd.DataFrame, domain: str, domain_name: Optional[str]) -> pd.DataFrame:
    """For a table served by a kabupaten/kota BPS domain the rows are kecamatan (or
    kelurahan). Return the kecamatan rows tagged level='kecamatan' plus one row per
    (year, religion) for the kabupaten itself, with unit_code = domain: the table's
    total row when it has one, otherwise the sum of the kecamatan rows."""
    if df.empty or not is_kabupaten_domain(domain):
        return df
    d = df.drop_duplicates(["unit_name", "year", "religion", "count"]).copy()
    # total row, in order of trust: labelled 'Jumlah' > equals the sum of the others >
    # carries the kabupaten's own name (a kecamatan may share that name, so last)
    is_total = d["unit_name"] == "__PROVINCE__"
    if not is_total.any():
        is_total = _rows_equal_to_sum_of_others(d)
    if not is_total.any() and domain_name:
        dn = norm_unit_name(domain_name)
        nm = d["unit_name"].map(norm_unit_name)
        by_name = (nm == dn) | nm.str.match(r"^(kabupaten|kota|kab)\s+" + re.escape(dn) + r"$") \
            | nm.str.match(r"^" + re.escape(dn) + r"\s+(19|20)\d\d$")
        # a kecamatan often carries the kabupaten's name: accept the name match only if that
        # row is the largest and clearly dominates the second largest (a total must be)
        if by_name.any():
            big = d.dropna(subset=["count"])
            rel = big.groupby("religion")["count"].sum().idxmax() if len(big) else None
            per_unit = big[big["religion"] == rel].groupby("unit_name")["count"].sum().sort_values(ascending=False)
            named = set(d.loc[by_name, "unit_name"])
            if len(per_unit) >= 2 and per_unit.index[0] in named and per_unit.iloc[0] >= 1.5 * per_unit.iloc[1]:
                is_total = by_name & (d["unit_name"] == per_unit.index[0])
    kec = d[~is_total].copy()
    kec["level"] = "kecamatan"
    kec["unit_code"] = None
    tot = d[is_total].copy()
    if len(tot):  # several total-like rows: keep one per (year, religion), the largest
        tot = tot.sort_values("count", ascending=False).drop_duplicates(["year", "religion"], keep="first")
    if tot.empty:
        tot = (kec.dropna(subset=["count"]).groupby(["year", "religion"], dropna=False)["count"].sum()
               .reset_index())
        tot["source"], tot["ref"], tot["semester"] = "bps_kabsum", d["ref"].iloc[0], None
        tot["province_code"] = d["province_code"].iloc[0]
    tot["unit_code"] = str(domain).zfill(4)
    tot["unit_name"] = domain_name or str(domain)
    tot["level"] = "kabupaten"
    tot["unit_name_norm"] = norm_unit_name(tot["unit_name"].iloc[0]) if len(tot) else None
    cols = LONG_COLUMNS + ["level", "unit_name_norm"]
    return pd.concat([tot.reindex(columns=cols), kec.reindex(columns=cols)], ignore_index=True)


def header_report(html: str) -> List[dict]:
    """For debugging: every grid's chosen header row with each cell's religion mapping."""
    out = []
    for grid in grid_tables(html):
        scores = [len({canonical_religion(c) for c in row} - {None, "total"}) for row in grid]
        if not scores:
            continue
        h = max(range(len(grid)), key=lambda i: scores[i])
        out.append({"header_row_index": h, "score": scores[h], "n_rows": len(grid),
                    "cells": [(c, canonical_religion(c)) for c in grid[h] if c],
                    "first_data_rows": [r[:9] for r in grid[h + 1:h + 4]]})
    return out


def kabupaten_code_table(session, key: str, log=print) -> pd.DataFrame:
    """unit_code, unit_name for every kabupaten/kota BPS domain (domain id = BPS code)."""
    rows = []
    for code, name in PROVINCES.items():
        try:
            doms = list_domains(session, key, code)
        except RuntimeError as e:
            log(f"  {code} {name}: {e}")
            continue
        for d in doms:
            if is_kabupaten_domain(d["domain_id"]):
                rows.append({"unit_code": d["domain_id"], "unit_name": d["domain_name"], "province_code": code})
        log(f"  {code} {name}: {len(doms)} domains")
        time.sleep(0.2)
    return pd.DataFrame(rows, columns=["unit_code", "unit_name", "province_code"])
