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
