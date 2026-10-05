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
sample ──> discover ──> cost ──> fetch ──> ocr ──> classify ──> aggregate ──> validate
points.csv  panos.csv            images/   ocr_*.csv  *_classified  panel_*.csv   labels
```

| Stage | What it does | Needs |
| --- | --- | --- |
| `sample` | Systematic points every N metres along roads inside each admin polygon, with road bearing | polygons GeoJSON; roads GeoJSON or osmnx |
| `discover` | Nearest panorama per point. `jsapi` backend also returns historical panoramas (the Maps JS API `time` array, undocumented) | `GOOGLE_MAPS_API_KEY`; Playwright + Chromium for `jsapi` |
| `cost` | Estimated bill before fetching | |
| `fetch` | Static API images at bearing ±90° (both sides of the street) | API key; billed per image |
| `ocr` | Scene-text detection, flags boxes containing CJK ideographs, simplified/traditional if `hanzidentifier` is installed | `easyocr` or `paddleocr` |
| `classify` | Splits CJK boxes into **local** (Chinese-Indonesian), **mainland** (PRC) or ambiguous from script, keywords and Latin co-text. Keeps the treatment (Chinese presence) out of the outcome (identity display) | |
| `aggregate` | pano → point-year → unit-year panels, with separate local / mainland indices when `classify` ran | |
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
python -m signage.cli classify
python -m signage.cli aggregate --ocr-images data/ocr_images_classified.csv
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
| `share_points_local`, `share_points_mainland` | same as `share_points_cjk`, split by sign type (after `classify`) |

See `docs/signage_design.md` for identification caveats and `docs/konghucu_data_sources.md`
for the Konghucu registration measure.

## Second module: `konghucu/` — registered religion by kabupaten

Self-collected panel of Dukcapil/BPS religion counts (Islam … Khonghucu) by
kabupaten/kota, for the "switching one's ID-card religion to Confucianism"
identity measure. Three public sources, one long format, one harmonizer.

```bash
export BPS_API_KEY=...                                   # free: https://webapi.bps.go.id
python -m konghucu.cli bps-search                        # catalogue religion tables in all 38 provinces
python -m konghucu.cli bps-fetch                         # download + parse the by-kabupaten ones
python -m konghucu.cli arcgis-discover                   # which GIS Dukcapil layers carry religion fields
python -m konghucu.cli arcgis-fetch --layer-url <url> --ref dkb2023s2 --year 2023 --semester 2
python -m konghucu.cli pdf-extract data/raw/dukcapil/*.pdf --province-code 61
python -m konghucu.cli harmonize --codes data/raw/bps_kabupaten_codes.csv \
       --inputs data/konghucu/bps_long.csv data/konghucu/arcgis_long.csv data/konghucu/pdf_long.csv
```

Output `data/konghucu/religion_panel.csv`: one row per unit × year × semester
(semester 0 = annual source), one column per religion, `konghucu_share`, and
which sources fed the cell. Unmatched unit names are printed so you can fix the
code table. Sources and caveats: `docs/konghucu_data_sources.md`.
