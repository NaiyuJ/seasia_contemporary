import numpy as np
import pandas as pd
import pytest

pytest.importorskip("statsmodels")
from analysis import konghucu as an


def _panel(seed=0, n=60, effect=0.5):
    rng = np.random.default_rng(seed)
    rows, inv = [], []
    for i in range(n):
        code = f"{11 + i % 6}{i:02d}"  # six provinces
        pop = rng.integers(80_000, 900_000)
        base = rng.uniform(0, 3)
        x = {2019: 0.0, 2020: 0.0, 2021: 0.0, 2022: rng.uniform(0, 5), 2023: rng.uniform(0, 8)}
        for y in range(2019, 2024):
            k = (base + effect * x[y] + rng.normal(0, 0.2)) * pop / 1000
            rows.append(dict(unit_code=code, year=y, population=pop, total=pop * 1.02, total_to_pop=1.02,
                             konghucu=max(k, 0), konghucu_ub=max(k, 0), buddha=pop * 0.01, kristen=pop * 0.05,
                             katolik=pop * 0.01, ref="da:x:y"))
            inv.append(dict(unit_code=code, year=y, value=np.expm1(x[y])))
    return pd.DataFrame(rows), pd.DataFrame(inv)


def test_two_period_and_long_difference_recover_a_planted_effect(tmp_path):
    panel, inv = _panel()
    panel.to_csv(tmp_path / "panel.csv", index=False)
    p = an.load_panel(str(tmp_path / "panel.csv"))
    assert p["dukcapil_type"].all()
    tp = an.two_period(p, "y_exact")
    assert len(tp) == 60 and set(tp.columns) >= {"y2021", "y2023", "change", "change_fixedpop", "dlog_count", "log_pop"}
    assert np.allclose(tp["change"], tp["change_fixedpop"])  # constant population in the synthetic panel
    assert tp["same_source"].all()
    res, d = an.long_difference(tp, inv, "value")
    assert abs(res.params["d_inv"] - 0.5) < 0.15
    res_fe, _ = an.long_difference(tp, inv, "value", province_fe=True)
    assert abs(res_fe.params["d_inv"] - 0.5) < 0.2
    res_tw, _ = an.twfe(p, "y_exact", inv, "value")
    assert abs(res_tw.params["inv_w"] - 0.5) < 0.15


def test_kemenag_type_cells_are_excluded_and_cli_runs(tmp_path, capsys):
    panel, inv = _panel(n=20)
    panel.loc[panel.index[:5], "total_to_pop"] = 1.6  # Kemenag-like
    panel.to_csv(tmp_path / "panel.csv", index=False)
    inv.to_csv(tmp_path / "inv.csv", index=False)
    p = an.load_panel(str(tmp_path / "panel.csv"))
    assert int((~p["dukcapil_type"]).sum()) == 5
    an.main(["--panel", str(tmp_path / "panel.csv"), "--codes", str(tmp_path / "none.csv"), "--out", str(tmp_path / "out")])
    out = capsys.readouterr().out
    assert "regressions skipped" in out and (tmp_path / "out" / "two_period_y_exact.csv").exists()
    an.main(["--panel", str(tmp_path / "panel.csv"), "--codes", str(tmp_path / "none.csv"), "--out", str(tmp_path / "out"),
             "--investment", str(tmp_path / "inv.csv")])
    out = capsys.readouterr().out
    assert "TWFE y_exact" in out and (tmp_path / "out" / "regressions.csv").exists()


def test_upper_bound_sample_excludes_indigenous_religion_provinces(tmp_path):
    panel, inv = _panel(n=20)
    panel["unit_code"] = panel["unit_code"].where(panel["unit_code"] != "1100", "5301")  # one NTT unit
    panel.to_csv(tmp_path / "panel.csv", index=False)
    p = an.load_panel(str(tmp_path / "panel.csv"))
    assert "5301" in set(an.two_period(p, "y_exact")["unit_code"])
    assert "5301" not in set(an.two_period(p, "y_ub")["unit_code"])
