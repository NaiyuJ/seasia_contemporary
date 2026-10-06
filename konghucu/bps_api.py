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
from .religion import (LONG_COLUMNS, PROVINCES, canonical_religion, norm_label, parse_count,
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
                   r"guru|murid|penyuluh|pemuka|peribadatan|pemakaman|dprd|desa|nikah|perkara|kegiatan keagamaan|orang rimba|jemaah|haji")
KEYWORDS = ("agama", "pemeluk", "umat", "penganut")


def classify_title(title: object) -> dict:
    t = norm_label(title)
    about = bool(re.search(RELIGION_POP_RE, t)) and not re.search(NOT_RELIGION_RE, t)
    return {"about_religion": about,
            "by_unit": about and bool(re.search(r"kabupaten|kota|kab/kota|kecamatan", t)),
            "is_percent": "persentase" in t or "persen" in t}


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


def _is_number_like(cell: str) -> bool:
    c = (cell or "").strip()
    return bool(c) and parse_count(c) is not None and not re.search(r"[A-Za-z]{3,}", c)


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
            rel_cols.append((j, rel, yr))
        if not rel_cols:
            continue
        data_start = h + 1
        if header2 is not None:
            nonempty = [c for c in header2 if c and c.strip()]
            only_years = bool(nonempty) and all(re.fullmatch(r"\d{4}(/\d{2,4})?", c.strip()) for c in nonempty)
            if only_years or not any(_is_number_like(c) for c in header2):
                data_start = h + 2  # header2 was a header row (years or sub-labels), not data
        for row in grid[data_start:]:
            name = next((c.strip() for c in row if c and c.strip() and not _is_number_like(c)), None)
            if not name:
                continue
            nm = norm_label(name)
            if nm in {"kabupaten/kota", "kabupaten", "kota", "wilayah", "daerah", "kecamatan", "no", "no."} \
                    or canonical_religion(nm) is not None and nm not in {"jumlah", "total"}:
                continue
            vals = [(j, rel, yr, parse_count(row[j]) if j < len(row) else None) for j, rel, yr in rel_cols]
            if all(v is None for *_, v in vals):
                continue
            prov_nm = norm_label(PROVINCES.get(province_code, "")).replace(" ", "")
            is_prov_total = nm.replace(" ", "") == prov_nm or nm.startswith("provinsi") \
                or nm.startswith("jumlah") or nm.startswith("total")
            for j, rel, yr, v in vals:
                frames.append({"source": source, "province_code": province_code, "unit_code": None,
                               "unit_name": "__PROVINCE__" if is_prov_total else name,
                               "year": yr or year, "semester": None, "religion": rel, "count": v, "ref": ref})
    df = pd.DataFrame(frames, columns=LONG_COLUMNS)
    df["level"] = df["unit_name"].map(unit_level)
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
    return [{"th_id": r.get("th_id"), "th": r.get("th")} for r in rows]


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


def parse_dynamic(js: dict, province_code: str, ref: str, source: str = "bps") -> pd.DataFrame:
    """BPS dynamic-table JSON -> long rows. datacontent keys are the concatenation of
    vervar (region) + var + turvar (category) + tahun + turtahun ids, so we rebuild
    every combination and look it up instead of splitting the key."""
    if js.get("data-availability") != "available":
        return pd.DataFrame(columns=LONG_COLUMNS)
    vervar = js.get("vervar") or []
    var = (js.get("var") or [{}])[0]
    turvar = js.get("turvar") or [{"val": 0, "label": ""}]
    tahun = js.get("tahun") or []
    turtahun = js.get("turtahun") or [{"val": 0, "label": ""}]
    content = js.get("datacontent") or {}
    rows = []
    for vv in vervar:
        region = str(vv.get("label", "")).strip()
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
                    nm = norm_label(region)
                    is_prov = nm.startswith("provinsi") or nm.replace(" ", "") == norm_label(PROVINCES.get(province_code, "")).replace(" ", "") \
                        or nm in {"jumlah", "total"}
                    rows.append({"source": source, "province_code": province_code, "unit_code": None,
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
            if raw is not None and raw.exists() and raw.stat().st_size > 0:
                js = json.loads(raw.read_text(encoding="utf-8"))
            else:
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


def rollup_kabupaten_domain(df: pd.DataFrame, domain: str, domain_name: Optional[str]) -> pd.DataFrame:
    """For a table served by a kabupaten/kota BPS domain the rows are kecamatan (or
    kelurahan). Return the kecamatan rows tagged level='kecamatan' plus one row per
    (year, religion) for the kabupaten itself, with unit_code = domain: the table's
    total row when it has one, otherwise the sum of the kecamatan rows."""
    if df.empty or not is_kabupaten_domain(domain):
        return df
    d = df.copy()
    is_total = d["unit_name"] == "__PROVINCE__"
    kec = d[~is_total].copy()
    kec["level"] = "kecamatan"
    kec["unit_code"] = None
    tot = d[is_total].copy()
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
