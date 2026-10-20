import numpy as np
import pandas as pd
import pytest

pytest.importorskip("statsmodels")
from analysis import konghucu as an


def _panel(seed=0, n=60, effect=0.5, treated=lambda i: True):
    rng = np.random.default_rng(seed)
    rows, inv = [], []
    for i in range(n):
        code = f"{11 + i % 6}{i:02d}"  # six provinces
        pop = rng.integers(80_000, 900_000)
        base = rng.uniform(0, 3)
        on = float(treated(i))
        flow = {2019: 0.0, 2020: 0.0, 2021: 0.0, 2022: on * rng.uniform(0, 3000), 2023: on * rng.uniform(0, 5000)}
        cum = {y: sum(flow[k] for k in flow if k <= y) for y in flow}
        x = {y: np.log1p(cum[y]) for y in flow}  # the stock outcome responds to cumulative investment
        for y in range(2019, 2024):
            k = (base + effect * x[y] + rng.normal(0, 0.2)) * pop / 1000
            rows.append(dict(unit_code=code, year=y, population=pop, total=pop * 1.02, total_to_pop=1.02,
                             konghucu=max(k, 0), konghucu_ub=max(k, 0), buddha=pop * 0.01, kristen=pop * 0.05,
                             katolik=pop * 0.01, ref="da:x:y"))
            inv.append(dict(unit_code=code, year=y, value=flow[y]))
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
    panel0, inv0 = _panel(treated=lambda i: i % 2 == 0)  # half the units never receive investment
    panel0.to_csv(tmp_path / "panel0.csv", index=False)
    tp0 = an.two_period(an.load_panel(str(tmp_path / "panel0.csv")), "y_exact")
    res_any, d_any = an.long_difference(tp0, inv0, "value", treatment="any")
    assert set(d_any["d_inv"].unique()) == {0.0, 1.0} and res_any.params["d_inv"] > 0.5
    res_int, d_int = an.long_difference(tp, inv, "value", interact_high=True)
    assert {"high", "d_inv_x_high"} <= set(d_int.columns) and "d_inv_x_high" in res_int.params
    assert abs(res_int.params["d_inv"] + res_int.params["d_inv_x_high"] - 0.5) < 0.3  # effect is homogeneous in the DGP


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


def test_bkpm_conversion(tmp_path):
    from analysis import bkpm
    codes = pd.DataFrame({"unit_code": ["6101", "6172", "3171"], "unit_name": ["Kabupaten Sambas", "Kota Singkawang", "Kota Jakarta Pusat"],
                          "province_code": ["61", "61", "31"]})
    codes.to_csv(tmp_path / "codes.csv", index=False)
    rows = [
        dict(periode="2022 - Triwulan 1", status_penanaman_modal="PMA", negara="Tiongkok", provinsi="Kalimantan Barat",
             kabupaten_kota="Kabupaten Sambas", investasi_us_ribu=100.0, year=2022, q=1),
        dict(periode="2022 - Triwulan 2", status_penanaman_modal="PMA", negara="R.R. Tiongkok", provinsi="Kalimantan Barat",
             kabupaten_kota="Kabupaten Sambas", investasi_us_ribu=50.0, year=2022, q=2),
        dict(periode="2022 - Triwulan 2", status_penanaman_modal="PMA", negara="Hongkong, RRT", provinsi="Kalimantan Barat",
             kabupaten_kota="Kabupaten Sambas", investasi_us_ribu=7.0, year=2022, q=2),
        dict(periode="2022 - Triwulan 2", status_penanaman_modal="PMA", negara="Taiwan", provinsi="Kalimantan Barat",
             kabupaten_kota="Kota Singkawang", investasi_us_ribu=9.0, year=2022, q=2),
        dict(periode="2022 - Triwulan 3", status_penanaman_modal="PMDN", negara="Indonesia", provinsi="Daerah Khusus Ibukota Jakarta",
             kabupaten_kota="Kota Adm. Jakarta Pusat", investasi_us_ribu=300.0, year=2022, q=3),
        dict(periode="2022 - Triwulan 3", status_penanaman_modal="PMA", negara="China", provinsi="Kalimantan Barat",
             kabupaten_kota="Kabupaten Nowhere", investasi_us_ribu=999.0, year=2022, q=3),
    ]
    pd.DataFrame(rows).to_csv(tmp_path / "bkpm.csv", index=False)
    out = bkpm.convert(str(tmp_path / "bkpm.csv"), str(tmp_path / "codes.csv"), log=lambda *a: None).set_index(["unit_code", "year"])
    assert out.loc[("6101", 2022), "china_usd_k"] == 150 and out.loc[("6101", 2022), "hk_usd_k"] == 7
    assert out.loc[("6101", 2022), "fdi_usd_k"] == 157 and out.loc[("6101", 2022), "china_plus_hk_usd_k"] == 157
    assert out.loc[("6172", 2022), "china_usd_k"] == 0 and out.loc[("6172", 2022), "fdi_usd_k"] == 9
    assert out.loc[("3171", 2022), "pmdn_usd_k"] == 300
    assert "Nowhere" not in str(out.index)


def test_mixed_definition_pairs_are_dropped_from_the_upper_bound_sample(tmp_path):
    panel, inv = _panel(n=12)
    panel["konghucu_ub_is_lainnya"] = False
    # unit 1100: exact in 2021, Lainnya (larger) in 2023 -> would read as a rise; must be dropped
    m = (panel["unit_code"] == "1100") & (panel["year"] == 2023)
    panel.loc[m, ["konghucu_ub_is_lainnya", "konghucu_ub"]] = [True, 10 * panel.loc[m, "konghucu_ub"].iloc[0]]
    panel.loc[m, "konghucu"] = np.nan
    panel.to_csv(tmp_path / "panel.csv", index=False)
    p = an.load_panel(str(tmp_path / "panel.csv"))
    tp = an.two_period(p, "y_ub")
    assert "1100" not in set(tp["unit_code"]) and tp.attrs["dropped_mixed_definition"] == 1
    assert "1100" not in set(an.two_period(p, "y_exact")["unit_code"])  # 2023 exact count is missing


def test_duplicate_unit_year_rows_raise(tmp_path):
    panel, inv = _panel(n=5)
    panel = pd.concat([panel, panel[panel["year"] == 2021].iloc[[0]]])  # a second 2021 row for one unit
    panel.to_csv(tmp_path / "panel.csv", index=False)
    with pytest.raises(ValueError, match="duplicate"):
        an.two_period(an.load_panel(str(tmp_path / "panel.csv")), "y_exact")


def test_few_clusters_fall_back_to_hc3():
    rng = np.random.default_rng(0)
    X = pd.DataFrame({"x": rng.normal(size=40)})
    y = rng.normal(size=40)
    res = an.ols(y, X, cluster=pd.Series(np.arange(40) % 6))
    assert res.cov_type == "HC3"
    res = an.ols(y, X, cluster=pd.Series(np.arange(40) % 20))
    assert res.cov_type == "cluster"


def test_size_check_runs():
    from analysis import size_check
    r = size_check.rejection_rates(reps=3, n=20, provinces=4)
    assert set(r.index) >= {"HC1", "HC3", "cluster_4"} and (r <= 1).all()


def test_twfe_on_an_unbalanced_panel_does_not_load_the_year_effect_on_investment(tmp_path):
    """half the units observed 2019-21, half 2021-23; investment in half of the late group; a
    pure year effect and no investment effect. Raw year dummies would give a large positive coef."""
    rng = np.random.default_rng(1)
    rows, inv = [], []
    for i in range(40):
        code = f"{11 + i % 4}{i:02d}"
        late = i % 2 == 1
        pop = 200_000
        for y in (range(2021, 2024) if late else range(2019, 2022)):
            yr_eff = 0.5 * (y - 2019)
            rows.append(dict(unit_code=code, year=y, population=pop, total=pop, total_to_pop=1.0,
                             konghucu=(1 + yr_eff + rng.normal(0, 0.05)) * pop / 1000, konghucu_ub=np.nan,
                             buddha=1, kristen=1, katolik=1, ref="da:x:y"))
            inv.append(dict(unit_code=code, year=y, value=3000.0 if late and i % 4 == 1 and y >= 2022 else 0.0))
    panel = pd.DataFrame(rows); panel["konghucu_ub"] = panel["konghucu"]
    panel.to_csv(tmp_path / "panel.csv", index=False)
    res, d = an.twfe(an.load_panel(str(tmp_path / "panel.csv")), "y_exact", pd.DataFrame(inv), "value")
    assert abs(res.params["inv_w"]) < 0.02


def test_twfe_upper_bound_sample_excludes_indigenous_provinces_and_mixed_definitions(tmp_path):
    panel, inv = _panel(n=12)
    panel["konghucu_ub_is_lainnya"] = False
    panel["unit_code"] = panel["unit_code"].where(panel["unit_code"] != "1100", "5301")  # NTT
    m = (panel["unit_code"] == "1201") & (panel["year"] >= 2022)
    panel.loc[m, "konghucu_ub_is_lainnya"] = True  # definition switches mid-panel
    panel.to_csv(tmp_path / "panel.csv", index=False)
    p = an.load_panel(str(tmp_path / "panel.csv"))
    _, d = an.twfe(p, "y_ub", inv, "value")
    assert "5301" not in set(d["unit_code"]) and "1201" not in set(d["unit_code"])
    _, d = an.twfe(p, "y_exact", inv, "value")
    assert "5301" in set(d["unit_code"])


def test_load_panel_collapses_semesters_and_excludes_percentage_cells(tmp_path):
    panel, inv = _panel(n=4)
    panel["semester"] = 0
    panel["sources"] = "pdf_da"
    extra = panel[(panel["unit_code"] == "1100") & (panel["year"] == 2021)].copy()
    extra["semester"] = 2; extra["konghucu"] = 999  # end-of-year cell wins
    panel = pd.concat([panel, extra])
    panel.loc[panel["unit_code"] == "1201", "sources"] = "pdf_da_pct"
    panel.to_csv(tmp_path / "panel.csv", index=False)
    p = an.load_panel(str(tmp_path / "panel.csv"))
    assert not p.duplicated(["unit_code", "year"]).any()
    assert p[(p["unit_code"] == "1100") & (p["year"] == 2021)]["konghucu"].item() == 999
    assert not p.loc[p["unit_code"] == "1201", "dukcapil_type"].any()


def test_collinear_interaction_is_dropped_not_reported():
    rng = np.random.default_rng(2)
    x = rng.normal(size=60)
    X = pd.DataFrame({"d_inv": x, "high": 1.0, "d_inv_x_high": x})
    res = an.ols(x * 0.5 + rng.normal(size=60, scale=0.1), X)
    assert "d_inv_x_high" not in res.params and abs(res.params["d_inv"] - 0.5) < 0.1
    assert np.isnan(an._row("s", res, "d_inv_x_high")["coef_d_inv"])


def test_bkpm_status_whitespace_and_bare_ambiguous_names(tmp_path):
    from analysis import bkpm
    codes = pd.DataFrame([
        {"unit_code": "3204", "unit_name": "Bandung", "province_code": "32", "level": "kabupaten"},
        {"unit_code": "3273", "unit_name": "Kota Bandung", "province_code": "32", "level": "kota"},
        {"unit_code": "6302", "unit_name": "Kotabaru", "province_code": "63", "level": "kabupaten"},
    ])
    codes.to_csv(tmp_path / "codes.csv", index=False)
    src = pd.DataFrame([
        dict(periode="2022Q1", status_penanaman_modal="PMA ", negara="R.R. Tiongkok", provinsi="Jawa Barat",
             kabupaten_kota="Kota Bandung", investasi_rp_juta=1, investasi_us_ribu=77, year=2022, q=1),
        dict(periode="2022Q1", status_penanaman_modal="PMA", negara="China, Republic of", provinsi="Jawa Barat",
             kabupaten_kota="Kota Bandung", investasi_rp_juta=1, investasi_us_ribu=5, year=2022, q=1),
        dict(periode="2022Q1", status_penanaman_modal="PMA", negara="Tiongkok", provinsi="Jawa Barat",
             kabupaten_kota="Bandung", investasi_rp_juta=1, investasi_us_ribu=9, year=2022, q=1),
        dict(periode="2022Q1", status_penanaman_modal="PMA", negara="Tiongkok", provinsi="Kalimantan Selatan",
             kabupaten_kota="Kabupaten Kota Baru", investasi_rp_juta=1, investasi_us_ribu=3, year=2022, q=1),
    ])
    src.to_csv(tmp_path / "src.csv", index=False)
    logs = []
    out = bkpm.convert(str(tmp_path / "src.csv"), str(tmp_path / "codes.csv"), log=logs.append)
    by = out.set_index("unit_code")
    assert by.loc["3273", "china_usd_k"] == 77 and by.loc["3273", "fdi_usd_k"] == 82  # Taiwan is FDI, not China
    assert by.loc["3204", "china_usd_k"] == 9  # a bare 'Bandung' is the kabupaten in BPS naming, never the kota
    assert by.loc["6302", "china_usd_k"] == 3


def test_singleton_provinces_leave_the_province_fe_spec_and_errors_stay_finite(tmp_path):
    panel, inv = _panel(n=30)
    panel["unit_code"] = panel["unit_code"].where(panel["unit_code"] != "1100", "9900")  # one unit in province 99
    panel.to_csv(tmp_path / "panel.csv", index=False)
    tp = an.two_period(an.load_panel(str(tmp_path / "panel.csv")), "y_exact")
    res, d = an.long_difference(tp, inv, "value", province_fe=True)
    assert "9900" not in set(d["unit_code"]) and int(res.nobs) == 29
    assert np.isfinite(res.bse).all()
    # HC3 blows up on a leverage-one observation: the helper falls back to HC1
    rng = np.random.default_rng(3)
    X = pd.DataFrame({"x": rng.normal(size=30), "dummy": [1.0] + [0.0] * 29})
    assert np.isfinite(an.ols(rng.normal(size=30), X).bse).all()
