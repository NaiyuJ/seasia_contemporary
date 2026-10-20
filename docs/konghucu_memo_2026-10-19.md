# Memo: Konghucu Registration and Chinese Investment

As of 2026-10-20 (results refreshed after the code review of the same day). Companion to `docs/konghucu_analysis_design.md` (specifications, full
results table) and `docs/konghucu_data_sources.md` (sources, cleaning rules, known bad tables).

**Bottom line.** Between 2021 and 2023, how much Chinese investment a kabupaten received has no
detectable relationship with the change in its registered Konghucu (Confucian) population.
Kabupaten with any Chinese investment gained about 0.3 more registrants per 1,000 residents than
those with none, but the difference is not significant and is not concentrated where Chinese
Indonesians live. The panel, the investment variable and every regression rerun from `data/raw`
with the scripts in this repository.

## Question and hypothesis

The dissertation asks whether Chinese investment leads Chinese Indonesians to cooperate
economically with China while identifying politically and socially as Indonesian. This strand
tests one observable, countable act of identification: changing the religion on one's ID card
(KTP) to Khonghucu.

Why this measure:

- Presidential Instruction 14/1967 suppressed Chinese religion, and most Confucians registered as
  Buddhist. Only after Law 23/2006 could a KTP legally say Khonghucu. Switching back is a costly,
  recorded, ethnically marked public statement.
- It is an administrative count, available per kabupaten per year, so it supports a panel.
- Either sign is interpretable. Investment could raise the value of a visibly Chinese identity
  and push registration up, or raise the risk of anti-Chinese backlash and hold it flat or down.
  A null is informative too.

The test is of the first direction: do kabupaten with more Chinese investment inflows show larger
growth in registered Konghucu per 1,000 residents?

## Data sources and panel construction

The outcome panel covers 2,075 kabupaten-years for 449 kabupaten/kota, with an official BPS
population for 82 to 83 percent of cells. It is assembled from public sources only, after
deciding not to file a data request with Dukcapil.

| Source | What it gives | Role in the panel |
| --- | --- | --- |
| BPS Web API, static and dynamic tables (`bps-search`, `bps-fetch`) | Province-level yearbook tables of population by religion and kabupaten, 2010s onward | Backbone for earlier years; the table header records whether the figures are Dukcapil or Kemenag |
| *Kabupaten/Kota Dalam Angka* yearbook PDFs (`bps-publications`, `dalam-angka-extract`) | Table 4.3, population by kecamatan and religion, sourced from the local Dukcapil office | Fills 2019 to 2023 for kabupaten absent from the API; 243 count tables and 6 percentage tables read from the 2024 books |
| BPS population series (`bps-population`) | Official mid-year population per kabupaten | Denominator and plausibility anchor |
| GIS Dukcapil ArcGIS layers | Current-period registration by religion | Unreachable from a US address; not used |

Two definitions of "adherents" circulate and must never be mixed. Dukcapil counts people whose
KTP names the religion. The Ministry of Religion (Kemenag) counts congregants and runs 1.3 to 1.8
times the kabupaten population. Only *Dukcapil-type* cells enter the analysis: the religion total
must be within 0.8 to 1.25 of the official population.

Cleaning rules, all in `konghucu/harmonize.py` and rerunnable:

- One source table per kabupaten-year, so all religions in a cell come from the same table.
  Source preference: ArcGIS, then PDF, then yearbook, then BPS dynamic and static tables, then
  kecamatan sums.
- A reported total that differs from the sum of religions by more than 10 percent is replaced by
  the sum. Cells above 1.5 or below 0.5 times the population are dropped.
- 36 hand-verified bad cells are listed in `konghucu/drop_cells.csv` with the reason (a Sibolga
  row that copied its neighbour's Muslim count, Kemenag-sourced Samarinda at 32,001 Konghucu,
  kecamatan-level tables mistaken for kabupaten tables).
- Where a table has no Konghucu column, Konghucu is folded into *Lainnya* (other). The panel
  carries `konghucu` (exact) and `konghucu_ub` (upper bound: Konghucu, else Lainnya) with a flag
  saying which.
- Yearbook data years are the title year minus one; the parser scores candidate pages, handles
  two-level kecamatan/kelurahan numbering, split-page tables, missing total rows and watermark
  characters leaking into digits.

Coverage is thin before 2019 and best for 2021 to 2023, where 233, 289 and 233 kabupaten
respectively have usable Dukcapil-type cells (91, 106 and 70 with an exact Konghucu count).
51 kabupaten have an exact Konghucu count in both 2021 and 2023; 102 have an exact or
upper-bound count under the same definition in both years.

## Investment variable

The treatment comes from BKPM's quarterly realised-investment file (2010 to 2026 Q2): one row per
period, PMA/PMDN status, source country, province and kabupaten, with values in thousand USD. The
script `analysis/bkpm.py` converts it to one row per kabupaten-year with five columns.

| Column | Definition |
| --- | --- |
| `china_usd_k` | PMA from mainland China (labels Tiongkok, R.R. Tiongkok, China); the main treatment |
| `hk_usd_k` | PMA from Hong Kong, kept apart because mainland money is routed through it |
| `china_plus_hk_usd_k` | Sum of the two; second treatment |
| `fdi_usd_k` | All foreign investment; a placebo for "it is just FDI" |
| `pmdn_usd_k` | Domestic investment |

Kabupaten names are matched to BPS 4-digit codes with the same normaliser the religion tables
use, in order: province plus level plus name, province plus unique name, national unique name,
national level plus name, and full name with or without a *Kota* prefix. After aliases for the
new Papua provinces, Selayar and Padang Sidempuan, every BKPM name matches a code. The result is
7,602 kabupaten-years for 508 units. Chinese FDI is extremely skewed: Morowali (nickel)
dominates, and most kabupaten record zero in most years, so the regressions use log(1 + flow)
and, separately, a dummy for any flow in the window.

## Analysis design

The outcome is registered Konghucu per 1,000 residents, a stock. The main comparison is its
change from 2021 to 2023, both years divided by the 2021 population so that population growth
alone does not read as a fall. All specifications are in `analysis/konghucu.py`.

1. **Long difference.** Change in y on log(1 + Chinese investment realised in 2022 to 2023),
   controlling for log(1 + cumulative investment to 2021), the 2021 level of y and log
   population. HC3 standard errors (province-clustered only with 20 or more provinces;
   `analysis/size_check.py` shows six-cluster errors reject a true null 20% of the time); a
   second version adds province fixed effects, dropping provinces with a single sampled unit.
2. **Variants of the long difference.** Change in log(1 + count) as outcome; pairs whose two
   cells come from the same source type; the sample without Singkawang, which alone accounts for
   most of the movement; a 0/1 dummy for any Chinese investment in the window instead of the log
   flow; and the treatment interacted with a dummy for a 2021 Konghucu level at or above the
   sample median, since re-registration can only happen where Chinese Indonesians live.
3. **Two-way fixed effects.** The unbalanced 2019 to 2023 panel, y on log(1 + cumulative
   investment to year t), unit and year effects, errors clustered by unit.
4. **Placebos.** The same long difference with Buddhist, Protestant and Catholic shares as
   outcomes. Investment that moves Konghucu but not Buddhism, the religion most Chinese
   Indonesians hold, is the identity pattern; a move in all three points to migration or a
   registration drive.

Two samples throughout. *Exact*: tables with a Konghucu column (51 kabupaten in 2021 and 2023).
*Upper bound*: Konghucu or Lainnya (102 after excluding Nusa Tenggara Timur, Kalimantan Tengah
and Papua, where Lainnya is an indigenous religion, and 8 units whose definition differs between the two years). The upper-bound sample is a robustness
check, never pooled with the exact one.

Descriptively the stock barely moves. The median two-year change is zero; 49 percent of
exact-sample kabupaten rise, 18 percent are unchanged, 33 percent fall. Singkawang rises from 5.9
to 9.4 per 1,000 (1,542 to 2,316 people) and Pontianak by 0.5. Singkawang records almost no
Chinese FDI.

## Results

No specification finds an effect of investment intensity. Coefficients are the change in registered Konghucu per 1,000 residents, 2021 to 2023, per unit of Δlog(1 + thousand USD) realised in 2022 to 2023; HC3 standard errors in parentheses. Dummy rows are per 1,000 residents for kabupaten with any investment versus none; "—" marks a regressor without variation (every exact-sample kabupaten has some FDI); province-FE rows drop provinces with a single sampled kabupaten. Run of 20 October 2026 on the rebuilt panel, `data/konghucu/analysis/regressions.csv`.

| Specification | n | China | China + HK | All FDI |
| --- | --- | --- | --- | --- |
| Long diff, exact | 51 | 0.002 (0.023) | −0.004 (0.012) | 0.013 (0.044) |
| + province FE | 48 | 0.013 (0.030) | 0.028 (0.059) | −0.003 (0.037) |
| Δlog(count) | 51 | −0.007 (0.023) | 0.007 (0.015) | 0.010 (0.036) |
| Without Singkawang | 50 | −0.005 (0.012) | −0.007 (0.009) | 0.015 (0.012) |
| Any-investment dummy | 51 | 0.33 (0.32) | 0.34 (0.34) | 0.38 (0.44) |
| Dummy + province FE | 48 | 0.37 (0.41) | 0.45 (0.50) | −0.20 (0.34) |
| Dummy × high baseline | 51 | 0.19 (0.23) | 0.19 (0.27) | — |
| Log flow × high baseline | 51 | −0.003 (0.018) | −0.022 (0.030) | −0.066 (0.100) |
| TWFE 2019–2023, exact | 361 | 0.002 (0.039) | 0.017 (0.055) | 0.142 (0.119) |
| Long diff, upper bound | 102 | 0.029 (0.018) | 0.019 (0.016) | 0.020 (0.017) |
| + province FE | 99 | 0.042 (0.024) | 0.044 (0.033) | 0.025 (0.026) |
| Any-investment dummy | 102 | 0.30 (0.17) | 0.25 (0.15) | 0.15 (0.14) |
| Dummy + province FE | 99 | 0.36 (0.21) | 0.36 (0.24) | 0.23 (0.21) |
| TWFE 2019–2023, upper bound | 567 | 0.016 (0.034) | 0.033 (0.043) | 0.086 (0.072) |
| Placebo: Buddhist share | 132 | 0.021 (0.034) | −0.001 (0.049) | 0.007 (0.022) |
| Placebo: Protestant share | 139 | −0.01 (0.34) | 0.48 (0.67) | 0.38 (0.62) |
| Placebo: Catholic share | 139 | −0.25 (0.22) | −0.30 (0.16) | −0.03 (0.23) |

Reading the table:

- **Intensity: null.** In the exact sample the log-flow coefficient changes sign across specifications and never exceeds one standard error. The tightest estimate, without Singkawang, is −0.005 with a standard error of 0.012. At the 5 percent level this rules out effects above roughly 0.025 per 1,000 per log point, so a kabupaten going from zero to USD 10 million of Chinese investment (about 9 log points) adding more than 0.2 Konghucu per 1,000 residents. Typical exact-sample levels are 0.2 to 2 per 1,000.
- **Any investment: a weak, non-significant hint.** Kabupaten with any Chinese investment in 2022 to 2023 gained about 0.3 more per 1,000 in both samples. The point estimate survives province fixed effects (0.37 and 0.36) but the p-values are 0.36 and 0.08. The all-FDI dummy turns negative with province effects, so the hint is somewhat specific to Chinese money. Treated kabupaten are larger and more urban, which the controls only partly absorb.
- **Not where Chinese Indonesians live.** The interaction with a high 2021 Konghucu level is zero or negative for the log flow and positive but imprecise for the dummy (0.19 and 0.10, p ≈ 0.4 to 0.5). The re-registration mechanism predicts the effect should sit in exactly these places.
- **Upper-bound sample.** The p ≈ 0.07 to 0.10 results there do not hold with the China + HK or all-FDI measures or in the TWFE panel, and the Catholic placebo reaches p = 0.07 with the China + HK measure. These are read as noise from the Lainnya column.
- **Placebos.** The Buddhist share, the religion most Chinese Indonesians hold, does not respond to any investment measure, so there is no sign that investment moves Chinese population shares through migration.

## Limitations and identification

- **Power.** Two years, 51 kabupaten and a stock that moves little in most places. The null is
  informative against large effects only; a small effect of the size the dummy hints at cannot
  be ruled in or out.
- **Selection into coverage.** Which kabupaten publish a usable Dukcapil-type religion table with
  a Konghucu column is not random. The exact sample over-represents Kalimantan Barat, Bangka
  Belitung and Jawa Tengah. The investment distribution of the sample should be compared with
  that of all kabupaten before the result is generalised.
- **Registration is not belief.** A rise can be new converts, existing Confucians correcting a
  KTP that said Buddhist, or Dukcapil data cleaning. Singkawang's jump, in a city with almost no
  Chinese FDI, looks like local mobilisation by the Confucian association Matakin rather than
  anything investment did.
- **Lainnya contamination.** The upper-bound outcome also contains Kepercayaan (indigenous
  belief) and, outside the excluded provinces, small local religions. Its marginal results are
  not trusted.
- **Timing.** Yearbook stocks are end-of-year; BKPM realisations are quarterly flows. A one-year
  lag of investment has not been run.
- **Denominator.** Per 1,000 residents, not per 1,000 ethnic Chinese. The 2010 census microdata
  (IPUMS) could supply a Chinese-population denominator and a baseline share of Chinese already
  registered as Konghucu; neither has been merged yet.
- **Treatment measure.** BKPM realised PMA by source country understates Chinese capital routed
  through Singapore and Hong Kong and misses Chinese contractors on domestic projects.

## Next steps and reproduction

The investment-to-registration line can be written up as a null. Making the null persuasive, or
resolving the 0.3 hint, needs one of two things:

- [ ] Extend the yearbook extraction to the 2018 to 2021 books so the panel runs 2017 to 2023.
      Nothing new is needed; the download roughly doubles.
- [ ] Merge the IPUMS 2010 census microdata for an ethnic-Chinese denominator and a baseline
      Konghucu-among-Chinese share.
- [ ] Switch to a more sensitive outcome: Street View signage of Chinese associations, clan halls
      and temples (`signage/` module; needs `GOOGLE_MAPS_API_KEY` in the git-ignored `.env`).
- [ ] Run the investment variable with a one-year lag and with cumulative stock since 2010 as the
      treatment.
- [ ] Regenerate the BPS API key that was once committed.

Reproduction, from the repository root with `data/raw` populated:

```bash
python -m konghucu.cli bps-population
python -m konghucu.cli bps-publications --years 2022 2023 2024 --download data/raw/pubs
python -m konghucu.cli dalam-angka-extract data/raw/pubs/*.pdf
python -m konghucu.cli harmonize --population
python -m analysis.bkpm --src <BKPM realisasi CSV>
python -m analysis.konghucu --investment data/raw/china_investment.csv --inv-col china_usd_k
```

Tests: `python -m pytest -q`, 168 passing.
