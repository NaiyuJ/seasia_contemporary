#!/usr/bin/env python3
"""Real-OCR smoke test on the synthetic storefront fixtures.

    python scripts/ocr_smoke.py [--detector easyocr|paddleocr]

Runs ocr -> classify -> aggregate on tests/fixtures/*.png through the real
detector and prints what it read. Expected: local_trad and local_assoc -> local,
mainland_simp -> mainland, no_cjk -> no CJK boxes. Use it after installing an
OCR backend to confirm the wrapper works before paying for Street View images.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from signage import aggregate, classify, ocr  # noqa: E402

FIX = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
EXPECTED = {"local_trad": "local", "local_assoc": "local", "mainland_simp": "mainland", "no_cjk": None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--detector", default="easyocr", choices=["easyocr", "paddleocr"])
    a = ap.parse_args()
    det = ocr.make_detector(a.detector)
    images = pd.DataFrame([{"pano_id": p.stem, "heading": 0, "path": str(p), "status": "OK", "bytes": p.stat().st_size}
                           for p in sorted(FIX.glob("*.png"))])
    boxes, imgs = ocr.run_ocr(images, det, min_conf=0.3)
    cl = classify.classify_boxes(boxes)
    imgs = classify.image_type_counts(cl, imgs)
    pd.set_option("display.width", 200)
    print(cl[["pano_id", "text", "conf", "is_cjk", "script", "sign_type", "sign_reasons"]].to_string(index=False))
    print()
    ok = True
    for rec in imgs.itertuples(index=False):
        got = None
        if rec.n_cjk_boxes:
            row = cl[(cl["pano_id"] == rec.pano_id) & cl["sign_type"].notna()]
            got = row["sign_type"].mode().iloc[0] if len(row) else "none"
        exp = EXPECTED.get(rec.pano_id)
        flag = "ok" if got == exp else "MISMATCH"
        ok &= got == exp
        print(f"[{flag:8}] {rec.pano_id:15} cjk_boxes={rec.n_cjk_boxes} local={rec.n_local_boxes} "
              f"mainland={rec.n_mainland_boxes} ambiguous={rec.n_ambiguous_boxes} -> {got} (expected {exp})")
    panos = pd.DataFrame([{"point_id": f"p_{i}", "unit_id": "fixture", "bearing": 0, "pano_id": pid, "date": "2024-01",
                           "is_current": True, "pano_lat": 0, "pano_lon": 0, "status": "OK"}
                          for i, pid in enumerate(images["pano_id"])])
    uy = aggregate.unit_year_panel(aggregate.point_year_panel(aggregate.pano_level(imgs, panos)))
    print("\nunit-year panel row:\n" + uy.T.to_string(header=False))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
