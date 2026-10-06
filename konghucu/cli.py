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


class _Checkpoint:
    """Append each scanned domain's rows to the catalogue CSV and its id to a .scanned
    sidecar, so an interrupted scan resumes where it stopped (--resume)."""

    def __init__(self, out: str, resume: bool, columns):
        self.out, self.scanned_path, self.columns = Path(_out(out)), Path(out + ".scanned"), columns
        self.done = set()
        if resume and self.scanned_path.exists():
            self.done = set(self.scanned_path.read_text().split())
        elif not resume:
            self.out.unlink(missing_ok=True)
            self.scanned_path.unlink(missing_ok=True)
        self.header_written = self.out.exists() and self.out.stat().st_size > 0

    def __call__(self, domain, rows):
        if rows:
            pd.DataFrame(rows, columns=self.columns).to_csv(self.out, mode="a", index=False, header=not self.header_written)
            self.header_written = True
        with self.scanned_path.open("a") as f:
            f.write(f"{domain}\n")

    def load(self):
        return pd.read_csv(self.out, dtype=str) if self.out.exists() and self.out.stat().st_size > 0 \
            else pd.DataFrame(columns=self.columns)


STATIC_COLS = ["domain", "province_code", "domain_name", "table_id", "title", "subj", "updt_date", "excel",
               "about_religion", "by_unit", "is_percent", "is_sub_kecamatan"]
VAR_COLS = ["domain", "province_code", "domain_name", "var_id", "title", "subj", "vertical", "unit", "notes",
            "about_religion", "by_unit", "is_percent", "is_sub_kecamatan"]


def cmd_bps_search(a):
    key = bps_api.get_key()
    s = requests.Session()
    kw = a.keywords or None
    pd.set_option("display.max_colwidth", 100)
    pd.set_option("display.width", 200)
    print(f"== static tables ({a.level} domains){' [resuming]' if a.resume else ''}")
    ck = _Checkpoint(a.out, a.resume, STATIC_COLS)
    bps_api.search_all_provinces(s, key, level=a.level, provinces=a.provinces, keywords=kw,
                                 skip_domains=ck.done, on_domain=ck)
    df = ck.load()
    for c in ("about_religion", "by_unit", "is_percent", "is_sub_kecamatan"):
        df[c] = df[c].astype(str).str.lower() == "true"
    sel = df[df["about_religion"]]
    print(f"{len(df)} tables, {len(sel)} about population by religion ({int(sel['is_percent'].sum())} are percentages) -> {a.out}")
    print(sel[["domain", "domain_name", "table_id", "is_percent", "title"]].to_string(index=False))
    if a.skip_vars:
        return
    print(f"== dynamic tables ({a.level} domains){' [resuming]' if a.resume else ''}")
    ckv = _Checkpoint(a.out_vars, a.resume, VAR_COLS)
    bps_api.search_vars_all_provinces(s, key, level=a.level, provinces=a.provinces, keywords=kw,
                                      skip_domains=ckv.done, on_domain=ckv)
    dv = ckv.load()
    for c in ("about_religion", "by_unit", "is_percent", "is_sub_kecamatan"):
        dv[c] = dv[c].astype(str).str.lower() == "true"
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
    def _load(paths):
        frames = [pd.read_csv(p, dtype=str) for p in paths if Path(p).exists() and Path(p).stat().st_size > 0]
        if not frames:
            return None
        df = pd.concat(frames, ignore_index=True)
        if "is_sub_kecamatan" not in df.columns:  # catalogues made before this flag existed
            df["is_sub_kecamatan"] = df["title"].map(lambda t: bps_api.classify_title(t)["is_sub_kecamatan"])
        for c in ("about_religion", "by_unit", "is_percent", "is_sub_kecamatan"):
            df[c] = df[c].astype(str).str.lower() == "true"
        return df if a.all else df[df["about_religion"] & ~df["is_percent"] & ~df["is_sub_kecamatan"]]

    parts = []
    cat = _load(a.catalogue)
    if cat is not None:
        print(f"static tables to fetch: {len(cat)}")
        parts.append(bps_api.fetch_tables(s, cat, key, raw_dir=a.raw_dir))
    cv = _load(a.catalogue_vars)
    if cv is not None:
        print(f"dynamic variables to fetch: {len(cv)}")
        parts.append(bps_api.fetch_vars(s, cv, key, raw_dir=a.raw_dir))
    if not parts:
        raise SystemExit("no catalogue files found; run bps-search first")
    df = pd.concat(parts, ignore_index=True)
    df.to_csv(_out(a.out), index=False)
    print(f"{len(df)} rows from {df['ref'].nunique()} tables -> {a.out}")
    if df.empty or "level" not in df.columns:
        print("nothing parsed; run `python -m konghucu.cli bps-probe` and paste the output")
        return
    print("rows by level and source:")
    print(df.groupby(["level", "source"]).size().to_string())
    print("rows by religion label:")
    print(df["religion"].value_counts().to_string())
    kab = df[df["level"] != "kecamatan"]
    cov = kab.groupby("ref")["religion"].agg(lambda s: "konghucu" in set(s))
    print(f"tables with a konghucu column: {int(cov.sum())} of {len(cov)}; without (first 15):")
    print("  " + "\n  ".join(cov[~cov].index[:15]))
    k = df[(df["religion"] == "konghucu") & (df["unit_name"] != "__PROVINCE__") & (df["level"] != "kecamatan")]
    if len(k):
        print("konghucu rows at kabupaten level (or unit rows of province tables), by province and year:")
        print(k.groupby(["province_code", "year"]).agg(units=("unit_name", "nunique")).unstack("year")
              .fillna(0).astype(int).to_string())
    else:
        print("no konghucu rows found; inspect data/raw/bps and the column headers")


def cmd_bps_probe(a):
    """Print the raw API responses for one static table and one dynamic variable."""
    import json
    key = bps_api.get_key()
    s = requests.Session()
    print(f"== static table view: domain={a.domain} table_id={a.table_id}")
    js = bps_api.view_static_table_raw(s, a.domain, a.table_id, key)
    txt = json.dumps(js, ensure_ascii=False)
    print(txt[:a.chars])
    print(f"... ({len(txt)} chars total)")
    print(f"== years for var: domain={a.var_domain} var_id={a.var_id}")
    print(bps_api.list_years(s, a.var_domain, a.var_id, key))
    print(f"== dynamic data view: domain={a.var_domain} var_id={a.var_id} (all years, 2 per call)")
    js = bps_api.view_data_all_years(s, a.var_domain, a.var_id, key)
    txt = json.dumps(js, ensure_ascii=False)
    print(txt[:a.chars])
    print(f"... ({len(txt)} chars total)")


def cmd_bps_inspect(a):
    """Show how one cached static table was read: header cells and their religion mapping."""
    import json
    raw = Path(a.raw_dir) / f"bps_{a.domain}_{a.table_id}.html"
    if not raw.exists():
        raise SystemExit(f"{raw} not found; run bps-fetch first")
    html = raw.read_text(encoding="utf-8")
    for rep in bps_api.header_report(html):
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    d = bps_api.parse_religion_html(html, a.domain[:2], None, f"bps:{a.domain}:{a.table_id}")
    d = bps_api.rollup_kabupaten_domain(d, a.domain, a.domain)
    pd.set_option("display.width", 200)
    print(d[["unit_name", "level", "religion", "year", "count"]].head(40).to_string(index=False))


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
    s.add_argument("--resume", action="store_true", help="continue an interrupted scan (uses <out>.scanned)")
    s.add_argument("--skip-vars", action="store_true", help="only static tables")
    s.set_defaults(func=cmd_bps_search)

    f = sp.add_parser("bps-fetch", help="download and parse the catalogued tables")
    f.add_argument("--catalogue", nargs="+", default=["data/konghucu/bps_catalogue.csv", "data/konghucu/bps_catalogue_kab.csv"])
    f.add_argument("--catalogue-vars", nargs="+", default=["data/konghucu/bps_catalogue_vars.csv", "data/konghucu/bps_catalogue_vars_kab.csv"])
    f.add_argument("--all", action="store_true", help="fetch every table, not only by_unit ones")
    f.add_argument("--raw-dir", default="data/raw/bps")
    f.add_argument("--out", default="data/konghucu/bps_long.csv")
    f.set_defaults(func=cmd_bps_fetch)

    pr = sp.add_parser("bps-probe", help="print raw API responses for one static table and one variable")
    pr.add_argument("--domain", default="1200"); pr.add_argument("--table-id", default="2793")
    pr.add_argument("--var-domain", default="1200"); pr.add_argument("--var-id", default="804")
    pr.add_argument("--chars", type=int, default=1500)
    pr.set_defaults(func=cmd_bps_probe)

    ins = sp.add_parser("bps-inspect", help="show header mapping and parsed rows of one cached static table")
    ins.add_argument("--domain", required=True); ins.add_argument("--table-id", required=True)
    ins.add_argument("--raw-dir", default="data/raw/bps")
    ins.set_defaults(func=cmd_bps_inspect)

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
