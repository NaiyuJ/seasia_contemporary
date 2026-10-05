"""Stage 6: hand-coding sample and precision/recall for the CJK flag.

OCR on street scenes makes two kinds of error you must measure before using the
panel: missed signs (recall) and Latin or decorative text read as CJK (precision).
`export_sample` draws a stratified random sample of images, draws the detected
boxes on copies (red = CJK, blue = other), and writes a labels template for a
human coder. `score` compares the filled-in template with the OCR flag.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

LABEL_COLUMNS = ["path", "annotated_path", "ocr_any_cjk", "ocr_n_cjk_boxes",
                 "human_any_cjk", "human_n_cjk_signs", "human_sign_type", "human_notes"]
# human_sign_type: local | mainland | ambiguous | none (see signage.classify)


def _parse_bbox(s: str):
    return [tuple(float(v) for v in pt.split(",")) for pt in s.split(";")]


def draw_boxes(src: Path, dst: Path, boxes: pd.DataFrame) -> None:
    with Image.open(src) as im:
        im = im.convert("RGB")
        d = ImageDraw.Draw(im)
        for rec in boxes.itertuples(index=False):
            pts = _parse_bbox(rec.bbox)
            colour = (255, 0, 0) if rec.is_cjk else (0, 90, 255)
            d.polygon(pts, outline=colour, width=3)
            d.text((pts[0][0], max(pts[0][1] - 12, 0)), f"{rec.text[:20]} {rec.conf:.2f}", fill=colour)
        im.save(dst, quality=90)


def export_sample(ocr_images: pd.DataFrame, ocr_boxes: pd.DataFrame, out_dir: str | Path,
                  n_pos: int = 100, n_neg: int = 100, seed: int = 0) -> pd.DataFrame:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    ok = ocr_images[ocr_images["ocr_status"] == "OK"]
    pos = ok[ok["n_cjk_boxes"] > 0]
    neg = ok[ok["n_cjk_boxes"] == 0]
    pick = pd.concat([pos.sample(min(n_pos, len(pos)), random_state=int(rng.integers(1 << 31))),
                      neg.sample(min(n_neg, len(neg)), random_state=int(rng.integers(1 << 31)))])
    pick = pick.sample(frac=1, random_state=int(rng.integers(1 << 31)))  # shuffle so coder is blind
    rows = []
    for rec in pick.itertuples(index=False):
        src = Path(rec.path)
        dst = out_dir / f"{src.stem}_annot.jpg"
        draw_boxes(src, dst, ocr_boxes[ocr_boxes["path"] == rec.path])
        rows.append({"path": rec.path, "annotated_path": str(dst), "ocr_any_cjk": int(rec.n_cjk_boxes > 0),
                     "ocr_n_cjk_boxes": int(rec.n_cjk_boxes), "human_any_cjk": "",
                     "human_n_cjk_signs": "", "human_sign_type": "", "human_notes": ""})
    labels = pd.DataFrame(rows, columns=LABEL_COLUMNS)
    labels.to_csv(out_dir / "labels_template.csv", index=False)
    return labels


def score(labels: pd.DataFrame) -> dict:
    """Precision/recall of ocr_any_cjk against human_any_cjk (rows with a human label)."""
    lab = labels.dropna(subset=["human_any_cjk"])
    lab = lab[lab["human_any_cjk"].astype(str).str.strip() != ""]
    y = lab["human_any_cjk"].astype(int).to_numpy()
    p = lab["ocr_any_cjk"].astype(int).to_numpy()
    tp = int(((p == 1) & (y == 1)).sum())
    fp = int(((p == 1) & (y == 0)).sum())
    fn = int(((p == 0) & (y == 1)).sum())
    tn = int(((p == 0) & (y == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else float("nan")
    recall = tp / (tp + fn) if tp + fn else float("nan")
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else float("nan")
    return {"n": int(len(lab)), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": precision, "recall": recall, "f1": f1,
            "accuracy": (tp + tn) / len(lab) if len(lab) else float("nan")}
