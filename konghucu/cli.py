"""`python -m konghucu.cli <command>`: collect public religion-by-kabupaten tables."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


def _out(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path
import requests

from . import arcgis, bps_api, harmonize, pdf_tables
from .religion import LONG_COLUMNS


def cmd_bps_search(a):
    key = bps_api.get_key()
    s = requests.Session()
    kw = a.keywords or None
    pd.set_option("display.max_colwidth", 100)
    pd.set_option("display.width", 200)
    print(f"== static tables ({a.level} domains)")
    df = bps_api.search_all_provinces(s, key, level=a.level, provinces=a.provinces, keywords=kw)
    df.to_csv(_out(a.out), index=False)
    sel = df[df["about_religion"]]
    print(f"{len(df)} tables, {len(sel)} about population by religion ({int(sel['is_percent'].sum())} are percentages) -> {a.out}")
    print(sel[["domain", "domain_name", "table_id", "is_percent", "title"]].to_string(index=False))
    print(f"== dynamic tables ({a.level} domains)")
    dv = bps_api.search_vars_all_provinces(s, key, level=a.level, provinces=a.provinces, keywords=kw)
    dv.to_csv(_out(a.out_vars), index=False)
    selv = dv[dv["about_religion"]]
    print(f"{len(dv)} variables, {len(selv)} about population by religion ({int(selv['is_percent'].sum())} are percentages) -> {a.out_vars}")
    print(selv[["domain", "domain_name", "var_id", "is_percent", "title"]].to_string(index=False))
    have = set(sel["province_code"]) | set(selv["province_code"])
    missing = [f"{c} {n}" for c, n in bps_api.PROVINCES.items() if c not in have and (not a.provinces or c in a.provinces)]
    print(f"== provinces with no population-by-religion table at this level: {len(missing)}")
    print("   " + "; ".join(missing))
    if a.level == "province" and missing:
        print("   try: python -m konghucu.cli bps-search --level kabupaten --provinces " +
              " ".join(m.split()[0] for m in missing))


def cmd_bps_fetch(a):
    key = bps_api.get_key()
    s = requests.Session()
    cat = pd.read_csv(a.catalogue, dtype={"domain": str, "province_code": str, "table_id": str})
    if not a.all:
        cat = cat[cat["about_religion"] & ~cat["is_percent"]]
    parts = [bps_api.fetch_tables(s, cat, key, raw_dir=a.raw_dir)]
    if Path(a.catalogue_vars).exists():
        cv = pd.read_csv(a.catalogue_vars, dtype={"domain": str, "province_code": str, "var_id": str})
        if not a.all:
            cv = cv[cv["about_religion"] & ~cv["is_percent"]]
        parts.append(bps_api.fetch_vars(s, cv, key, raw_dir=a.raw_dir))
    df = pd.concat(parts, ignore_index=True)
    df.to_csv(_out(a.out), index=False)
    print(f"{len(df)} rows from {df['ref'].nunique()} tables -> {a.out}")
    print(df.groupby(["province_code", "year"]).size().to_string())


def cmd_arcgis_discover(a):
    df = arcgis.discover_religion_layers(requests.Session(), a.base)
    df.to_csv(_out(a.out), index=False)
    print(df[df["n_religion_fields"] > 0].to_string(index=False) if (df["n_religion_fields"] > 0).any()
          else "no public layer with religion fields found; see 'error' column for token-protected ones")


def cmd_arcgis_fetch(a):
    s = requests.Session()
    wide = arcgis.query_all(s, a.layer_url)
    if a.raw_dir:
        Path(a.raw_dir).mkdir(parents=True, exist_ok=True)
        wide.to_csv(Path(a.raw_dir) / f"arcgis_{a.ref}.csv", index=False)
    print("columns:", list(wide.columns))
    df = arcgis.layer_to_long(wide, ref=f"arcgis:{a.ref}", year=a.year, semester=a.semester,
                              name_col=a.name_col, code_col=a.code_col, prov_col=a.prov_col)
    df.to_csv(_out(a.out), index=False)
    print(f"{len(df)} rows -> {a.out}")


def cmd_pdf_extract(a):
    parts = []
    for p in a.pdfs:
        try:
            d = pdf_tables.extract_pdf(p, province_code=a.province_code, year=a.year, semester=a.semester)
            print(f"{p}: {len(d)} rows, year={d['year'].iloc[0] if len(d) else None}")
            parts.append(d)
        except Exception as e:  # noqa: BLE001
            print(f"{p}: FAILED {type(e).__name__}: {e}")
    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=LONG_COLUMNS)
    df.to_csv(_out(a.out), index=False)


def cmd_harmonize(a):
    codes = harmonize.load_code_table(a.codes)
    long = pd.concat([pd.read_csv(p, dtype={"province_code": str, "unit_code": str}) for p in a.inputs],
                     ignore_index=True)
    long = harmonize.attach_codes(long, codes)
    unmatched = long[~long["matched"] & (long["unit_name"] != "__PROVINCE__")]
    long.to_csv(_out(a.out_long), index=False)
    panel = harmonize.build_panel(long)
    panel.to_csv(_out(a.out_panel), index=False)
    print(f"{len(long)} rows, {int(long['matched'].sum())} matched to a code; "
          f"{unmatched['unit_name'].nunique()} unmatched names -> {a.out_long}")
    if len(unmatched):
        print(unmatched[["province_code", "unit_name", "ref"]].drop_duplicates().head(40).to_string(index=False))
    print(f"panel: {len(panel)} unit-year cells, {panel['unit_code'].nunique()} units -> {a.out_panel}")


def build_parser():
    p = argparse.ArgumentParser(prog="konghucu", description=__doc__)
    sp = p.add_subparsers(dest="cmd", required=True)

    s = sp.add_parser("bps-search", help="catalogue BPS static tables about religion in every province")
    s.add_argument("--keywords", nargs="*", default=None, help="default: agama pemeluk umat penganut")
    s.add_argument("--level", choices=["province", "kabupaten"], default="province",
                   help="which BPS domains to scan; kabupaten is ~500 domains, use --provinces to limit")
    s.add_argument("--provinces", nargs="*", default=None, help="2-digit province codes to limit the scan")
    s.add_argument("--out", default="data/konghucu/bps_catalogue.csv")
    s.add_argument("--out-vars", default="data/konghucu/bps_catalogue_vars.csv")
    s.set_defaults(func=cmd_bps_search)

    f = sp.add_parser("bps-fetch", help="download and parse the catalogued tables")
    f.add_argument("--catalogue", default="data/konghucu/bps_catalogue.csv")
    f.add_argument("--catalogue-vars", default="data/konghucu/bps_catalogue_vars.csv")
    f.add_argument("--all", action="store_true", help="fetch every table, not only by_unit ones")
    f.add_argument("--raw-dir", default="data/raw/bps")
    f.add_argument("--out", default="data/konghucu/bps_long.csv")
    f.set_defaults(func=cmd_bps_fetch)

    d = sp.add_parser("arcgis-discover", help="scan GIS Dukcapil for layers with religion fields")
    d.add_argument("--base", default=arcgis.DEFAULT_BASE)
    d.add_argument("--out", default="data/konghucu/arcgis_layers.csv")
    d.set_defaults(func=cmd_arcgis_discover)

    g = sp.add_parser("arcgis-fetch", help="pull one layer and convert to long form")
    g.add_argument("--layer-url", required=True)
    g.add_argument("--ref", required=True, help="short label for this layer, e.g. dkb2023s2")
    g.add_argument("--year", type=int, required=True)
    g.add_argument("--semester", type=int, default=None)
    g.add_argument("--name-col"); g.add_argument("--code-col"); g.add_argument("--prov-col")
    g.add_argument("--raw-dir", default="data/raw/arcgis")
    g.add_argument("--out", default="data/konghucu/arcgis_long.csv")
    g.set_defaults(func=cmd_arcgis_fetch)

    e = sp.add_parser("pdf-extract", help="religion tables out of Dukcapil PDFs")
    e.add_argument("pdfs", nargs="+")
    e.add_argument("--province-code", default=None)
    e.add_argument("--year", type=int, default=None)
    e.add_argument("--semester", type=int, default=None)
    e.add_argument("--out", default="data/konghucu/pdf_long.csv")
    e.set_defaults(func=cmd_pdf_extract)

    h = sp.add_parser("harmonize", help="attach BPS codes and build the unit x year panel")
    h.add_argument("--codes", required=True, help="CSV with unit_code, unit_name")
    h.add_argument("--inputs", nargs="+", required=True, help="long CSVs from the fetch commands")
    h.add_argument("--out-long", default="data/konghucu/religion_long.csv")
    h.add_argument("--out-panel", default="data/konghucu/religion_panel.csv")
    h.set_defaults(func=cmd_harmonize)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    sys.exit(main())
