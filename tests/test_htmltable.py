from konghucu.htmltable import read_html_tables


def test_strings_and_spans():
    html = """<table><thead>
    <tr><th rowspan="2">Kab</th><th colspan="2">Agama</th><th rowspan="2">Jumlah</th></tr>
    <tr><th>Islam</th><th>Khonghucu</th></tr></thead>
    <tbody><tr><td>Sambas</td><td>1.200</td><td>5</td><td>1.205</td></tr></tbody></table>"""
    t = read_html_tables(html)[0]
    assert list(t.columns) == ["Kab", "Agama | Islam", "Agama | Khonghucu", "Jumlah"]
    assert t.iloc[0].tolist() == ["Sambas", "1.200", "5", "1.205"]   # no float conversion


def test_no_thead_first_row_header_and_duplicates():
    html = "<table><tr><td>Negara</td><td>2019</td><td>2019</td></tr><tr><td>Tiongkok</td><td>1</td><td>2</td></tr></table>"
    t = read_html_tables(html)[0]
    assert list(t.columns) == ["Negara", "2019", "2019.1"]
    assert len(t) == 1


def test_empty_or_garbage_html_is_no_tables():
    assert read_html_tables("") == []
    assert read_html_tables("   ") == []
    assert read_html_tables("<p>no table here</p>") == []


def test_nested_wrapper_table_counted_once():
    html = "<table><tr><td><table><tr><th>Kec</th><th>Islam</th><th>Konghucu</th></tr><tr><td>A</td><td>1</td><td>2</td></tr></table></td></tr></table>"
    from konghucu.htmltable import grid_tables
    grids = grid_tables(html)
    assert len(grids) == 1 and len(grids[0]) == 2
