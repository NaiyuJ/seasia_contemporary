"""CKAN open-data portals (data.go.id and provincial Satu Data): Kemnaker TKA datasets.

CKAN exposes /api/3/action/package_search and resources with direct file URLs.
Tabular resources (CSV/XLSX) are downloaded and mapped to long form by guessing
column roles from headers; pass explicit column names when the guess is wrong.
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import List, Optional

import pandas as pd

from konghucu.religion import norm_label, parse_count, year_from_text

from .nationality import LONG_COLUMNS, canonical_nationality, canonical_permit, header_role

DEFAULT_PORTALS = ["https://katalog.data.go.id", "https://data.go.id"]
NAT_COL_RE = re.compile(r"negara|kebangsaan|kewarganegaraan|asal|nationality|country", re.I)
REGION_COL_RE = re.compile(r"provinsi|kabupaten|kota|wilayah|daerah|kanim|kantor|region|nama_wil|bps_nama", re.I)
YEAR_COL_RE = re.compile(r"tahun|year|periode", re.I)
COUNT_COL_RE = re.compile(r"jumlah|total|nilai|value|tka|orang|count|banyak", re.I)
PERMIT_COL_RE = re.compile(r"izin|jenis|permit|kategori", re.I)


def search_packages(session, query: str, portal: str, rows: int = 50) -> List[dict]:
    r = session.get(f"{portal}/api/3/action/package_search", params={"q": query, "rows": rows}, timeout=60)
    if r.status_code != 200:
        return []
    js = r.json()
    out = []
    for pkg in js.get("result", {}).get("results", []):
        for res in pkg.get("resources", []):
            fmt = (res.get("format") or "").upper()
            if fmt in ("CSV", "XLSX", "XLS", "JSON"):
                out.append({"portal": portal, "package": pkg.get("name"), "title": pkg.get("title"),
                            "organization": (pkg.get("organization") or {}).get("title"),
                            "resource_id": res.get("id"), "resource_name": res.get("name"), "format": fmt,
                            "url": res.get("url"), "modified": res.get("last_modified") or pkg.get("metadata_modified")})
    return out


def search_all(session, queries=("tenaga kerja asing", "TKA negara asal", "orang asing kebangsaan"),
               portals=DEFAULT_PORTALS) -> pd.DataFrame:
    rows, seen = [], set()
    for portal in portals:
        for q in queries:
            for r in search_packages(session, q, portal):
                if r["url"] in seen:
                    continue
                seen.add(r["url"])
                rows.append(r)
    return pd.DataFrame(rows, columns=["portal", "package", "title", "organization", "resource_id",
                                       "resource_name", "format", "url", "modified"])


def download_resource(session, url: str, dest: Path) -> Path:
    r = session.get(url, timeout=120)
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return dest


def read_tabular(path: Path) -> pd.DataFrame:
    suf = path.suffix.lower()
    if suf in (".xlsx", ".xls"):
        return pd.read_excel(path)
    if suf == ".json":
        return pd.json_normalize(pd.read_json(path).to_dict("records"))
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "latin-1"):
        try:
            txt = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sep = ";" if txt.count(";") > txt.count(",") else ","
    return pd.read_csv(io.StringIO(txt), sep=sep)


def _pick(cols, pat):
    for c in cols:
        if pat.search(str(c)):
            return c
    return None


def table_to_long(df: pd.DataFrame, ref: str, source: str = "ckan", province_code: Optional[str] = None,
                  year: Optional[int] = None, region_level: str = "province",
                  nat_col=None, region_col=None, year_col=None, count_col=None, permit_col=None) -> pd.DataFrame:
    cols = list(df.columns)
    nat_col = nat_col or _pick(cols, NAT_COL_RE)
    region_col = region_col or _pick([c for c in cols if c != nat_col], REGION_COL_RE)
    year_col = year_col or _pick(cols, YEAR_COL_RE)
    permit_col = permit_col or _pick([c for c in cols if c not in (nat_col, region_col, year_col)], PERMIT_COL_RE)
    rows = []
    if nat_col is not None:
        count_col = count_col or _pick([c for c in cols if c not in (nat_col, region_col, year_col, permit_col)], COUNT_COL_RE)
        if count_col is None:
            raise ValueError(f"no count column found in {cols}")
        for rec in df.to_dict("records"):
            nat = canonical_nationality(rec[nat_col])
            if nat is None:
                continue
            rows.append({"source": source, "province_code": province_code,
                         "region_name": str(rec[region_col]).strip() if region_col else None,
                         "region_level": region_level if region_col else "national",
                         "nationality": nat,
                         "permit_type": canonical_permit(rec[permit_col]) if permit_col else "TKA",
                         "year": (year_from_text(rec[year_col]) if year_col else None) or year,
                         "count": parse_count(rec[count_col]), "ref": ref})
    else:  # wide: nationality columns
        nat_cols = [(c, canonical_nationality(c)) for c in cols if header_role(c)[0] == "nationality"]
        if not nat_cols:
            raise ValueError(f"no nationality column or nationality headers in {cols}")
        for rec in df.to_dict("records"):
            for c, nat in nat_cols:
                rows.append({"source": source, "province_code": province_code,
                             "region_name": str(rec[region_col]).strip() if region_col else None,
                             "region_level": region_level if region_col else "national",
                             "nationality": nat, "permit_type": "TKA",
                             "year": (year_from_text(rec[year_col]) if year_col else None) or year,
                             "count": parse_count(rec[c]), "ref": ref})
    return pd.DataFrame(rows, columns=LONG_COLUMNS)
