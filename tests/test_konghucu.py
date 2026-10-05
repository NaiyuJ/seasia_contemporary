import json

import pandas as pd
import pytest

from konghucu import arcgis, bps_api, harmonize, pdf_tables
from konghucu.religion import (canonical_religion, norm_unit_name, parse_count, semester_from_text,
                               unit_level, year_from_text)


# ---------- label helpers ----------

@pytest.mark.parametrize("label,expected", [
    ("Khonghucu", "konghucu"), ("Kong Hu Cu", "konghucu"), ("KONGHUCU", "konghucu"), ("Konghuchu", "konghucu"),
    ("Islam", "islam"), ("Kristen Protestan", "kristen"), ("Katholik", "katolik"), ("Budha", "buddha"),
    ("Aliran Kepercayaan", "kepercayaan"), ("Jumlah", "total"), ("Lainnya", "lainnya"),
    ("Kabupaten/Kota", None), ("2020", None),
])
def test_canonical_religion(label, expected):
    assert canonical_religion(label) == expected


@pytest.mark.parametrize("s,v", [
    ("1.234.567", 1234567), ("1,234,567", 1234567), ("12,5", 12.5), ("0.03", 0.03), ("-", None), ("", None),
    (" 345 ", 345), ("1 234", 1234), (None, None),
])
def test_parse_count(s, v):
    assert parse_count(s) == v


def test_unit_name_helpers():
    assert norm_unit_name("Kab. Deli Serdang") == "deli serdang"
    assert norm_unit_name("KOTA MEDAN") == "medan"
    assert norm_unit_name("12 Kabupaten Sambas") == "sambas"
    assert unit_level("Kota Medan") == "kota" and unit_level("Kabupaten Sambas") == "kabupaten"
    assert unit_level("Sambas") == "unknown"
    assert year_from_text("Jumlah Penduduk Menurut Agama, 2020") == 2020
    assert semester_from_text("DKB Semester II 2023") == 2 and semester_from_text("Semester I") == 1


# ---------- BPS HTML table (two-level header: 'Agama' over religions) ----------

BPS_HTML = """
<table>
<thead>
<tr><th rowspan="2">Kabupaten/Kota</th><th colspan="4">Agama</th><th rowspan="2">Jumlah</th></tr>
<tr><th>Islam</th><th>Kristen</th><th>Budha</th><th>Khonghucu</th></tr>
</thead>
<tbody>
<tr><td>Sambas</td><td>500.000</td><td>20.000</td><td>30.000</td><td>1.234</td><td>551.234</td></tr>
<tr><td>Kota Singkawang</td><td>100.000</td><td>10.000</td><td>80.000</td><td>5.678</td><td>195.678</td></tr>
<tr><td>Kalimantan Barat</td><td>600.000</td><td>30.000</td><td>110.000</td><td>6.912</td><td>746.912</td></tr>
</tbody>
</table>
"""


def test_parse_bps_html():
    df = bps_api.parse_religion_html(BPS_HTML, "61", 2020, "bps:6100:1")
    assert set(df["religion"]) == {"islam", "kristen", "buddha", "konghucu", "total"}
    k = df[(df["religion"] == "konghucu")].set_index("unit_name")["count"]
    assert k["Sambas"] == 1234 and k["Kota Singkawang"] == 5678
    assert k["__PROVINCE__"] == 6912          # province total row flagged, not treated as a unit
    assert (df["year"] == 2020).all()
    assert df[df["unit_name"] == "Kota Singkawang"]["level"].iloc[0] == "kota"
    assert df[df["unit_name"] == "Sambas"]["unit_name_norm"].iloc[0] == "sambas"


class FakeResp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status
        self.text = json.dumps(payload)

    def json(self):
        return self._p


class FakeSession:
    """Routes URLs to canned payloads; records calls."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        for k, v in self.routes.items():
            if k in url:
                return FakeResp(v(url, params) if callable(v) else v)
        return FakeResp({"error": {"code": 404, "message": "no route"}}, 404)


def test_bps_list_paginates():
    def lister(url, params):
        page = int(url.split("/page/")[1].split("/")[0])
        rows = [{"table_id": f"t{page}", "title": f"Penduduk Menurut Kabupaten/Kota dan Agama {page}"}]
        return {"status": "OK", "data-availability": "available", "data": [{"page": page, "pages": 2}, rows]}
    s = FakeSession({"/list/model/statictable": lister})
    rows = bps_api.list_static_tables(s, "6100", "agama", "k")
    assert [r["table_id"] for r in rows] == ["t1", "t2"]
    assert all(r["domain"] == "6100" for r in rows)


def test_bps_fetch_tables(tmp_path):
    s = FakeSession({"/view/model/statictable": {"status": "OK", "data": {
        "title": "Penduduk Menurut Kabupaten/Kota dan Agama 2021", "table": BPS_HTML}}})
    cat = pd.DataFrame([{"domain": "6100", "province_code": "61", "table_id": "9", "title": "x", "by_unit": True}])
    df = bps_api.fetch_tables(s, cat, "k", sleep_s=0, raw_dir=str(tmp_path))
    assert (df["year"] == 2021).all() and (df["ref"] == "bps:6100:9").all()
    assert (tmp_path / "bps_6100_9.html").exists()


# ---------- ArcGIS ----------

def _arcgis_routes():
    base = arcgis.DEFAULT_BASE
    layer = {"name": "Agama_Kab_2023", "maxRecordCount": 2,
             "fields": [{"name": "KODE_KAB", "alias": "Kode"}, {"name": "NAMA_KAB", "alias": "Nama"},
                        {"name": "ISLAM"}, {"name": "KHONGHUCU"}, {"name": "JUMLAH"}]}
    feats = [{"KODE_KAB": "6101", "NAMA_KAB": "KAB. SAMBAS", "ISLAM": 500000, "KHONGHUCU": 1234, "JUMLAH": 551234},
             {"KODE_KAB": "6172", "NAMA_KAB": "KOTA SINGKAWANG", "ISLAM": 100000, "KHONGHUCU": 5678, "JUMLAH": 195678},
             {"KODE_KAB": "6102", "NAMA_KAB": "KAB. BENGKAYANG", "ISLAM": 1, "KHONGHUCU": 2, "JUMLAH": 3}]

    def query(url, params):
        off, n = int(params["resultOffset"]), int(params["resultRecordCount"])
        chunk = feats[off:off + n]
        return {"features": [{"attributes": f} for f in chunk], "exceededTransferLimit": off + n < len(feats)}

    return {
        f"{base}/Agama/FeatureServer/0/query": query,
        f"{base}/Agama/FeatureServer/0": layer,
        f"{base}/Agama/FeatureServer": {"layers": [{"id": 0, "name": "Agama_Kab_2023"}]},
        f"{base}/Sekolah/MapServer": {"error": {"code": 499, "message": "Token Required"}},
        f"{base}/Demografi": {"services": [], "folders": []},
        base: {"folders": ["Demografi"], "services": [{"name": "Agama", "type": "FeatureServer"},
                                                      {"name": "Sekolah", "type": "MapServer"},
                                                      {"name": "Geocode", "type": "GPServer"}]},
    }


def test_arcgis_discover_and_query():
    s = FakeSession(_arcgis_routes())
    disc = arcgis.discover_religion_layers(s, sleep_s=0)
    assert disc.iloc[0]["service"] == "Agama" and disc.iloc[0]["n_religion_fields"] == 2  # ISLAM, KHONGHUCU
    assert disc[disc["service"] == "Sekolah"]["error"].iloc[0] == 499
    assert "Geocode" not in set(disc["service"])

    wide = arcgis.query_all(s, f"{arcgis.DEFAULT_BASE}/Agama/FeatureServer/0")
    assert len(wide) == 3                                 # paginated 2 + 1
    long = arcgis.layer_to_long(wide, ref="arcgis:t", year=2023, semester=2)
    k = long[long["religion"] == "konghucu"].set_index("unit_code")["count"]
    assert k["6101"] == 1234 and k["6172"] == 5678
    assert (long["province_code"] == "61").all()
    assert set(long["religion"]) == {"islam", "konghucu", "total"}
    assert long[long["unit_code"] == "6172"]["level"].iloc[0] == "kota"

    with pytest.raises(PermissionError):
        arcgis.query_all(s, f"{arcgis.DEFAULT_BASE}/Sekolah/MapServer/0")


# ---------- PDF tables (pure parsing) ----------

def test_pdf_tables_to_long():
    tables = [
        [["NO", "KECAMATAN", "ISLAM", "KRISTEN", "KATOLIK", "HINDU", "BUDHA", "KONGHUCU", "KEPERCAYAAN", "JUMLAH"],
         ["1", "Pemangkat", "40.000", "1.000", "500", "10", "3.000", "250", "-", "44.760"],
         ["2", "Tebas", "60.000", "800", "300", "5", "1.000", "120", "", "62.225"]],
        [["Uraian", "Nilai"], ["Luas wilayah", "6.394"]],   # not a religion table
    ]
    # first column is 'NO' here; the unit name is in column 2, so simulate the common
    # layout where the extractor dropped the number column
    tables[0] = [row[1:] for row in tables[0]]
    df = pdf_tables.tables_to_long(tables, ref="pdf:x.pdf", year=2024, semester=1, province_code="61")
    k = df[df["religion"] == "konghucu"].set_index("unit_name")["count"]
    assert k["Pemangkat"] == 250 and k["Tebas"] == 120
    assert df[df["religion"] == "kepercayaan"]["count"].isna().all()
    assert (df["semester"] == 1).all() and df["ref"].nunique() == 1


# ---------- harmonize ----------

def test_harmonize_and_panel(tmp_path):
    codes = tmp_path / "codes.csv"
    pd.DataFrame({"unit_code": ["6101", "6102", "6172"],
                  "unit_name": ["Kabupaten Sambas", "Kabupaten Bengkayang", "Kota Singkawang"]}).to_csv(codes, index=False)
    ct = harmonize.load_code_table(str(codes))
    assert list(ct["level"]) == ["kabupaten", "kabupaten", "kota"]

    bps = bps_api.parse_religion_html(BPS_HTML, "61", 2020, "bps:6100:1")
    arc = arcgis.layer_to_long(pd.DataFrame([
        {"KODE_KAB": "6101", "NAMA_KAB": "KAB. SAMBAS", "ISLAM": 510000, "KHONGHUCU": 1300, "JUMLAH": 560000}]),
        ref="arcgis:dkb", year=2020, semester=2)
    long = harmonize.attach_codes(pd.concat([bps, arc], ignore_index=True), ct)
    s = long[long["unit_name"] == "Sambas"]
    assert (s["unit_code"] == "6101").all()                     # level unknown, unique name in province
    assert (long[long["unit_name"] == "Kota Singkawang"]["unit_code"] == "6172").all()
    assert (~long[long["unit_name"] == "__PROVINCE__"]["matched"]).all()

    panel = harmonize.build_panel(long)
    assert set(panel["unit_code"]) == {"6101", "6172"}
    # BPS (semester NaN) and arcgis (semester 2) are different cells, so both survive
    sambas = panel[panel["unit_code"] == "6101"]
    assert len(sambas) == 2
    bps_row = sambas[sambas["sources"] == "bps"].iloc[0]
    assert bps_row["konghucu"] == 1234 and abs(bps_row["konghucu_share"] - 1234 / 551234) < 1e-12
    arc_row = sambas[sambas["sources"] == "arcgis"].iloc[0]
    assert arc_row["konghucu"] == 1300 and arc_row["total"] == 560000


def test_bps_404_is_empty_not_fatal():
    s = FakeSession({})  # every URL -> 404
    assert bps_api.list_static_tables(s, "9200", "agama", "k") == []
    df = bps_api.search_all_provinces(s, "k", sleep_s=0, log=lambda *_: None)
    assert len(df) == 0 and list(df.columns)[:3] == ["domain", "province_code", "table_id"]
