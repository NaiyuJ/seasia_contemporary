import numpy as np

from signage import sample
from signage.geo import bearing_from_dxdy, haversine_m, utm_epsg


def test_utm_zone_jakarta():
    assert utm_epsg(106.8, -6.2) == 32748  # southern hemisphere zone 48


def test_bearing():
    assert bearing_from_dxdy(0, 1) == 0.0
    assert bearing_from_dxdy(1, 0) == 90.0
    assert bearing_from_dxdy(0, -1) == 180.0
    assert bearing_from_dxdy(-1, 0) == 270.0


def test_sample_points_spacing_and_bearing(polygons_path, roads_path):
    polys = sample.load_polygons(str(polygons_path), "unit_id")
    df = sample.sample_points(polys, str(roads_path), spacing_m=100.0, max_per_unit=None, seed=1)
    assert set(df["unit_id"]) == {"A", "B"}
    assert df["point_id"].is_unique
    # E-W road through both units: ~1.1 km each -> ~11 points per unit; N-S road adds ~11 in A
    assert 15 <= (df["unit_id"] == "A").sum() <= 26
    assert 8 <= (df["unit_id"] == "B").sum() <= 14
    # bearings on the E-W road are ~90, on the N-S road ~0
    b = df["bearing"].to_numpy()
    assert np.all((np.abs(b - 90) < 3) | (b < 3) | (b > 357))
    # consecutive points along a line are ~100 m apart
    a = df[(df["unit_id"] == "B")].sort_values("lon")
    gaps = [haversine_m(a.iloc[i].lon, a.iloc[i].lat, a.iloc[i + 1].lon, a.iloc[i + 1].lat) for i in range(len(a) - 1)]
    assert all(95 < g < 105 for g in gaps)


def test_sample_points_cap_is_reproducible(polygons_path, roads_path):
    polys = sample.load_polygons(str(polygons_path), "unit_id")
    d1 = sample.sample_points(polys, str(roads_path), spacing_m=50.0, max_per_unit=5, seed=7)
    d2 = sample.sample_points(polys, str(roads_path), spacing_m=50.0, max_per_unit=5, seed=7)
    assert (d1["unit_id"].value_counts() == 5).all()
    assert d1.equals(d2)


def test_footway_filtered(roads_path):
    lines = sample.load_roads_geojson(str(roads_path))
    assert len(lines) == 3
    assert len(sample.load_roads_geojson(str(roads_path), highways=None)) == 4
