"""Allocate immigration-office (kanim) and province rows to kabupaten; build the panel.

Crosswalk CSV columns: kanim (name as printed, any casing), unit_code (4-digit),
weight (optional; rows for one kanim are normalised to sum to 1). Without weights
the kanim count is split equally across its kabupaten. Province-level rows are
kept as province_code x year context and are NOT split.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from konghucu.harmonize import load_code_table
from konghucu.religion import norm_unit_name, unit_level

from .nationality import norm_kanim


def load_kanim_crosswalk(path: str) -> pd.DataFrame:
    cw = pd.read_csv(path, dtype=str)
    cw["kanim_norm"] = cw["kanim"].map(norm_kanim)
    cw["unit_code"] = cw["unit_code"].str.strip().str.zfill(4)
    w = pd.to_numeric(cw.get("weight", pd.Series([None] * len(cw))), errors="coerce")
    cw["weight"] = w
    cw["weight"] = cw.groupby("kanim_norm")["weight"].transform(lambda s: s.fillna(1.0) / s.fillna(1.0).sum())
    return cw[["kanim_norm", "unit_code", "weight"]]


def allocate_to_kabupaten(long: pd.DataFrame, crosswalk: Optional[pd.DataFrame] = None,
                          codes: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Return rows at kabupaten level: direct kabupaten rows matched by name, plus
    kanim rows split by the crosswalk. Adds unit_code and `allocated` (bool)."""
    df = long.copy()
    df["unit_code"], df["allocated"] = None, False
    out = []
    kab = df[df["region_level"].isin(["kabupaten", "kecamatan"])].copy()
    if len(kab) and codes is not None:
        kab["level"] = kab["region_name"].map(unit_level)
        kab["unit_name_norm"] = kab["region_name"].map(norm_unit_name)
        key = codes.set_index(["province_code", "level", "unit_name_norm"])["unit_code"]
        key2 = codes.drop_duplicates(["province_code", "unit_name_norm"], keep=False) \
                    .set_index(["province_code", "unit_name_norm"])["unit_code"]
        for idx, r in kab.iterrows():
            k = (r["province_code"], r["level"], r["unit_name_norm"])
            if k in key.index:
                kab.at[idx, "unit_code"] = key.loc[k]
            elif (r["province_code"], r["unit_name_norm"]) in key2.index:
                kab.at[idx, "unit_code"] = key2.loc[(r["province_code"], r["unit_name_norm"])]
        out.append(kab.drop(columns=["level", "unit_name_norm"]))
    elif len(kab):
        out.append(kab)
    kan = df[df["region_level"] == "kanim"]
    if len(kan) and crosswalk is not None:
        m = kan.merge(crosswalk, left_on=kan["region_name"].map(norm_kanim), right_on="kanim_norm", how="left",
                      suffixes=("", "_cw"))
        matched = m["unit_code_cw"].notna()
        m.loc[matched, "unit_code"] = m.loc[matched, "unit_code_cw"]
        m.loc[matched, "count"] = m.loc[matched, "count"] * m.loc[matched, "weight"]
        m.loc[matched, "allocated"] = True
        out.append(m.drop(columns=["kanim_norm", "unit_code_cw", "weight", "key_0"], errors="ignore"))
    elif len(kan):
        out.append(kan)
    res = pd.concat(out, ignore_index=True) if out else df.iloc[0:0]
    return res


def build_panel(allocated: pd.DataFrame, province_rows: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """kabupaten x year with: chn_<permit> columns (CHN by permit type, summed over
    sources), wna_resident (Dukcapil), foreign_total (all nationalities, any permit)."""
    df = allocated[allocated["unit_code"].notna() & allocated["count"].notna()].copy()
    df["year"] = df["year"].astype("Int64")
    df["permit_type"] = df["permit_type"].fillna("ANY")
    chn = df[df["nationality"] == "CHN"].groupby(["unit_code", "year", "permit_type"])["count"].sum().unstack("permit_type")
    chn.columns = [f"chn_{c.lower()}" for c in chn.columns]
    chn["chn_any"] = chn.sum(axis=1, min_count=1)
    wna = df[df["nationality"] == "WNA"].groupby(["unit_code", "year"])["count"].sum().rename("wna_resident")
    tot = df[(df["nationality"] == "TOTAL")].groupby(["unit_code", "year"])["count"].sum().rename("foreign_total")
    src = df.groupby(["unit_code", "year"])["source"].agg(lambda s: ";".join(sorted(set(s)))).rename("sources")
    panel = pd.concat([chn, wna, tot, src], axis=1).reset_index()
    if province_rows is not None and len(province_rows):
        p = province_rows[province_rows["nationality"] == "CHN"].copy()
        p["year"] = p["year"].astype("Int64")
        pp = p.groupby(["province_code", "year"])["count"].sum().rename("chn_province_any").reset_index()
        panel["province_code"] = panel["unit_code"].str[:2]
        panel = panel.merge(pp, on=["province_code", "year"], how="left")
    return panel.sort_values(["unit_code", "year"]).reset_index(drop=True)
