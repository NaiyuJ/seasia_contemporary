"""Size check for the long-difference estimator: simulate the test DGP with NO investment
effect and report how often each standard-error choice rejects at the 5% level.

    python -m analysis.size_check [--reps 400] [--n 51] [--provinces 6]

Used to choose the covariance estimator in analysis/konghucu.py: with n = 51 and six
provinces, HC1 rejected 8%, HC3 7%, classical 7%, and province-clustered errors 20%.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import warnings
from pathlib import Path

import numpy as np
import pandas as pd


def synthetic(seed: int, n: int, provinces: int):
    rng = np.random.default_rng(seed)
    rows, inv = [], []
    for i in range(n):
        code = f"{11 + i % provinces}{i:02d}"
        pop = rng.integers(80_000, 900_000)
        base = rng.uniform(0, 3)
        on = float((i * 7 + seed) % 3 != 0)
        flow = {2019: 0.0, 2020: 0.0, 2021: 0.0, 2022: on * rng.uniform(0, 3000), 2023: on * rng.uniform(0, 5000)}
        for y in range(2019, 2024):
            k = max(base + rng.normal(0, 0.2), 0) * pop / 1000  # no effect of investment
            rows.append(dict(unit_code=code, year=y, population=pop, total=pop * 1.02, total_to_pop=1.02,
                             konghucu=k, konghucu_ub=k, konghucu_ub_is_lainnya=False, buddha=pop * 0.01,
                             kristen=pop * 0.05, katolik=pop * 0.01, ref="da:x:y"))
            inv.append(dict(unit_code=code, year=y, value=flow[y]))
    return pd.DataFrame(rows), pd.DataFrame(inv)


def rejection_rates(reps: int = 400, n: int = 51, provinces: int = 6) -> pd.Series:
    import statsmodels.api as sm
    from analysis import konghucu as an
    tmp = Path(tempfile.mkdtemp())
    rej = {k: 0 for k in ["HC1", "HC3", "classical", f"cluster_{provinces}", "provFE_HC3", "provFE_HC1"]}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for s in range(reps):
            panel, inv = synthetic(s, n, provinces)
            panel.to_csv(tmp / "p.csv", index=False)
            tp = an.two_period(an.load_panel(str(tmp / "p.csv")), "y_exact")
            _, d = an.long_difference(tp, inv, "value")
            X = sm.add_constant(d[["d_inv", "y2021", "log_pop"]])
            y = d["change_fixedpop"].values
            for cov, key in [("HC1", "HC1"), ("HC3", "HC3"), ("nonrobust", "classical")]:
                rej[key] += sm.OLS(y, X).fit(cov_type=cov).pvalues["d_inv"] < 0.05
            g = pd.factorize(d["province_code"])[0]
            rej[f"cluster_{provinces}"] += sm.OLS(y, X).fit(cov_type="cluster", cov_kwds={"groups": g}).pvalues["d_inv"] < 0.05
            Xf = pd.concat([X, pd.get_dummies(d["province_code"], prefix="p", drop_first=True, dtype=float)], axis=1)
            rej["provFE_HC3"] += sm.OLS(y, Xf).fit(cov_type="HC3").pvalues["d_inv"] < 0.05
            rej["provFE_HC1"] += sm.OLS(y, Xf).fit(cov_type="HC1").pvalues["d_inv"] < 0.05
    return pd.Series({k: v / reps for k, v in rej.items()}, name="rejection_rate_at_5pct")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=400)
    ap.add_argument("--n", type=int, default=51)
    ap.add_argument("--provinces", type=int, default=6)
    a = ap.parse_args(argv)
    print(rejection_rates(a.reps, a.n, a.provinces).round(3).to_string())


if __name__ == "__main__":
    main()
