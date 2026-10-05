"""Stage 1: sample points along roads inside administrative units.

Input
  polygons: GeoJSON of admin units (e.g. kabupaten/kota) with an id property
  roads:    either a GeoJSON of LineStrings (e.g. exported from Geofabrik/QGIS)
            or "osm" to pull the drivable network with osmnx (optional dependency)
Output
  CSV with one row per sample point: unit_id, point_id, lat, lon, bearing
  `bearing` is the road direction at the point (0 = north, clockwise); the fetch
  stage looks perpendicular to it (bearing +/- 90) to face the storefronts.
"""
from __future__ import annotations

import json
from typing import Iterable, List, Sequence, Tuple

import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiLineString, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shp_transform

from .geo import bearing_from_dxdy, make_transformers

DEFAULT_HIGHWAYS = (
    "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link", "residential", "unclassified", "living_street",
)


def load_polygons(path: str, id_field: str) -> List[Tuple[str, BaseGeometry]]:
    with open(path, encoding="utf-8") as f:
        gj = json.load(f)
    out = []
    for feat in gj["features"]:
        props = feat.get("properties") or {}
        if id_field not in props:
            raise KeyError(f"polygon feature missing id field '{id_field}': {props}")
        out.append((str(props[id_field]), shape(feat["geometry"])))
    return out


def polygons_from_names(names: Sequence[str]) -> List[Tuple[str, BaseGeometry]]:
    """Geocode admin-unit names with osmnx/Nominatim, e.g. 'Kota Singkawang, Indonesia'.
    Pass 'label=Name, Indonesia' to choose the unit_id, else a slug of the name is used."""
    try:
        import osmnx as ox  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise ImportError("--units needs `pip install osmnx`") from e
    out = []
    for raw in names:
        label, _, query = raw.partition("=") if "=" in raw else (None, None, raw)
        gdf = ox.geocode_to_gdf(query)
        geom = gdf.geometry.iloc[0]
        uid = label or "".join(ch if ch.isalnum() else "_" for ch in query.split(",")[0].strip().lower())
        out.append((uid, geom))
    return out


def _iter_lines(geom: BaseGeometry) -> Iterable[LineString]:
    if geom.is_empty:
        return
    if isinstance(geom, LineString):
        yield geom
    elif isinstance(geom, MultiLineString):
        yield from geom.geoms
    elif hasattr(geom, "geoms"):  # GeometryCollection
        for g in geom.geoms:
            yield from _iter_lines(g)


def load_roads_geojson(path: str, highways: Sequence[str] | None = DEFAULT_HIGHWAYS) -> List[LineString]:
    """Load road centrelines (lon/lat) from GeoJSON. Keeps features whose
    'highway' property is in `highways`; features without the property are kept."""
    with open(path, encoding="utf-8") as f:
        gj = json.load(f)
    lines: List[LineString] = []
    for feat in gj["features"]:
        props = feat.get("properties") or {}
        hw = props.get("highway")
        if highways is not None and hw is not None and hw not in highways:
            continue
        lines.extend(_iter_lines(shape(feat["geometry"])))
    return lines


def roads_from_osm(polygon: BaseGeometry, highways: Sequence[str] = DEFAULT_HIGHWAYS) -> List[LineString]:
    """Pull road centrelines inside `polygon` from OpenStreetMap via osmnx."""
    try:
        import osmnx as ox  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise ImportError("roads='osm' needs `pip install osmnx`") from e
    filt = '["highway"~"' + "|".join(highways) + '"]'
    g = ox.graph_from_polygon(polygon, custom_filter=filt, simplify=True, retain_all=True)
    edges = ox.graph_to_gdfs(g, nodes=False, edges=True)
    lines: List[LineString] = []
    for geom in edges.geometry:
        lines.extend(_iter_lines(geom))
    return lines


def sample_along_lines(lines: Iterable[LineString], spacing_m: float, rng: np.random.Generator,
                       fwd, inv) -> List[Tuple[float, float, float]]:
    """Systematic sampling every `spacing_m` metres along each line, with a random
    start offset per line. Returns (lon, lat, bearing) tuples."""
    pts = []
    for line in lines:
        m = shp_transform(fwd.transform, line)
        length = m.length
        if length < 1.0:
            continue
        start = rng.uniform(0, min(spacing_m, length))
        for d in np.arange(start, length, spacing_m):
            p = m.interpolate(d)
            q = m.interpolate(min(d + 2.0, length)) if d + 2.0 <= length else m.interpolate(max(d - 2.0, 0.0))
            dx, dy = (q.x - p.x, q.y - p.y) if d + 2.0 <= length else (p.x - q.x, p.y - q.y)
            lon, lat = inv.transform(p.x, p.y)
            pts.append((lon, lat, bearing_from_dxdy(dx, dy)))
    return pts


def sample_points(polygons: List[Tuple[str, BaseGeometry]], roads: str, spacing_m: float = 50.0,
                  max_per_unit: int | None = 300, seed: int = 0,
                  highways: Sequence[str] = DEFAULT_HIGHWAYS) -> pd.DataFrame:
    """Sample road points per unit. `roads` is a GeoJSON path or 'osm'."""
    rng = np.random.default_rng(seed)
    all_roads = None if roads == "osm" else load_roads_geojson(roads, highways)
    rows = []
    for unit_id, poly in polygons:
        c = poly.centroid
        fwd, inv = make_transformers(c.x, c.y)
        if roads == "osm":
            lines = roads_from_osm(poly, highways)
        else:
            lines = []
            for ln in all_roads:  # type: ignore[union-attr]
                if ln.intersects(poly):
                    lines.extend(_iter_lines(ln.intersection(poly)))
        pts = sample_along_lines(lines, spacing_m, rng, fwd, inv)
        if max_per_unit is not None and len(pts) > max_per_unit:
            idx = rng.choice(len(pts), size=max_per_unit, replace=False)
            pts = [pts[i] for i in sorted(idx)]
        for i, (lon, lat, b) in enumerate(pts):
            rows.append({"unit_id": unit_id, "point_id": f"{unit_id}_{i:05d}",
                         "lat": round(lat, 6), "lon": round(lon, 6), "bearing": round(b, 1)})
    return pd.DataFrame(rows, columns=["unit_id", "point_id", "lat", "lon", "bearing"])
