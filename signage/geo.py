"""Small geodesy helpers (no geopandas dependency)."""
from __future__ import annotations

import math
from typing import Tuple

from pyproj import Transformer


def utm_epsg(lon: float, lat: float) -> int:
    """EPSG code of the WGS84 UTM zone containing (lon, lat)."""
    zone = int((lon + 180) // 6) + 1
    return (32600 if lat >= 0 else 32700) + zone


def make_transformers(lon: float, lat: float) -> Tuple[Transformer, Transformer]:
    """Forward (lon/lat -> metres) and inverse transformers for the local UTM zone."""
    epsg = utm_epsg(lon, lat)
    fwd = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    inv = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    return fwd, inv


def bearing_from_dxdy(dx: float, dy: float) -> float:
    """Compass bearing (0 = north, clockwise) of a step (dx east, dy north) in metres."""
    return math.degrees(math.atan2(dx, dy)) % 360.0


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
