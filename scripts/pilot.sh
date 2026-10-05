#!/usr/bin/env bash
# Local pilot: the three first steps, in order. Run from the repo root.
#   bash scripts/pilot.sh                 # all three
#   bash scripts/pilot.sh konghucu        # one of: konghucu | arcgis | signage
# Needs: GOOGLE_MAPS_API_KEY, BPS_API_KEY (see scripts/preflight.py).
set -euo pipefail
STEP="${1:-all}"
PILOT_UNITS="${PILOT_UNITS:-Kota Singkawang, Indonesia|Kota Administrasi Jakarta Barat, Indonesia}"
MAX_IMAGES="${MAX_IMAGES:-200}"
DETECTOR="${DETECTOR:-easyocr}"

python scripts/preflight.py || { echo "fix the items above first"; exit 1; }
mkdir -p data/konghucu data/foreigners

if [[ "$STEP" == "all" || "$STEP" == "konghucu" ]]; then
  echo "== 1. BPS: religion tables by kabupaten, all provinces"
  python -m konghucu.cli bps-search
  python -m konghucu.cli bps-fetch
  python - <<'PY'
import pandas as pd
d = pd.read_csv("data/konghucu/bps_long.csv", dtype={"province_code": str})
k = d[d["religion"] == "konghucu"]
print("provinces with a by-kabupaten religion table:", k["province_code"].nunique())
print(k.groupby("province_code")["year"].agg(["min", "max", "nunique"]).to_string())
PY
fi

if [[ "$STEP" == "all" || "$STEP" == "arcgis" ]]; then
  echo "== 2. GIS Dukcapil: which layers carry religion fields and are public"
  python -m konghucu.cli arcgis-discover
  echo "open https://gis.dukcapil.kemendagri.go.id/arcgis/rest/services in a browser to compare;"
  echo "then: python -m konghucu.cli arcgis-fetch --layer-url <url> --ref <label> --year <yyyy> --semester <1|2>"
fi

if [[ "$STEP" == "all" || "$STEP" == "signage" ]]; then
  echo "== 3. Street View pilot on: $PILOT_UNITS"
  IFS='|' read -r -a UNITS <<< "$PILOT_UNITS"
  python -m signage.cli sample --units "${UNITS[@]}" --roads osm --spacing 50 --max-per-unit 300
  python -m signage.cli discover --backend jsapi --radius 30
  python -m signage.cli cost
  python -m signage.cli fetch --max-images "$MAX_IMAGES"
  python -m signage.cli ocr --detector "$DETECTOR"
  python -m signage.cli classify
  python -m signage.cli aggregate --ocr-images data/ocr_images_classified.csv
  python -m signage.cli validate-export --n-pos 100 --n-neg 100
  echo "hand-code data/validation/labels_template.csv (human_any_cjk, human_sign_type), then:"
  echo "python -m signage.cli validate-score"
fi
