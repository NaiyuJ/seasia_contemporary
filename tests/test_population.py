import pandas as pd

from konghucu import population


def test_title_classifier():
    yes = ["Jumlah Penduduk Menurut Kabupaten/Kota (Jiwa)", "Jumlah Penduduk (Ribu Jiwa)", "Penduduk",
           "Jumlah Penduduk Menurut Kabupaten/Kota Hasil Proyeksi", "Penduduk Menurut Kabupaten/Kota di Provinsi Jawa Tengah"]
    yes.append("Jumlah Penduduk Menurut Kabupaten/Kota dan Jenis Kelamin")  # used through its 'Jumlah' category
    no = ["Jumlah Penduduk Menurut Kabupaten/Kota (Laki-Laki)", "Jumlah Penduduk Miskin", "Jumlah Penduduk Menurut Agama",
          "Penduduk Menurut Kabupaten/Kota dan Jenis Kegiatan", "Jumlah Penduduk Hasil Sensus Penduduk 2020 menurut Generasi dan Kabupaten/Kota",
          "Jumlah Penduduk Kabupaten Bogor", "Laju Pertumbuhan Penduduk", "Kepadatan Penduduk", "Jumlah Penduduk Menurut Kecamatan"]
    yes += ["[SK.Kp.002] [Proyeksi SP2010] Jumlah Penduduk Hasil Proyeksi Sensus Penduduk 2010 menurut Kabupaten/Kota dan Jenis Kelamin",
            "Proyeksi Jumlah Penduduk menurut Kabupaten/Kota di D.I. Yogyakarta ", "Penduduk Menurut Kabupaten/Kota di Provinsi Jambi",
            "Proyeksi Penduduk Menurut Kabupaten/Kota (Perempuan+Laki-Laki)"]
    no += ["Jumlah Penduduk menurut Provinsi", "Jumlah Penduduk Menurut Provinsi di Indonesia", "Proyeksi Penduduk Menurut Jenis Wilayah",
           "Penduduk Kabupaten Kerinci", "Penduduk Usia 15 Tahun Ke Atas yang Bekerja Menurut Jam Kerja"]
    assert all(population.classify_population_title(t)["about_population"] for t in yes)
    assert not any(population.classify_population_title(t)["about_population"] for t in no)


def _js(unit_label="Ribu Jiwa"):
    return {"data-availability": "available",
            "vervar": [{"val": 1200, "label": "Sumatera Utara"}, {"val": 1271, "label": "Sibolga"}, {"val": 1275, "label": "Medan"}],
            "var": [{"val": 100, "label": "Jumlah Penduduk Menurut Kabupaten/Kota", "unit": unit_label}],
            "turvar": [{"val": 0, "label": ""}],
            "tahun": [{"val": 120, "label": "2020"}, {"val": 121, "label": "2021"}],
            "turtahun": [{"val": 0, "label": ""}],
            "datacontent": {"120010001200": 14.8, "127110001200": 89.6, "127110001210": 90.1,
                            "127510001200": 2435.3, "127510001210": 2460.9}}


def test_fetch_population_scales_units(tmp_path):
    raw = tmp_path / "bps_var_1200_100.json"
    raw.write_text(pd.io.json.dumps(_js()) if hasattr(pd.io.json, "dumps") else __import__("json").dumps(_js()))
    cat = pd.DataFrame([{"domain": "1200", "province_code": "12", "var_id": "100", "unit": "Ribu Jiwa", "title": "x"}])
    long = population.fetch_population(None, cat, "key", raw_dir=str(tmp_path), log=lambda *a: None)
    assert set(long["unit_name"]) == {"Sibolga", "Medan"}  # the province row is dropped
    sib = long[(long.unit_name == "Sibolga") & (long.year == 2021)].iloc[0]
    assert sib["population"] == 90100 and sib["unit_code"] is None or sib["unit_code"] in (None, "nan") or pd.isna(sib["unit_code"])
    rec = population.reconcile_population(long.assign(unit_code=long["unit_name"].map({"Sibolga": "1271", "Medan": "1275"})))
    assert len(rec) == 4 and rec[(rec.unit_code == "1275") & (rec.year == 2020)]["population"].iloc[0] == 2435300


def test_fetch_drops_rows_named_after_another_province(tmp_path):
    import json
    js = _js("Jiwa")
    js["vervar"] = [{"val": 1600, "label": "Sumatera Selatan"}, {"val": 1700, "label": "Bengkulu"}, {"val": 1671, "label": "Palembang"}]
    js["datacontent"] = {"160010001200": 8500000, "170010001200": 2000000, "167110001200": 1700000}
    (tmp_path / "bps_var_1600_573.json").write_text(json.dumps(js))
    cat = pd.DataFrame([{"domain": "1600", "province_code": "16", "var_id": "573", "unit": "Jiwa", "title": "x"}])
    long = population.fetch_population(None, cat, "key", raw_dir=str(tmp_path), log=lambda *a: None)
    assert list(long["unit_name"]) == ["Palembang"]


def test_reconcile_median_and_spread():
    long = pd.DataFrame({"unit_code": ["1271"] * 3, "year": [2020] * 3, "population": [89000, 90000, 100000],
                         "ref": ["a", "b", "c"]})
    rec = population.reconcile_population(long)  # equal coverage: first ref by name is the primary series
    assert rec.iloc[0]["population"] == 89000 and rec.iloc[0]["n_refs"] == 3 and abs(rec.iloc[0]["spread"] - 1.124) < 1e-3


def test_reconcile_prefers_the_series_with_most_coverage_and_drops_implausible_values():
    rows = [("1271", y, 90000 + y, "wide") for y in (2019, 2020, 2021)] + [("1271", 2020, 50000, "narrow"),
                                                                            ("1271", 2022, 118_000_000, "narrow")]
    long = pd.DataFrame(rows, columns=["unit_code", "year", "population", "ref"])
    rec = population.reconcile_population(long).set_index("year")
    assert rec.loc[2020, "population"] == 92020 and rec.loc[2020, "ref"] == "wide" and rec.loc[2020, "n_refs"] == 2
    assert 2022 not in rec.index  # 118 million is not a kabupaten


def test_parse_population_uses_total_category_of_sex_split_variable():
    js = _js("Jiwa")
    js["turvar"] = [{"val": 1, "label": "Laki-laki"}, {"val": 2, "label": "Perempuan"}, {"val": 3, "label": "Jumlah"}]
    js["datacontent"] = {"127110011200": 44000, "127110021200": 46000, "127110031200": 90000}
    d = population.parse_population(js, "12", "r")
    assert len(d) == 1 and d.iloc[0]["count"] == 90000 and d.iloc[0]["unit_name"] == "Sibolga"
    js["turvar"] = js["turvar"][:2]
    assert population.parse_population(js, "12", "r").iloc[0]["count"] == 90000  # male and female only: added up


def test_parse_population_adds_male_and_female_when_no_total():
    js = _js("Jiwa")
    js["turvar"] = [{"val": 1, "label": "Laki-laki"}, {"val": 2, "label": "Perempuan"}]
    js["datacontent"] = {"127110011200": 44000, "127110021200": 46000, "127510011200": 1200000, "127510021200": 1250000}
    d = population.parse_population(js, "12", "r").set_index("unit_name")
    assert d.loc["Sibolga", "count"] == 90000 and d.loc["Medan", "count"] == 2450000
    js["turvar"] = [{"val": 1, "label": "Perkotaan"}, {"val": 2, "label": "Perdesaan"}]
    assert population.parse_population(js, "12", "r").empty  # urban/rural split without a total: skipped


def test_reconcile_discards_a_series_value_the_others_contradict():
    long = pd.DataFrame({"unit_code": ["3206"] * 3, "year": [2013] * 3, "population": [17201, 1720123, 1725000],
                         "ref": ["a", "b", "c"]})
    rec = population.reconcile_population(long)
    assert rec.iloc[0]["population"] == 1720123 and rec.iloc[0]["n_refs"] == 2


def test_total_category_spellings():
    for lab in ["Jumlah", "Total", "Laki-laki + Perempuan", "Laki-Laki+Perempuan", "Laki-laki dan Perempuan", "Jumlah Penduduk", "L+P"]:
        js = _js("Jiwa")
        js["turvar"] = [{"val": 1, "label": "Laki-laki"}, {"val": 2, "label": "Perempuan"}, {"val": 3, "label": lab}]
        js["datacontent"] = {"127110011200": 44000, "127110021200": 46000, "127110031200": 90000}
        d = population.parse_population(js, "12", "r")
        assert len(d) == 1 and d.iloc[0]["count"] == 90000, lab
