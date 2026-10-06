"""Attach BPS kabupaten codes to names and build the unit x year panel.

Needs a code table (CSV with columns unit_code, unit_name, e.g. from BPS
'Kode dan Nama Wilayah' or sig.bps.go.id). Code splits (pemekaran) are NOT
collapsed here; do that with an explicit crosswalk once you have the panel.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from .religion import norm_unit_name, unit_level


def load_code_table(path: str) -> pd.DataFrame:
    codes = pd.read_csv(path, dtype=str)
    codes["unit_code"] = codes["unit_code"].str.strip().str.zfill(4)
    codes["province_code"] = codes["unit_code"].str[:2]
    codes["level"] = codes["unit_name"].map(unit_level)
    codes.loc[codes["level"] == "unknown", "level"] = codes["unit_code"].str[2].map(
        lambda c: "kota" if c == "7" else "kabupaten")  # BPS: kota codes are xx71-xx79
    codes["unit_name_norm"] = codes["unit_name"].map(norm_unit_name)
    return codes[["unit_code", "unit_name", "province_code", "level", "unit_name_norm"]]


def attach_codes(long: pd.DataFrame, codes: pd.DataFrame) -> pd.DataFrame:
    """Fill unit_code by (province, level, normalised name); then by (province, name)
    when the level is unknown and the name is unique within the province."""
    df = long.copy()
    df["unit_code"] = df["unit_code"].where(df["unit_code"].notna() & (df["unit_code"] != ""), None)
    missing = df["unit_code"].isna() & (df["unit_name"] != "__PROVINCE__")
    key = codes.set_index(["province_code", "level", "unit_name_norm"])["unit_code"]
    for idx in df.index[missing]:
        r = df.loc[idx]
        k = (r["province_code"], r["level"], r["unit_name_norm"])
        if k in key.index:
            df.at[idx, "unit_code"] = key.loc[k]
            continue
        if r["level"] == "unknown":
            cand = codes[(codes["province_code"] == r["province_code"]) & (codes["unit_name_norm"] == r["unit_name_norm"])]
            if len(cand) == 1:
                df.at[idx, "unit_code"] = cand["unit_code"].iloc[0]
    df["matched"] = df["unit_code"].notna()
    return df


def build_panel(long: pd.DataFrame, prefer: Optional[list] = None) -> pd.DataFrame:
    """unit x year (x semester) wide table with one column per religion, plus
    konghucu share. When several sources cover the same cell, `prefer` orders them
    (default: arcgis, pdf, bpsvar, bps, bps_kabsum: dynamic BPS tables are cleaner than
    the Excel-exported static ones, and a labelled total beats a sum of kecamatan).
    semester is 0 when the source is annual."""
    prefer = prefer or ["arcgis", "pdf", "bpsvar", "bps", "bps_kabsum"]
    df = long[long["unit_code"].notna() & long["count"].notna()].copy()
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
    if "total" not in wide.columns:
        rel_cols = [c for c in wide.columns if c in {"islam", "kristen", "katolik", "hindu", "buddha", "konghucu", "kepercayaan", "lainnya"}]
        wide["total"] = wide[rel_cols].sum(axis=1, min_count=1)
    if "konghucu" in wide.columns:
        wide["konghucu_share"] = wide["konghucu"] / wide["total"]
    return wide.sort_values(["unit_code", "year", "semester"]).reset_index(drop=True)
