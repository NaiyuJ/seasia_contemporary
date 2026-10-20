# IPUMS 2010 census: ethnic-Chinese denominator

Module `konghucu/ipums.py`, command `python -m konghucu.cli ipums-chinese --csv <extract> --ddi <codebook>`,
output `data/raw/ipums_chinese_2010.csv`; used by `python -m analysis.konghucu --chinese data/raw/ipums_chinese_2010.csv`.

## What it measures

The 2010 population census is the only source that records ethnicity (suku) and religion for
the same person at kabupaten level. From the IPUMS International 10% sample it gives, per
kabupaten/kota in 2010 boundaries:

- `chinese_share`: weighted share of residents whose ethnicity is Chinese (Tionghoa).
- `konghucu_of_chinese`, `buddha_of_chinese`: shares of the ethnic Chinese reporting
  Khonghucu and Buddhism in 2010. The first is the baseline rate of the identification act
  the panel tracks; the second is the pool from which re-registration draws.
- `n_chinese_sample`: unweighted Chinese respondents behind the shares.

The analysis uses it two ways. First, a second outcome `y_exact_chn`: registered Konghucu per
1,000 ethnic Chinese, with the 2010 share applied to the current official population. The
per-resident outcome mostly reflects where Chinese Indonesians live; this one asks what
fraction of them register. Second, heterogeneity on the per-resident outcome: investment
interacted with a dummy for a 2010 Chinese share above the sample median.

## Making the extract

At https://international.ipums.org: sample Indonesia 2010; variables `GEO2_ID2010` (kabupaten,
2010 boundaries), `GEO1_ID2010` (province), `ID2010A_ETHNIC` (ethnicity), `ID2010A_RELIG`
(religion, sample-specific: the harmonised `RELIGION` folds Khonghucu into "Other" in some
releases), `PERWT`; format CSV; download the data file and the DDI codebook (.xml). The
command finds the categories by their labels (Chinese / Tionghoa; Khonghucu / Confucian;
Buddhist) and prints the labels it matched, so a renamed category is visible. A person weight
summing to more than ten times the census population is divided by 100 (implied decimals).

## Identification caveats

- **Boundaries.** 2010 kabupaten. Kabupaten created after 2010 get no share and drop out of
  the Chinese-denominator outcome; the parent keeps the pre-split share, which is then applied
  to the parent's post-split population. A crosswalk would be the fix.
- **Precision.** The 10% sample has few Chinese respondents outside the cities; shares are
  used only where at least 30 Chinese respondents are observed (`MIN_CHINESE_SAMPLE`). The
  usable set is therefore biased towards places with many Chinese Indonesians, which is also
  where the mechanism can operate.
- **Ethnicity is self-reported.** Peranakan who report Javanese or Betawi are not counted;
  `chinese_share` is a lower bound and `y_exact_chn` an upper bound on the registration rate.
- **A fixed 2010 share.** Chinese in-migration to Morowali-type investment sites after 2010
  would raise the true denominator there and inflate `y_exact_chn`; the Buddhist-share
  placebo on the per-resident outcome is the check for that kind of movement.
