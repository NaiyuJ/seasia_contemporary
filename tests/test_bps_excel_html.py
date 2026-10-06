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
