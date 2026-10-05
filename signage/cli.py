"""Command-line entry point: `python -m signage.cli <stage> [options]` or `signage <stage>`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from . import aggregate, classify, discover, fetch, ocr, sample, validate


def _read_if_exists(path: Path):
    return pd.read_csv(path) if path.exists() else None


def cmd_sample(a):
    polys = sample.load_polygons(a.polygons, a.id_field)
    df = sample.sample_points(polys, a.roads, a.spacing, a.max_per_unit, a.seed)
    df.to_csv(a.out, index=False)
    print(f"{len(df)} points in {df['unit_id'].nunique()} units -> {a.out}")


def cmd_discover(a):
    key = discover.get_api_key()
    points = pd.read_csv(a.points)
    existing = _read_if_exists(Path(a.out)) if a.resume else None
    if a.backend == "metadata":
        df = discover.discover_metadata(points, key, a.radius, existing=existing)
    else:
        df = discover.discover_jsapi(points, key, a.radius, existing=existing)
    df.to_csv(a.out, index=False)
    ok = df[df["status"] == "OK"]
    print(f"{len(df)} rows, {ok['pano_id'].nunique()} unique panos, "
          f"{ok['point_id'].nunique()}/{points['point_id'].nunique()} points with imagery -> {a.out}")
    if len(ok):
        print(ok["date"].astype(str).str.slice(0, 4).value_counts().sort_index().to_string())


def cmd_cost(a):
    panos = discover.dedupe_panos(pd.read_csv(a.panos))
    print(json.dumps(fetch.estimate_cost(len(panos), len(a.headings), a.usd_per_1000), indent=2))


def cmd_fetch(a):
    key = discover.get_api_key()
    panos = discover.dedupe_panos(pd.read_csv(a.panos))
    existing = _read_if_exists(Path(a.out)) if a.resume else None
    df = fetch.fetch_images(panos, a.images_dir, key, heading_offsets=a.headings, size=a.size,
                            fov=a.fov, pitch=a.pitch, max_images=a.max_images, existing=existing)
    df.to_csv(a.out, index=False)
    print(df["status"].value_counts().to_string())


def cmd_ocr(a):
    images = pd.read_csv(a.images)
    existing = _read_if_exists(Path(a.out_images)) if a.resume else None
    det = ocr.make_detector(a.detector, gpu=a.gpu)
    boxes, imgs = ocr.run_ocr(images, det, min_conf=a.min_conf, existing_images=existing, limit=a.limit)
    if a.resume and Path(a.out_boxes).exists():
        boxes = pd.concat([pd.read_csv(a.out_boxes), boxes], ignore_index=True)
    boxes.to_csv(a.out_boxes, index=False)
    imgs.to_csv(a.out_images, index=False)
    print(f"{len(imgs)} images, {int((imgs['n_cjk_boxes'] > 0).sum())} with CJK text, "
          f"{len(boxes)} boxes -> {a.out_boxes}")


def cmd_classify(a):
    boxes = classify.classify_boxes(pd.read_csv(a.ocr_boxes))
    imgs = classify.image_type_counts(boxes, pd.read_csv(a.ocr_images))
    boxes.to_csv(a.out_boxes, index=False)
    imgs.to_csv(a.out_images, index=False)
    print(boxes["sign_type"].value_counts(dropna=True).to_string())
    print(f"-> {a.out_boxes}, {a.out_images} (pass the latter to aggregate --ocr-images)")


def cmd_aggregate(a):
    panos = pd.read_csv(a.panos)
    imgs = pd.read_csv(a.ocr_images)
    pano = aggregate.pano_level(imgs, panos)
    py = aggregate.point_year_panel(pano)
    uy = aggregate.unit_year_panel(py)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pano.to_csv(out / "panel_pano.csv", index=False)
    py.to_csv(out / "panel_point_year.csv", index=False)
    uy.to_csv(out / "panel_unit_year.csv", index=False)
    print(uy.to_string(index=False))


def cmd_validate_export(a):
    labels = validate.export_sample(pd.read_csv(a.ocr_images), pd.read_csv(a.ocr_boxes), a.out_dir,
                                    a.n_pos, a.n_neg, a.seed)
    print(f"{len(labels)} images for hand coding -> {Path(a.out_dir) / 'labels_template.csv'}")


def cmd_validate_score(a):
    print(json.dumps(validate.score(pd.read_csv(a.labels)), indent=2))


def build_parser():
    p = argparse.ArgumentParser(prog="signage", description=__doc__)
    sp = p.add_subparsers(dest="cmd", required=True)

    s = sp.add_parser("sample", help="sample road points inside admin polygons")
    s.add_argument("--polygons", required=True, help="GeoJSON of admin units")
    s.add_argument("--id-field", default="unit_id")
    s.add_argument("--roads", default="osm", help="roads GeoJSON path, or 'osm' (needs osmnx)")
    s.add_argument("--spacing", type=float, default=50.0, help="metres between candidate points")
    s.add_argument("--max-per-unit", type=int, default=300)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--out", default="data/points.csv")
    s.set_defaults(func=cmd_sample)

    d = sp.add_parser("discover", help="find panoramas near each point")
    d.add_argument("--points", default="data/points.csv")
    d.add_argument("--backend", choices=["metadata", "jsapi"], default="jsapi")
    d.add_argument("--radius", type=int, default=30, help="search radius in metres")
    d.add_argument("--resume", action="store_true")
    d.add_argument("--out", default="data/panos.csv")
    d.set_defaults(func=cmd_discover)

    c = sp.add_parser("cost", help="estimate the image bill before fetching")
    c.add_argument("--panos", default="data/panos.csv")
    c.add_argument("--headings", type=int, nargs="+", default=[-90, 90])
    c.add_argument("--usd-per-1000", type=float, default=7.0)
    c.set_defaults(func=cmd_cost)

    f = sp.add_parser("fetch", help="download images")
    f.add_argument("--panos", default="data/panos.csv")
    f.add_argument("--images-dir", default="data/images")
    f.add_argument("--headings", type=int, nargs="+", default=[-90, 90], help="offsets from road bearing")
    f.add_argument("--size", default="640x640")
    f.add_argument("--fov", type=int, default=90)
    f.add_argument("--pitch", type=int, default=5)
    f.add_argument("--max-images", type=int, default=None, help="hard cap for a pilot run")
    f.add_argument("--resume", action="store_true")
    f.add_argument("--out", default="data/images.csv")
    f.set_defaults(func=cmd_fetch)

    o = sp.add_parser("ocr", help="detect text and flag CJK")
    o.add_argument("--images", default="data/images.csv")
    o.add_argument("--detector", choices=["easyocr", "paddleocr"], default="easyocr")
    o.add_argument("--gpu", action="store_true")
    o.add_argument("--min-conf", type=float, default=0.3)
    o.add_argument("--limit", type=int, default=None)
    o.add_argument("--resume", action="store_true")
    o.add_argument("--out-boxes", default="data/ocr_boxes.csv")
    o.add_argument("--out-images", default="data/ocr_images.csv")
    o.set_defaults(func=cmd_ocr)

    k = sp.add_parser("classify", help="split CJK boxes into local / mainland / ambiguous")
    k.add_argument("--ocr-boxes", default="data/ocr_boxes.csv")
    k.add_argument("--ocr-images", default="data/ocr_images.csv")
    k.add_argument("--out-boxes", default="data/ocr_boxes_classified.csv")
    k.add_argument("--out-images", default="data/ocr_images_classified.csv")
    k.set_defaults(func=cmd_classify)

    g = sp.add_parser("aggregate", help="build pano / point-year / unit-year panels")
    g.add_argument("--panos", default="data/panos.csv")
    g.add_argument("--ocr-images", default="data/ocr_images.csv")
    g.add_argument("--out-dir", default="data")
    g.set_defaults(func=cmd_aggregate)

    ve = sp.add_parser("validate-export", help="draw a hand-coding sample")
    ve.add_argument("--ocr-images", default="data/ocr_images.csv")
    ve.add_argument("--ocr-boxes", default="data/ocr_boxes.csv")
    ve.add_argument("--out-dir", default="data/validation")
    ve.add_argument("--n-pos", type=int, default=100)
    ve.add_argument("--n-neg", type=int, default=100)
    ve.add_argument("--seed", type=int, default=0)
    ve.set_defaults(func=cmd_validate_export)

    vs = sp.add_parser("validate-score", help="precision/recall from the filled labels file")
    vs.add_argument("--labels", default="data/validation/labels_template.csv")
    vs.set_defaults(func=cmd_validate_score)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    sys.exit(main())
