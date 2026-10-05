"""Stage 3: download storefront-facing images for each panorama.

For every pano we request images at bearing +/- 90 degrees (both sides of the
street). Each request is billed by Google; run `signage cost` first.
Output: images.csv with pano_id, heading, path, status, bytes.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional, Sequence

import pandas as pd
import requests

STATIC_URL = "https://maps.googleapis.com/maps/api/streetview"
MIN_BYTES = 4000  # Google's "no imagery" placeholder is a tiny grey image


def image_url(pano_id: str, heading: float, key: str, size: str = "640x640", fov: int = 90,
              pitch: int = 5) -> str:
    return (f"{STATIC_URL}?size={size}&pano={pano_id}&heading={heading:.0f}"
            f"&fov={fov}&pitch={pitch}&source=outdoor&key={key}")


def image_path(out_dir: Path, pano_id: str, heading: float) -> Path:
    return out_dir / f"{pano_id}_{int(round(heading)) % 360:03d}.jpg"


def fetch_images(panos: pd.DataFrame, out_dir: str | Path, key: str,
                 heading_offsets: Sequence[int] = (-90, 90), size: str = "640x640", fov: int = 90,
                 pitch: int = 5, sleep_s: float = 0.05, max_images: Optional[int] = None,
                 existing: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    done = set(existing["path"]) if existing is not None and len(existing) else set()
    session = requests.Session()
    rows, n = [], 0
    for rec in panos.itertuples(index=False):
        for off in heading_offsets:
            heading = (float(rec.bearing) + off) % 360
            path = image_path(out_dir, rec.pano_id, heading)
            if str(path) in done or path.exists():
                continue
            if max_images is not None and n >= max_images:
                break
            status, nbytes = "ERROR", 0
            for attempt in range(3):
                try:
                    r = session.get(image_url(rec.pano_id, heading, key, size, fov, pitch), timeout=30)
                except requests.RequestException:
                    time.sleep(2 ** attempt)
                    continue
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
                    nbytes = len(r.content)
                    if nbytes < MIN_BYTES:
                        status = "NO_IMAGE"
                    else:
                        path.write_bytes(r.content)
                        status = "OK"
                    break
                if r.status_code in (429, 500, 502, 503):
                    time.sleep(2 ** attempt)
                    continue
                status = f"HTTP_{r.status_code}"
                break
            rows.append({"pano_id": rec.pano_id, "heading": int(round(heading)) % 360,
                         "path": str(path), "status": status, "bytes": nbytes})
            n += 1
            time.sleep(sleep_s)
    new = pd.DataFrame(rows, columns=["pano_id", "heading", "path", "status", "bytes"])
    return pd.concat([existing, new], ignore_index=True) if existing is not None else new


def estimate_cost(n_panos: int, n_headings: int = 2, usd_per_1000: float = 7.0) -> dict:
    """Rough bill. Check Google's current Street View Static API price before trusting it."""
    n_images = n_panos * n_headings
    return {"n_images": n_images, "usd": round(n_images / 1000 * usd_per_1000, 2),
            "usd_per_1000_assumed": usd_per_1000}
