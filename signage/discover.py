"""Stage 2: find Street View panoramas near each sample point.

Two backends:
  metadata  Street View Static API metadata endpoint. Free, no key restrictions
            beyond the key itself, but returns ONLY the most recent panorama.
  jsapi     Maps JavaScript API via headless Chromium (Playwright). Returns the
            current panorama plus the `time` array of historical panoramas at the
            same spot, which is what makes a within-location panel possible.
            `time` is not in Google's public docs, so treat it as best-effort.

Output: panos.csv with one row per (point, pano):
  point_id, unit_id, query_lat, query_lon, bearing, pano_id, date (YYYY-MM),
  pano_lat, pano_lon, is_current, status
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"
HTML_PATH = Path(__file__).resolve().parent.parent / "tools" / "discover.html"
COLUMNS = ["point_id", "unit_id", "query_lat", "query_lon", "bearing", "pano_id", "date",
           "pano_lat", "pano_lon", "is_current", "status"]


def get_api_key(key: Optional[str] = None) -> str:
    key = key or os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        raise RuntimeError("set GOOGLE_MAPS_API_KEY in the environment (never paste it into chat or code)")
    return key


def metadata_lookup(session: requests.Session, lat: float, lon: float, radius_m: int, key: str,
                    retries: int = 3) -> dict:
    params = {"location": f"{lat},{lon}", "radius": radius_m, "source": "outdoor", "key": key}
    for attempt in range(retries):
        try:
            r = session.get(METADATA_URL, params=params, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503):
                time.sleep(2 ** attempt)
                continue
            return {"status": f"HTTP_{r.status_code}"}
        except requests.RequestException:
            time.sleep(2 ** attempt)
    return {"status": "REQUEST_FAILED"}


def discover_metadata(points: pd.DataFrame, key: str, radius_m: int = 30, sleep_s: float = 0.02,
                      existing: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    done = set(existing["point_id"]) if existing is not None and len(existing) else set()
    session = requests.Session()
    rows = []
    for rec in points.itertuples(index=False):
        if rec.point_id in done:
            continue
        md = metadata_lookup(session, rec.lat, rec.lon, radius_m, key)
        base = {"point_id": rec.point_id, "unit_id": rec.unit_id, "query_lat": rec.lat,
                "query_lon": rec.lon, "bearing": rec.bearing}
        if md.get("status") == "OK":
            loc = md.get("location", {})
            rows.append({**base, "pano_id": md.get("pano_id"), "date": md.get("date"),
                         "pano_lat": loc.get("lat"), "pano_lon": loc.get("lng"),
                         "is_current": True, "status": "OK"})
        else:
            rows.append({**base, "pano_id": None, "date": None, "pano_lat": None, "pano_lon": None,
                         "is_current": None, "status": md.get("status", "UNKNOWN")})
        time.sleep(sleep_s)
    new = pd.DataFrame(rows, columns=COLUMNS)
    return pd.concat([existing, new], ignore_index=True) if existing is not None else new


def discover_jsapi(points: pd.DataFrame, key: str, radius_m: int = 30,
                   existing: Optional[pd.DataFrame] = None, headless: bool = True) -> pd.DataFrame:
    """Historical panorama discovery through the Maps JavaScript API.

    The API key must have the Maps JavaScript API enabled. The page is loaded from
    a file:// URL, so a key restricted by HTTP referrer will be rejected; use a key
    without referrer restrictions (restrict it by API instead)."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise ImportError("backend 'jsapi' needs `pip install playwright` and a Chromium install") from e
    done = set(existing["point_id"]) if existing is not None and len(existing) else set()
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(f"file://{HTML_PATH}?key={key}")
        page.wait_for_function("window.svReady === true", timeout=60_000)
        for rec in points.itertuples(index=False):
            if rec.point_id in done:
                continue
            res = page.evaluate("([lat, lng, r]) => window.findPanos(lat, lng, r)",
                                [float(rec.lat), float(rec.lon), int(radius_m)])
            base = {"point_id": rec.point_id, "unit_id": rec.unit_id, "query_lat": rec.lat,
                    "query_lon": rec.lon, "bearing": rec.bearing}
            if isinstance(res, dict) and "error" in res:
                rows.append({**base, "pano_id": None, "date": None, "pano_lat": None, "pano_lon": None,
                             "is_current": None, "status": res["error"]})
                continue
            cur = next((p for p in res if p.get("current")), None)
            for p in res:
                rows.append({**base, "pano_id": p["pano"], "date": p.get("date"),
                             "pano_lat": p.get("lat") if p.get("lat") is not None else (cur or {}).get("lat"),
                             "pano_lon": p.get("lng") if p.get("lng") is not None else (cur or {}).get("lng"),
                             "is_current": bool(p.get("current")), "status": "OK"})
        browser.close()
    new = pd.DataFrame(rows, columns=COLUMNS)
    return pd.concat([existing, new], ignore_index=True) if existing is not None else new


def dedupe_panos(panos: pd.DataFrame) -> pd.DataFrame:
    """A panorama can be the nearest one to several sample points. Keep one row per
    pano_id (the first point that found it) so no image is fetched or counted twice."""
    ok = panos[panos["status"] == "OK"].copy()
    ok["year"] = ok["date"].astype(str).str.slice(0, 4)
    return ok.drop_duplicates("pano_id", keep="first").reset_index(drop=True)
