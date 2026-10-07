"""Attach BPS kabupaten codes to names and build the unit x year panel.

Needs a code table (CSV with columns unit_code, unit_name, e.g. from BPS
'Kode dan Nama Wilayah' or sig.bps.go.id). Code splits (pemekaran) are NOT
collapsed here; do that with an explicit crosswalk once you have the panel.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from .religion import norm_unit_name, squash_unit_name, unit_level


def load_code_table(path: str) -> pd.DataFrame:
    codes = pd.read_csv(path, dtype=str)
    codes["unit_code"] = codes["unit_code"].str.strip().str.zfill(4)
    codes["province_code"] = codes["unit_code"].str[:2]
    codes["level"] = codes["unit_name"].map(unit_level)
    codes.loc[codes["level"] == "unknown", "level"] = codes["unit_code"].str[2].map(
        lambda c: "kota" if c == "7" else "kabupaten")  # BPS: kota codes are xx71-xx79
    codes["unit_name_norm"] = codes["unit_name"].map(norm_unit_name)
    codes["unit_key"] = codes["unit_name"].map(squash_unit_name)
    return codes[["unit_code", "unit_name", "province_code", "level", "unit_name_norm", "unit_key"]]


def attach_codes(long: pd.DataFrame, codes: pd.DataFrame) -> pd.DataFrame:
    """Fill unit_code by (province, level, normalised name); then by (province, name)
    when the level is unknown and the name is unique within the province."""
    df = long.copy()
    df["unit_code"] = df["unit_code"].where(df["unit_code"].notna() & (df["unit_code"] != ""), None)
    df["unit_code"] = df["unit_code"].map(lambda c: str(c).zfill(4) if c is not None and str(c) != "nan" else None)
    df["unit_key"] = df["unit_name"].map(squash_unit_name)
    if "level" not in df.columns:
        df["level"] = df["unit_name"].map(unit_level)
    # kecamatan rows (from kabupaten-domain tables) never get a kabupaten code: their names
    # collide with kabupaten/kota names elsewhere ('Tebing Tinggi', 'Medan', 'Bogor')
    missing = df["unit_code"].isna() & (df["unit_name"] != "__PROVINCE__") & (df["level"] != "kecamatan")
    by_level = codes.set_index(["province_code", "level", "unit_key"])["unit_code"]
    by_level = by_level[~by_level.index.duplicated()]
    uniq = codes.drop_duplicates(["province_code", "unit_key"], keep=False).set_index(["province_code", "unit_key"])["unit_code"]
    nat_uniq = codes.drop_duplicates(["unit_key"], keep=False).set_index("unit_key")["unit_code"]
    nat_kab = codes[codes["level"] == "kabupaten"].drop_duplicates("unit_key", keep=False).set_index("unit_key")["unit_code"]
    # resolve each distinct (province, level, key) once, then map
    cache = {}
    for prov, lvl, k in set(map(tuple, df.loc[missing, ["province_code", "level", "unit_key"]].itertuples(index=False))):
        code = None
        if (prov, lvl, k) in by_level.index:
            code = by_level.loc[(prov, lvl, k)]
        elif (prov, k) in uniq.index:  # level unknown (or wrong) but the name is unique in the province
            code = uniq.loc[(prov, k)]
        elif lvl == "unknown" and (prov, "kabupaten", k) in by_level.index:
            code = by_level.loc[(prov, "kabupaten", k)]  # BPS: only kota carry a prefix, so a bare name is the kabupaten
        elif k in nat_uniq.index:  # table filed under another province's domain (e.g. old Papua tables)
            code = nat_uniq.loc[k]
        elif lvl == "unknown" and k in nat_kab.index:
            code = nat_kab.loc[k]
        cache[(prov, lvl, k)] = code
    df.loc[missing, "unit_code"] = [cache[(p, l, k)] for p, l, k in
                                    df.loc[missing, ["province_code", "level", "unit_key"]].itertuples(index=False)]
    df["matched"] = df["unit_code"].notna()
    return df


BAD_REFS = {
    "bps:3300:1881",  # Jawa Tengah 2019-2021: identical values across years, shifted columns in the source
    "bps:6400:321",   # Kalimantan Timur 2015 (Kemenag): Samarinda Konghucu 32,001, an order of magnitude off
}


DROP_CELLS_FILE = Path(__file__).with_name("drop_cells.csv")


def load_drop_cells(path: Optional[str] = None) -> pd.DataFrame:
    """Hand-curated rows to leave out of the panel. Columns: unit_code, year, ref, reason;
    unit_code, year and ref are each optional and a rule matches long rows that agree on
    every field it sets (so `ref=bps:1200:2793` alone drops that whole table, `ref` plus
    `year` one year of a dynamic table, `unit_code` plus `year` one unit-year from every
    source). Used for source data-entry errors that no parser can fix. Kept in the repo."""
    f = Path(path) if path else DROP_CELLS_FILE
    cols = ["unit_code", "year", "ref", "reason"]
    if not f.exists():
        return pd.DataFrame(columns=cols)
    d = pd.read_csv(f, dtype=str, comment="#")
    for c in cols:
        if c not in d.columns:
            d[c] = None
    d = d[cols]
    d["year"] = pd.to_numeric(d["year"], errors="coerce").astype("Int64")
    d["unit_code"] = d["unit_code"].where(d["unit_code"].notna() & (d["unit_code"].str.strip() != ""), None)
    d["ref"] = d["ref"].where(d["ref"].notna() & (d["ref"].str.strip() != ""), None)
    return d


def apply_drop_rules(df: pd.DataFrame, rules: pd.DataFrame) -> pd.Series:
    """Boolean mask of long rows matched by any rule (see load_drop_cells)."""
    hit = pd.Series(False, index=df.index)
    for r in rules.itertuples(index=False):
        m = pd.Series(True, index=df.index)
        if r.unit_code is not None and not pd.isna(r.unit_code):
            m &= df["unit_code"].astype(str) == str(r.unit_code)
        if not pd.isna(r.year):
            m &= df["year"] == int(r.year)
        if r.ref is not None and not pd.isna(r.ref):
            m &= df["ref"].astype(str) == str(r.ref)
        if m.all():  # an empty rule would wipe the panel
            continue
        hit |= m
    return hit


MAJOR = ["islam", "kristen", "katolik"]
RELIGIONS = ["islam", "kristen", "katolik", "hindu", "buddha", "konghucu", "kepercayaan", "lainnya"]


def cell_quality(wide: pd.DataFrame) -> pd.Series:
    """Label unit-year cells that cannot be used as counts, from their own values:
    'percent'   religions sum to about 100 and none exceeds 100
    'placeholder' four or more religions carry the identical value (e.g. all 100)
    'no_religions' only a total is reported
    'partial'   one of islam/kristen/katolik is missing, so a summed total is not a population
    '' otherwise."""
    rel = [c for c in RELIGIONS if c in wide.columns]
    vals = wide[rel]
    n = vals.notna().sum(axis=1)
    s = vals.sum(axis=1, min_count=1)
    mx = vals.max(axis=1)
    q = pd.Series("", index=wide.index)
    q[(n >= 3) & s.between(99, 101) & (mx <= 100)] = "percent"
    same = vals.apply(lambda r: r.dropna().value_counts().max() >= 4 if r.notna().sum() >= 4 else False, axis=1)
    q[(q == "") & same] = "placeholder"
    q[(q == "") & (n == 0)] = "no_religions"
    major = [c for c in MAJOR if c in wide.columns]
    q[(q == "") & (wide[major].isna().any(axis=1) if major else False)] = "partial"
    return q


def build_panel(long: pd.DataFrame, prefer: Optional[list] = None, exclude_refs: Optional[set] = None,
                drop_cells: Optional[pd.DataFrame] = None, population: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """unit x year (x semester) wide table with one column per religion, plus
    konghucu share. When several sources cover the same cell, `prefer` orders them
    (default: arcgis, pdf, pdf_da, bpsvar, bps, bps_kabsum: dynamic BPS tables are cleaner than
    the Excel-exported static ones, and a labelled total beats a sum of kecamatan).
    semester is 0 when the source is annual."""
    prefer = prefer or ["arcgis", "pdf", "pdf_da", "bpsvar", "bps", "bps_kabsum"]
    bad = BAD_REFS | set(exclude_refs or ())
    df = long[long["unit_code"].notna() & long["count"].notna() & ~long["ref"].isin(bad)].copy()
    if "level" in df.columns:
        df = df[df["level"] != "kecamatan"]
    no_year = df["year"].isna()
    if no_year.any():
        refs = sorted(set(df.loc[no_year, "ref"].astype(str)))
        print(f"build_panel: dropping {int(no_year.sum())} rows without a year from {len(refs)} tables: {refs[:10]}")
        df = df[~no_year]
    # semester 0 = annual / unspecified (BPS yearbook tables); pandas drops NaN index keys
    df["semester"] = df["semester"].fillna(0).astype(int)
    df["year"] = df["year"].astype(int)
    if drop_cells is not None and len(drop_cells):
        dropped = apply_drop_rules(df, drop_cells)
        if dropped.any():
            print(f"build_panel: drop rules remove {int(dropped.sum())} rows "
                  f"({len(set(zip(df.loc[dropped, 'unit_code'], df.loc[dropped, 'year'])))} unit-years touched)")
        df = df[~dropped]
    # one table per cell: every religion of a unit-year comes from the same ref, chosen by
    # source preference, then by how many religions the table reports, then by ref name
    df["rank"] = df["source"].map({s: i for i, s in enumerate(prefer)}).fillna(len(prefer))
    cell = ["unit_code", "year", "semester"]
    nrel = df.groupby(cell + ["ref"])["religion"].nunique().rename("n_rel").reset_index()
    best = df[cell + ["ref", "rank"]].drop_duplicates().merge(nrel, on=cell + ["ref"])
    best = best.sort_values(cell + ["rank", "n_rel", "ref"], ascending=[True, True, True, True, False, True])
    best = best.drop_duplicates(cell, keep="first")[cell + ["ref"]]
    df = df.merge(best, on=cell + ["ref"], how="inner")
    df = df.drop_duplicates(cell + ["religion"], keep="first")
    wide = df.pivot_table(index=["unit_code", "year", "semester"], columns="religion", values="count",
                          aggfunc="first").reset_index()
    wide.columns.name = None
    src = df.groupby(["unit_code", "year", "semester"], dropna=False)["source"].agg(lambda s: ";".join(sorted(set(s))))
    wide = wide.merge(src.rename("sources").reset_index(), on=["unit_code", "year", "semester"], how="left")
    kref = df[df["religion"] == "konghucu"].groupby(["unit_code", "year", "semester"])["ref"].first().rename("konghucu_ref")
    wide = wide.merge(kref.reset_index(), on=["unit_code", "year", "semester"], how="left")
    ref = df.groupby(["unit_code", "year", "semester"])["ref"].first().rename("ref")
    wide = wide.merge(ref.reset_index(), on=["unit_code", "year", "semester"], how="left")
    wide["quality"] = cell_quality(wide)
    bad_q = wide["quality"].isin(["percent", "placeholder", "no_religions"])
    if bad_q.any():
        print("build_panel: dropping unusable cells: " + ", ".join(f"{k}={v}" for k, v in
                                                                     wide.loc[bad_q, "quality"].value_counts().items()))
    wide = wide[~bad_q].copy()
    rel_cols = [c for c in RELIGIONS if c in wide.columns]
    summed = wide[rel_cols].sum(axis=1, min_count=1)
    summed[wide["quality"] == "partial"] = float("nan")  # a sum without a major religion is not a population
    if "total" not in wide.columns:
        wide["total"] = float("nan")
    wide["total_reported"] = wide["total"]
    # a reported total that disagrees with the religions by more than 10% is a wrong cell
    # in the source (Indragiri Hilir 2023 reports 30); the sum is then the better number
    bad_total = wide["total"].notna() & summed.notna() & ~(wide["total"] / summed).between(0.9, 1.1)
    wide.loc[bad_total, "total"] = float("nan")
    wide["total"] = wide["total"].fillna(summed)
    wide["total_is_sum"] = wide["total"].notna() & wide["total"].eq(summed)
    if "konghucu" in wide.columns:
        wide["konghucu_share"] = wide["konghucu"] / wide["total"]
    if population is not None and len(population):
        pop = population[["unit_code", "year", "population"]].copy()
        pop["unit_code"] = pop["unit_code"].astype(str).str.zfill(4)
        pop["year"] = pop["year"].astype(int)
        wide = wide.merge(pop, on=["unit_code", "year"], how="left")
        wide["total_to_pop"] = wide["total"] / wide["population"]
        # a table from a kabupaten domain whose total is under 30% of the official population
        # is a single-kecamatan table published without the kecamatan name (Jombang has several)
        dom = wide["ref"].astype(str).str.extract(r":(\d{4}):")[0]
        sub = dom.notna() & ~dom.str.endswith("00") & (wide["total_to_pop"] < 0.3)
        if sub.any():
            print(f"build_panel: dropping {int(sub.sum())} cells from kabupaten-domain tables whose total is <30% "
                  f"of the population (sub-kabupaten tables): {sorted(set(wide.loc[sub, 'ref']))[:8]}")
            wide = wide[~sub].copy()
        # a count of residents is not 1.5x the population (Kemenag adherent counts that
        # exceed it, a province row rolled up as the kota) nor under half of it (partial counts)
        bad = wide["total_to_pop"].notna() & ((wide["total_to_pop"] > 1.5) | (wide["total_to_pop"] < 0.5))
        if bad.any():
            print(f"build_panel: dropping {int(bad.sum())} cells whose total is >1.5x or <0.5x the official population: "
                  f"{sorted(set(wide.loc[bad, 'ref']))[:8]}")
            wide = wide[~bad].copy()
        if "konghucu" in wide.columns:
            wide["konghucu_share_pop"] = wide["konghucu"] / wide["population"]
    return wide.sort_values(["unit_code", "year", "semester"]).reset_index(drop=True)


def konghucu_breaks(panel: pd.DataFrame, ratio: float = 5.0, min_count: float = 20, max_gap: int = 4) -> pd.DataFrame:
    """Units whose konghucu count jumps by more than `ratio` between consecutive observed
    years: usually a change of source definition (Kemenag adherent counts vs Dukcapil
    ID-card registration), not a real change. One row per jump with both refs. Jumps
    where both counts are below `min_count` are ignored (2 -> 17 is noise, not a break)."""
    if "konghucu" not in panel.columns:
        return pd.DataFrame()
    p = panel.dropna(subset=["konghucu"]).sort_values(["unit_code", "year"])
    rows = []
    for code, g in p.groupby("unit_code"):
        prev = None
        for r in g.itertuples(index=False):
            if prev is not None and min(prev.konghucu, r.konghucu) > 0 and r.year - prev.year <= max_gap and \
                    max(prev.konghucu, r.konghucu) >= min_count and \
                    max(prev.konghucu, r.konghucu) / min(prev.konghucu, r.konghucu) > ratio:
                rows.append({"unit_code": code, "year_a": prev.year, "konghucu_a": prev.konghucu, "ref_a": prev.konghucu_ref,
                             "year_b": r.year, "konghucu_b": r.konghucu, "ref_b": r.konghucu_ref})
            prev = r
    return pd.DataFrame(rows)


def total_outliers(panel: pd.DataFrame, tol: float = 0.35, min_obs: int = 3, min_year: int = 2000) -> pd.DataFrame:
    """Unit-years whose religion total is more than `tol` away from the official population
    (column `population`, when the panel carries one) or, failing that, from the unit's
    median total across years. A kabupaten does not gain or lose a third of its population
    in a few years, so these are almost always one religion copied from the wrong row.
    Years before `min_year` are left alone: a 1980 census count is legitimately different."""
    p = panel.dropna(subset=["total"])
    p = p[p["year"] >= min_year]
    rows = []
    for code, g in p.groupby("unit_code"):
        med = g["total"].median()
        for r in g.itertuples(index=False):
            if "population" in g.columns and pd.notna(getattr(r, "population", None)) and r.population > 0:
                anchor, kind = r.population, "population"
            elif len(g) >= min_obs and med > 0:
                anchor, kind = med, "median"
            else:
                continue
            if abs(r.total / anchor - 1) > tol:
                rows.append({"unit_code": code, "year": r.year, "total": r.total, "anchor": anchor, "anchor_kind": kind,
                             "ratio": round(r.total / anchor, 2), "ref": getattr(r, "ref", None)})
    out = pd.DataFrame(rows)
    if len(out):
        rel = [c for c in ["islam", "kristen", "katolik", "hindu", "buddha", "konghucu", "lainnya"] if c in panel.columns]
        out = out.merge(panel[["unit_code", "year"] + rel], on=["unit_code", "year"], how="left")
    return out
