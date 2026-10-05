"""Generic ArcGIS REST client, used for GIS Dukcapil (gis.dukcapil.kemendagri.go.id/arcgis).

Only reads public layers. If a layer answers with error code 498/499 it needs a
token; we record that and move on rather than trying to get around it.
"""
from __future__ import annotations

import re
import time
from typing import Dict, Iterable, List, Optional

import pandas as pd

from .religion import LONG_COLUMNS, canonical_religion, norm_label, norm_unit_name, unit_level

DEFAULT_BASE = "https://gis.dukcapil.kemendagri.go.id/arcgis/rest/services"
RELIGION_FIELD_RE = re.compile(r"agama|islam|kristen|protestan|katolik|hindu|bud+ha|kong|khong|kepercayaan", re.I)
UNIT_NAME_RE = re.compile(r"(nama|nm)_?(kab|kabkot|kabupaten|wil)|^kabkot$|^kabupaten$|^wadmkk$|^nmkab", re.I)
UNIT_CODE_RE = re.compile(r"(kode|kd|id)_?(kab|kabkot|kabupaten|wil)|^kdkab|^kdpkab|^kode_kk$", re.I)
PROV_CODE_RE = re.compile(r"(kode|kd|id)_?(prov|propinsi|provinsi)|^kdprov|^kdppum", re.I)


def _get(session, url: str, params: Optional[dict] = None, retries: int = 3) -> dict:
    params = {**(params or {}), "f": "json"}
    for attempt in range(retries):
        r = session.get(url, params=params, timeout=60)
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                return {"error": {"code": -1, "message": "non-JSON response"}}
        if r.status_code in (429, 500, 502, 503):
            time.sleep(2 ** attempt)
            continue
        return {"error": {"code": r.status_code, "message": r.text[:200]}}
    return {"error": {"code": -1, "message": "retries exhausted"}}


def list_services(session, base: str = DEFAULT_BASE) -> List[dict]:
    """Recursively list Map/Feature services: [{name, type, url}]."""
    out, stack = [], [base]
    while stack:
        url = stack.pop()
        js = _get(session, url)
        for f in js.get("folders", []):
            stack.append(f"{base}/{f}")
        for s in js.get("services", []):
            if s.get("type") in ("FeatureServer", "MapServer"):
                out.append({"name": s["name"], "type": s["type"], "url": f"{base}/{s['name']}/{s['type']}"})
    return out


def list_layers(session, service_url: str) -> List[dict]:
    js = _get(session, service_url)
    if "error" in js:
        return [{"id": None, "name": None, "url": service_url, "error": js["error"].get("code")}]
    return [{"id": l["id"], "name": l.get("name"), "url": f"{service_url}/{l['id']}"}
            for l in js.get("layers", []) + js.get("tables", [])]


def layer_fields(session, layer_url: str) -> dict:
    js = _get(session, layer_url)
    if "error" in js:
        return {"error": js["error"].get("code"), "fields": [], "maxRecordCount": 0}
    return {"fields": [{"name": f["name"], "alias": f.get("alias", f["name"]), "type": f.get("type")}
                       for f in js.get("fields", [])],
            "maxRecordCount": int(js.get("maxRecordCount") or 1000), "name": js.get("name")}


def discover_religion_layers(session, base: str = DEFAULT_BASE, sleep_s: float = 0.1) -> pd.DataFrame:
    """Scan every layer; keep those with at least one religion-like field."""
    rows = []
    for svc in list_services(session, base):
        for lyr in list_layers(session, svc["url"]):
            if lyr.get("error"):
                rows.append({"service": svc["name"], "layer_id": None, "layer_name": None, "url": svc["url"],
                             "n_religion_fields": 0, "religion_fields": "", "error": lyr["error"]})
                continue
            info = layer_fields(session, lyr["url"])
            rel = [f["name"] for f in info["fields"] if RELIGION_FIELD_RE.search(f["name"] + " " + str(f["alias"]))]
            rows.append({"service": svc["name"], "layer_id": lyr["id"], "layer_name": info.get("name") or lyr["name"],
                         "url": lyr["url"], "n_religion_fields": len(rel), "religion_fields": ";".join(rel),
                         "error": info.get("error")})
            time.sleep(sleep_s)
    df = pd.DataFrame(rows, columns=["service", "layer_id", "layer_name", "url", "n_religion_fields",
                                     "religion_fields", "error"])
    return df.sort_values("n_religion_fields", ascending=False).reset_index(drop=True)


def query_all(session, layer_url: str, where: str = "1=1", page_size: Optional[int] = None) -> pd.DataFrame:
    """All attribute rows of a layer, paginated with resultOffset. Raises on token errors."""
    info = layer_fields(session, layer_url)
    if info.get("error"):
        raise PermissionError(f"layer {layer_url} returned error {info['error']} (498/499 = token required)")
    size = page_size or min(info["maxRecordCount"], 2000)
    rows, offset = [], 0
    while True:
        js = _get(session, f"{layer_url}/query", {"where": where, "outFields": "*", "returnGeometry": "false",
                                                   "resultOffset": offset, "resultRecordCount": size})
        if "error" in js:
            raise PermissionError(f"query on {layer_url} failed: {js['error']}")
        feats = js.get("features", [])
        rows.extend(f.get("attributes", {}) for f in feats)
        if not feats or not js.get("exceededTransferLimit", len(feats) == size):
            break
        offset += len(feats)
    return pd.DataFrame(rows)


def _pick(cols: Iterable[str], pat: re.Pattern) -> Optional[str]:
    for c in cols:
        if pat.search(c):
            return c
    return None


def layer_to_long(df: pd.DataFrame, ref: str, year: Optional[int], semester: Optional[int] = None,
                  name_col: Optional[str] = None, code_col: Optional[str] = None,
                  prov_col: Optional[str] = None) -> pd.DataFrame:
    """Wide ArcGIS attribute table -> long religion rows. Column roles are guessed
    from names unless given explicitly (print df.columns and pass them if the guess fails)."""
    cols = list(df.columns)
    name_col = name_col or _pick(cols, UNIT_NAME_RE)
    code_col = code_col or _pick(cols, UNIT_CODE_RE)
    prov_col = prov_col or _pick(cols, PROV_CODE_RE)
    if name_col is None and code_col is None:
        raise ValueError(f"could not find a unit name/code column in {cols}")
    rel_cols = [(c, canonical_religion(c)) for c in cols if c not in (name_col, code_col, prov_col)]
    rel_cols = [(c, r) for c, r in rel_cols if r is not None]
    out = []
    for rec in df.to_dict("records"):
        code = str(rec[code_col]).strip() if code_col and pd.notna(rec.get(code_col)) else None
        if code and code.isdigit() and len(code) in (4, 5):
            code = code.zfill(4) if len(code) == 4 else code
        prov = (str(rec[prov_col]).zfill(2) if prov_col and pd.notna(rec.get(prov_col))
                else (code[:2] if code else None))
        name = str(rec[name_col]).strip() if name_col and pd.notna(rec.get(name_col)) else None
        for c, r in rel_cols:
            v = rec.get(c)
            out.append({"source": "arcgis", "province_code": prov, "unit_code": code, "unit_name": name,
                        "year": year, "semester": semester, "religion": r,
                        "count": float(v) if v is not None and pd.notna(v) else None, "ref": ref})
    res = pd.DataFrame(out, columns=LONG_COLUMNS)
    res["level"] = res["unit_name"].map(unit_level)
    res["unit_name_norm"] = res["unit_name"].map(norm_unit_name)
    return res
