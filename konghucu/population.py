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

NOT_POP_WORDS = ["agama", "umur", "usia", "kelompok", "miskin", "kerja", "bekerja", "kegiatan", "angkatan", "laju",
                 "kepadatan", "rasio", "persen", "persentase", "rumah tangga", "generasi", "kecamatan", "desa", "kelurahan",
                 "pendidikan", "kawin", "status", "lahir", "migrasi", "cacat", "disabilitas", "wna", "asing", "perkotaan",
                 "perdesaan", "pedesaan", "penerima", "peserta", "per km", "sex", "pertumbuhan", "konsumsi", "internet",
                 "telepon", "pengeluaran", "pangan", "pengangguran", "jam", "lapangan", "triwulan", "bukan", "angka",
                 "harapan", "sekolah", "menurut provinsi", "di indonesia", "wilayah", "suku", "anak", "lansia", "nik"]
NOT_POP_RE = "|".join(r"\b" + re.escape(w) + r"\b" for w in NOT_POP_WORDS)
# words a plain population-by-kabupaten title may consist of, besides a province name
POP_WORDS = {"jumlah", "proyeksi", "penduduk", "menurut", "kabupaten", "kota", "kabupaten/kota", "kab", "kab/kota", "kabupeten",
             "dan", "jenis", "kelamin", "provinsi", "prov", "di", "hasil", "sensus", "survei", "antar", "supas", "sp",
             "jiwa", "ribu", "orang", "laki-laki", "laki", "perempuan", "l+p", "laki-laki+perempuan", "laki+perempuan", "termasuk", "per",
             "tahun", "lfsp", "registrasi", "total", "seluruh", "menurutkabupaten"}
PROVINCE_WORDS = {w for name in PROVINCES.values() for w in norm_label(name).split()} | {"d", "i", "daerah", "istimewa", "dki"}
PROVINCE_KEYS = {norm_label(n).replace(" ", ""): c for c, n in PROVINCES.items()}
TOTAL_LABEL_RE = r"^(jumlah|total|laki-laki \+ perempuan|l\s*\+\s*p|laki-laki dan perempuan)( \(.*\))?$"


def classify_population_title(title: object) -> dict:
    """True for a title that is plain population by kabupaten/kota (possibly by sex, used
    through its total; possibly a projection or census result), false for anything
    about a subgroup (age, labour, poverty, urban) or a rate."""
    t = norm_label(title).strip()
    t = re.sub(r"\[[^\]]*\]", " ", t).strip()  # '[Proyeksi SP2010]' tags
    if re.search(NOT_POP_RE, t) or "penduduk" not in t:
        return {"about_population": False}
    if not re.match(r"^(proyeksi )?(jumlah |total )?penduduk\b", t):
        return {"about_population": False}
    words = re.sub(r"[(),.;:*+-]+", " ", t).split()
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


SEX_LABEL_RE = {"male": r"^laki", "female": r"^perempuan|^wanita"}
POP_LONG_COLS = ["source", "province_code", "unit_code", "unit_name", "level", "unit_name_norm", "year", "count", "ref"]


def parse_population(js: dict, province_code: str, ref: str, log=None) -> pd.DataFrame:
    """Dynamic-table JSON -> one row per unit x year. A variable with a single category
    is taken as is. One split by sex is used through its 'Jumlah'/'Total' category, or,
    when the table has only the two sexes, by adding them. Any other split is skipped."""
    from .bps_api import parse_dynamic
    turvar = [x for x in (js.get("turvar") or []) if isinstance(x, dict)]
    if len(turvar) > 1:
        labels = {str(tv.get("val")): norm_label(tv.get("label", "")) for tv in turvar}
        tot = [tv for tv in turvar if re.search(TOTAL_LABEL_RE, labels[str(tv.get("val"))])]
        if tot:
            js = dict(js, turvar=[tot[0]])
        else:
            sexes = [tv for tv in turvar if any(re.search(pat, labels[str(tv.get("val"))]) for pat in SEX_LABEL_RE.values())]
            if len(sexes) != 2 or len(turvar) != 2:
                if log:
                    log(f"  {ref}: split by {sorted(labels.values())[:6]} without a total; skipped")
                return pd.DataFrame(columns=POP_LONG_COLS)
            parts = [parse_dynamic(dict(js, turvar=[tv]), province_code, ref, source="bpspop") for tv in sexes]
            parts = [q[(q["religion"] == "total") & (q["unit_name"] != "__PROVINCE__") & q["count"].notna()] for q in parts]
            key = ["unit_name", "year"]
            m = parts[0].merge(parts[1][key + ["count"]], on=key, how="inner", suffixes=("", "_f"))
            m["count"] = m["count"] + m["count_f"]
            return m[POP_LONG_COLS] if len(m) else pd.DataFrame(columns=POP_LONG_COLS)
    d = parse_dynamic(js, province_code, ref, source="bpspop")
    d = d[(d["religion"] == "total") & (d["unit_name"] != "__PROVINCE__") & d["count"].notna()]
    return d[POP_LONG_COLS] if len(d) else pd.DataFrame(columns=POP_LONG_COLS)


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
            d = parse_population(js, str(rec.province_code), ref, log=log)
            # a row named after another province is a province total in a national table,
            # not a kabupaten ('Bengkulu' in a Sumatera Selatan table is not Kota Bengkulu)
            other_prov = d["unit_name"].map(lambda n: PROVINCE_KEYS.get(norm_label(str(n)).replace(" ", "")))
            d = d[other_prov.isna() | (other_prov == str(rec.province_code))]
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
    # a value that disagrees with every other series for that unit-year by >1.5x while
    # those agree is a typo in that series (Garut 2013 is 17,201 in one table, 1.72M in the rest)
    med = d.groupby(["unit_code", "year"])["population"].transform("median")
    n = d.groupby(["unit_code", "year"])["population"].transform("size")
    off = (n >= 2) & ~(d["population"] / med).between(1 / 1.5, 1.5)
    d = d[~off]
    d = d.sort_values(["unit_code", "year", "cover", "ref"], ascending=[True, True, False, True])
    best = d.drop_duplicates(["unit_code", "year"], keep="first")[["unit_code", "year", "population", "ref"]]
    g = d.groupby(["unit_code", "year"])["population"]
    stats = pd.DataFrame({"n_refs": g.nunique(), "spread": (g.max() / g.min()).round(3)}).reset_index()
    out = best.merge(stats, on=["unit_code", "year"])
    return out.sort_values(["unit_code", "year"]).reset_index(drop=True)
