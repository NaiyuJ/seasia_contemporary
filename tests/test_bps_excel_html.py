"""Static tables as BPS actually serves them: entity-escaped Excel HTML with title rows."""
import html as _html

from konghucu import bps_api
from konghucu.htmltable import grid_tables, unescape_if_needed

EXCEL_HTML = """<html><head><style>table {mso-displayed-thousand-separator:"\\,";}</style></head><body>
<table border=0 cellpadding=0 cellspacing=0>
 <tr><td colspan=8 class=xl63>Jumlah Penduduk Menurut Kabupaten/Kota dan Agama yang Dianut, 2021</td></tr>
 <tr><td colspan=8></td></tr>
 <tr><td rowspan=2>Kabupaten/Kota</td><td colspan=6>Agama</td><td rowspan=2>Jumlah</td></tr>
 <tr><td>Islam</td><td>Kristen</td><td>Katolik</td><td>Hindu</td><td>Buddha</td><td>Konghucu</td></tr>
 <tr><td>Nias</td><td>5,000</td><td>120,000</td><td>30,000</td><td>10</td><td>50</td><td>-</td><td>155,060</td></tr>
 <tr><td>Kota Medan</td><td>1,500,000</td><td>400,000</td><td>100,000</td><td>5,000</td><td>200,000</td><td>1,234</td><td>2,206,234</td></tr>
 <tr><td>Sumatera Utara</td><td>9,000,000</td><td>3,000,000</td><td>800,000</td><td>20,000</td><td>400,000</td><td>2,500</td><td>13,222,500</td></tr>
 <tr><td colspan=8>Sumber: Kementerian Agama</td></tr>
</table></body></html>"""


def test_unescape_and_grid():
    esc = _html.escape(EXCEL_HTML)
    assert "&lt;table" in esc and "<table" not in esc
    grids = grid_tables(esc)
    assert len(grids) == 1 and len(grids[0]) == 8
    assert grids[0][3][1] == "Islam" and grids[0][2][1] == "Agama"   # colspan expanded


def test_parse_escaped_excel_table():
    df = bps_api.parse_religion_html(_html.escape(EXCEL_HTML), "12", 2021, "bps:1200:2793")
    k = df[df["religion"] == "konghucu"].set_index("unit_name")["count"]
    assert k["Kota Medan"] == 1234 and k["__PROVINCE__"] == 2500
    assert k["Nias"] != k["Nias"]  # NaN for '-'
    assert df[(df["unit_name"] == "Kota Medan") & (df["religion"] == "total")]["count"].item() == 2206234
    assert "Sumber: Kementerian Agama" not in set(df["unit_name"])
    assert (df["year"] == 2021).all()
    assert df[df["unit_name"] == "Kota Medan"]["level"].iloc[0] == "kota"


def test_parse_year_columns_under_religions():
    html = """<table>
    <tr><td>Kabupaten</td><td colspan=2>Islam</td><td colspan=2>Konghucu</td></tr>
    <tr><td></td><td>2019</td><td>2020</td><td>2019</td><td>2020</td></tr>
    <tr><td>Sambas</td><td>1</td><td>2</td><td>30</td><td>40</td></tr></table>"""
    df = bps_api.parse_religion_html(html, "61", None, "x")
    k = df[df["religion"] == "konghucu"].set_index("year")["count"]
    assert k[2019] == 30 and k[2020] == 40


def test_konghucu_spellings():
    from konghucu.religion import canonical_religion
    for lab in ["Khong Hu Chu", "Kong Hu Chu", "Konghuchu", "Khonghuchu", "Kong Hu Cu", "Khonghucu", "KONGHUCU",
                "Konghutju", "Kong Fu Cu"]:
        assert canonical_religion(lab) == "konghucu", lab


def test_transposed_religion_rows():
    html = """<table>
    <tr><td>Agama</td><td>Laki-laki</td><td>Perempuan</td><td>Jumlah</td></tr>
    <tr><td>Islam</td><td>100</td><td>110</td><td>210</td></tr>
    <tr><td>Khong Hu Chu</td><td>3</td><td>4</td><td>7</td></tr>
    <tr><td>Jumlah</td><td>103</td><td>114</td><td>217</td></tr></table>"""
    df = bps_api.parse_religion_html(html, "35", 2019, "x")
    k = df[df["religion"] == "konghucu"].set_index("unit_name")["count"]
    assert k["__PROVINCE__"] == 7          # the 'Jumlah' column becomes the total row
    assert k["Laki-laki"] == 3 and k["Perempuan"] == 4


def test_sub_kecamatan_flag():
    c = bps_api.classify_title
    assert c("Banyaknya Penduduk Menurut Agama dan Jenis Kelamin Kecamatan Rungkut Tahun 2019")["is_sub_kecamatan"]
    assert c("Jumlah Penduduk Menurut Agama Kec Paiton")["is_sub_kecamatan"]
    assert c("Jumlah Penduduk Menurut Agama per Kelurahan, 2013")["is_sub_kecamatan"]
    assert not c("Jumlah Penduduk Menurut Kecamatan dan Agama yang Dianut di Kabupaten Magetan, 2023")["is_sub_kecamatan"]


def test_letter_spaced_names_are_names():
    html = """<table><tr><th>Kabupaten/Kota</th><th>Islam</th><th>Khonghucu</th></tr>
    <tr><td>Kabupaten</td><td></td><td></td></tr>
    <tr><td>01 N i a s</td><td>1 672</td><td>0</td></tr>
    <tr><td>Kota</td><td></td><td></td></tr>
    <tr><td>75 M e d a n</td><td>1 743 292</td><td>285</td></tr>
    <tr><td>Sumatera Utara</td><td>10 064 383</td><td>738</td></tr></table>"""
    df = bps_api.parse_religion_html(html, "12", 2021, "x")
    k = df[df["religion"] == "konghucu"].set_index("unit_name")
    assert k.loc["75 M e d a n", "count"] == 285 and k.loc["75 M e d a n", "level"] == "kota"
    assert k.loc["01 N i a s", "level"] == "kabupaten" and k.loc["__PROVINCE__", "count"] == 738
    from konghucu.religion import squash_unit_name
    assert squash_unit_name("75 M e d a n") == "medan"


def _sex_table(blocks, super_labels=None):
    rels = ["Islam", "Kristen", "Katolik", "Hindu", "Budha", "Khong", "Lainnya", "Total"]
    rows = ["<tr><td colspan=25>Penduduk Menurut Agama, Jenis Kelamin dan Kabupaten/Kota 2010</td></tr>"]
    if super_labels:
        rows.append("<tr><td></td>" + "".join(f"<td colspan={len(rels)}>{lab}</td>" for lab in super_labels) + "</tr>")
    rows.append("<tr><td>Regency/City</td>" + "".join(f"<td>{r}</td>" for r in rels) * len(blocks) + "</tr>")
    for name, per_block in [("Cilacap", blocks)]:
        cells = "".join("".join(f"<td>{v}</td>" for v in blk) for blk in per_block)
        rows.append(f"<tr><td>{name}</td>{cells}</tr>")
    return "<table>" + "".join(rows) + "</table>"


def _wide(df):
    return df[df.unit_name == "Cilacap"].set_index("religion")["count"].to_dict()


def test_sex_split_table_uses_total_block():
    male = [808199, 7670, 3430, 73, 1160, 10, 587, 821129]
    female = [800000, 7000, 3000, 70, 1100, 12, 500, 811682]
    total = [m + f for m, f in zip(male, female)]
    html = _sex_table([male, female, total], ["Laki-laki / Male", "Perempuan / Female", "Jumlah / Total"])
    d = bps_api.parse_religion_html(html, "33", 2010, "t")
    w = _wide(d)
    assert w["islam"] == 1608199 and w["konghucu"] == 22 and w["total"] == 1632811


def test_sex_split_table_without_labels_takes_last_block_and_sums_male_female():
    male = [808199, 7670, 3430, 73, 1160, 10, 587, 821129]
    female = [800000, 7000, 3000, 70, 1100, 12, 500, 811682]
    total = [m + f for m, f in zip(male, female)]
    w = _wide(bps_api.parse_religion_html(_sex_table([male, female, total]), "33", 2010, "t"))
    assert w["islam"] == 1608199  # no super-header: BPS prints the total last
    w = _wide(bps_api.parse_religion_html(_sex_table([male, female], ["Laki-laki", "Perempuan"]), "33", 2010, "t"))
    assert w["islam"] == 1608199 and w["konghucu"] == 22  # male + female only: added up


def test_multi_year_blocks_are_kept():
    html = ("<table><tr><td>Kabupaten</td><td colspan=2>2019</td><td colspan=2>2020</td></tr>"
            "<tr><td></td><td>Islam</td><td>Kristen</td><td>Islam</td><td>Kristen</td></tr>"
            "<tr><td>Cilacap</td><td>100</td><td>10</td><td>110</td><td>11</td></tr></table>")
    d = bps_api.parse_religion_html(html, "33", None, "t")
    got = d[d.unit_name == "Cilacap"].set_index(["year", "religion"])["count"].to_dict()
    assert got == {(2019, "islam"): 100, (2019, "kristen"): 10, (2020, "islam"): 110, (2020, "kristen"): 11}
