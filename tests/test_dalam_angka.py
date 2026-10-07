import pandas as pd

from konghucu import dalam_angka as da

SAMBAS_TEXT = ("SOCIAL AND WELFARE\n4.3 AGAMA DAN SOSIAL LAINNYA\nTabel Jumlah Penduduk Menurut Kecamatan dan Agama yang\n"
               "4.3.1\nTable Dianut, 2022\nPopulation By Subdistrict and Religion, 2022\n")
SAMBAS_ROWS = [
    ["Kecamatan\nSubdistrict", "Islam", "Protestan\nProtestant", "Katolik\nCatholic", "dHindu\ni", "Budha\nBuddha", "Lainnya\nOthers"],
    ["(1)", "(2)", "(3)", "(4)", ". o (5)", "(6)", "(7)"],
    ["Selakau", "33 657", "198", "g 122", "-", "4 105", "278"],
    ["Pemangkat", "39 416", "696b", "p 925", "6", "9 866", "1 906"],
    ["a s Sebawi", "19 119", "101", "49", "-", "1 506", "81"],
    ["Kabupaten Sambas", "567 092", "11 867", "18 505", "173", "39 870", "3 071"],
]
SINGKAWANG_ROWS = [
    ["Kecamatan\nDistrict", "Islam\nIslam", "Protestan\nProtesta", "Katolik\nCatholic", "Budha\nBuddha", "Hindu\nHindu", "Konghucu\nKonghucu", "Lainnya\nOthers"],
    ["(1)", "(2)", "(3)", "(4)", "(5)", "(6)", "(7)", "(8)"],
    ["Singkawang Selatan", "22.226", "4.422", "4.636", "25.279", "4i1", "d 1.053", "-"],
    ["Singkawang Barat", "16.629", "3.331", "3.277", "p 30b.040", "16", "726", "3"],
    ["Kota Singkawang", "133.327", "13.829", "18.14k3", "t o 77.020", "67", "2.316", "4"],
]


def test_clean_number_strips_watermark():
    assert da.clean_number("4i1") == 41 and da.clean_number("30b.040") == 30040 and da.clean_number("5.01.4") == 5014
    assert da.clean_number("80a1") == 801 and da.clean_number("k 2 390") == 2390 and da.clean_number("1.13") == 113
    assert da.clean_number("-") == 0 and da.clean_number("–") == 0 and da.clean_number("i . o-") == 0
    assert da.clean_number("") is None and da.clean_number(None) is None


def test_clean_label():
    assert da.clean_label("a s Sebawi") == "Sebawi" and da.clean_label("1. Sungai Raya") == "Sungai Raya"
    assert da.clean_label("/ / Sajad :") == "Sajad" and da.clean_label("Kabupaten Bengkayang") == "Kabupaten Bengkayang"


def test_parse_sambas_table():
    d = da.parse_rows(SAMBAS_ROWS, SAMBAS_TEXT, "da:6101:x", "61", "6101", 2023)
    tot = d[d.level != "kecamatan"].set_index("religion")["count"]
    assert d["year"].iloc[0] == 2022 and tot["islam"] == 567092 and tot["lainnya"] == 3071 and tot["buddha"] == 39870
    assert "konghucu" not in tot.index
    assert set(d[d.level == "kecamatan"]["unit_name"]) == {"Selakau", "Pemangkat", "Sebawi"}
    assert d[(d.unit_name == "Pemangkat") & (d.religion == "kristen")]["count"].iloc[0] == 696
    assert d[d.level == "kecamatan"]["unit_code"].isna().all() and (d[d.level != "kecamatan"]["unit_code"] == "6101").all()


def test_parse_singkawang_table_with_konghucu():
    text = "Tabel Jumlah Penduduk Menurut Kecamatan dan Agama\n4.3.1\nTable yang Dianut di Kota Singkawang, 2023\n"
    d = da.parse_rows(SINGKAWANG_ROWS, text, "da:6172:y", "61", "6172", 2024)
    tot = d[d.level == "kota"].set_index("religion")["count"]
    assert d["year"].iloc[0] == 2023 and tot["konghucu"] == 2316 and tot["buddha"] == 77020 and tot["katolik"] == 18143
    sel = d[(d.unit_name == "Singkawang Selatan")].set_index("religion")["count"]
    assert sel["hindu"] == 41 and sel["konghucu"] == 1053 and sel["lainnya"] == 0


def test_page_score_prefers_population_table_over_places_of_worship():
    pop = "Tabel Jumlah Penduduk Menurut Kecamatan dan Agama yang Dianut, 2022\nIslam Protestan Katolik Hindu Budha Lainnya"
    worship = "Tabel Jumlah Rumah Ibadah Menurut Jenis Agama\nIslam Katholik Kristen Budha Hindu Konghucu\nMasjid Gereja"
    assert da.page_score(pop) > da.page_score(worship)
