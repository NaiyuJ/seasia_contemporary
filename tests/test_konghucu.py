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
    assert len(df) == 0 and list(df.columns)[:2] == ["domain", "province_code"]


def test_parse_dynamic_table():
    js = {"data-availability": "available",
          "vervar": [{"val": 6101, "label": "Sambas"}, {"val": 6172, "label": "Kota Singkawang"}, {"val": 6100, "label": "Kalimantan Barat"}],
          "var": [{"val": 55, "label": "Jumlah Penduduk Menurut Agama"}],
          "turvar": [{"val": 1, "label": "Islam"}, {"val": 6, "label": "Khonghucu"}, {"val": 9, "label": "Jumlah"}],
          "tahun": [{"val": 120, "label": "2020"}, {"val": 121, "label": "2021"}],
          "turtahun": [{"val": 0, "label": ""}],
          "datacontent": {"6101551120" + "0": 500000, "6101556120" + "0": "1.234", "6101559120" + "0": 551234,
                          "6172556121" + "0": 5678, "6100556120" + "0": 6912}}
    df = bps_api.parse_dynamic(js, "61", "bpsvar:6100:55")
    k = df[df["religion"] == "konghucu"]
    assert k[(k["unit_name"] == "Sambas") & (k["year"] == 2020)]["count"].item() == 1234
    assert k[(k["unit_name"] == "Kota Singkawang") & (k["year"] == 2021)]["count"].item() == 5678
    assert k[k["unit_name"] == "__PROVINCE__"]["count"].item() == 6912
    assert df[(df["unit_name"] == "Sambas") & (df["religion"] == "total")]["count"].item() == 551234
    assert len(df[df["year"] == 2021]) == 1          # only the cells that exist
    assert bps_api.parse_dynamic({"data-availability": "list-not-available"}, "61", "x").empty


def test_dotenv(tmp_path, monkeypatch):
    from konghucu.envfile import load_dotenv
    f = tmp_path / ".env"
    f.write_text("# c\nBPS_API_KEY='abc'\nexport GOOGLE_MAPS_API_KEY=xyz\nBAD\n")
    monkeypatch.setenv("BPS_API_KEY", "")          # exported but empty: must be overridden
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "keep")
    info = load_dotenv(f)
    import os
    assert os.environ["BPS_API_KEY"] == "abc" and os.environ["GOOGLE_MAPS_API_KEY"] == "keep"
    assert info["found"] and info["keys"] == ["BPS_API_KEY"]


@pytest.mark.parametrize("title,about,by_unit,pct", [
    ("Jumlah Penduduk Menurut Kabupaten/Kota dan Agama yang Dianut, 2021", True, True, False),
    ("Jumlah Umat Agama Menurut Kabupaten/Kota di Provinsi Sumatera Utara, 2022", True, True, False),
    ("Banyaknya Pemeluk Agama Menurut Golongan Agama dan Kabupaten/Kota 2015", True, True, False),
    ("Persentase Penduduk Menurut Kabupaten/Kota dan Agama yang Dianut 2016", True, True, True),
    ("Jumlah Penduduk Menurut Agama yang Dianut", True, False, False),
    ("Jumlah Sekolah, Guru, dan Murid Madrasah Aliyah (MA) di Bawah Kementerian Agama Menurut Kabupaten/Kota", False, False, False),
    ("Banyaknya Perkara di Pengadilan Agama Menurut Kabupaten/Kota, 2015", False, False, False),
    ("Banyaknya Pemuka Agama Menurut Agama dan Kabupaten/Kota di Provinsi Bali", False, False, False),
    ("Jumlah Tempat Peribadatan Menurut Kabupaten/Kota dan Agama", False, False, False),
])
def test_classify_title(title, about, by_unit, pct):
    c = bps_api.classify_title(title)
    assert (c["about_religion"], c["by_unit"], c["is_percent"]) == (about, by_unit, pct)


def test_search_scans_kabupaten_domains():
    def router(url, params):
        if "/domain/type/kabbyprov/" in url:
            return {"data": [{"total": 2}, [{"domain_id": "6101", "domain_name": "Kab. Sambas"},
                                           {"domain_id": "6172", "domain_name": "Kota Singkawang"}]]}
        if "/list/model/statictable" in url and "/domain/6172/" in url and "/keyword/agama/" in url:
            return {"data-availability": "available", "data": [{"pages": 1}, [
                {"table_id": "7", "title": "Jumlah Penduduk Menurut Kecamatan dan Agama yang Dianut, 2022"}]]}
        return {"data-availability": "list-not-available", "data": []}
    s = FakeSession({"webapi.bps.go.id": router})
    df = bps_api.search_all_provinces(s, "k", level="kabupaten", provinces=["61"], sleep_s=0, log=lambda *_: None)
    assert len(df) == 1 and df.iloc[0]["domain"] == "6172" and df.iloc[0]["by_unit"]


def test_rollup_kabupaten_domain_with_and_without_total_row():
    html_total = """<table><tr><th>Kecamatan</th><th>Islam</th><th>Khonghucu</th></tr>
    <tr><td>Pemangkat</td><td>100</td><td>5</td></tr><tr><td>Tebas</td><td>200</td><td>7</td></tr>
    <tr><td>Jumlah</td><td>300</td><td>12</td></tr></table>"""
    d = bps_api.parse_religion_html(html_total, "61", 2022, "bps:6101:1")
    r = bps_api.rollup_kabupaten_domain(d, "6101", "Sambas")
    kab = r[r["level"] == "kabupaten"]
    assert set(kab["unit_code"]) == {"6101"} and kab[kab["religion"] == "konghucu"]["count"].item() == 12
    assert (r[r["level"] == "kecamatan"]["unit_code"].isna()).all() and len(r[r["level"] == "kecamatan"]) == 4

    html_nototal = html_total.replace("<tr><td>Jumlah</td><td>300</td><td>12</td></tr>", "")
    d2 = bps_api.parse_religion_html(html_nototal, "61", 2022, "bps:6101:2")
    r2 = bps_api.rollup_kabupaten_domain(d2, "6101", "Sambas")
    kab2 = r2[r2["level"] == "kabupaten"]
    assert kab2[kab2["religion"] == "konghucu"]["count"].item() == 12 and (kab2["source"] == "bps_kabsum").all()

    # province domain: untouched
    assert bps_api.rollup_kabupaten_domain(d, "6100", "Kalbar").equals(d)


def test_network_error_becomes_runtime_error_and_scan_continues(monkeypatch):
    import requests

    class Boom:
        def get(self, url, timeout=None):
            raise requests.ConnectionError("reset")
    monkeypatch.setattr(bps_api.time, "sleep", lambda *_: None)
    with pytest.raises(RuntimeError):
        bps_api._get_json(Boom(), "https://x")
    logs = []
    df = bps_api.search_all_provinces(Boom(), "k", provinces=["61"], sleep_s=0, log=logs.append)
    assert len(df) == 0 and any("network error" in m for m in logs)


def test_checkpoint_resume(tmp_path):
    from konghucu.cli import _Checkpoint, STATIC_COLS
    out = str(tmp_path / "cat.csv")
    ck = _Checkpoint(out, resume=False, columns=STATIC_COLS)
    ck("6101", [{"domain": "6101", "province_code": "61", "domain_name": "Sambas", "table_id": "1", "title": "t",
                 "subj": None, "updt_date": None, "excel": None, "about_religion": True, "by_unit": True, "is_percent": False}])
    ck("6102", [])
    ck2 = _Checkpoint(out, resume=True, columns=STATIC_COLS)
    assert ck2.done == {"6101", "6102"} and len(ck2.load()) == 1
    ck3 = _Checkpoint(out, resume=False, columns=STATIC_COLS)
    assert ck3.done == set() and len(ck3.load()) == 0


def test_fetch_tables_skips_bad_tables_and_reuses_raw(tmp_path):
    calls = []

    def view(url, params):
        calls.append(url)
        if "/id/1/" in url:
            return {"status": "OK", "data": {"title": "Penduduk Menurut Kabupaten/Kota dan Agama 2021", "table": BPS_HTML}}
        if "/id/2/" in url:
            return {"status": "OK", "data": {"title": "x", "table": ""}}          # empty
        return {"status": "OK", "data": {"title": "y", "table": "<table><tr><th>A</th></tr></table>"}}  # no religion
    s = FakeSession({"/view/model/statictable": view})
    cat = pd.DataFrame([{"domain": "6100", "province_code": "61", "domain_name": "Kalbar", "table_id": t, "title": "t"}
                        for t in ("1", "2", "3")])
    logs = []
    df = bps_api.fetch_tables(s, cat, "k", sleep_s=0, raw_dir=str(tmp_path), log=logs.append)
    assert df["ref"].nunique() == 1 and (df["year"] == 2021).all()
    assert any("EMPTY" in m for m in logs) and any("NO RELIGION" in m for m in logs)
    n = len(calls)
    df2 = bps_api.fetch_tables(s, cat, "k", sleep_s=0, raw_dir=str(tmp_path), log=logs.append)
    assert len(calls) == n + 1            # tables 1 and 3 come from raw_dir; only the empty one is re-fetched
    assert df2.equals(df)


def test_view_data_all_years_merges_two_year_chunks():
    calls = []

    def router(url, params):
        if "/model/th/" in url:
            return {"data": [{"total": 3}, [{"th_id": 121, "th": "2021"}, {"th_id": 122, "th": "2022"}, {"th_id": 123, "th": "2023"}]]}
        if "/model/data/" in url:
            th = url.split("/th/")[1].split("/")[0]
            calls.append(th)
            ids = th.split(";")
            return {"data-availability": "available", "vervar": [{"val": 6101, "label": "Sambas"}],
                    "var": [{"val": 55, "label": "Penduduk Menurut Agama"}], "turvar": [{"val": 6, "label": "Khonghucu"}],
                    "tahun": [{"val": int(i), "label": str(1900 + int(i))} for i in ids], "turtahun": [{"val": 0, "label": ""}],
                    "datacontent": {f"6101556{i}0": int(i) for i in ids}}
        return {"data-availability": "list-not-available", "data": []}
    s = FakeSession({"webapi.bps.go.id": router})
    js = bps_api.view_data_all_years(s, "6100", 55, "k", sleep_s=0)
    assert calls == ["121;122", "123"]
    assert [t["val"] for t in js["tahun"]] == [121, 122, 123] and len(js["datacontent"]) == 3
    df = bps_api.parse_dynamic(js, "61", "x")
    assert sorted(df["year"]) == [2021, 2022, 2023]


def test_rollup_detects_unlabelled_total_row():
    # total row labelled with the kabupaten name, not 'Jumlah': must not be double counted
    html = """<table><tr><th>Kecamatan</th><th>Islam</th><th>Konghucu</th></tr>
    <tr><td>Pemangkat</td><td>100</td><td>5</td></tr><tr><td>Tebas</td><td>200</td><td>7</td></tr>
    <tr><td>Sambas</td><td>300</td><td>12</td></tr></table>"""
    d = bps_api.parse_religion_html(html, "61", 2022, "x")
    r = bps_api.rollup_kabupaten_domain(d, "6101", "Kab. Sambas")
    kab = r[r["level"] == "kabupaten"]
    assert kab[kab["religion"] == "islam"]["count"].item() == 300
    assert kab[kab["religion"] == "konghucu"]["count"].item() == 12
    assert len(r[r["level"] == "kecamatan"]) == 4

    # total row labelled with the year only: found by arithmetic
    html2 = html.replace("<td>Sambas</td>", "<td>Trenggalek 2019</td>")
    d2 = bps_api.parse_religion_html(html2, "35", 2019, "y")
    r2 = bps_api.rollup_kabupaten_domain(d2, "3503", "Kabupaten Trenggalek")
    assert r2[(r2["level"] == "kabupaten") & (r2["religion"] == "islam")]["count"].item() == 300


def test_years_row_beside_rowspan_label_is_not_data():
    html = """<table>
    <tr><td rowspan=2>Kabupaten/ Kota Regency/ Municipality</td><td colspan=2>Islam</td><td colspan=2>Budha</td></tr>
    <tr><td>2019</td><td>2020</td><td>2019</td><td>2020</td></tr>
    <tr><td>Kabupaten/ Regency</td><td></td><td></td><td></td><td></td></tr>
    <tr><td>Cilacap</td><td>1 793 687</td><td>1 800 000</td><td>600</td><td>1 463</td></tr></table>"""
    df = bps_api.parse_religion_html(html, "33", None, "z")
    assert set(df["unit_name"]) == {"Cilacap"}
    c = df.set_index(["religion", "year"])["count"]
    assert c[("islam", 2019)] == 1793687 and c[("islam", 2020)] == 1800000 and c[("buddha", 2020)] == 1463
