"""Stage 4: detect text in each image and flag CJK (Chinese) characters.

The detector is pluggable so the rest of the pipeline can be tested without a
GPU or model download. Two real backends are provided (EasyOCR, PaddleOCR); both
are lazily imported.

Outputs
  ocr_boxes.csv   one row per detected text box
  ocr_images.csv  one row per image (including images with no text), so that
                  denominators in the aggregation stage are correct
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Protocol, Sequence

import pandas as pd
from PIL import Image

# CJK Unified Ideographs + Extension A. Hangul and kana are deliberately excluded.
CJK_RE = re.compile(r"[一-鿿㐀-䶿]")

BOX_COLUMNS = ["path", "pano_id", "heading", "box_idx", "text", "conf", "n_chars", "n_cjk",
               "is_cjk", "script", "area_px", "bbox"]
IMAGE_COLUMNS = ["path", "pano_id", "heading", "img_area_px", "n_boxes", "n_cjk_boxes",
                 "cjk_area_px", "text_area_px", "n_simplified", "n_traditional", "ocr_status"]


@dataclass
class TextBox:
    text: str
    conf: float
    bbox: List[List[float]]  # 4 corner points [[x, y], ...]


class Detector(Protocol):
    def detect(self, path: str) -> List[TextBox]: ...


class EasyOCRDetector:
    """pip install easyocr. Chinese (simplified) + English scene text."""

    def __init__(self, langs: Sequence[str] = ("ch_sim", "en"), gpu: bool = False):
        import easyocr  # type: ignore
        self.reader = easyocr.Reader(list(langs), gpu=gpu)

    def detect(self, path: str) -> List[TextBox]:
        out = []
        for bbox, text, conf in self.reader.readtext(path):
            out.append(TextBox(text=str(text), conf=float(conf), bbox=[[float(x), float(y)] for x, y in bbox]))
        return out


class PaddleOCRDetector:
    """pip install paddlepaddle paddleocr. lang='ch' handles mixed Chinese/Latin."""

    def __init__(self, lang: str = "ch", use_gpu: bool = False):
        from paddleocr import PaddleOCR  # type: ignore
        self.ocr = PaddleOCR(lang=lang, use_angle_cls=True, use_gpu=use_gpu, show_log=False)

    def detect(self, path: str) -> List[TextBox]:
        res = self.ocr.ocr(path, cls=True)
        out = []
        for line in (res[0] or []) if res else []:
            bbox, (text, conf) = line
            out.append(TextBox(text=str(text), conf=float(conf), bbox=[[float(x), float(y)] for x, y in bbox]))
        return out


def make_detector(name: str, gpu: bool = False) -> Detector:
    if name == "easyocr":
        return EasyOCRDetector(gpu=gpu)
    if name == "paddleocr":
        return PaddleOCRDetector(use_gpu=gpu)
    raise ValueError(f"unknown detector '{name}' (easyocr | paddleocr)")


def count_cjk(text: str) -> int:
    return len(CJK_RE.findall(text or ""))


def script_of(text: str) -> str:
    """'simplified' | 'traditional' | 'both' | 'mixed' | 'none' | 'unknown'.
    Uses hanzidentifier when installed; otherwise 'unknown' for any CJK text."""
    if count_cjk(text) == 0:
        return "none"
    try:
        import hanzidentifier as hz  # type: ignore
    except ImportError:
        return "unknown"
    code = hz.identify(text)
    return {hz.SIMPLIFIED: "simplified", hz.TRADITIONAL: "traditional", hz.BOTH: "both",
            hz.MIXED: "mixed"}.get(code, "unknown")


def polygon_area(bbox: Sequence[Sequence[float]]) -> float:
    pts = list(bbox)
    n = len(pts)
    s = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def summarise_boxes(boxes: List[TextBox], min_conf: float) -> dict:
    kept = [b for b in boxes if b.conf >= min_conf]
    cjk = [b for b in kept if count_cjk(b.text) > 0]
    scripts = [script_of(b.text) for b in cjk]
    return {"n_boxes": len(kept), "n_cjk_boxes": len(cjk),
            "cjk_area_px": sum(polygon_area(b.bbox) for b in cjk),
            "text_area_px": sum(polygon_area(b.bbox) for b in kept),
            "n_simplified": sum(s == "simplified" for s in scripts),
            "n_traditional": sum(s == "traditional" for s in scripts)}


def run_ocr(images: pd.DataFrame, detector: Detector, min_conf: float = 0.3,
            existing_images: Optional[pd.DataFrame] = None, limit: Optional[int] = None):
    """Run the detector over images.csv rows with status OK. Resumable: rows already
    present in `existing_images` are skipped."""
    done = set(existing_images["path"]) if existing_images is not None and len(existing_images) else set()
    todo = images[(images["status"] == "OK") & (~images["path"].isin(done))]
    if limit is not None:
        todo = todo.head(limit)
    box_rows, img_rows = [], []
    for rec in todo.itertuples(index=False):
        p = Path(rec.path)
        try:
            with Image.open(p) as im:
                w, h = im.size
            boxes = detector.detect(str(p))
            status = "OK"
        except Exception as e:  # noqa: BLE001 - record and continue
            w = h = 0
            boxes, status = [], f"ERROR:{type(e).__name__}"
        for i, b in enumerate(boxes):
            if b.conf < min_conf:
                continue
            n_cjk = count_cjk(b.text)
            box_rows.append({"path": rec.path, "pano_id": rec.pano_id, "heading": rec.heading,
                             "box_idx": i, "text": b.text, "conf": round(b.conf, 4),
                             "n_chars": len(b.text), "n_cjk": n_cjk, "is_cjk": n_cjk > 0,
                             "script": script_of(b.text), "area_px": round(polygon_area(b.bbox), 1),
                             "bbox": ";".join(f"{x:.0f},{y:.0f}" for x, y in b.bbox)})
        summ = summarise_boxes(boxes, min_conf)
        img_rows.append({"path": rec.path, "pano_id": rec.pano_id, "heading": rec.heading,
                         "img_area_px": w * h, **summ, "ocr_status": status})
    new_boxes = pd.DataFrame(box_rows, columns=BOX_COLUMNS)
    new_imgs = pd.DataFrame(img_rows, columns=IMAGE_COLUMNS)
    if existing_images is not None and len(existing_images):
        new_imgs = pd.concat([existing_images, new_imgs], ignore_index=True)
    return new_boxes, new_imgs
