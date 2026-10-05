#!/usr/bin/env python3
"""Check everything the local pilot needs and say exactly what is missing.

    python scripts/preflight.py
Exit code 0 when all required items pass; prints a to-do list otherwise.
Never prints secret values, only whether they are set.
"""
from __future__ import annotations

import importlib
import os
import sys

import requests

CHECKS = []


def check(name, ok, fix=""):
    CHECKS.append((name, ok, fix))
    print(f"[{'ok' if ok else '--'}] {name}" + ("" if ok else f"\n      -> {fix}"))


def reachable(url, timeout=10):
    try:
        r = requests.get(url, timeout=timeout)
        return r.status_code < 500
    except requests.RequestException:
        return False


def has(mod):
    try:
        importlib.import_module(mod)
        return True
    except Exception:  # noqa: BLE001
        return False


print("== keys (values are never printed)")
check("GOOGLE_MAPS_API_KEY set", bool(os.environ.get("GOOGLE_MAPS_API_KEY")),
      "Google Cloud console: enable 'Street View Static API' and 'Maps JavaScript API', create a key "
      "restricted by API (not by HTTP referrer), then: export GOOGLE_MAPS_API_KEY=...")
check("BPS_API_KEY set", bool(os.environ.get("BPS_API_KEY")),
      "register at https://webapi.bps.go.id (free), then: export BPS_API_KEY=...")

print("== network")
check("Street View metadata endpoint", reachable("https://maps.googleapis.com/maps/api/streetview/metadata"),
      "blocked by your network or proxy; the signage discover/fetch stages need it")
check("BPS Web API", reachable("https://webapi.bps.go.id/"), "konghucu/foreigners bps-* stages need it")
check("GIS Dukcapil ArcGIS", reachable("https://gis.dukcapil.kemendagri.go.id/arcgis/rest/services?f=pjson"),
      "konghucu arcgis-* stages need it")
check("data.go.id CKAN", reachable("https://katalog.data.go.id/api/3/action/status_show"),
      "foreigners ckan-* stages need it")
check("Overpass (OSM roads)", reachable("https://overpass-api.de/api/status"),
      "signage sample --roads osm needs it; alternative: export roads from Geofabrik and pass --roads file.geojson")
check("Nominatim (OSM geocoding)", reachable("https://nominatim.openstreetmap.org/status"),
      "signage sample --units <names> needs it; alternative: pass --polygons file.geojson")

print("== python packages")
check("core (pandas, shapely, pyproj, lxml, PIL)", all(has(m) for m in ("pandas", "shapely", "pyproj", "lxml", "PIL")),
      "pip install -r requirements.txt")
check("osmnx (roads + polygons from OSM)", has("osmnx"), "pip install osmnx")
check("playwright (historical panoramas)", has("playwright"), "pip install playwright && playwright install chromium")
ocr = has("easyocr") or has("paddleocr")
check("an OCR backend (easyocr or paddleocr)", ocr, "pip install easyocr   (or: pip install paddlepaddle paddleocr)")
check("hanzidentifier (simplified/traditional)", has("hanzidentifier"), "pip install hanzidentifier  (optional)")
check("pdfplumber (Dukcapil PDFs)", has("pdfplumber"), "pip install pdfplumber  (optional)")

if has("playwright"):
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            b.close()
        check("chromium launches", True)
    except Exception as e:  # noqa: BLE001
        check("chromium launches", False, f"playwright install chromium  ({type(e).__name__})")

required = [c for c in CHECKS if c[0] in {"GOOGLE_MAPS_API_KEY set", "BPS_API_KEY set",
                                           "core (pandas, shapely, pyproj, lxml, PIL)",
                                           "an OCR backend (easyocr or paddleocr)"}]
missing = [c for c in required if not c[1]]
print("\n" + ("ready for the pilot" if not missing else f"{len(missing)} required item(s) missing (see above)"))
sys.exit(1 if missing else 0)
