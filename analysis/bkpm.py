"""BKPM realised investment (quarterly, by kabupaten/kota and source country) ->
data/raw/china_investment.csv: one row per kabupaten-year with Chinese FDI, Hong Kong FDI,
all FDI (PMA) and domestic investment (PMDN), in thousand USD.

    python -m analysis.bkpm --src /path/to/bkpm_realisasi_2010_2026Q2_all.csv

Source countries are matched on the BKPM spelling: mainland China is 'Tiongkok' / 'R.R.
Tiongkok' / 'China' / 'Cina' (Taiwan, Hong Kong and Macau excluded; Hong Kong kept apart
because much mainland money is routed through it). Kabupaten names are matched to BPS
codes with the same normaliser the religion tables use; unmatched names are printed.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

from konghucu.harmonize import load_code_table
from konghucu.religion import squash_unit_name, unit_level

CHINA_RE = re.compile(r"(?i)^(r\.?\s?r\.?\s?)?(tiongkok|china|cina|republik rakyat (tiongkok|cina|china))\b|^r\.?\s?r\.?\s?t\.?$")
NOT_CHINA_RE = re.compile(r"(?i)taiwan|taipei|hong\s?kong|hongkong|macau|makau")
HK_RE = re.compile(r"(?i)hong\s?kong|hongkong")


def classify_country(name: object) -> str:
    s = str(name or "")
    if HK_RE.search(s):
        return "hk"
    if CHINA_RE.search(s) and not NOT_CHINA_RE.search(s):
        return "china"
    return "other"


def name_key(name: str) -> str:
    s = re.sub(r"(?i)^kota adm\.?\s+", "Kota ", str(name)).strip()
    return squash_unit_name(s)


def convert(src: str, codes_path: str, value_col: str = "investasi_us_ribu", log=print) -> pd.DataFrame:
    d = pd.read_csv(src, low_memory=False)
    d["origin"] = d["negara"].map(classify_country)
    log("country labels taken as mainland China: " + ", ".join(sorted(set(d.loc[d["origin"] == "china", "negara"].astype(str)))))
    log("taken as Hong Kong: " + ", ".join(sorted(set(d.loc[d["origin"] == "hk", "negara"].astype(str)))))
    codes = load_code_table(codes_path)
    key_to_code = {}
    for r in codes.itertuples(index=False):
        key_to_code.setdefault((r.province_code, r.level, r.unit_key), r.unit_code)
    uniq = codes.drop_duplicates(["province_code", "unit_key"], keep=False)
    key_prov = dict(zip(zip(uniq["province_code"], uniq["unit_key"]), uniq["unit_code"]))
    from konghucu.religion import PROVINCES
    prov_of = {squash_unit_name(n): c for c, n in PROVINCES.items()}
    prov_of.update({"daerahkhususibukotajakarta": "31", "dkijakarta": "31", "daerahistimewayogyakarta": "34"})

    d["prov"] = d["provinsi"].map(lambda s: prov_of.get(squash_unit_name(str(s))))
    d["key"] = d["kabupaten_kota"].map(name_key)
    d["lvl"] = d["kabupaten_kota"].map(unit_level)

    nat = codes.drop_duplicates(["unit_key"], keep=False)  # name unique in the country: province may be stale
    nat_code = dict(zip(nat["unit_key"], nat["unit_code"]))  # (BKPM files Sorong under Papua Barat Daya; BPS codes do not)
    natl = codes.drop_duplicates(["level", "unit_key"], keep=False)  # Kabupaten Sorong vs Kota Sorong
    natl_code = dict(zip(zip(natl["level"], natl["unit_key"]), natl["unit_code"]))
    from konghucu.religion import norm_label
    full = codes.assign(k=codes["unit_name"].map(lambda n: norm_label(n).replace(" ", ""))).drop_duplicates("k", keep=False)
    full_code = dict(zip(full["k"], full["unit_code"]))  # 'kotabaru' == 'Kota Baru' with the prefix kept
    d["full"] = d["kabupaten_kota"].map(lambda n: norm_label(re.sub(r"(?i)^(kabupaten|kota adm\.?|kota)\s+", "", str(n))).replace(" ", ""))

    def code_of(r):
        return (key_to_code.get((r.prov, r.lvl, r.key)) or key_prov.get((r.prov, r.key)) or nat_code.get(r.key)
                or natl_code.get((r.lvl, r.key)) or full_code.get(r.full) or full_code.get("kota" + r.full))
    pairs = d[["prov", "lvl", "key", "full"]].drop_duplicates()
    pairs["unit_code"] = pairs.apply(code_of, axis=1)
    d = d.merge(pairs, on=["prov", "lvl", "key", "full"], how="left")
    um = d[d["unit_code"].isna()].groupby(["provinsi", "kabupaten_kota"])[value_col].sum().sort_values(ascending=False)
    if len(um):
        log(f"{len(um)} kabupaten/kota names not matched to a BPS code (their investment is dropped; largest first):")
        log(um.head(25).to_string())
    d = d[d["unit_code"].notna()].copy()
    d["year"] = d["year"].astype(int)
    pma = d[d["status_penanaman_modal"] == "PMA"]
    g = pma.groupby(["unit_code", "year"])
    out = pd.DataFrame({
        "china_usd_k": pma[value_col].where(pma["origin"] == "china", 0).groupby([pma["unit_code"], pma["year"]]).sum(),
        "hk_usd_k": pma[value_col].where(pma["origin"] == "hk", 0).groupby([pma["unit_code"], pma["year"]]).sum(),
        "fdi_usd_k": g[value_col].sum(),
    }).reset_index()
    pmdn = d[d["status_penanaman_modal"] == "PMDN"].groupby(["unit_code", "year"])[value_col].sum().rename("pmdn_usd_k")
    out = out.merge(pmdn.reset_index(), on=["unit_code", "year"], how="outer").fillna(0)
    out["china_plus_hk_usd_k"] = out["china_usd_k"] + out["hk_usd_k"]
    return out.sort_values(["unit_code", "year"]).reset_index(drop=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True)
    ap.add_argument("--codes", default="data/raw/bps_kabupaten_codes.csv")
    ap.add_argument("--out", default="data/raw/china_investment.csv")
    a = ap.parse_args(argv)
    out = convert(a.src, a.codes)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(a.out, index=False)
    print(f"{len(out)} kabupaten-years, {out['unit_code'].nunique()} units, years {out['year'].min()}..{out['year'].max()} -> {a.out}")
    print("Chinese FDI (thousand USD) by year, all kabupaten:")
    print(out.groupby("year")[["china_usd_k", "hk_usd_k", "fdi_usd_k"]].sum().round(0).to_string())
    print("kabupaten with any Chinese FDI, by year:")
    print(out[out["china_usd_k"] > 0].groupby("year")["unit_code"].nunique().to_string())
    top = out[out["year"].between(2021, 2023)].groupby("unit_code")["china_usd_k"].sum().nlargest(10)
    print("top 10 kabupaten by Chinese FDI 2021-2023 (thousand USD):")
    print(top.round(0).to_string())


if __name__ == "__main__":
    main()
