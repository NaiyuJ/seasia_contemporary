import pandas as pd

from signage.cli import main


def test_cli_sample(polygons_path, roads_path, tmp_path):
    out = tmp_path / "points.csv"
    main(["sample", "--polygons", str(polygons_path), "--roads", str(roads_path),
          "--spacing", "100", "--max-per-unit", "5", "--out", str(out)])
    df = pd.read_csv(out)
    assert list(df.columns) == ["unit_id", "point_id", "lat", "lon", "bearing"]
    assert len(df) == 10


def test_cli_cost(tmp_path, capsys):
    p = tmp_path / "panos.csv"
    pd.DataFrame({"point_id": ["a", "b", "c"], "unit_id": "A", "query_lat": 0, "query_lon": 0, "bearing": 0,
                  "pano_id": ["x", "x", "y"], "date": "2020-01", "pano_lat": 0, "pano_lon": 0,
                  "is_current": True, "status": "OK"}).to_csv(p, index=False)
    main(["cost", "--panos", str(p)])
    assert '"n_images": 4' in capsys.readouterr().out


def test_bps_publications_lists_and_filters(tmp_path, monkeypatch, capsys):
    from konghucu import bps_api, cli
    pubs = [{"pub_id": "1", "title": "Kabupaten Sambas Dalam Angka 2023", "rl_date": "2023-02-28", "size": "9 MB", "pdf": "http://x/1.pdf"},
            {"pub_id": "2", "title": "Kabupaten Sambas Dalam Angka 2021", "rl_date": "2021-02-26", "size": "8 MB", "pdf": "http://x/2.pdf"}]
    monkeypatch.setattr(bps_api, "get_key", lambda: "k")
    monkeypatch.setattr(bps_api, "list_publications", lambda s, dom, kw, key: pubs)
    out = tmp_path / "pubs.csv"
    cli.main(["bps-publications", "--domains", "6101", "--years", "2023", "--out", str(out)])
    text = capsys.readouterr().out
    assert "Dalam Angka 2023" in text and "Dalam Angka 2021" not in text
    import pandas as pd
    assert list(pd.read_csv(out)["pub_id"]) == [1]


def test_dalam_angka_extract_uses_cache(tmp_path, monkeypatch, capsys):
    import pandas as pd
    from konghucu import cli, dalam_angka
    calls = []

    def fake_extract(path, debug=False, title=None):
        calls.append(path)
        d = pd.DataFrame([dict(source="pdf_da", province_code="61", unit_code="6101", unit_name="Kabupaten Sambas", year=2023,
                               semester=None, religion="islam", count=1.0, ref="da:6101:abc", level="kabupaten")])
        d.attrs["status"] = "ok"
        return d
    monkeypatch.setattr(dalam_angka, "extract_book", fake_extract)
    pdf = tmp_path / "6101_abc.pdf"
    pdf.write_bytes(b"%PDF")
    args = ["dalam-angka-extract", str(pdf), "--out", str(tmp_path / "out.csv"), "--cache", str(tmp_path / "cache"),
            "--catalogue", str(tmp_path / "none.csv")]
    cli.main(args)
    cli.main(args)
    assert len(calls) == 1 and "taken from the cache" in capsys.readouterr().out
    # a year off the book's year is corrected from the catalogue title
    (tmp_path / "cat.csv").write_text("domain,pub_id,title\n6101,abc,Kabupaten Sambas Dalam Angka 2024\n")
    def wrong_year(path, debug=False, title=None):
        d = fake_extract(path)
        d["year"] = 2088
        return d
    monkeypatch.setattr(dalam_angka, "extract_book", wrong_year)
    cli.main(args[:-2] + ["--catalogue", str(tmp_path / "cat.csv"), "--no-cache"])
    assert pd.read_csv(tmp_path / "out.csv")["year"].iloc[0] == 2023
    cli.main(args + ["--no-cache"])
    assert len(calls) == 2
