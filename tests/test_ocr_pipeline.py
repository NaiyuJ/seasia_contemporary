"""End-to-end test of ocr -> aggregate -> validate with a fake detector."""
from pathlib import Path

import pandas as pd
from PIL import Image

from signage import aggregate, ocr, validate
from signage.discover import dedupe_panos


class FakeDetector:
    """Returns boxes keyed on the file name so tests control the outcome."""

    def detect(self, path):
        name = Path(path).stem
        if name.startswith("p1_"):
            return [ocr.TextBox("金龙酒家", 0.9, [[10, 10], [200, 10], [200, 60], [10, 60]]),
                    ocr.TextBox("TOKO MAJU", 0.8, [[10, 80], [150, 80], [150, 120], [10, 120]])]
        if name.startswith("p2_"):
            return [ocr.TextBox("Warung Bu Sri", 0.7, [[0, 0], [100, 0], [100, 30], [0, 30]]),
                    ocr.TextBox("福", 0.2, [[0, 0], [10, 0], [10, 10], [0, 10]])]  # below min_conf
        if name.startswith("p4_"):
            raise RuntimeError("corrupt")
        return []


def _make_images(tmp_path, pano_ids, headings=(0, 180)):
    d = tmp_path / "images"
    d.mkdir()
    rows = []
    for pid in pano_ids:
        for h in headings:
            p = d / f"{pid}_{h:03d}.jpg"
            Image.new("RGB", (64, 48), (120, 120, 120)).save(p)
            rows.append({"pano_id": pid, "heading": h, "path": str(p), "status": "OK", "bytes": 1000})
    rows.append({"pano_id": "p9", "heading": 0, "path": str(d / "p9_000.jpg"), "status": "NO_IMAGE", "bytes": 0})
    return pd.DataFrame(rows)


def _panos():
    return pd.DataFrame([
        # point X in unit A seen in 2015 (p1) and 2021 (p2); point Y in unit B 2021 (p3); p4 corrupt
        dict(point_id="A_0", unit_id="A", query_lat=0, query_lon=0, bearing=90, pano_id="p1", date="2015-06",
             pano_lat=0, pano_lon=0, is_current=False, status="OK"),
        dict(point_id="A_0", unit_id="A", query_lat=0, query_lon=0, bearing=90, pano_id="p2", date="2021-02",
             pano_lat=0, pano_lon=0, is_current=True, status="OK"),
        dict(point_id="A_1", unit_id="A", query_lat=0, query_lon=0, bearing=90, pano_id="p2", date="2021-02",
             pano_lat=0, pano_lon=0, is_current=True, status="OK"),  # duplicate pano from another point
        dict(point_id="B_0", unit_id="B", query_lat=0, query_lon=0, bearing=0, pano_id="p3", date="2021-09",
             pano_lat=0, pano_lon=0, is_current=True, status="OK"),
        dict(point_id="B_1", unit_id="B", query_lat=0, query_lon=0, bearing=0, pano_id="p4", date="2019-01",
             pano_lat=0, pano_lon=0, is_current=True, status="OK"),
        dict(point_id="B_2", unit_id="B", query_lat=0, query_lon=0, bearing=0, pano_id=None, date=None,
             pano_lat=None, pano_lon=None, is_current=None, status="ZERO_RESULTS"),
    ])


def test_cjk_helpers():
    assert ocr.count_cjk("金龙酒家 Restaurant") == 4
    assert ocr.count_cjk("TOKO MAJU") == 0
    assert ocr.count_cjk("한국어") == 0          # Hangul is not CJK ideographs
    assert ocr.script_of("TOKO") == "none"
    assert ocr.polygon_area([[0, 0], [10, 0], [10, 5], [0, 5]]) == 50


def test_dedupe_panos():
    d = dedupe_panos(_panos())
    assert list(d["pano_id"]) == ["p1", "p2", "p3", "p4"]
    assert d.loc[d["pano_id"] == "p2", "point_id"].item() == "A_0"


def test_run_ocr_aggregate_validate(tmp_path):
    images = _make_images(tmp_path, ["p1", "p2", "p3", "p4"])
    boxes, imgs = ocr.run_ocr(images, FakeDetector(), min_conf=0.3)

    assert len(imgs) == 8                      # NO_IMAGE row skipped
    assert set(boxes["path"].map(lambda p: Path(p).stem[:2])) == {"p1", "p2"}
    p1 = imgs[imgs["pano_id"] == "p1"].iloc[0]
    assert p1["n_boxes"] == 2 and p1["n_cjk_boxes"] == 1 and p1["cjk_area_px"] == 190 * 50
    p2 = imgs[imgs["pano_id"] == "p2"].iloc[0]
    assert p2["n_boxes"] == 1 and p2["n_cjk_boxes"] == 0  # low-conf 福 dropped
    assert imgs[imgs["pano_id"] == "p4"]["ocr_status"].str.startswith("ERROR").all()

    # resume: nothing new to do when everything is already in existing_images
    b2, i2 = ocr.run_ocr(images, FakeDetector(), existing_images=imgs)
    assert len(b2) == 0 and len(i2) == len(imgs)

    pano = aggregate.pano_level(imgs, _panos())
    assert set(pano["pano_id"]) == {"p1", "p2", "p3"}  # p4 errored out
    assert pano.set_index("pano_id").loc["p1", "any_cjk"] == 1
    assert pano.set_index("pano_id").loc["p1", "n_cjk_boxes"] == 2  # both headings
    assert pano.set_index("pano_id").loc["p1", "cjk_box_share"] == 0.5
    assert pano.set_index("pano_id").loc["p2", "point_id"] == "A_0"

    py = aggregate.point_year_panel(pano)
    a0 = py[py["point_id"] == "A_0"].set_index("year")
    assert list(a0.index) == ["2015", "2021"]
    assert a0.loc["2015", "any_cjk"] == 1 and a0.loc["2021", "any_cjk"] == 0
    assert (a0["n_years_observed"] == 2).all()

    uy = aggregate.unit_year_panel(py).set_index(["unit_id", "year"])
    assert uy.loc[("A", "2015"), "share_points_cjk"] == 1.0
    assert uy.loc[("A", "2021"), "share_points_cjk"] == 0.0
    assert uy.loc[("B", "2021"), "share_points_cjk"] == 0.0
    assert uy.loc[("A", "2015"), "n_points_multi_year"] == 1

    labels = validate.export_sample(imgs, boxes, tmp_path / "val", n_pos=5, n_neg=5, seed=0)
    assert len(labels) == 2 + 4                 # 2 positives (p1) + 4 negatives (p2, p3); p4 errored
    assert all(Path(p).exists() for p in labels["annotated_path"])
    # hand-code: say the human agrees on positives and finds one missed sign
    labels["human_any_cjk"] = labels["ocr_any_cjk"]
    labels.loc[labels[labels["ocr_any_cjk"] == 0].index[0], "human_any_cjk"] = 1
    s = validate.score(labels)
    assert s["tp"] == 2 and s["fn"] == 1 and s["fp"] == 0
    assert s["precision"] == 1.0 and abs(s["recall"] - 2 / 3) < 1e-9
