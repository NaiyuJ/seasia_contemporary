"""Self-collected panel of registered religion (incl. Khonghucu) by kabupaten/kota.

Sources handled here (all public aggregate data, no personal records):
  bps      BPS Web API static tables ("penduduk menurut agama") per province
  arcgis   GIS Dukcapil ArcGIS REST layers with religion fields
  pdf      kabupaten/province Dukcapil "Data Agregat Kependudukan" PDFs
All three are normalised into one long table:
  source, province_code, unit_code, unit_name, year, semester, religion, count, ref
"""
__version__ = "0.1.0"
