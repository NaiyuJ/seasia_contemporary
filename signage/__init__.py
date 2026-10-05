"""Street View storefront Chinese-character detection pipeline.

Stages (see signage.cli):
  sample    -> data/points.csv          sample points along roads inside admin units
  discover  -> data/panos.csv           find panoramas (current + historical) near each point
  fetch     -> data/images/, images.csv download storefront-facing images
  ocr       -> data/ocr_boxes.csv       detect text, flag CJK characters
  aggregate -> data/panel_*.csv         pano -> point-year -> unit-year panels
  validate  -> data/validation/         hand-coding sample and precision/recall
"""
__version__ = "0.1.0"
