"""`python -m foreigners.cli <command>`: foreign-national presence by kabupaten."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import requests

from konghucu.bps_api import get_key
from konghucu.harmonize import load_code_table

from . import bps_tables, ckan, dukcapil_wna, harmonize
from .nationality import LONG_COLUMNS


def cmd_bps_search(a):
    df = bps_tables.search_all_provinces(requests.Session(), get_key())
    df.to_csv(a.out, index=False)
    print(f"{len(df)} tables, {int(df['by_nationality'].sum())} by nationality -> {a.out}")
    print(df[df["by_nationality"]][["domain", "table_id", "title"]].to_string(index=False))


def cmd_bps_fetch(a):
    cat = pd.read_csv(a.catalogue, dtype={"domain": str, "province_code": str, "table_id": str})
    if not a.all:
        cat = cat[cat["by_nationality"]]
    df = bps_tables.fetch_tables(requests.Session(), cat, get_key(), raw_dir=a.raw_dir)
    df.to_csv(a.out, index=False)
    print(f"{len(df)} rows; CHN rows: {int((df['nationality'] == 'CHN').sum())} -> {a.out}")
    print(df.groupby(["region_level", "permit_type"], dropna=False).size().to_string())


def cmd_ckan_search(a):
    df = ckan.search_all(requests.Session(), portals=a.portals)
    df.to_csv(a.out, index=False)
    print(f"{len(df)} tabular resources -> {a.out}")
    print(df[["organization", "title", "format", "modified"]].to_string(index=False))


def cmd_ckan_fetch(a):
    s = requests.Session()
    cat = pd.read_csv(a.catalogue)
    if a.rows:
        cat = cat.iloc[a.rows]
    parts = []
    for rec in cat.itertuples(index=False):
        dest = Path(a.raw_dir) / f"{rec.resource_id}.{rec.format.lower()}"
        try:
            ckan.download_resource(s, rec.url, dest)
            df = ckan.read_tabular(dest)
            long = ckan.table_to_long(df, ref=f"ckan:{rec.resource_id}", province_code=a.province_code,
                                      year=a.year, region_level=a.region_level)
            print(f"{rec.title}: {len(long)} rows, columns were {list(df.columns)}")
            parts.append(long)
        except Exception as e:  # noqa: BLE001
            print(f"{rec.title}: FAILED {type(e).__name__}: {e}")
    out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=LONG_COLUMNS)
    out.to_csv(a.out, index=False)


def cmd_pdf_wna(a):
    parts = []
    for p in a.pdfs:
        try:
            d = dukcapil_wna.extract_pdf(p, a.province_code, a.year, a.semester, a.region_level)
            print(f"{p}: {len(d)} rows")
            parts.append(d)
        except Exception as e:  # noqa: BLE001
            print(f"{p}: FAILED {type(e).__name__}: {e}")
    out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=LONG_COLUMNS)
    out.to_csv(a.out, index=False)


def cmd_harmonize(a):
    long = pd.concat([pd.read_csv(p, dtype={"province_code": str}) for p in a.inputs], ignore_index=True)
    codes = load_code_table(a.codes) if a.codes else None
    cw = harmonize.load_kanim_crosswalk(a.kanim_crosswalk) if a.kanim_crosswalk else None
    alloc = harmonize.allocate_to_kabupaten(long, cw, codes)
    alloc.to_csv(a.out_long, index=False)
    prov = long[long["region_level"] == "province"]
    panel = harmonize.build_panel(alloc, prov)
    panel.to_csv(a.out_panel, index=False)
    unmatched = alloc[alloc["unit_code"].isna()]["region_name"].drop_duplicates()
    print(f"{len(alloc)} kabupaten-level rows, {int(alloc['unit_code'].notna().sum())} with a code; "
          f"{len(unmatched)} unmatched region names (first 30 below) -> {a.out_long}")
    print(unmatched.head(30).to_string(index=False))
    print(f"panel: {len(panel)} unit-years -> {a.out_panel}")


def build_parser():
    p = argparse.ArgumentParser(prog="foreigners", description=__doc__)
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("bps-search"); s.add_argument("--out", default="data/foreigners/bps_catalogue.csv"); s.set_defaults(func=cmd_bps_search)
    f = sp.add_parser("bps-fetch"); f.add_argument("--catalogue", default="data/foreigners/bps_catalogue.csv")
    f.add_argument("--all", action="store_true"); f.add_argument("--raw-dir", default="data/raw/bps_foreign")
    f.add_argument("--out", default="data/foreigners/bps_long.csv"); f.set_defaults(func=cmd_bps_fetch)
    c = sp.add_parser("ckan-search"); c.add_argument("--portals", nargs="+", default=ckan.DEFAULT_PORTALS)
    c.add_argument("--out", default="data/foreigners/ckan_catalogue.csv"); c.set_defaults(func=cmd_ckan_search)
    g = sp.add_parser("ckan-fetch"); g.add_argument("--catalogue", default="data/foreigners/ckan_catalogue.csv")
    g.add_argument("--rows", type=int, nargs="*", help="catalogue row numbers to fetch (default all)")
    g.add_argument("--province-code", default=None); g.add_argument("--year", type=int, default=None)
    g.add_argument("--region-level", default="province"); g.add_argument("--raw-dir", default="data/raw/ckan")
    g.add_argument("--out", default="data/foreigners/ckan_long.csv"); g.set_defaults(func=cmd_ckan_fetch)
    w = sp.add_parser("pdf-wna"); w.add_argument("pdfs", nargs="+"); w.add_argument("--province-code", required=True)
    w.add_argument("--year", type=int, default=None); w.add_argument("--semester", type=int, default=None)
    w.add_argument("--region-level", default="kecamatan", choices=["kecamatan", "kabupaten"])
    w.add_argument("--out", default="data/foreigners/dukcapil_wna_long.csv"); w.set_defaults(func=cmd_pdf_wna)
    h = sp.add_parser("harmonize"); h.add_argument("--inputs", nargs="+", required=True)
    h.add_argument("--codes", default=None, help="BPS unit_code,unit_name CSV")
    h.add_argument("--kanim-crosswalk", default=None, help="CSV: kanim, unit_code[, weight]")
    h.add_argument("--out-long", default="data/foreigners/foreign_long_kabupaten.csv")
    h.add_argument("--out-panel", default="data/foreigners/foreign_panel.csv"); h.set_defaults(func=cmd_harmonize)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    sys.exit(main())
