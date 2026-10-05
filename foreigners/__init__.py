"""Foreign-national presence by kabupaten: Chinese nationals as a control / exclusion.

Public sources, all aggregate:
  bps      BPS provincial tables "orang asing menurut kebangsaan dan izin tinggal"
           (immigration-office data; rows are nationalities, columns permit types,
           years or immigration offices)
  ckan     data.go.id / provincial Satu Data CKAN portals: Kemnaker foreign-worker
           (TKA) datasets by country of origin
  dukcapil WNI/WNA split in Dukcapil aggregate PDFs (permanent residents only)
Long format:
  source, province_code, region_name, region_level, nationality, permit_type, year, count, ref
region_level is province | kanim | kabupaten | kecamatan. Immigration-office (kanim)
rows are allocated to kabupaten with a user-supplied crosswalk in `harmonize`.
"""
__version__ = "0.1.0"
