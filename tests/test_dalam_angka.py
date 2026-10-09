import pandas as pd

from konghucu import dalam_angka as da

SAMBAS_TEXT = ("SOCIAL AND WELFARE\n4.3 AGAMA DAN SOSIAL LAINNYA\nTabel Jumlah Penduduk Menurut Kecamatan dan Agama yang\n"
               "4.3.1\nTable Dianut, 2022\nPopulation By Subdistrict and Religion, 2022\n")
SAMBAS_ROWS = [
    ["Kecamatan\nSubdistrict", "Islam", "Protestan\nProtestant", "Katolik\nCatholic", "d\nHindu\ni", "Budha\nBuddha", "Lainnya\nOthers"],
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
    assert "konghucu" not in tot.index and tot["hindu"] == 173
    assert da.header_map(["Kecamatan", "dHindu i", "Budha\nBuddha"]) == [(1, "hindu"), (2, "buddha")]
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


def test_total_row_found_by_sum_not_by_name():
    rows = [
        ["Kecamatan", "Islam", "Protestan", "Katolik", "Hindu", "Budha", "Lainnya"],
        ["Kota Soe", "150", "34.620", "3.752", "7.902", "0", "0"],
        ["Mollo Utara", "20", "30.000", "2.000", "100", "0", "1"],
        ["Timor Tengah Selatan", "170", "64.620", "5.752", "8.002", "0", "1"],   # the total, no prefix
    ]
    d = da.parse_rows(rows, "Agama yang Dianut, 2023", "da:5303:x", "53", "5303", 2024)
    tot = d[d.level != "kecamatan"]
    assert set(tot.unit_name) == {"Timor Tengah Selatan"} and tot.set_index("religion")["count"]["kristen"] == 64620
    assert set(d[d.level == "kecamatan"].unit_name) == {"Kota Soe", "Mollo Utara"}
    assert (tot.level == "kabupaten").all()


def test_total_row_name_is_cleaned():
    rows = [
        ["Kecamatan", "Islam", "Protestan", "Katolik", "Hindu", "Budha", "Lainnya"],
        ["Kota Lama", "100", "200", "50", "1", "0", "0"],
        ["Kota Raja", "100", "200", "50", "1", "0", "0"],
        ["Kota Kupang Kupang Municipality", "200", "400", "100", "2", "0", "0"],
    ]
    d = da.parse_rows(rows, "Agama yang Dianut, 2023", "da:5371:x", "53", "5371", 2024)
    tot = d[d.level != "kecamatan"]
    assert set(tot.unit_name) == {"Kota Kupang"} and (tot.level == "kota").all()
    assert da.clean_unit_name("Kota Bitung/ Bitung Municipality") == "Kota Bitung"
    assert da.clean_unit_name("Kabupaten Rote Ndao Rote Ndao Regency") == "Kabupaten Rote Ndao"


class _FakePage:
    """pdfplumber page stand-in: words with positions, no ruled table."""

    def __init__(self, lines):
        self.words = []
        for top, items in lines:
            for x0, text in items:
                self.words.append({"text": text, "x0": x0, "x1": x0 + 6 * len(text), "top": top, "bottom": top + 8})

    def extract_words(self):
        return self.words

    def extract_tables(self):
        return []


def test_rows_from_words_borderless_table():
    page = _FakePage([
        (100, [(40, "Kecamatan"), (200, "Islam"), (260, "Protestan"), (330, "Katolik"), (400, "Hindu"), (460, "Budha"), (520, "Lainnya")]),
        (101, [(200, "(2)"), (260, "(3)")]),
        (120, [(40, "Selakau"), (200, "33"), (215, "657"), (262, "198"), (330, "122"), (402, "-"), (460, "4"), (475, "105"), (522, "278")]),
        (121, [(150, "b")]),  # watermark letter on its own
        (140, [(40, "Kabupaten"), (90, "Sambas"), (196, "567"), (212, "092"), (258, "11"), (272, "867"), (326, "18"), (342, "505"), (400, "173"), (456, "39"), (472, "870"), (518, "3"), (532, "071")]),
    ])
    rows = da.rows_from_words(page)
    assert rows[0] == ["Kecamatan", "islam", "kristen", "katolik", "hindu", "buddha", "lainnya"]
    d = da.parse_rows(rows, "Agama yang Dianut, 2022", "da:6101:x", "61", "6101", 2023)
    tot = d[d.level != "kecamatan"].set_index("religion")["count"]
    assert tot["islam"] == 567092 and tot["lainnya"] == 3071 and tot["hindu"] == 173
    sel = d[d.unit_name == "Selakau"].set_index("religion")["count"]
    assert sel["islam"] == 33657 and sel["buddha"] == 4105 and sel["hindu"] == 0
    assert da.religion_tables(page) == [rows]


def test_split_table_total_found_after_joining_pages():
    hdr = ["Kecamatan", "Islam", "Protestan", "Katolik", "Hindu", "Budha", "Lainnya"]
    page1 = [hdr, ["(1)", "(2)", "(3)", "(4)", "(5)", "(6)", "(7)"], ["01. Semau", "-", "11.175", "374", "-", "-", "-"],
             ["02. Kupang Barat", "1.212", "26.714", "932", "-", "-", "-"]]
    page2 = [hdr, ["03. Takari", "680", "19.199", "1.954", "-", "-", "-"],
             ["Kabupaten Kupang", "1.892", "57.088", "3.260", "-", "-", "-"]]
    rows = [hdr] + da._data_rows(page1)
    assert da.total_row_index(rows, da.header_map(hdr), 0) is None
    rows += da._data_rows(page2)
    d = da.parse_rows(rows, "Agama yang Dianut, 2023", "da:5301:x", "53", "5301", 2024)
    tot = d[d.level != "kecamatan"]
    assert set(tot.unit_name) == {"Kabupaten Kupang"} and tot.set_index("religion")["count"]["kristen"] == 57088
    assert set(d[d.level == "kecamatan"].unit_name) == {"Semau", "Kupang Barat", "Takari"}


def test_percent_table_is_skipped():
    rows = [["Kecamatan", "Islam", "Protestan", "Katolik", "Hindu", "Budha", "Lainnya"],
            ["1. Sungai Beremas", "6,4390", "_", "_", "_", "_", "_"],
            ["4. Sungai Aur", "7,7433", "0,0276", "0,0345", "0,0002", "0 ,0021", "_"],
            ["Pasaman Barat", "99,6196", "0,1312", "0,2418", "0,0002", "0,0021", "0,0145"]]
    d = da.parse_rows(rows, "Agama yang Dianut, 2023", "da:1312:x", "13", "1312", 2024)
    assert d.empty and d.attrs.get("percent")


def test_total_row_from_book_name_hint():
    rows = [["Kecamatan", "Islam", "Protestan", "Katolik", "Hindu", "Budha", "Lainnya"],
            ["Banda", "7.145", "28", "2", "-", "2", "4"],
            ["Tehoru", "5.762", "1.255", "16", "54", "-", "-"],
            ["Maluku Tengah", "84.646", "46.733", "1.014", "610", "7", "4"]]  # total is not the sum: a partial table
    d = da.parse_rows(rows, "Agama yang Dianut, 2023", "da:8103:x", "81", "8103", 2024, unit_hint="Maluku Tengah")
    tot = d[d.level != "kecamatan"]
    assert set(tot.unit_name) == {"Maluku Tengah"} and (tot.level == "kabupaten").all()
    assert da.parse_rows(rows, "x, 2023", "r", "81", "8103", 2024)[lambda x: x.level != "kecamatan"].empty
