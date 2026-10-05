import pandas as pd
import pytest

from foreigners import bps_tables, ckan, dukcapil_wna, harmonize
from foreigners.nationality import canonical_nationality, canonical_permit, header_role, norm_kanim
from konghucu.harmonize import load_code_table


@pytest.mark.parametrize("label,code", [
    ("Tiongkok", "CHN"), ("Republik Rakyat Tiongkok", "CHN"), ("China", "CHN"), ("RRT", "CHN"), ("Cina", "CHN"),
    ("Taiwan", "TWN"), ("China (Taiwan)", "TWN"), ("Hong Kong", "HKG"), ("Korea Selatan", "KOR"),
    ("Korea Utara", "PRK"), ("Jepang", "JPN"), ("Amerika Serikat", "USA"), ("Lainnya", "OTHER"),
    ("Jumlah", "TOTAL"), ("Kantor Imigrasi Medan", None), ("2021", None),
])
def test_canonical_nationality(label, code):
    assert canonical_nationality(label) == code


def test_permit_and_roles():
    assert canonical_permit("Izin Tinggal Terbatas (ITAS)") == "ITAS"
    assert canonical_permit("KITAP") == "ITAP" and canonical_permit("Izin Tinggal Kunjungan") == "ITK"
    assert header_role("Tiongkok") == ("nationality", "CHN")
    assert header_role("2021") == ("year", "2021")
    assert header_role("Kantor Imigrasi Kelas I TPI Medan") == ("kanim", "kantor imigrasi kelas i tpi medan")
    assert header_role("ITAS") == ("permit", "ITAS")
    assert header_role("Jumlah") == ("total", "TOTAL")
    assert header_role("Kabupaten Sambas") == ("other", None)
    assert norm_kanim("Kantor Imigrasi Kelas I TPI Medan") == "medan"


HTML_NAT_ROWS = """
<table><thead><tr><th>Kebangsaan</th><th>ITAS</th><th>ITAP</th><th>Jumlah</th></tr></thead>
<tbody><tr><td>Tiongkok</td><td>1.200</td><td>30</td><td>1.230</td></tr>
<tr><td>Jepang</td><td>400</td><td>10</td><td>410</td></tr>
<tr><td>Jumlah</td><td>1.600</td><td>40</td><td>1.640</td></tr></tbody></table>"""

HTML_KANIM_ROWS = """
<table><thead><tr><th>Kantor Imigrasi</th><th>Tiongkok</th><th>India</th><th>Jumlah</th></tr></thead>
<tbody><tr><td>Kantor Imigrasi Kelas I TPI Medan</td><td>900</td><td>50</td><td>950</td></tr>
<tr><td>Kantor Imigrasi Kelas II Belawan</td><td>300</td><td>5</td><td>305</td></tr></tbody></table>"""

HTML_YEAR_COLS = """
<table><thead><tr><th>Negara</th><th>2019</th><th>2020</th></tr></thead>
<tbody><tr><td>Tiongkok</td><td>800</td><td>650</td></tr><tr><td>Korea Selatan</td><td>100</td><td>90</td></tr></tbody></table>"""


def test_parse_foreign_html_orientations():
    a = bps_tables.parse_foreign_html(HTML_NAT_ROWS, "12", 2021, "r1")
    chn = a[a["nationality"] == "CHN"].set_index("permit_type")["count"]
    assert chn["ITAS"] == 1200 and chn["ITAP"] == 30 and chn["TOTAL"] == 1230
    assert (a["region_level"] == "province").all() and (a["year"] == 2021).all()
    assert a[a["nationality"] == "TOTAL"]["count"].sum() == 1600 + 40 + 1640

    b = bps_tables.parse_foreign_html(HTML_KANIM_ROWS, "12", 2022, "r2")
    assert set(b["region_level"]) == {"kanim"}
    assert b[(b["nationality"] == "CHN") & (b["region_name"] == "medan")]["count"].item() == 900
    assert b[(b["nationality"] == "CHN") & (b["region_name"] == "belawan")]["count"].item() == 300

    c = bps_tables.parse_foreign_html(HTML_YEAR_COLS, "12", None, "r3")
    chn = c[c["nationality"] == "CHN"].set_index("year")["count"]
    assert chn[2019] == 800 and chn[2020] == 650

    assert len(bps_tables.parse_foreign_html("<table><tr><th>A</th><th>B</th></tr><tr><td>x</td><td>1</td></tr></table>",
                                             "12", 2020, "r4")) == 0


def test_ckan_table_to_long_long_and_wide():
    long_in = pd.DataFrame({"Provinsi": ["Jawa Timur", "Jawa Timur", "Jawa Timur"],
                            "Negara Asal": ["Tiongkok", "Jepang", "Total"],
                            "Tahun": [2023, 2023, 2023], "Jumlah TKA": ["1.500", "200", "1.700"]})
    out = ckan.table_to_long(long_in, ref="ckan:x", province_code="35")
    assert out[out["nationality"] == "CHN"]["count"].item() == 1500
    assert (out["permit_type"] == "TKA").all() and (out["year"] == 2023).all()
    assert out[out["nationality"] == "TOTAL"]["count"].item() == 1700

    wide_in = pd.DataFrame({"Kabupaten/Kota": ["Kab. Morowali", "Kota Palu"], "Tiongkok": [5000, 40],
                            "Filipina": [20, 3], "Tahun": [2022, 2022]})
    out = ckan.table_to_long(wide_in, ref="ckan:y", province_code="72", region_level="kabupaten")
    m = out[(out["region_name"] == "Kab. Morowali") & (out["nationality"] == "CHN")]
    assert m["count"].item() == 5000 and m["region_level"].item() == "kabupaten"

    with pytest.raises(ValueError):
        ckan.table_to_long(pd.DataFrame({"a": [1], "b": [2]}), ref="z")


def test_ckan_search_packages():
    class S:
        def get(self, url, params=None, timeout=None):
            class R:
                status_code = 200

                def json(self):
                    return {"result": {"results": [{"name": "tka", "title": "Jumlah TKA", "organization": {"title": "Kemnaker"},
                                                    "resources": [{"id": "r1", "name": "2023", "format": "csv", "url": "http://x/r1.csv"},
                                                                  {"id": "r2", "name": "pdf", "format": "PDF", "url": "http://x/r2.pdf"}]}]}}
            return R()
    df = ckan.search_all(S(), queries=("tka",), portals=["http://p"])
    assert len(df) == 1 and df.iloc[0]["format"] == "CSV"


def test_dukcapil_wna_tables():
    tables = [[["KECAMATAN", "WNI", "WNA", "JUMLAH"],
               ["Bahodopi", "25.000", "120", "25.120"],
               ["Bungku Tengah", "30.000", "-", "30.000"]],
              [["Uraian", "Nilai"], ["Luas", "1"]]]
    df = dukcapil_wna.tables_to_wna_long(tables, "pdf:a", 2023, 2, "72")
    wna = df[df["nationality"] == "WNA"].set_index("region_name")["count"]
    assert wna["Bahodopi"] == 120 and pd.isna(wna["Bungku Tengah"])
    assert df[df["nationality"] == "WNI"]["count"].sum() == 55000
    assert (df["semester"] == 2).all()


def test_harmonize_allocation_and_panel(tmp_path):
    codes = tmp_path / "codes.csv"
    pd.DataFrame({"unit_code": ["1271", "1207", "1275", "7206"],
                  "unit_name": ["Kota Medan", "Kabupaten Deli Serdang", "Kota Binjai", "Kabupaten Morowali"]}).to_csv(codes, index=False)
    cw = tmp_path / "kanim.csv"
    pd.DataFrame({"kanim": ["Kantor Imigrasi Kelas I TPI Medan"] * 2 + ["Kanim Belawan"],
                  "unit_code": ["1271", "1207", "1275"], "weight": [3, 1, None]}).to_csv(cw, index=False)
    ct, cwdf = load_code_table(str(codes)), harmonize.load_kanim_crosswalk(str(cw))
    assert list(cwdf[cwdf["kanim_norm"] == "medan"]["weight"]) == [0.75, 0.25]

    b = bps_tables.parse_foreign_html(HTML_KANIM_ROWS, "12", 2022, "r2")
    a = bps_tables.parse_foreign_html(HTML_NAT_ROWS, "12", 2022, "r1")
    k = ckan.table_to_long(pd.DataFrame({"Kabupaten/Kota": ["Kab. Morowali"], "Tiongkok": [5000], "Tahun": [2022]}),
                           ref="ckan:y", province_code="72", region_level="kabupaten")
    long = pd.concat([a, b, k], ignore_index=True)
    alloc = harmonize.allocate_to_kabupaten(long, cwdf, ct)
    chn = alloc[alloc["nationality"] == "CHN"].groupby("unit_code")["count"].sum()
    assert chn["1271"] == 675 and chn["1207"] == 225 and chn["1275"] == 300 and chn["7206"] == 5000
    assert (alloc[alloc["unit_code"] == "1271"]["allocated"]).all()
    assert "province" not in set(alloc["region_level"])

    panel = harmonize.build_panel(alloc, long[long["region_level"] == "province"])
    row = panel.set_index("unit_code").loc["1271"]
    assert row["chn_any"] == 675 and row["chn_province_any"] == 1230 + 1200 + 30  # province CHN rows summed
    assert panel.set_index("unit_code").loc["7206", "chn_tka"] == 5000
    assert "foreign_total" in panel.columns
