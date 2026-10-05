import json
from pathlib import Path

import pytest

# Two adjacent "kabupaten" squares near Jakarta, ~1.1 km on a side.
LON0, LAT0 = 106.80, -6.20
D = 0.01


def _square(x, y, d=D):
    return [[[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]]


@pytest.fixture
def polygons_path(tmp_path: Path) -> Path:
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"unit_id": "A"},
         "geometry": {"type": "Polygon", "coordinates": _square(LON0, LAT0)}},
        {"type": "Feature", "properties": {"unit_id": "B"},
         "geometry": {"type": "Polygon", "coordinates": _square(LON0 + D, LAT0)}},
    ]}
    p = tmp_path / "units.geojson"
    p.write_text(json.dumps(gj))
    return p


@pytest.fixture
def roads_path(tmp_path: Path) -> Path:
    # one east-west road crossing both units, one north-south road in A only,
    # one footway (should be filtered out), one road entirely outside
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"highway": "secondary"},
         "geometry": {"type": "LineString", "coordinates": [[LON0 - D, LAT0 + D / 2], [LON0 + 3 * D, LAT0 + D / 2]]}},
        {"type": "Feature", "properties": {"highway": "residential"},
         "geometry": {"type": "LineString", "coordinates": [[LON0 + D / 2, LAT0], [LON0 + D / 2, LAT0 + D]]}},
        {"type": "Feature", "properties": {"highway": "footway"},
         "geometry": {"type": "LineString", "coordinates": [[LON0, LAT0], [LON0 + D, LAT0 + D]]}},
        {"type": "Feature", "properties": {"highway": "primary"},
         "geometry": {"type": "LineString", "coordinates": [[LON0 + 5 * D, LAT0], [LON0 + 6 * D, LAT0]]}},
    ]}
    p = tmp_path / "roads.geojson"
    p.write_text(json.dumps(gj))
    return p
