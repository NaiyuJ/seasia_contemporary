"""BPS Web API client for static tables ("penduduk menurut agama").

Register for a free key at https://webapi.bps.go.id and export BPS_API_KEY.
Domains: '0000' national, '1200' a province (2-digit code + '00'), '1201' a kabupaten.
"""
from __future__ import annotations

import os
import re
import time
from io import StringIO
from typing import Iterable, List, Optional

import pandas as pd

from .religion import (LONG_COLUMNS, PROVINCES, canonical_religion, norm_label, parse_count,
                       unit_level, norm_unit_name, year_from_text)

BASE = "https://webapi.bps.go.id/v1/api"


def get_key(key: Optional[str] = None) -> str:
    key = key or os.environ.get("BPS_API_KEY")
    if not key:
        raise RuntimeError("set BPS_API_KEY (free at https://webapi.bps.go.id); never paste it into chat")
    return key


def _get_json(session, url: str, retries: int = 3) -> dict:
    for attempt in range(retries):
        r = session.get(url, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503):
            time.sleep(2 ** attempt)
            continue
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


def view_static_table(session, domain: str, table_id: str | int, key: str, lang: str = "ind") -> dict:
    url = f"{BASE}/view/model/statictable/lang/{lang}/domain/{domain}/id/{table_id}/key/{key}"
    js = _get_json(session, url)
    return js.get("data") or {}


def search_all_provinces(session, key: str, keyword: str = "agama", sleep_s: float = 0.2) -> pd.DataFrame:
    rows = []
    for code in PROVINCES:
        for r in list_static_tables(session, f"{code}00", keyword, key):
            rows.append({"domain": r["domain"], "province_code": code, "table_id": r.get("table_id"),
                         "title": r.get("title"), "subj": r.get("subj"), "updt_date": r.get("updt_date"),
                         "excel": r.get("excel")})
        time.sleep(sleep_s)
    df = pd.DataFrame(rows, columns=["domain", "province_code", "table_id", "title", "subj", "updt_date", "excel"])
    # keep tables that are by kabupaten/kota and about religion
    mask = df["title"].fillna("").map(norm_label).str.contains("agama") & \
        df["title"].fillna("").map(norm_label).str.contains(r"kabupaten|kota|kab/kota|kabupaten/kota", regex=True)
    df["by_unit"] = mask
    return df


def _flatten_columns(cols) -> List[str]:
    out = []
    for c in cols:
        if isinstance(c, tuple):
            parts = [str(p) for p in c if not str(p).startswith("Unnamed")]
            out.append(" | ".join(dict.fromkeys(parts)))
        else:
            out.append(str(c))
    return out


def parse_religion_html(html: str, province_code: str, year: Optional[int], ref: str,
                        source: str = "bps") -> pd.DataFrame:
    """Parse a BPS 'penduduk menurut kabupaten/kota dan agama' HTML table into long form.

    Handles multi-level headers (e.g. a 'Agama' super-header over religion names, or
    year super-headers over religions). The first text column is the unit name."""
    tables = pd.read_html(StringIO(html), thousands=None)
    frames = []
    for t in tables:
        t.columns = _flatten_columns(t.columns)
        if t.shape[1] < 2:
            continue
        name_col = t.columns[0]
        rel_cols = [(c, canonical_religion(c), year_from_text(c)) for c in t.columns[1:]]
        rel_cols = [(c, r, y) for c, r, y in rel_cols if r is not None]
        if not rel_cols:
            continue
        for rec in t.itertuples(index=False):
            name = rec[0]
            if pd.isna(name):
                continue
            nm = norm_label(name)
            if not nm or nm in {"kabupaten/kota", "kabupaten", "kota", "wilayah", "daerah"}:
                continue
            is_prov_total = nm.replace(" ", "") in {norm_label(PROVINCES.get(province_code, "")).replace(" ", ""), "jumlah", "total"} \
                or nm.startswith("provinsi") or nm.startswith("jumlah") or nm.startswith("total")
            for i, (col, rel, col_year) in enumerate(rel_cols):
                val = parse_count(rec[t.columns.get_loc(col)])
                frames.append({"source": source, "province_code": province_code,
                               "unit_code": None,
                               "unit_name": ("__PROVINCE__" if is_prov_total else str(name).strip()),
                               "year": col_year or year, "semester": None, "religion": rel,
                               "count": val, "ref": ref})
    df = pd.DataFrame(frames, columns=LONG_COLUMNS)
    df["level"] = df["unit_name"].map(unit_level)
    df["unit_name_norm"] = df["unit_name"].map(norm_unit_name)
    return df


def fetch_tables(session, catalogue: pd.DataFrame, key: str, sleep_s: float = 0.3,
                 raw_dir: Optional[str] = None) -> pd.DataFrame:
    """Download and parse every row of `catalogue` (output of search_all_provinces, filtered)."""
    from pathlib import Path
    parts = []
    for rec in catalogue.itertuples(index=False):
        data = view_static_table(session, rec.domain, rec.table_id, key)
        html = data.get("table") or ""
        if raw_dir:
            p = Path(raw_dir)
            p.mkdir(parents=True, exist_ok=True)
            (p / f"bps_{rec.domain}_{rec.table_id}.html").write_text(html, encoding="utf-8")
        if not html:
            continue
        year = year_from_text(data.get("title") or rec.title)
        ref = f"bps:{rec.domain}:{rec.table_id}"
        try:
            parts.append(parse_religion_html(html, str(rec.province_code), year, ref))
        except ValueError:
            continue
        time.sleep(sleep_s)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=LONG_COLUMNS)
