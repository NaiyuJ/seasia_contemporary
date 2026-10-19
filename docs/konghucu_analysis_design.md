# Konghucu registration and Chinese investment: analysis design

Script: `python -m analysis.konghucu [--investment data/raw/china_investment.csv --inv-col value]`.
Outputs in `data/konghucu/analysis/`: `two_period_y_exact.csv`, `two_period_y_ub.csv`,
`regressions.csv`. Everything printed comes from these inputs; nothing is computed by hand.

## Outcome

Registered Konghucu residents per 1,000 residents of the kabupaten/kota, with the official BPS
population as denominator (`konghucu_share_pop * 1000`). Changing the religion on one's KTP to
Konghucu is a costly, legible act of identification; the count is the stock of people who have
done so.

Two versions, reported separately:

- `y_exact`: the source table has a Konghucu column.
- `y_ub`: Konghucu folded into *Lainnya* (with Kepercayaan); an upper bound. Used as a robustness
  sample, never pooled with the exact one without a flag.

`two_period_*.csv` carries three changes per unit: `change` (per 1,000 with each year's own
population), `change_fixedpop` (both years over the 2021 population, so population growth alone
does not read as a fall; the regression default) and `dlog_count` (log(1+count) difference).

## Sample

Only *Dukcapil-type* cells: the religion total is within 0.8 to 1.25 of the official population.
Ministry of Religion (Kemenag) adherent counts run 1.3 to 1.8 times the population in the same
kabupaten and count a different thing; mixing the two creates spurious jumps (see
`konghucu_breaks.csv`). `konghucu_ref` names the table behind every cell.

Main comparison: 2021 to 2023 (yearbooks published 2022 and 2024, BPS API tables). Units observed
in both years with an exact count: 52; with exact or upper bound: 131 (as of October 2026).

The upper-bound sample excludes provinces whose *Lainnya* is an indigenous religion rather than
Konghucu: Nusa Tenggara Timur (Marapu; Sumba Barat Daya shows 17 per 1,000), Kalimantan Tengah
(Kaharingan) and the Papua provinces (`UB_EXCLUDE_PROVINCES`).

What the 2021 to 2023 descriptives show (October 2026 run): the registered stock barely moves in
two years. The median change is zero; most of the movement is Singkawang (5.9 to 9.4 per 1,000,
1,542 to 2,316 people) and Pontianak (+0.5). A specification without Singkawang is reported with
every long difference.

## Specifications

1. Long difference: Δy(2021→2023), the outcome being a stock, on log(1 + Chinese investment
   realised in 2022–2023), controlling for log(1 + cumulative Chinese investment up to 2021), the
   baseline level of y and log population; HC1 standard errors, and a version with province fixed
   effects and province-clustered errors. Also reported: Δlog(1+count) as outcome, same-source
   pairs only, and the sample without Singkawang.
2. Two-way fixed effects on the unbalanced 2019–2023 panel: y_it on log(1 + cumulative Chinese
   investment up to t) with unit and year effects (within transformation), errors clustered by unit.
3. Placebos: the same long difference with Buddhist, Protestant and Catholic shares as outcomes.
   Investment that moves Konghucu registration but not Buddhism (the religion most Chinese
   Indonesians hold) is the pattern the identity argument predicts; a move in all of them points
   to migration or registration drives.

## Investment variable

`python -m analysis.bkpm --src <BKPM realisasi CSV>` builds `data/raw/china_investment.csv` from
BKPM's quarterly realisation file (PMA/PMDN, source country, kabupaten name, thousand USD): per
kabupaten-year `china_usd_k` (mainland China: Tiongkok / R.R. Tiongkok / China), `hk_usd_k`
(Hong Kong, kept apart because mainland money is routed through it), `fdi_usd_k` (all PMA),
`pmdn_usd_k` (domestic) and `china_plus_hk_usd_k`. Kabupaten names are matched to BPS codes with
the religion tables' normaliser; the script prints the unmatched names and their investment.
Units without a row are zero investment. log(1+x) because the distribution is extremely skewed
with many zeros; run `--inv-col china_plus_hk_usd_k` and `--inv-col fdi_usd_k` (all foreign
investment, a placebo for "it is just FDI") as further columns of the results table.

## Identification caveats

- **Selection into coverage.** Which kabupaten publish a usable religion table (and with a
  Konghucu column) is not random: the exact sample over-represents Kalimantan Barat, Bangka
  Belitung and Jawa Tengah. Report the sample's provinces and compare its investment distribution
  with the full set of kabupaten.
- **Registration vs belief.** The count is administrative. A rise can come from new converts,
  from existing Confucians correcting a KTP that said Buddhist (the common pre-2006 workaround), or
  from Dukcapil data cleaning. The yearbook-vs-API comparison for the same kabupaten-year bounds
  the last.
- **Timing.** Yearbook data are end-of-year stocks; BKPM investment realisations are flows by
  quarter. Lag the investment variable (t-1) as a check.
- **Pemekaran.** Kabupaten split during the window change both numerator and denominator; the
  population anchor flags them (`total_to_pop` far from 1 in the split year) and they should be
  dropped or merged to the parent unit.
- **Measurement error from parsing.** Yearbook figures pass through a watermark-stripping parser;
  every book's total was checked against the official population (within 1 to 2 percent in the
  books inspected by hand). Residual error is classical in the outcome and attenuates nothing in
  the regressor.
- **Power.** 52 units give a two-period design little power for small effects; the upper-bound
  sample and the TWFE panel are there for precision, the exact sample for interpretation.
