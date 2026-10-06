"""Official kabupaten/kota population from BPS dynamic tables, as the denominator for
religion shares and as the anchor for sanity-checking religion totals.

Every province domain publishes a dynamic variable like "Jumlah Penduduk Menurut
Kabupaten/Kota (Jiwa)" (annual, projection-based between censuses). We list the
variables whose title is about plain population by kabupaten, fetch all their years,
attach codes, and reconcile several candidate variables per unit-year by the median.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import List, Optional

import pandas as pd

from . import bps_api
from .religion import PROVINCES, norm_label

POP_TITLE_RE = (r"^(jumlah )?penduduk( menurut kabupaten/kota| kabupaten/kota| per kabupaten/kota)?( \(.*\))?"
                r"( hasil .*| di provinsi .*| provinsi .*| menurut kabupaten/kota .*)?$")
NOT_POP_RE = (r"agama|jenis kelamin|umur|usia|kelompok|miskin|kerja|angkatan|laju|kepadatan|rasio|persen|rumah tangga|"
              r"kecamatan|desa|kelurahan|pendidikan|kawin|status|lahir|migrasi|cacat|disabilitas|wna|asing|"
              r"penerima|peserta|\bkabupaten (?!hasil|per\b|menurut|dan\b|di\b|dalam|tahun)[a-z]|"
              r"(?<!kabupaten/)\bkota (?!hasil|per\b|menurut|dan\b|di\b|dalam|tahun)[a-z]|per km|sex|pertumbuhan")


def classify_population_title(title: object) -> dict:
    t = norm_label(title).strip()
    return {"about_population": bool(re.search(POP_TITLE_RE, t)) and not re.search(NOT_POP_RE, t)}


def search_population_vars(session, key: str, provinces: Optional[List[str]] = None, sleep_s: float = 0.2,
                           log=print) -> pd.DataFrame:
    rows = []
    for code, name in PROVINCES.items():
        if provinces and code not in provinces:
            continue
        domain = f"{code}00"
        try:
            found = bps_api.list_vars(session, domain, "penduduk", key)
        except RuntimeError as e:
            log(f"  {domain} {name}: {e}")
            continue
        n = 0
        for r in found:
            c = classify_population_title(r.get("title"))
            rows.append({"domain": domain, "province_code": code, "domain_name": name, "var_id": r.get("var_id"),
                         "title": r.get("title"), "unit": r.get("unit"), "subj": r.get("subj"), **c})
            n += c["about_population"]
        log(f"  {domain} {name}: {len(found)} variables, {n} about population by kabupaten/kota")
        time.sleep(sleep_s)
    return pd.DataFrame(rows, columns=["domain", "province_code", "domain_name", "var_id", "title", "unit", "subj",
                                       "about_population"])


def _scale(unit: object) -> float:
    u = norm_label(unit)
    if "ribu" in u or "000" in u:
        return 1000.0
    if "juta" in u:
        return 1e6
    return 1.0


def fetch_population(session, catalogue: pd.DataFrame, key: str, raw_dir: Optional[str] = None,
                     sleep_s: float = 0.3, log=print) -> pd.DataFrame:
    """Long table: province_code, unit_code (from the label prefix when BPS gives it),
    unit_name, year, population, ref. One row per variable x unit x year."""
    parts = []
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
                js = bps_api.view_data_all_years(session, rec.domain, rec.var_id, key, sleep_s=sleep_s)
                if raw is not None:
                    raw.parent.mkdir(parents=True, exist_ok=True)
                    raw.write_text(json.dumps(js, ensure_ascii=False), encoding="utf-8")
                time.sleep(sleep_s)
            d = bps_api.parse_dynamic(js, str(rec.province_code), ref, source="bpspop")
            d = d[(d["religion"] == "total") & (d["unit_name"] != "__PROVINCE__") & d["count"].notna()]
            if d.empty:
                log(f"  [{i}/{len(catalogue)}] {ref} EMPTY  {str(rec.title)[:50]}")
                continue
            d = d.copy()
            d["population"] = d["count"] * _scale(getattr(rec, "unit", ""))
            yrs = sorted(set(d["year"].dropna().astype(int)))
            log(f"  [{i}/{len(catalogue)}] {ref} ok units={d['unit_name'].nunique()} years={yrs[:1]}..{yrs[-1:]}  "
                f"{str(rec.title)[:50]}")
            parts.append(d[["source", "province_code", "unit_code", "unit_name", "level", "unit_name_norm", "year",
                            "population", "ref"]])
        except Exception as e:  # noqa: BLE001
            log(f"  [{i}/{len(catalogue)}] {ref} ERROR {type(e).__name__}: {str(e)[:80]}")
    cols = ["source", "province_code", "unit_code", "unit_name", "level", "unit_name_norm", "year", "population", "ref"]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols)


def reconcile_population(long: pd.DataFrame) -> pd.DataFrame:
    """One row per unit-year: median across variables, with the number of variables and
    the max/min spread so disagreements between BPS series are visible."""
    d = long[long["unit_code"].notna() & long["year"].notna() & long["population"].notna()].copy()
    d["year"] = d["year"].astype(int)
    d = d[d["population"] > 0]
    g = d.groupby(["unit_code", "year"])["population"]
    out = g.median().rename("population").reset_index()
    out["n_refs"] = g.nunique().values
    out["spread"] = (g.max() / g.min()).round(3).values
    return out.sort_values(["unit_code", "year"]).reset_index(drop=True)
