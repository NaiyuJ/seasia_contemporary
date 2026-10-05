# seasia_contemporary

Empirical project on Chinese investment and Chinese-Indonesian identity.
First measurement module: **`signage/`**, a pipeline that turns Google Street View
imagery into a panel of "Chinese characters visible on storefront signs" by
administrative unit and year.

## Why this measure

Public use of Chinese script was banned in Indonesia from 1966 until 2000.
A shop owner putting Chinese characters on a sign today is a costly, public,
behavioral act of identity display that no survey question captures. Street
View has historical imagery for the same spot, so the same street can be
compared across years (within-location variation).

## Pipeline

```
sample ──> discover ──> cost ──> fetch ──> ocr ──> aggregate ──> validate
points.csv  panos.csv            images/   ocr_*.csv  panel_*.csv   labels
```

| Stage | What it does | Needs |
| --- | --- | --- |
| `sample` | Systematic points every N metres along roads inside each admin polygon, with road bearing | polygons GeoJSON; roads GeoJSON or osmnx |
| `discover` | Nearest panorama per point. `jsapi` backend also returns historical panoramas (the Maps JS API `time` array, undocumented) | `GOOGLE_MAPS_API_KEY`; Playwright + Chromium for `jsapi` |
| `cost` | Estimated bill before fetching | |
| `fetch` | Static API images at bearing ±90° (both sides of the street) | API key; billed per image |
| `ocr` | Scene-text detection, flags boxes containing CJK ideographs, simplified/traditional if `hanzidentifier` is installed | `easyocr` or `paddleocr` |
| `aggregate` | pano → point-year → unit-year panels | |
| `validate-export` / `validate-score` | Stratified hand-coding sample with boxes drawn on; precision/recall of the CJK flag | |

## Setup

```bash
pip install -r requirements.txt
pip install easyocr                 # or: pip install paddlepaddle paddleocr
pip install playwright && playwright install chromium   # for historical imagery
pip install osmnx hanzidentifier    # optional
export GOOGLE_MAPS_API_KEY=...      # never commit it; keep it in the environment
```

The key needs the **Street View Static API** and, for `--backend jsapi`, the
**Maps JavaScript API**. The JS page is loaded from `file://`, so restrict the
key by API, not by HTTP referrer.

## Run (pilot on two kabupaten)

```bash
python -m signage.cli sample   --polygons data/units.geojson --id-field kabupaten_code \
                               --roads osm --spacing 50 --max-per-unit 300
python -m signage.cli discover --backend jsapi --radius 30
python -m signage.cli cost
python -m signage.cli fetch    --max-images 200          # pilot first
python -m signage.cli ocr      --detector easyocr --limit 200
python -m signage.cli aggregate
python -m signage.cli validate-export --n-pos 100 --n-neg 100
# hand-code data/validation/labels_template.csv, then:
python -m signage.cli validate-score
```

Every stage is resumable with `--resume`; outputs live under `data/`, which is
git-ignored. `tests/` runs without a key, a browser or an OCR model:

```bash
python -m pytest -q
```

## Output variables (`data/panel_unit_year.csv`)

| Column | Meaning |
| --- | --- |
| `n_points`, `n_panos` | coverage; watch for thin cells |
| `share_points_cjk` | share of sampled street points with any Chinese text visible |
| `mean_cjk_boxes` | mean number of Chinese text boxes per point |
| `mean_cjk_box_share` | Chinese boxes / all text boxes (Chinese share of signage) |
| `mean_cjk_area_share` | pixel area of Chinese text / image area |
| `n_simplified`, `n_traditional` | script counts (mainland vs Taiwan/HK convention) |
| `n_points_multi_year` | points observed in more than one year (usable for FE designs) |

See `docs/signage_design.md` for identification caveats and `docs/konghucu_data_sources.md`
for the Konghucu registration measure.
