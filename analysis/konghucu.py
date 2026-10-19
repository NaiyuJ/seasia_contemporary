"""Konghucu (Confucian) registration and Chinese investment: descriptives, long differences, TWFE.

Inputs (all produced by rerunnable commands, see README):
  data/konghucu/religion_panel.csv      kabupaten x year, from `konghucu.cli harmonize`
  data/raw/bps_kabupaten_codes.csv      names
  data/raw/china_investment.csv         OPTIONAL: unit_code, year, <value column>; Chinese
                                        realised investment by kabupaten-year (BKPM)

Outcome: registered Konghucu per 1,000 residents (official population as denominator).
Two samples: EXACT (the table has a Konghucu column) and UB (Konghucu folded into
'Lainnya' with Kepercayaan: an upper bound). Only Dukcapil-type cells are used: a
religion total within 0.8..1.25 of the official population; Ministry of Religion
adherent counts exceed it and are a different concept.

    python -m analysis.konghucu                       # descriptives + 2021->2023 changes
    python -m analysis.konghucu --investment data/raw/china_investment.csv --inv-col value
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

RELIGION_SHARES = ["konghucu", "buddha", "kristen", "katolik"]


def load_panel(path: str, codes: Optional[str] = None) -> pd.DataFrame:
    p = pd.read_csv(path, dtype={"unit_code": str})
    p = p[p["population"].notna() & (p["population"] > 0)].copy()
    p["dukcapil_type"] = p["total_to_pop"].between(0.8, 1.25)
    p["y_exact"] = p["konghucu"] / p["population"] * 1000
    p["y_ub"] = p["konghucu_ub"] / p["population"] * 1000
    for r in ["buddha", "kristen", "katolik"]:
        if r in p.columns:
            p[f"share_{r}"] = p[r] / p["population"] * 1000
    p["log_pop"] = np.log(p["population"])
    p["province_code"] = p["unit_code"].str[:2]
    if codes and Path(codes).exists():
        c = pd.read_csv(codes, dtype=str)
        p = p.merge(c[["unit_code", "unit_name"]].drop_duplicates("unit_code"), on="unit_code", how="left")
    return p


# provinces whose 'Lainnya' is an indigenous religion (Marapu in NTT, Kaharingan in Kalimantan
# Tengah, local religions in Papua), so the upper bound says nothing about Konghucu there
UB_EXCLUDE_PROVINCES = ("53", "62", "91", "92", "93", "94", "95", "96")
COUNT_OF = {"y_exact": "konghucu", "y_ub": "konghucu_ub", "share_buddha": "buddha", "share_kristen": "kristen",
            "share_katolik": "katolik"}


def two_period(p: pd.DataFrame, y: str, t0: int = 2021, t1: int = 2023) -> pd.DataFrame:
    """Units observed (Dukcapil-type) in both years: level in each and three changes:
    `change` in per-1,000 with each year's own population, `change_fixedpop` with the t0
    population for both years (so population growth alone does not read as a fall), and
    `dlog_count` = log(1+count_t1) - log(1+count_t0)."""
    d = p[p["dukcapil_type"] & p["year"].isin([t0, t1]) & p[y].notna()]
    if y == "y_ub":
        d = d[~d["province_code"].isin(UB_EXCLUDE_PROVINCES)]
    w = d.pivot_table(index="unit_code", columns="year", values=y)
    w = w.dropna(subset=[t0, t1])
    out = w.rename(columns={t0: f"y{t0}", t1: f"y{t1}"})
    out["change"] = out[f"y{t1}"] - out[f"y{t0}"]
    cnt = d.pivot_table(index="unit_code", columns="year", values=COUNT_OF[y]).reindex(out.index)
    pop0 = d[d["year"] == t0].set_index("unit_code")["population"].reindex(out.index)
    out["change_fixedpop"] = (cnt[t1] - cnt[t0]) / pop0 * 1000
    out["dlog_count"] = np.log1p(cnt[t1]) - np.log1p(cnt[t0])
    base = d.drop_duplicates("unit_code").set_index("unit_code")
    for c in ["unit_name", "province_code"]:
        if c in base.columns:
            out[c] = base[c]
    out["log_pop"] = d[d["year"] == t0].set_index("unit_code")["log_pop"]
    # both years from the same kind of source (API table / yearbook)? a switch between them
    # is the usual reason for a large apparent change (Mojokerto 0.30 -> 0.03)
    src = d.assign(src=d["ref"].astype(str).str.split(":").str[0]).pivot_table(
        index="unit_code", columns="year", values="src", aggfunc="first").reindex(out.index)
    out["same_source"] = (src[t0] == src[t1]).fillna(False).astype(bool)
    return out.reset_index()


def describe(p: pd.DataFrame) -> dict:
    out = {}
    dk = p[p["dukcapil_type"]]
    out["coverage"] = dk.groupby("year").agg(units=("unit_code", "nunique"),
                                             exact=("y_exact", lambda s: int(s.notna().sum())),
                                             ub=("y_ub", lambda s: int(s.notna().sum()))).loc[2019:2023]
    for y in ["y_exact", "y_ub"]:
        s = dk[dk["year"].isin([2021, 2023]) & dk[y].notna()]
        out[f"levels_{y}"] = s.groupby("year")[y].describe(percentiles=[.25, .5, .75, .9]).round(3)
    for y in ["y_exact", "y_ub"]:
        tp = two_period(p, y)
        out[f"two_period_{y}"] = tp
        out[f"change_summary_{y}"] = pd.Series({
            "units": len(tp), "mean_change": tp["change"].mean(), "median_change": tp["change"].median(),
            "mean_change_fixedpop": tp["change_fixedpop"].mean(), "median_change_fixedpop": tp["change_fixedpop"].median(),
            "share_count_up": (tp["dlog_count"] > 0).mean(), "share_count_down": (tp["dlog_count"] < 0).mean(),
            "share_count_unchanged": (tp["dlog_count"] == 0).mean(),
            "units_same_source": int(tp["same_source"].sum())}).round(4)
    return out


def ols(y: np.ndarray, X: pd.DataFrame, cluster: Optional[pd.Series] = None, hc: str = "HC1"):
    import statsmodels.api as sm
    sd, mean = X.std(numeric_only=True), X.abs().mean(numeric_only=True)
    X = X.loc[:, sd > 1e-9 * (mean + 1)]  # a constant regressor (no investment at baseline) is dropped
    Xc = sm.add_constant(X, has_constant="add")
    m = sm.OLS(y, Xc, missing="drop")
    if cluster is not None:
        groups = pd.factorize(cluster.loc[Xc.index].astype(str))[0]  # statsmodels wants integer group ids
        if groups.max() >= 1:  # at least two clusters, else fall back to heteroskedasticity-robust SE
            return m.fit(cov_type="cluster", cov_kwds={"groups": groups})
    return m.fit(cov_type=hc)


def long_difference(tp: pd.DataFrame, inv: pd.DataFrame, inv_col: str, t0: int = 2021, t1: int = 2023,
                    province_fe: bool = False, outcome: str = "change_fixedpop", treatment: str = "log",
                    interact_high: bool = False):
    """change in y (a stock) on log(1 + investment flow realised in the window t0+1..t1)
    (`treatment="any"`: a dummy for any flow in the window instead), controlling for
    log(1 + cumulative investment up to t0), the baseline level of y and log population; HC1 or
    province-clustered SE. `d_inv` is the window flow. `interact_high` adds a dummy for a
    baseline y at or above the sample median and its product with d_inv (`d_inv_x_high`): the
    identity mechanism can only operate where there are Chinese Indonesians to re-register."""
    flow = inv[inv["year"].between(t0 + 1, t1)].groupby("unit_code")[inv_col].sum()
    stock = inv[inv["year"] <= t0].groupby("unit_code")[inv_col].sum()
    iv = pd.DataFrame({"d_inv": np.log1p(flow), "inv_base": np.log1p(stock)}).fillna(0)
    d = tp.merge(iv[["d_inv", "inv_base"]], left_on="unit_code", right_index=True, how="left")
    d["d_inv"] = d["d_inv"].fillna(0)
    d["inv_base"] = d["inv_base"].fillna(0)
    if treatment == "any":
        d["d_inv"] = (d["d_inv"] > 0).astype(float)
    cols = ["d_inv", "inv_base", f"y{t0}", "log_pop"]
    if interact_high:
        d["high"] = (d[f"y{t0}"] >= d[f"y{t0}"].median()).astype(float)
        d["d_inv_x_high"] = d["d_inv"] * d["high"]
        cols = ["d_inv", "high", "d_inv_x_high", "inv_base", f"y{t0}", "log_pop"]
    X = d[cols].copy()
    if province_fe and "province_code" in d.columns:
        X = pd.concat([X, pd.get_dummies(d["province_code"], prefix="prov", drop_first=True, dtype=float)], axis=1)
    return ols(d[outcome].values, X, cluster=d["province_code"] if province_fe else None), d


def twfe(p: pd.DataFrame, y: str, inv: pd.DataFrame, inv_col: str, years=(2019, 2023)):
    """y_it (a stock) on log(1 + cumulative investment up to t) with unit and year fixed
    effects (within transformation), SE clustered by unit."""
    d = p[p["dukcapil_type"] & p["year"].between(*years) & p[y].notna()].copy()
    iv = inv.groupby(["unit_code", "year"])[inv_col].sum().unstack("year").fillna(0)
    iv = iv.reindex(columns=range(int(iv.columns.min()), years[1] + 1), fill_value=0).cumsum(axis=1)
    cum = iv.stack().rename("inv").reset_index()
    cum.columns = ["unit_code", "year", "inv"]
    d = d.merge(cum, on=["unit_code", "year"], how="left")
    d["inv"] = np.log1p(d["inv"].fillna(0))
    d = d[d.groupby("unit_code")["year"].transform("size") >= 2]
    # within transformation for the unit effect, year dummies for the year effect
    for c in [y, "inv", "log_pop"]:
        d[f"{c}_w"] = d[c] - d.groupby("unit_code")[c].transform("mean")
    X = pd.concat([d[["inv_w", "log_pop_w"]], pd.get_dummies(d["year"], prefix="yr", drop_first=True, dtype=float)], axis=1)
    res = ols(d[f"{y}_w"].values, X, cluster=d["unit_code"])
    return res, d


def _row(spec: str, res, name: str = "d_inv") -> dict:
    """one results-table row; NaN when the regressor was constant and dropped (e.g. every
    unit treated, so the any-investment dummy has no variation)."""
    return {"spec": spec, "n": int(res.nobs), "coef_d_inv": res.params.get(name, np.nan),
            "se": res.bse.get(name, np.nan), "p": res.pvalues.get(name, np.nan)}


def load_investment(path: str, inv_col: str) -> pd.DataFrame:
    inv = pd.read_csv(path, dtype={"unit_code": str})
    inv["unit_code"] = inv["unit_code"].str.zfill(4)
    inv["year"] = inv["year"].astype(int)
    inv[inv_col] = pd.to_numeric(inv[inv_col], errors="coerce").fillna(0)
    return inv


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--panel", default="data/konghucu/religion_panel.csv")
    ap.add_argument("--codes", default="data/raw/bps_kabupaten_codes.csv")
    ap.add_argument("--investment", default=None, help="CSV with unit_code, year and the investment column")
    ap.add_argument("--inv-col", default="value")
    ap.add_argument("--out", default="data/konghucu/analysis")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 200)
    p = load_panel(a.panel, a.codes)
    print(f"panel rows with population: {len(p)}; Dukcapil-type (total within 0.8-1.25 of population): "
          f"{int(p['dukcapil_type'].sum())}")
    desc = describe(p)
    print("\n== Dukcapil-type coverage by year (units; with exact konghucu; with exact or upper bound)")
    print(desc["coverage"].to_string())
    for y, label in [("y_exact", "EXACT konghucu per 1,000"), ("y_ub", "UPPER BOUND (konghucu or lainnya) per 1,000")]:
        print(f"\n== {label}: levels in 2021 and 2023")
        print(desc[f"levels_{y}"].to_string())
        print(f"-- change 2021 -> 2023, units observed in both years:")
        print(desc[f"change_summary_{y}"].to_string())
        tp = desc[f"two_period_{y}"]
        tp.to_csv(out / f"two_period_{y}.csv", index=False)
        cols = [c for c in ["unit_code", "unit_name", "y2021", "y2023", "change_fixedpop", "dlog_count", "same_source"] if c in tp.columns]
        print("-- largest increases (per 1,000, base-year population):")
        print(tp.nlargest(8, "change_fixedpop")[cols].round(3).to_string(index=False))
        print("-- largest decreases:")
        print(tp.nsmallest(5, "change_fixedpop")[cols].round(3).to_string(index=False))
    if not a.investment:
        print("\nno --investment file: regressions skipped. Expected: CSV with unit_code (BPS 4-digit), year, "
              f"and a value column (--inv-col, default 'value'); one row per kabupaten-year (or several, summed).")
        return
    inv = load_investment(a.investment, a.inv_col)
    print(f"\ninvestment: {len(inv)} rows, {inv['unit_code'].nunique()} units, years {inv['year'].min()}..{inv['year'].max()}; "
          f"units in panel sample with any investment: "
          f"{inv[inv[a.inv_col] > 0]['unit_code'].isin(p[p['dukcapil_type']]['unit_code']).sum()}")
    rows = []
    for y in ["y_exact", "y_ub"]:
        tp = desc[f"two_period_{y}"]
        for fe in (False, True):
            res, d = long_difference(tp, inv, a.inv_col, province_fe=fe)
            rows.append({"spec": f"long-diff {y}{' +prov FE' if fe else ''}", "n": int(res.nobs),
                         "coef_d_inv": res.params["d_inv"], "se": res.bse["d_inv"], "p": res.pvalues["d_inv"]})
        res, d = long_difference(tp, inv, a.inv_col, outcome="dlog_count")
        rows.append({"spec": f"long-diff {y} dlog(count)", "n": int(res.nobs),
                     "coef_d_inv": res.params["d_inv"], "se": res.bse["d_inv"], "p": res.pvalues["d_inv"]})
        res, d = long_difference(tp[tp["same_source"]], inv, a.inv_col)
        rows.append({"spec": f"long-diff {y} same-source pairs only", "n": int(res.nobs),
                     "coef_d_inv": res.params["d_inv"], "se": res.bse["d_inv"], "p": res.pvalues["d_inv"]})
        res, d = long_difference(tp, inv, a.inv_col, treatment="any")
        rows.append(_row(f"long-diff {y} any-investment dummy", res))
        res, d = long_difference(tp, inv, a.inv_col, interact_high=True)
        rows.append(_row(f"long-diff {y} x high baseline (interaction)", res, "d_inv_x_high"))
        if "6172" in set(tp["unit_code"]):  # Singkawang drives most of the movement in the exact sample
            res, d = long_difference(tp[tp["unit_code"] != "6172"], inv, a.inv_col)
            rows.append({"spec": f"long-diff {y} without Singkawang", "n": int(res.nobs),
                         "coef_d_inv": res.params["d_inv"], "se": res.bse["d_inv"], "p": res.pvalues["d_inv"]})
        res, d = twfe(p, y, inv, a.inv_col)
        rows.append({"spec": f"TWFE {y} 2019-2023", "n": int(res.nobs), "coef_d_inv": res.params["inv_w"],
                     "se": res.bse["inv_w"], "p": res.pvalues["inv_w"]})
    for r in ["share_buddha", "share_kristen", "share_katolik"]:  # placebo outcomes
        if r in p.columns:
            tp = two_period(p, r)
            res, d = long_difference(tp, inv, a.inv_col)
            rows.append({"spec": f"placebo long-diff {r}", "n": int(res.nobs), "coef_d_inv": res.params["d_inv"],
                         "se": res.bse["d_inv"], "p": res.pvalues["d_inv"]})
    tab = pd.DataFrame(rows)
    tab.to_csv(out / "regressions.csv", index=False)
    print("\n== effect of the change in log(1+investment) on the outcome (per 1,000 residents)")
    print(tab.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
