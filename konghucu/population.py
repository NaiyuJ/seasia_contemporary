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

NOT_POP_RE = (r"agama|umur|usia|kelompok|miskin|kerja|kegiatan|angkatan|laju|kepadatan|rasio|persen|rumah tangga|generasi|"
              r"kecamatan|desa|kelurahan|pendidikan|kawin|status|lahir|migrasi|cacat|disabilitas|wna|asing|perkotaan|perdesaan|"
              r"pedesaan|penerima|peserta|per km|sex|pertumbuhan|konsumsi|internet|telepon|pengeluaran|pangan|pengangguran|"
              r"bekerja|jam|lapangan|triwulan|bukan")
# words a plain population-by-kabupaten title may consist of, besides a province name
POP_WORDS = {"jumlah", "proyeksi", "penduduk", "menurut", "kabupaten", "kota", "kabupaten/kota", "kab", "kab/kota", "kabupeten",
             "dan", "jenis", "kelamin", "provinsi", "prov", "di", "hasil", "sensus", "survei", "antar", "supas", "sp",
             "jiwa", "ribu", "orang", "laki-laki", "laki", "perempuan", "l+p", "laki-laki+perempuan", "laki+perempuan", "termasuk", "per",
             "tahun", "lfsp", "registrasi", "total", "seluruh", "wilayah", "indonesia", "menurutkabupaten"}
PROVINCE_WORDS = {w for name in PROVINCES.values() for w in norm_label(name).split()} | {"d.i.", "daerah", "istimewa", "dki"}
TOTAL_LABEL_RE = r"^(jumlah|total|laki-laki \+ perempuan|l\s*\+\s*p|laki-laki dan perempuan)( \(.*\))?$"


def classify_population_title(title: object) -> dict:
    """True for a title that is plain population by kabupaten/kota (possibly by sex, used
    through its total; possibly a projection or census result), false for anything
    about a subgroup (age, labour, poverty, urban) or a rate."""
    t = norm_label(title).strip()
    t = re.sub(r"\[[^\]]*\]", " ", t)  # '[Proyeksi SP2010]' tags
    if re.search(NOT_POP_RE, t) or "penduduk" not in t:
        return {"about_population": False}
    if not re.match(r"^(proyeksi |jumlah |total )?penduduk\b", t):
        return {"about_population": False}
    words = re.sub(r"[(),.;:*-]+", " ", t).split()
    extra = [w for w in words if w not in POP_WORDS and w not in PROVINCE_WORDS and not re.fullmatch(r"(19|20)\d{2}(/\d+)?", w)
             and not re.fullmatch(r"(sp|supas|lfsp)\d{4}", w)]
    if extra:
        return {"about_population": False}
    one_sex = bool(re.search(r"\blaki", t)) != bool(re.search(r"\bperempuan", t))  # one sex only, not L+P
    return {"about_population": not one_sex}


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


def _scale(unit: object, title: object = "") -> float:
    u = norm_label(unit)
    if "ribu" in u or "000" in u:
        return 1000.0
    if "juta" in u:
        return 1e6
    if u in ("", "tidak ada satuan", "none") and "ribu" in norm_label(title):
        return 1000.0  # unit missing but the title says '(Ribu Jiwa)'
    return 1.0


def parse_population(js: dict, province_code: str, ref: str) -> pd.DataFrame:
    """Dynamic-table JSON -> one row per unit x year. A variable with a single category
    is taken as is; one split by sex (or anything else) is used only through its
    'Jumlah'/'Total' category, so parts are never mistaken for the whole."""
    from .bps_api import parse_dynamic
    turvar = [x for x in (js.get("turvar") or []) if isinstance(x, dict)]
    if len(turvar) > 1:
        tot = [tv for tv in turvar if re.search(TOTAL_LABEL_RE, norm_label(tv.get("label", "")))]
        if not tot:
            return pd.DataFrame()
        js = dict(js, turvar=[tot[0]])
    d = parse_dynamic(js, province_code, ref, source="bpspop")
    return d[(d["religion"] == "total") & (d["unit_name"] != "__PROVINCE__") & d["count"].notna()]


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
            d = parse_population(js, str(rec.province_code), ref)
            if d.empty:
                log(f"  [{i}/{len(catalogue)}] {ref} EMPTY (no data, or split by category without a 'Jumlah')  "
                    f"{str(rec.title)[:50]}")
                continue
            d = d.copy()
            sc = _scale(getattr(rec, "unit", ""), getattr(rec, "title", ""))
            if sc > 1 and d["count"].median() * sc > PLAUSIBLE_MAX and d["count"].median() <= PLAUSIBLE_MAX:
                log(f"  {ref}: unit says thousands but values are already persons; not scaled")
                sc = 1.0  # Sulawesi Tenggara '(Ribu Jiwa)' in the title, persons in the cells
            d["population"] = d["count"] * sc
            yrs = sorted(set(d["year"].dropna().astype(int)))
            log(f"  [{i}/{len(catalogue)}] {ref} ok units={d['unit_name'].nunique()} years={yrs[:1]}..{yrs[-1:]}  "
                f"{str(rec.title)[:50]}")
            parts.append(d[["source", "province_code", "unit_code", "unit_name", "level", "unit_name_norm", "year",
                            "population", "ref"]])
        except Exception as e:  # noqa: BLE001
            log(f"  [{i}/{len(catalogue)}] {ref} ERROR {type(e).__name__}: {str(e)[:80]}")
    cols = ["source", "province_code", "unit_code", "unit_name", "level", "unit_name_norm", "year", "population", "ref"]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols)


PLAUSIBLE_MIN, PLAUSIBLE_MAX = 3_000, 7_000_000  # smallest kabupaten ~ 10k, Bogor ~ 5.5M


def reconcile_population(long: pd.DataFrame) -> pd.DataFrame:
    """One row per unit-year. Within a province the variable covering the most unit-years
    is the primary series; other variables fill only the unit-years it lacks, so a unit's
    series is internally consistent instead of a median that mixes definitions (a 2014
    labour-force count averaged with a population count gave Sulawesi Selatan 2.4x
    spreads). n_refs and spread report how far the other variables are from the chosen
    value. Values outside the plausible range for a kabupaten are ignored."""
    d = long[long["unit_code"].notna() & long["year"].notna() & long["population"].notna()].copy()
    d["year"] = d["year"].astype(int)
    d["unit_code"] = d["unit_code"].astype(str).str.zfill(4)
    d = d[d["population"].between(PLAUSIBLE_MIN, PLAUSIBLE_MAX)]
    cover = d.groupby("ref").size().rename("cover")
    d = d.merge(cover, left_on="ref", right_index=True)
    d = d.sort_values(["unit_code", "year", "cover", "ref"], ascending=[True, True, False, True])
    best = d.drop_duplicates(["unit_code", "year"], keep="first")[["unit_code", "year", "population", "ref"]]
    g = d.groupby(["unit_code", "year"])["population"]
    stats = pd.DataFrame({"n_refs": g.nunique(), "spread": (g.max() / g.min()).round(3)}).reset_index()
    out = best.merge(stats, on=["unit_code", "year"])
    return out.sort_values(["unit_code", "year"]).reset_index(drop=True)
