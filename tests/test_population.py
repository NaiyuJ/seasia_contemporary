import pandas as pd

from konghucu import population


def test_title_classifier():
    yes = ["Jumlah Penduduk Menurut Kabupaten/Kota (Jiwa)", "Jumlah Penduduk (Ribu Jiwa)", "Penduduk",
           "Jumlah Penduduk Menurut Kabupaten/Kota Hasil Proyeksi", "Penduduk Menurut Kabupaten/Kota di Provinsi Jawa Tengah"]
    yes.append("Jumlah Penduduk Menurut Kabupaten/Kota dan Jenis Kelamin")  # used through its 'Jumlah' category
    no = ["Jumlah Penduduk Menurut Kabupaten/Kota (Laki-Laki)", "Jumlah Penduduk Miskin", "Jumlah Penduduk Menurut Agama",
          "Penduduk Menurut Kabupaten/Kota dan Jenis Kegiatan", "Jumlah Penduduk Hasil Sensus Penduduk 2020 menurut Generasi dan Kabupaten/Kota",
          "Jumlah Penduduk Kabupaten Bogor", "Laju Pertumbuhan Penduduk", "Kepadatan Penduduk", "Jumlah Penduduk Menurut Kecamatan"]
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


def test_reconcile_median_and_spread():
    long = pd.DataFrame({"unit_code": ["1271"] * 3, "year": [2020] * 3, "population": [89000, 90000, 100000],
                         "ref": ["a", "b", "c"]})
    rec = population.reconcile_population(long)
    assert rec.iloc[0]["population"] == 90000 and rec.iloc[0]["n_refs"] == 3 and abs(rec.iloc[0]["spread"] - 1.124) < 1e-3


def test_parse_population_uses_total_category_of_sex_split_variable():
    js = _js("Jiwa")
    js["turvar"] = [{"val": 1, "label": "Laki-laki"}, {"val": 2, "label": "Perempuan"}, {"val": 3, "label": "Jumlah"}]
    js["datacontent"] = {"127110011200": 44000, "127110021200": 46000, "127110031200": 90000}
    d = population.parse_population(js, "12", "r")
    assert len(d) == 1 and d.iloc[0]["count"] == 90000 and d.iloc[0]["unit_name"] == "Sibolga"
    js["turvar"] = js["turvar"][:2]
    assert population.parse_population(js, "12", "r").empty  # male and female only: not used
