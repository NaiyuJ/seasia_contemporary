"""`python -m konghucu.cli <command>`: collect public religion-by-kabupaten tables."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd


def _out(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path
import requests

from . import arcgis, bps_api, dalam_angka, harmonize, pdf_tables, population
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
        if not (self.out.exists() and self.out.stat().st_size > 0):
            return pd.DataFrame(columns=self.columns)
        df = pd.read_csv(self.out, dtype=str)
        key = [c for c in ("domain", "table_id", "var_id") if c in df.columns]
        return df.drop_duplicates(key).reset_index(drop=True)


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
        df = df.drop_duplicates([c for c in ("domain", "table_id", "var_id") if c in df.columns])
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


def cmd_bps_codes(a):
    """Write the BPS kabupaten/kota code table from the API's domain list."""
    df = bps_api.kabupaten_code_table(requests.Session(), bps_api.get_key())
    df.to_csv(_out(a.out), index=False)
    print(f"{len(df)} kabupaten/kota codes -> {a.out}")


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
    if a.raw_rows:
        import re
        from konghucu.htmltable import unescape_if_needed
        trs = re.findall(r"<tr[^>]*>.*?</tr>", unescape_if_needed(html), flags=re.S | re.I)
        ws = re.compile(r"\s+")
        tags = re.compile(r"<[^>]+>")
        for i, tr in enumerate(trs[:a.raw_rows]):
            cells = re.findall(r"<t[dh]([^>]*)>(.*?)</t[dh]>", tr, flags=re.S | re.I)
            parts = []
            for attrs, txt in cells:
                attrs_s = ws.sub(" ", attrs).strip()[:40]
                txt_s = ws.sub(" ", tags.sub(" ", txt)).strip()[:25]
                parts.append(f"[{attrs_s}] {txt_s}")
            print(f"-- raw row {i}: " + " | ".join(parts))
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


def cmd_bps_publications(a):
    """List (and optionally download) BPS PDF publications for some domains, e.g. the yearly
    'Kabupaten Sambas Dalam Angka' books whose religion table is not in the API as a table."""
    key = bps_api.get_key()
    s = requests.Session()
    rows, seen = [], set()
    # searching 'dalam angka 2024' instead of 'dalam angka' skips the hundreds of
    # per-kecamatan booklets a domain lists (Sambas: 346), i.e. ~30 pages per domain
    keywords = [f"{a.keyword} {y}" for y in a.years] if a.years else [a.keyword]
    for i, dom in enumerate(a.domains, 1):
        n = 0
        for kw in keywords:
            try:
                found = bps_api.list_publications(s, dom, kw, key)
            except RuntimeError as e:
                print(f"  [{i}/{len(a.domains)}] {dom}: {e}", flush=True)
                continue
            for r in found:
                if (dom, r.get("pub_id")) in seen:
                    continue
                seen.add((dom, r.get("pub_id")))
                n += 1
                rows.append({"domain": dom, "pub_id": r.get("pub_id"), "title": r.get("title"), "rl_date": r.get("rl_date"),
                             "size": r.get("size"), "pdf": r.get("pdf")})
        print(f"  [{i}/{len(a.domains)}] {dom}: {n} publications matching {keywords}", flush=True)
    df = pd.DataFrame(rows, columns=["domain", "pub_id", "title", "rl_date", "size", "pdf"])
    if a.years:
        df = df[df["title"].astype(str).str.contains("|".join(a.years), regex=True)]
    if a.title_regex:
        df = df[df["title"].astype(str).str.contains(a.title_regex, regex=True, case=False)]
    df.to_csv(_out(a.out), index=False)
    pd.set_option("display.max_colwidth", 70)
    pd.set_option("display.width", 200)
    print(df[["domain", "pub_id", "rl_date", "size", "title"]].to_string(index=False))
    print(f"{len(df)} publications -> {a.out}")
    if a.download:
        out_dir = Path(a.download)
        out_dir.mkdir(parents=True, exist_ok=True)
        for r in df.itertuples(index=False):
            if not r.pdf:
                continue
            dest = out_dir / f"{r.domain}_{r.pub_id}.pdf"
            if dest.exists() and dest.stat().st_size > 0:
                print(f"  have {dest}")
                continue
            try:
                resp = s.get(r.pdf, timeout=120)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
                print(f"  {dest} ({len(resp.content) // 1024} KB)  {str(r.title)[:50]}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"  {dest}: FAILED {type(e).__name__}: {str(e)[:80]}")


def cmd_dalam_angka_extract(a):
    """Religion tables out of 'Dalam Angka' PDFs (from bps-publications --download)."""
    parts, status = [], []
    titles = {}
    if Path(a.catalogue).exists():
        cat = pd.read_csv(a.catalogue, dtype=str)
        titles = dict(zip(cat["domain"] + "_" + cat["pub_id"], cat["title"]))
    for p in a.pdfs:
        stem = Path(p).stem
        title = titles.get(stem, "")
        if re.match(r"(?i)^(kecamatan|distrik|kapanewon|kemantren)\b", title) or re.search(r"(?i)infografis", title):
            continue  # per-kecamatan booklet or infographic, not the yearbook
        try:
            d = dalam_angka.extract_book(p, debug=a.debug)
            status.append((stem, d.attrs.get("status", "?"), title))
            if len(d):
                parts.append(d)
        except Exception as e:  # noqa: BLE001
            print(f"  {p}: FAILED {type(e).__name__}: {str(e)[:100]}")
            status.append((stem, "error", title))
    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=LONG_COLUMNS + ["level"])
    df.to_csv(_out(a.out), index=False)
    kab = df[df["level"] != "kecamatan"]
    print(f"{len(df)} rows ({len(kab)} kabupaten/kota-level) from {df['ref'].nunique()} books -> {a.out}")
    st = pd.DataFrame(status, columns=["book", "status", "title"])
    print("books by outcome:")
    print(st["status"].value_counts().to_string())
    bad = st[st["status"] != "ok"]
    if len(bad):
        print("books without a usable table (domain, outcome, title):")
        for r in bad.itertuples(index=False):
            print(f"  {r.book[:4]} {r.status:9s} {str(r.title)[:60]}")


def cmd_bps_population(a):
    """Find and fetch each province's official population-by-kabupaten series."""
    key = bps_api.get_key()
    s = requests.Session()
    pd.set_option("display.max_colwidth", 90)
    pd.set_option("display.width", 200)
    cat_path = Path(a.catalogue)
    if a.search or not cat_path.exists():
        print("== population variables in province domains")
        cat = population.search_population_vars(s, key, provinces=a.provinces)
        cat.to_csv(_out(a.catalogue), index=False)
    else:
        cat = pd.read_csv(cat_path, dtype=str)  # reclassify the cached titles: the rules may have changed
        cat["about_population"] = cat["title"].map(lambda x: population.classify_population_title(x)["about_population"])
    sel = cat[cat["about_population"]]
    if a.var_ids:
        sel = cat[cat["var_id"].astype(str).isin(a.var_ids)]
    print(f"{len(cat)} variables, {len(sel)} selected -> {a.catalogue}")
    print(sel[["domain", "domain_name", "var_id", "unit", "title"]].to_string(index=False))
    missing = [f"{c} {n}" for c, n in bps_api.PROVINCES.items()
               if c not in set(sel["province_code"]) and (not a.provinces or c in a.provinces)]
    if missing:
        print(f"== provinces with no candidate: {'; '.join(missing)}")
        print("   their variables whose title mentions penduduk (pick the right one and pass --var-ids):")
        for m in missing:
            code = m.split()[0]
            tt = cat[(cat["province_code"] == code) & cat["title"].str.contains("enduduk", na=False)
                     & ~cat["title"].str.lower().str.contains(population.NOT_POP_RE, na=False, regex=True)]
            for r in tt.head(20).itertuples(index=False):
                print(f"     {r.domain} var {r.var_id:>5} [{r.unit}] {str(r.title)[:95]}")
    if a.search_only:
        return
    print("== fetching")
    long = population.fetch_population(s, sel, key, raw_dir=a.raw_dir)
    codes = harmonize.load_code_table(a.codes)
    long = harmonize.attach_codes(long, codes)
    long.to_csv(_out(a.out_long), index=False)
    um = long[~long["matched"]]
    if len(um):
        print(f"{um['unit_name'].nunique()} names without a code (not in the population file):")
        print("  " + "; ".join(sorted(set(um['unit_name']))[:40]))
    pop = population.reconcile_population(long)
    pop.to_csv(_out(a.out), index=False)
    print(f"{len(pop)} unit-years, {pop['unit_code'].nunique()} units, years {pop['year'].min()}..{pop['year'].max()} -> {a.out}")
    print("units per year:")
    print(pop.groupby("year")["unit_code"].nunique().to_string())
    have = pop.groupby(pop["unit_code"].str[:2])["unit_code"].nunique()
    want = codes.groupby("province_code")["unit_code"].nunique()
    cov = pd.DataFrame({"units_with_population": have, "units_in_code_table": want}).fillna(0).astype(int)
    cov["name"] = cov.index.map(bps_api.PROVINCES)
    short = cov[cov["units_with_population"] < cov["units_in_code_table"]]
    print(f"provinces where some kabupaten have no population series ({len(short)}):")
    print(short.to_string())
    dis = pop[pop["spread"] > 1.05]
    if len(dis):
        print(f"{len(dis)} unit-years where BPS series disagree by >5% (median used):")
        print(dis.head(30).to_string(index=False))


def cmd_harmonize(a):
    codes = harmonize.load_code_table(a.codes)
    long = pd.concat([pd.read_csv(p, dtype={"province_code": str, "unit_code": str}) for p in a.inputs],
                     ignore_index=True)
    long = harmonize.attach_codes(long, codes)
    unmatched = long[~long["matched"] & (long["unit_name"] != "__PROVINCE__")]
    long.to_csv(_out(a.out_long), index=False)
    drop = harmonize.load_drop_cells(a.drop_cells)
    pop = None
    if a.population and Path(a.population).exists():
        pop = pd.read_csv(a.population, dtype={"unit_code": str})
        print(f"population anchor: {len(pop)} unit-years from {a.population}")
    elif a.population:
        print(f"no population file at {a.population}; run `python -m konghucu.cli bps-population` to build it")
    panel = harmonize.build_panel(long, exclude_refs=set(a.exclude_refs or ()), drop_cells=drop, population=pop)
    panel.to_csv(_out(a.out_panel), index=False)
    kab_rows = long[long["level"] != "kecamatan"]
    print(f"{len(long)} rows; non-kecamatan rows {len(kab_rows)}, of which matched to a code {int(kab_rows['matched'].sum())} "
          f"-> {a.out_long}")
    um = unmatched[unmatched["level"] != "kecamatan"]
    if len(um):
        g = um.groupby(["province_code", "unit_name"]).agg(rows=("ref", "size"), refs=("ref", lambda s: ";".join(sorted(set(s))[:3]))).reset_index()
        print(f"{len(g)} unmatched non-kecamatan names (all listed):")
        print(g.sort_values(["province_code", "unit_name"]).to_string(index=False))
    print(f"panel: {len(panel)} unit-year cells, {panel['unit_code'].nunique()} units -> {a.out_panel}")
    breaks = harmonize.konghucu_breaks(panel)
    out_breaks = Path(a.out_panel).with_name("konghucu_breaks.csv")
    breaks.to_csv(_out(str(out_breaks)), index=False)
    if len(breaks):
        print(f"konghucu count jumps >5x between adjacent observations ({len(breaks)}; likely Kemenag vs Dukcapil "
              f"source switch, see docs/konghucu_data_sources.md) -> {out_breaks}")
        print(breaks.to_string(index=False))
    else:
        print("no konghucu jumps >5x between adjacent observations")
    outl = harmonize.total_outliers(panel)
    out_outl = Path(a.out_panel).with_name("total_outliers.csv")
    outl.to_csv(_out(str(out_outl)), index=False)
    if len(outl):
        kinds = ", ".join(f"{k}={v}" for k, v in outl["anchor_kind"].value_counts().items())
        print(f"unit-years whose total is >35% off the anchor ({len(outl)}; anchor: {kinds}; a religion count "
              f"copied from the wrong row in the source; add to konghucu/drop_cells.csv after checking) -> {out_outl}")
        pd.set_option("display.width", 250)
        print(outl.to_string(index=False, float_format=lambda v: f"{v:,.0f}" if abs(v) >= 100 else f"{v:.2f}"))
    else:
        print("no unit-year totals >35% off the anchor")
    if "population" in panel.columns:
        cov = panel["population"].notna().mean()
        print(f"panel cells with an official population: {cov:.0%}")


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

    cd = sp.add_parser("bps-codes", help="write unit_code,unit_name for all kabupaten/kota from the BPS domain list")
    cd.add_argument("--out", default="data/raw/bps_kabupaten_codes.csv")
    cd.set_defaults(func=cmd_bps_codes)

    pr = sp.add_parser("bps-probe", help="print raw API responses for one static table and one variable")
    pr.add_argument("--domain", default="1200"); pr.add_argument("--table-id", default="2793")
    pr.add_argument("--var-domain", default="1200"); pr.add_argument("--var-id", default="804")
    pr.add_argument("--chars", type=int, default=1500)
    pr.set_defaults(func=cmd_bps_probe)

    ins = sp.add_parser("bps-inspect", help="show header mapping and parsed rows of one cached static table")
    ins.add_argument("--domain", required=True); ins.add_argument("--table-id", required=True)
    ins.add_argument("--raw-dir", default="data/raw/bps")
    ins.add_argument("--raw-rows", type=int, default=0, help="also print the first N raw <tr> rows with cell attributes")
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

    pb = sp.add_parser("bps-publications", help="list/download BPS PDF publications (e.g. 'Dalam Angka') per domain")
    pb.add_argument("--domains", nargs="+", required=True, help="BPS domain ids, e.g. 6101 6102 6172")
    pb.add_argument("--keyword", default="dalam angka")
    pb.add_argument("--years", nargs="*", help="keep titles containing any of these years")
    pb.add_argument("--title-regex", default=r"^(?!Kecamatan|Distrik|Kapanewon|Kemantren|Statistik|Indikator|Analisis)(?!.*[Ii]nfografis)",
                    help="keep titles matching this (default: drop the per-kecamatan/distrik booklets and side "
                         "publications; some BPS offices title the book 'Aceh Besar Dalam Angka' without 'Kabupaten'); '' for all")
    pb.add_argument("--download", default=None, help="directory to download the PDFs into, e.g. data/raw/pubs")
    pb.add_argument("--out", default="data/konghucu/bps_publications.csv")
    pb.set_defaults(func=cmd_bps_publications)

    da = sp.add_parser("dalam-angka-extract", help="religion tables out of 'Dalam Angka' PDF yearbooks")
    da.add_argument("pdfs", nargs="+")
    da.add_argument("--out", default="data/konghucu/dalam_angka_long.csv")
    da.add_argument("--debug", action="store_true", help="print how each book's table was read")
    da.add_argument("--catalogue", default="data/konghucu/bps_publications.csv",
                    help="bps-publications output, used to skip per-kecamatan booklets and name failures")
    da.set_defaults(func=cmd_dalam_angka_extract)

    pp = sp.add_parser("bps-population", help="official population by kabupaten/kota from BPS dynamic tables")
    pp.add_argument("--provinces", nargs="*", help="2-digit province codes; default all")
    pp.add_argument("--search", action="store_true", help="rescan the province domains even if the catalogue exists")
    pp.add_argument("--search-only", action="store_true", help="list candidate variables and stop")
    pp.add_argument("--var-ids", nargs="*", help="fetch exactly these var ids instead of the title-based selection")
    pp.add_argument("--catalogue", default="data/konghucu/bps_population_vars.csv")
    pp.add_argument("--codes", default="data/raw/bps_kabupaten_codes.csv")
    pp.add_argument("--raw-dir", default="data/raw/bps")
    pp.add_argument("--out-long", default="data/konghucu/population_long.csv")
    pp.add_argument("--out", default="data/konghucu/population.csv")
    pp.set_defaults(func=cmd_bps_population)

    h = sp.add_parser("harmonize", help="attach BPS codes and build the unit x year panel")
    h.add_argument("--codes", required=True, help="CSV with unit_code, unit_name")
    h.add_argument("--inputs", nargs="+", required=True, help="long CSVs from the fetch commands")
    h.add_argument("--exclude-refs", nargs="*", default=None, help="table refs to drop in addition to the built-in bad list")
    h.add_argument("--out-long", default="data/konghucu/religion_long.csv")
    h.add_argument("--out-panel", default="data/konghucu/religion_panel.csv")
    h.add_argument("--population", default="data/konghucu/population.csv",
                   help="unit_code,year,population from bps-population; used as denominator and sanity anchor")
    h.add_argument("--drop-cells", default=None,
                   help="CSV of unit_code,year,reason to leave out of the panel (default konghucu/drop_cells.csv)")
    h.set_defaults(func=cmd_harmonize)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    sys.exit(main())
