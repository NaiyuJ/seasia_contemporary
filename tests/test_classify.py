import pandas as pd

from signage import aggregate, classify


def test_classify_box_rules():
    t, s, why = classify.classify_box("金龍酒家", "traditional", ["Bakmi Jaya", "Jl. Pecinan"])
    assert t == "local" and s >= 3 and "traditional" in why and "loanword" in why
    t, s, why = classify.classify_box("川菜馆", "simplified", ["Chuan Cai Guan"])
    assert t == "mainland" and "kw_mainland" in why and "pinyin_only" in why
    t, s, why = classify.classify_box("福", "simplified", ["TOKO MAJU"])
    assert t == "ambiguous"                      # simplified is a weak signal, Indonesian co-text cancels it
    t, s, why = classify.classify_box("福", "unknown", [])
    assert t == "ambiguous" and why == ""
    t, s, why = classify.classify_box("印尼中华总商会", "simplified", [])
    assert t == "local"                          # local keywords beat simplified script


def test_classify_boxes_and_counts():
    boxes = pd.DataFrame([
        {"path": "a.jpg", "pano_id": "p", "heading": 0, "text": "金龍酒家", "is_cjk": True, "script": "traditional"},
        {"path": "a.jpg", "pano_id": "p", "heading": 0, "text": "RUMAH MAKAN", "is_cjk": False, "script": "none"},
        {"path": "b.jpg", "pano_id": "p", "heading": 180, "text": "东北饺子", "is_cjk": True, "script": "simplified"},
        {"path": "b.jpg", "pano_id": "p", "heading": 180, "text": "Dongbei Jiaozi", "is_cjk": False, "script": "none"},
        {"path": "c.jpg", "pano_id": "q", "heading": 0, "text": "Warung", "is_cjk": False, "script": "none"},
    ])
    cl = classify.classify_boxes(boxes)
    assert cl.loc[0, "sign_type"] == "local" and cl.loc[2, "sign_type"] == "mainland"
    assert cl["sign_type"].isna().sum() == 3     # Latin boxes untouched

    imgs = pd.DataFrame([{"path": p, "pano_id": pid, "heading": h, "img_area_px": 100, "n_boxes": 2,
                          "n_cjk_boxes": c, "cjk_area_px": 0, "text_area_px": 0, "n_simplified": 0,
                          "n_traditional": 0, "ocr_status": "OK"}
                         for p, pid, h, c in [("a.jpg", "p", 0, 1), ("b.jpg", "p", 180, 1), ("c.jpg", "q", 0, 0)]])
    merged = classify.image_type_counts(cl, imgs)
    assert list(merged.set_index("path").loc["a.jpg", ["n_local_boxes", "n_mainland_boxes"]]) == [1, 0]
    assert list(merged.set_index("path").loc["c.jpg", ["n_local_boxes", "n_mainland_boxes"]]) == [0, 0]

    panos = pd.DataFrame([
        dict(point_id="A_0", unit_id="A", bearing=0, pano_id="p", date="2019-01", is_current=True, pano_lat=0, pano_lon=0, status="OK"),
        dict(point_id="A_1", unit_id="A", bearing=0, pano_id="q", date="2019-03", is_current=True, pano_lat=0, pano_lon=0, status="OK"),
    ])
    pano = aggregate.pano_level(merged, panos).set_index("pano_id")
    assert pano.loc["p", "n_local_boxes"] == 1 and pano.loc["p", "n_mainland_boxes"] == 1
    assert pano.loc["p", "any_local"] == 1 and pano.loc["q", "any_mainland"] == 0
    uy = aggregate.unit_year_panel(aggregate.point_year_panel(pano.reset_index()))
    assert uy.loc[0, "share_points_local"] == 0.5 and uy.loc[0, "share_points_mainland"] == 0.5


def test_keywords_match_across_scripts():
    t, _, why = classify.classify_box("東北餃子館", "traditional", ["Dongbei Jiaozi"])
    assert t == "mainland" and "kw_mainland" in why   # traditional reading of a mainland sign still matches
