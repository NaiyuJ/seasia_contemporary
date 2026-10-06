"""Attach BPS kabupaten codes to names and build the unit x year panel.

Needs a code table (CSV with columns unit_code, unit_name, e.g. from BPS
'Kode dan Nama Wilayah' or sig.bps.go.id). Code splits (pemekaran) are NOT
collapsed here; do that with an explicit crosswalk once you have the panel.
"""
from __future__ import annotations

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


def build_panel(long: pd.DataFrame, prefer: Optional[list] = None, exclude_refs: Optional[set] = None) -> pd.DataFrame:
    """unit x year (x semester) wide table with one column per religion, plus
    konghucu share. When several sources cover the same cell, `prefer` orders them
    (default: arcgis, pdf, bpsvar, bps, bps_kabsum: dynamic BPS tables are cleaner than
    the Excel-exported static ones, and a labelled total beats a sum of kecamatan).
    semester is 0 when the source is annual."""
    prefer = prefer or ["arcgis", "pdf", "bpsvar", "bps", "bps_kabsum"]
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
    df["rank"] = df["source"].map({s: i for i, s in enumerate(prefer)}).fillna(len(prefer))
    df = df.sort_values("rank").drop_duplicates(["unit_code", "year", "semester", "religion"], keep="first")
    wide = df.pivot_table(index=["unit_code", "year", "semester"], columns="religion", values="count",
                          aggfunc="first").reset_index()
    wide.columns.name = None
    src = df.groupby(["unit_code", "year", "semester"], dropna=False)["source"].agg(lambda s: ";".join(sorted(set(s))))
    wide = wide.merge(src.rename("sources").reset_index(), on=["unit_code", "year", "semester"], how="left")
    kref = df[df["religion"] == "konghucu"].groupby(["unit_code", "year", "semester"])["ref"].first().rename("konghucu_ref")
    wide = wide.merge(kref.reset_index(), on=["unit_code", "year", "semester"], how="left")
    rel_cols = [c for c in wide.columns if c in {"islam", "kristen", "katolik", "hindu", "buddha", "konghucu", "kepercayaan", "lainnya"}]
    summed = wide[rel_cols].sum(axis=1, min_count=1)
    if "total" not in wide.columns:
        wide["total"] = summed
    else:  # cells whose source had no 'Jumlah' category (most dynamic tables): sum the religions
        wide["total"] = wide["total"].fillna(summed)
    wide["total_is_sum"] = wide["total"].eq(summed)  # True when total was not reported by the source
    if "konghucu" in wide.columns:
        wide["konghucu_share"] = wide["konghucu"] / wide["total"]
    return wide.sort_values(["unit_code", "year", "semester"]).reset_index(drop=True)


def konghucu_breaks(panel: pd.DataFrame, ratio: float = 5.0) -> pd.DataFrame:
    """Units whose konghucu count jumps by more than `ratio` between consecutive observed
    years: usually a change of source definition (Kemenag adherent counts vs Dukcapil
    ID-card registration), not a real change. One row per jump with both refs."""
    if "konghucu" not in panel.columns:
        return pd.DataFrame()
    p = panel.dropna(subset=["konghucu"]).sort_values(["unit_code", "year"])
    rows = []
    for code, g in p.groupby("unit_code"):
        prev = None
        for r in g.itertuples(index=False):
            if prev is not None and min(prev.konghucu, r.konghucu) > 0 and \
                    max(prev.konghucu, r.konghucu) / min(prev.konghucu, r.konghucu) > ratio:
                rows.append({"unit_code": code, "year_a": prev.year, "konghucu_a": prev.konghucu, "ref_a": prev.konghucu_ref,
                             "year_b": r.year, "konghucu_b": r.konghucu, "ref_b": r.konghucu_ref})
            prev = r
    return pd.DataFrame(rows)
