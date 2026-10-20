"""IPUMS International, Indonesia 2010 census (10% sample): ethnic Chinese population and
religion among the ethnic Chinese by kabupaten/kota.

Input: an IPUMS extract as CSV (gzipped or not) plus its DDI codebook (.xml), with at least
  GEO2_ID2010   kabupaten/kota of residence, 2010 boundaries (or GEOLEV2)
  GEO1_ID2010   province (or GEOLEV1; optional, used to disambiguate names)
  ID2010A_ETHNIC  ethnicity / suku (the sample-specific variable; 'Chinese' is one category)
  RELIGION or ID2010A_RELIG  religion (Khonghucu is a category of the sample-specific one;
                the harmonised RELIGION folds it into 'Other' in some releases, so prefer
                ID2010A_RELIG when present)
  PERWT         person weight
Variable names are looked up case-insensitively; categories are found by their labels in the
DDI, and the labels actually used are printed so they can be checked.

Output, one row per kabupaten matched to a BPS code (2010 boundaries; kabupaten split after
2010 inherit nothing and must be mapped by hand or through a crosswalk):
  pop2010            weighted population
  chinese2010        weighted ethnic Chinese
  chinese_share      chinese2010 / pop2010
  konghucu2010       weighted Konghucu, all ethnicities
  konghucu_chinese2010, buddha_chinese2010   weighted Konghucu / Buddhist among the Chinese
  konghucu_of_chinese, buddha_of_chinese     the two as shares of chinese2010
  n_chinese_sample   unweighted Chinese respondents (precision of the shares)
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import pandas as pd

from .harmonize import attach_codes, load_code_table
from .religion import PROVINCES, squash_unit_name

ETHNIC_CHINESE_RE = re.compile(r"(?i)\b(chinese|cina|china|tionghoa|tionghua)\b")
KONGHUCU_RE = re.compile(r"(?i)kong\s?hu\s?cu|khong\s?hu\s?cu|confuc")
BUDDHA_RE = re.compile(r"(?i)budd?h|buda")

INDONESIA_2010_POPULATION = 237_641_326  # census count, used to detect implied decimals in the weight


def read_ddi(path: str) -> dict:
    """{variable name (upper): {code (str): label}} from an IPUMS DDI codebook."""
    tree = ET.parse(path)
    out = {}
    for var in tree.iter():
        if not var.tag.endswith("}var") and var.tag != "var":
            continue
        name = (var.get("name") or "").upper()
        labels = {}
        for cat in var.iter():
            if cat.tag.endswith("catgry") or cat.tag == "catgry":
                val = lab = None
                for ch in cat:
                    if ch.tag.endswith("catValu"):
                        val = (ch.text or "").strip()
                    elif ch.tag.endswith("labl"):
                        lab = (ch.text or "").strip()
                if val is not None:
                    labels[val] = lab or ""
        if name:
            out[name] = labels
    return out


def _find_col(columns, *candidates) -> Optional[str]:
    up = {c.upper(): c for c in columns}
    for cand in candidates:
        if cand.upper() in up:
            return up[cand.upper()]
    return None


def _codes_matching(labels: dict, pattern: re.Pattern) -> set:
    return {code for code, lab in labels.items() if pattern.search(lab or "")}


def tabulate(extract: pd.DataFrame, ddi: dict, log=print) -> pd.DataFrame:
    """Weighted counts per GEO2 unit: population, ethnic Chinese, Konghucu, Konghucu and
    Buddhist among the Chinese. Returns one row per GEO2 code with its label and province."""
    geo2 = _find_col(extract.columns, "GEO2_ID2010", "GEOLEV2")
    geo1 = _find_col(extract.columns, "GEO1_ID2010", "GEOLEV1")
    eth = _find_col(extract.columns, "ID2010A_ETHNIC", "ETHNICID", "ETHNIC")
    rel = _find_col(extract.columns, "ID2010A_RELIG", "RELIGIOND", "RELIGION")
    wt = _find_col(extract.columns, "PERWT")
    missing = [n for n, c in [("GEO2_ID2010", geo2), ("ID2010A_ETHNIC", eth), ("RELIGION", rel), ("PERWT", wt)] if c is None]
    if missing:
        raise SystemExit(f"extract lacks {missing}; columns are {list(extract.columns)}")
    d = extract[[c for c in [geo2, geo1, eth, rel, wt] if c]].copy()
    d[wt] = pd.to_numeric(d[wt], errors="coerce").fillna(0)
    total = d[wt].sum()
    if total > 10 * INDONESIA_2010_POPULATION:  # weight with two implied decimals
        d[wt] = d[wt] / 100
        log(f"PERWT sums to {total:,.0f}: divided by 100 (implied decimals); now {d[wt].sum():,.0f}")
    elif not 0.5 * INDONESIA_2010_POPULATION < total < 2 * INDONESIA_2010_POPULATION:
        log(f"warning: weighted population {total:,.0f} is far from the 2010 census count {INDONESIA_2010_POPULATION:,}")
    eth_labels = ddi.get(eth.upper(), {})
    rel_labels = ddi.get(rel.upper(), {})
    chinese_codes = _codes_matching(eth_labels, ETHNIC_CHINESE_RE)
    konghucu_codes = _codes_matching(rel_labels, KONGHUCU_RE)
    buddha_codes = _codes_matching(rel_labels, BUDDHA_RE)
    log(f"ethnic Chinese = {eth} in {sorted(chinese_codes)}: {[eth_labels[c] for c in sorted(chinese_codes)]}")
    log(f"Konghucu = {rel} in {sorted(konghucu_codes)}: {[rel_labels[c] for c in sorted(konghucu_codes)]}")
    log(f"Buddhist = {rel} in {sorted(buddha_codes)}: {[rel_labels[c] for c in sorted(buddha_codes)]}")
    if not chinese_codes or not konghucu_codes:
        raise SystemExit("could not find the Chinese ethnicity or the Konghucu religion category in the DDI labels; "
                         "check the variable names above")
    d["_eth"] = d[eth].astype(str).str.strip()
    d["_rel"] = d[rel].astype(str).str.strip()
    d["chinese"] = d["_eth"].isin(chinese_codes)
    d["konghucu"] = d["_rel"].isin(konghucu_codes)
    d["buddha"] = d["_rel"].isin(buddha_codes)
    w = d[wt]
    g = d.groupby(d[geo2].astype(str))
    out = pd.DataFrame({
        "pop2010": g[wt].sum(),
        "chinese2010": (w * d["chinese"]).groupby(d[geo2].astype(str)).sum(),
        "konghucu2010": (w * d["konghucu"]).groupby(d[geo2].astype(str)).sum(),
        "konghucu_chinese2010": (w * (d["konghucu"] & d["chinese"])).groupby(d[geo2].astype(str)).sum(),
        "buddha_chinese2010": (w * (d["buddha"] & d["chinese"])).groupby(d[geo2].astype(str)).sum(),
        "n_chinese_sample": d["chinese"].groupby(d[geo2].astype(str)).sum().astype(int),
    }).reset_index().rename(columns={geo2: "geo2"})
    out["geo2_label"] = out["geo2"].map(ddi.get(geo2.upper(), {})).fillna("")
    if geo1:
        prov = d.groupby(d[geo2].astype(str))[geo1].agg(lambda s: str(s.mode().iloc[0]))
        out["geo1_label"] = out["geo2"].map(prov).map(ddi.get(geo1.upper(), {})).fillna("")
    else:
        out["geo1_label"] = ""
    out["chinese_share"] = out["chinese2010"] / out["pop2010"]
    out["konghucu_of_chinese"] = out["konghucu_chinese2010"] / out["chinese2010"].where(out["chinese2010"] > 0)
    out["buddha_of_chinese"] = out["buddha_chinese2010"] / out["chinese2010"].where(out["chinese2010"] > 0)
    return out


def match_units(tab: pd.DataFrame, codes_path: str, log=print) -> pd.DataFrame:
    """Attach BPS 4-digit codes to the GEO2 labels with the religion tables' name matcher."""
    codes = load_code_table(codes_path)
    prov_of = {squash_unit_name(n): c for c, n in PROVINCES.items()}
    prov_of.update({"daerahkhususibukotajakarta": "31", "dkijakarta": "31", "daerahistimewayogyakarta": "34",
                    "jakarta": "31", "yogyakarta": "34"})
    long = pd.DataFrame({
        "unit_name": tab["geo2_label"].str.replace(r"(?i)^(kab\.?|kabupaten|kota)\s+", lambda m: "Kota " if m.group(1).lower() == "kota" else "", regex=True),
        "province_code": tab["geo1_label"].map(lambda s: prov_of.get(squash_unit_name(re.sub(r"(?i)^prov(insi)?\.?\s+", "", str(s))))),
        "unit_code": None,
    })
    matched = attach_codes(long, codes)
    tab = tab.copy()
    tab["unit_code"] = matched["unit_code"].values
    um = tab[tab["unit_code"].isna()]
    if len(um):
        log(f"{len(um)} IPUMS units not matched to a BPS code (map by hand or add aliases in konghucu/religion.py):")
        log(um[["geo2", "geo2_label", "geo1_label", "pop2010"]].to_string(index=False))
    dup = tab["unit_code"].notna() & tab["unit_code"].duplicated(keep=False)
    if dup.any():
        log(f"warning: {int(dup.sum())} IPUMS units share a BPS code (summed): {sorted(set(tab.loc[dup, 'unit_code']))}")
    return tab


def build(csv_path: str, ddi_path: str, codes_path: str, log=print) -> pd.DataFrame:
    extract = pd.read_csv(csv_path, dtype=str, low_memory=False)
    ddi = read_ddi(ddi_path)
    tab = tabulate(extract, ddi, log=log)
    tab = match_units(tab, codes_path, log=log)
    keep = tab[tab["unit_code"].notna()]
    agg = {c: "sum" for c in ["pop2010", "chinese2010", "konghucu2010", "konghucu_chinese2010", "buddha_chinese2010", "n_chinese_sample"]}
    out = keep.groupby("unit_code").agg({**agg, "geo2_label": "first"}).reset_index()
    out["chinese_share"] = out["chinese2010"] / out["pop2010"]
    out["konghucu_of_chinese"] = out["konghucu_chinese2010"] / out["chinese2010"].where(out["chinese2010"] > 0)
    out["buddha_of_chinese"] = out["buddha_chinese2010"] / out["chinese2010"].where(out["chinese2010"] > 0)
    log(f"{len(out)} kabupaten/kota; ethnic Chinese {out['chinese2010'].sum():,.0f} of {out['pop2010'].sum():,.0f} "
        f"({out['chinese_share'].mean():.2%} mean share; Konghucu among Chinese "
        f"{out['konghucu_chinese2010'].sum() / max(out['chinese2010'].sum(), 1):.1%})")
    return out.sort_values("unit_code").reset_index(drop=True)
