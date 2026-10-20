import numpy as np
import pandas as pd
import pytest

from konghucu import ipums

DDI = """<?xml version="1.0" encoding="UTF-8"?>
<codeBook xmlns="ddi:codebook:2_5">
  <dataDscr>
    <var ID="GEO1_ID2010" name="GEO1_ID2010"><labl>Province</labl>
      <catgry><catValu>36061</catValu><labl>Kalimantan Barat</labl></catgry>
      <catgry><catValu>36032</catValu><labl>Jawa Barat</labl></catgry>
    </var>
    <var ID="GEO2_ID2010" name="GEO2_ID2010"><labl>Kabupaten</labl>
      <catgry><catValu>360616172</catValu><labl>Kota Singkawang</labl></catgry>
      <catgry><catValu>360616101</catValu><labl>Sambas</labl></catgry>
      <catgry><catValu>360323204</catValu><labl>Bandung</labl></catgry>
      <catgry><catValu>360323273</catValu><labl>Kota Bandung</labl></catgry>
      <catgry><catValu>360329999</catValu><labl>Nowhere</labl></catgry>
    </var>
    <var ID="ID2010A_ETHNIC" name="ID2010A_ETHNIC"><labl>Ethnicity</labl>
      <catgry><catValu>01</catValu><labl>Jawa</labl></catgry>
      <catgry><catValu>02</catValu><labl>Sunda</labl></catgry>
      <catgry><catValu>17</catValu><labl>Chinese (Tionghoa)</labl></catgry>
      <catgry><catValu>99</catValu><labl>Unknown</labl></catgry>
    </var>
    <var ID="ID2010A_RELIG" name="ID2010A_RELIG"><labl>Religion</labl>
      <catgry><catValu>1</catValu><labl>Islam</labl></catgry>
      <catgry><catValu>4</catValu><labl>Buddhist</labl></catgry>
      <catgry><catValu>6</catValu><labl>Khonghucu</labl></catgry>
      <catgry><catValu>7</catValu><labl>Other</labl></catgry>
    </var>
    <var ID="PERWT" name="PERWT"><labl>Person weight</labl></var>
  </dataDscr>
</codeBook>
"""


def _extract(rng, weight_scale=1.0):
    rows = []
    plan = {  # geo2: (n people, chinese share, konghucu share among chinese, buddha share among chinese)
        "360616172": (400, 0.40, 0.30, 0.60), "360616101": (400, 0.10, 0.00, 0.80),
        "360323204": (400, 0.01, 0.00, 0.50), "360323273": (400, 0.05, 0.10, 0.70), "360329999": (50, 0.0, 0, 0),
    }
    for geo2, (n, cs, ks, bs) in plan.items():
        for i in range(n):
            chinese = rng.random() < cs
            if chinese:
                u = rng.random()
                rel = "6" if u < ks else ("4" if u < ks + bs else "7")
            else:
                rel = "1"
            rows.append(dict(GEO1_ID2010=geo2[:5], GEO2_ID2010=geo2, ID2010A_ETHNIC="17" if chinese else "01",
                             ID2010A_RELIG=rel, PERWT=10.0 * weight_scale))
    return pd.DataFrame(rows)


def test_tabulate_and_match(tmp_path, capsys):
    (tmp_path / "ddi.xml").write_text(DDI)
    rng = np.random.default_rng(0)
    ext = _extract(rng)
    ext.to_csv(tmp_path / "ext.csv", index=False)
    pd.DataFrame([
        {"unit_code": "6172", "unit_name": "Kota Singkawang"}, {"unit_code": "6101", "unit_name": "Sambas"},
        {"unit_code": "3204", "unit_name": "Bandung"}, {"unit_code": "3273", "unit_name": "Kota Bandung"},
    ]).to_csv(tmp_path / "codes.csv", index=False)
    logs = []
    out = ipums.build(str(tmp_path / "ext.csv"), str(tmp_path / "ddi.xml"), str(tmp_path / "codes.csv"), log=logs.append)
    by = out.set_index("unit_code")
    assert set(by.index) == {"6172", "6101", "3204", "3273"}
    assert abs(by.loc["6172", "chinese_share"] - 0.40) < 0.08 and by.loc["6172", "pop2010"] == 4000
    assert abs(by.loc["6172", "konghucu_of_chinese"] - 0.30) < 0.1
    assert by.loc["6101", "konghucu_chinese2010"] == 0 and by.loc["3204", "n_chinese_sample"] < 20
    assert any("Nowhere" in l for l in logs) and any("Chinese (Tionghoa)" in l for l in logs)


def test_weight_with_implied_decimals_is_rescaled(tmp_path):
    (tmp_path / "ddi.xml").write_text(DDI)
    rng = np.random.default_rng(1)
    ext = _extract(rng, weight_scale=1e6)  # sums far beyond 10x the 2010 population
    ddi = ipums.read_ddi(str(tmp_path / "ddi.xml"))
    logs = []
    tab = ipums.tabulate(ext, ddi, log=logs.append)
    assert any("divided by 100" in l for l in logs)
    assert abs(tab["pop2010"].sum() - 1650 * 10 * 1e6 / 100) < 1


def test_missing_categories_fail_loudly(tmp_path):
    (tmp_path / "ddi.xml").write_text(DDI.replace("Khonghucu", "Kejawen"))
    ext = _extract(np.random.default_rng(2))
    with pytest.raises(SystemExit, match="Konghucu"):
        ipums.tabulate(ext, ipums.read_ddi(str(tmp_path / "ddi.xml")))
