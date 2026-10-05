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
    script_hint: Optional[str] = None  # set by detectors that know which script model won


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


def _iou(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> float:
    ax0, ay0 = min(p[0] for p in a), min(p[1] for p in a)
    ax1, ay1 = max(p[0] for p in a), max(p[1] for p in a)
    bx0, by0 = min(p[0] for p in b), min(p[1] for p in b)
    bx1, by1 = max(p[0] for p in b), max(p[1] for p in b)
    iw, ih = max(0.0, min(ax1, bx1) - max(ax0, bx0)), max(0.0, min(ay1, by1) - max(ay0, by0))
    inter = iw * ih
    union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / union if union > 0 else 0.0


class EasyOCRDualDetector:
    """Runs EasyOCR twice, with the simplified (ch_sim) and traditional (ch_tra)
    Chinese models, and keeps the higher-confidence reading per text box.

    Why: on clean renders the ch_sim model reads traditional signs at confidence
    ~0.02 (garbled) while ch_tra reads them at ~0.99, and vice versa ch_tra maps
    simplified text onto wrong traditional characters. Indonesian signage mixes
    both scripts, so one model misses half of it. The winning model is also a
    better script signal than inspecting the output text (ch_tra always emits
    traditional forms)."""

    def __init__(self, gpu: bool = False, iou_match: float = 0.5):
        import easyocr  # type: ignore
        self.sim = easyocr.Reader(["ch_sim", "en"], gpu=gpu, verbose=False)
        self.tra = easyocr.Reader(["ch_tra", "en"], gpu=gpu, verbose=False)
        self.iou_match = iou_match

    @staticmethod
    def _read(reader, path: str, hint: str) -> List[TextBox]:
        return [TextBox(text=str(t), conf=float(c), bbox=[[float(x), float(y)] for x, y in b],
                        script_hint=hint if count_cjk(str(t)) else None)
                for b, t, c in reader.readtext(path)]

    def detect(self, path: str) -> List[TextBox]:
        a, b = self._read(self.sim, path, "simplified"), self._read(self.tra, path, "traditional")
        out, used = [], set()
        for x in a:
            best, best_iou = None, 0.0
            for j, y in enumerate(b):
                if j in used:
                    continue
                v = _iou(x.bbox, y.bbox)
                if v > best_iou:
                    best, best_iou = j, v
            if best is not None and best_iou >= self.iou_match:
                used.add(best)
                y = b[best]
                out.append(y if y.conf > x.conf else x)
            else:
                out.append(x)
        out.extend(y for j, y in enumerate(b) if j not in used)
        return out


class PaddleOCRDetector:
    """pip install paddlepaddle paddleocr. lang='ch' handles mixed Chinese/Latin.
    Supports the 3.x API (predict -> rec_texts/rec_scores/rec_polys) and the 2.x
    API (ocr -> [[bbox, (text, conf)], ...]). Model weights are downloaded on first
    use from Baidu/HuggingFace hosts; NOT verified in the cloud container (blocked)."""

    def __init__(self, lang: str = "ch", use_gpu: bool = False):
        from paddleocr import PaddleOCR  # type: ignore
        try:
            self.ocr = PaddleOCR(lang=lang, use_doc_orientation_classify=False, use_doc_unwarping=False,
                                 use_textline_orientation=False)
            self.api = 3
        except TypeError:  # 2.x signature
            self.ocr = PaddleOCR(lang=lang, use_angle_cls=True, use_gpu=use_gpu, show_log=False)
            self.api = 2

    def detect(self, path: str) -> List[TextBox]:
        out = []
        if self.api == 3:
            for r in self.ocr.predict(path):
                d = r.json["res"] if hasattr(r, "json") else r
                polys = d.get("rec_polys") if d.get("rec_polys") is not None else d.get("dt_polys")
                for text, conf, poly in zip(d.get("rec_texts", []), d.get("rec_scores", []), polys or []):
                    out.append(TextBox(text=str(text), conf=float(conf), bbox=[[float(x), float(y)] for x, y in poly]))
            return out
        res = self.ocr.ocr(path, cls=True)
        for line in (res[0] or []) if res else []:
            bbox, (text, conf) = line
            out.append(TextBox(text=str(text), conf=float(conf), bbox=[[float(x), float(y)] for x, y in bbox]))
        return out


def make_detector(name: str, gpu: bool = False) -> Detector:
    if name == "easyocr":
        return EasyOCRDualDetector(gpu=gpu)
    if name == "easyocr-sim":
        return EasyOCRDetector(langs=("ch_sim", "en"), gpu=gpu)
    if name == "easyocr-tra":
        return EasyOCRDetector(langs=("ch_tra", "en"), gpu=gpu)
    if name == "paddleocr":
        return PaddleOCRDetector(use_gpu=gpu)
    raise ValueError(f"unknown detector '{name}' (easyocr | easyocr-sim | easyocr-tra | paddleocr)")


def count_cjk(text: str) -> int:
    return len(CJK_RE.findall(text or ""))


def script_of(text: str, hint: Optional[str] = None) -> str:
    """'simplified' | 'traditional' | 'both' | 'mixed' | 'none' | 'unknown'.
    A detector hint (which script model won) takes precedence; otherwise
    hanzidentifier when installed; otherwise 'unknown' for any CJK text."""
    if count_cjk(text) == 0:
        return "none"
    if hint:
        return hint
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
    scripts = [script_of(b.text, b.script_hint) for b in cjk]
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
                             "script": script_of(b.text, b.script_hint), "area_px": round(polygon_area(b.bbox), 1),
                             "bbox": ";".join(f"{x:.0f},{y:.0f}" for x, y in b.bbox)})
        summ = summarise_boxes(boxes, min_conf)
        img_rows.append({"path": rec.path, "pano_id": rec.pano_id, "heading": rec.heading,
                         "img_area_px": w * h, **summ, "ocr_status": status})
    new_boxes = pd.DataFrame(box_rows, columns=BOX_COLUMNS)
    new_imgs = pd.DataFrame(img_rows, columns=IMAGE_COLUMNS)
    if existing_images is not None and len(existing_images):
        new_imgs = pd.concat([existing_images, new_imgs], ignore_index=True)
    return new_boxes, new_imgs
