"""Stage 5: pano -> point-year -> unit-year panels.

Measures (all defined at the panorama level first):
  any_cjk         1 if any text box with CJK characters was detected on either side
  n_cjk_boxes     number of CJK text boxes
  cjk_box_share   n_cjk_boxes / n_boxes            (share of signs that are Chinese)
  cjk_area_share  cjk_area_px / img_area_px        (how much of the view is Chinese text)
  n_simplified, n_traditional                      (script, if hanzidentifier installed)

point_year panel: one row per sample point and imagery year, built from every pano
that point found. Points seen in several years give within-location variation,
which is what a fixed-effects design needs.

unit_year panel: averages over points, plus counts so you can see where the
Street View coverage is thin.
"""
from __future__ import annotations

import pandas as pd


def pano_level(ocr_images: pd.DataFrame, panos: pd.DataFrame) -> pd.DataFrame:
    ok = ocr_images[ocr_images["ocr_status"] == "OK"]
    g = ok.groupby("pano_id").agg(n_images=("path", "size"), n_boxes=("n_boxes", "sum"),
                                  n_cjk_boxes=("n_cjk_boxes", "sum"), cjk_area_px=("cjk_area_px", "sum"),
                                  img_area_px=("img_area_px", "sum"),
                                  n_simplified=("n_simplified", "sum"),
                                  n_traditional=("n_traditional", "sum")).reset_index()
    g["any_cjk"] = (g["n_cjk_boxes"] > 0).astype(int)
    g["cjk_box_share"] = (g["n_cjk_boxes"] / g["n_boxes"]).where(g["n_boxes"] > 0)
    g["cjk_area_share"] = (g["cjk_area_px"] / g["img_area_px"]).where(g["img_area_px"] > 0)
    meta = panos[panos["status"] == "OK"][["pano_id", "point_id", "unit_id", "date", "is_current",
                                             "pano_lat", "pano_lon"]].drop_duplicates("pano_id")
    out = meta.merge(g, on="pano_id", how="inner")
    out["year"] = out["date"].astype(str).str.slice(0, 4)
    return out


def point_year_panel(pano: pd.DataFrame) -> pd.DataFrame:
    g = pano.groupby(["unit_id", "point_id", "year"]).agg(
        n_panos=("pano_id", "size"), any_cjk=("any_cjk", "max"), n_cjk_boxes=("n_cjk_boxes", "sum"),
        n_boxes=("n_boxes", "sum"), cjk_area_px=("cjk_area_px", "sum"), img_area_px=("img_area_px", "sum"),
        n_simplified=("n_simplified", "sum"), n_traditional=("n_traditional", "sum")).reset_index()
    g["cjk_box_share"] = (g["n_cjk_boxes"] / g["n_boxes"]).where(g["n_boxes"] > 0)
    g["cjk_area_share"] = (g["cjk_area_px"] / g["img_area_px"]).where(g["img_area_px"] > 0)
    years_per_point = g.groupby("point_id")["year"].transform("nunique")
    g["n_years_observed"] = years_per_point
    return g


def unit_year_panel(point_year: pd.DataFrame) -> pd.DataFrame:
    g = point_year.groupby(["unit_id", "year"]).agg(
        n_points=("point_id", "nunique"), n_panos=("n_panos", "sum"),
        share_points_cjk=("any_cjk", "mean"), mean_cjk_boxes=("n_cjk_boxes", "mean"),
        mean_cjk_box_share=("cjk_box_share", "mean"), mean_cjk_area_share=("cjk_area_share", "mean"),
        n_simplified=("n_simplified", "sum"), n_traditional=("n_traditional", "sum"),
        n_points_multi_year=("n_years_observed", lambda s: int((s > 1).sum()))).reset_index()
    return g
