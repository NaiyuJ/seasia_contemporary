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
Cells converted from percentage tables (`pdf_da_pct`) are excluded from the analysis samples:
their total is rebuilt from the official population, so the ratio is 1 by construction and
cannot tell a Kemenag table from a Dukcapil one, and shares printed to two decimals floor small
Konghucu counts to zero. `load_panel` keeps one row per unit-year (the end-of-year half-year
cell when a source is semi-annual) and refuses duplicates.
Ministry of Religion (Kemenag) adherent counts run 1.3 to 1.8 times the population in the same
kabupaten and count a different thing; mixing the two creates spurious jumps (see
`konghucu_breaks.csv`). `konghucu_ref` names the table behind every cell.

Main comparison: 2021 to 2023 (yearbooks published 2022 and 2024, BPS API tables). Units observed
in both years with an exact count: 52; with exact or upper bound: 131 (as of October 2026).

A unit-year pair enters the upper-bound sample only if both years have the same definition
(both an exact Konghucu count, or both Lainnya): an exact count in one year and Lainnya in the
other would read as a change in registration. `two_period` drops such pairs and the script
prints how many. It also refuses a panel with two rows for the same unit-year, which
`pivot_table` would otherwise average silently.

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
   baseline level of y and log population; HC3 standard errors, and a version with province fixed
   effects. Errors are clustered by province only when the sample has at least 20 provinces;
   with fewer, HC3 is used. `python -m analysis.size_check` simulates the test DGP with no
   effect: at n = 51 and six provinces, HC1 rejected a true null 8 to 9% of the time, HC3 8%,
   classical 7% (the synthetic draws, not the pipeline, carry that excess: the same draws
   regressed by hand give the same rate and pure Gaussian draws give 5%), and six-cluster
   errors 20%. Also reported: Δlog(1+count) as outcome, same-source
   pairs only, the sample without Singkawang, a dummy for any investment in the window instead
   of the log flow, and the log flow interacted with a dummy for a baseline y at or above the
   sample median (the re-registration mechanism needs Chinese Indonesians to be there).
2. Two-way fixed effects on the unbalanced 2019–2023 panel: y_it on log(1 + cumulative Chinese
   investment up to t) with unit and year effects, errors clustered by unit. The outcome, the
   regressors and the year dummies are all demeaned by unit (on an unbalanced panel raw year
   dummies are not orthogonal to the unit effects and the year trend leaks into the investment
   coefficient; `tests/test_analysis.py` plants a pure year effect to check this). For the
   upper-bound outcome the TWFE sample applies the same province exclusion as the long
   difference and keeps only units with one definition (exact or Lainnya) across years.
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

## Review fixes of 2026-10-20 (the results above are from the rerun after them)

An independent code review found, and these commits fixed: the TWFE year dummies were not
demeaned (above); the TWFE upper-bound sample lacked the province exclusion and the
same-definition rule; a printed dash in a BPS table was read as missing rather than zero, so
kabupaten with no Konghucu left the exact sample (selection on the outcome); the
`placeholder` quality rule counted four zeros as a placeholder pattern and dropped the same
kind of cell; percentage-table cells passed the Dukcapil filter mechanically; an interaction
collinear with its main effect would have been reported (now dropped); province-clustered
errors with few provinces over-rejected (HC3 with a 20-cluster guard); BKPM statuses with
stray whitespace, a bare ambiguous kabupaten name, and an empty PMDN USD column were silent.
Still open, by design: when two sources cover a cell, the source preference can pick a table
without a Konghucu column over one with it, so exact-sample coverage depends on which sources
were fetched.

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

## Results (run of 2026-10-20 on the rebuilt panel; `data/konghucu/analysis/regressions.csv`)

No specification finds an effect of investment intensity. Coefficients are the change in registered Konghucu per 1,000 residents, 2021 to 2023, per unit of Δlog(1 + thousand USD) realised in 2022 to 2023; HC3 standard errors in parentheses. Dummy rows are per 1,000 residents for kabupaten with any investment versus none; "—" marks a regressor without variation (every exact-sample kabupaten has some FDI) or an error not yet refreshed after the singleton-province fix. Run of 20 October 2026 on the rebuilt panel, `data/konghucu/analysis/regressions.csv`.

Dukcapil-type coverage by year: 101 / 173 / 233 / 289 / 233 kabupaten in 2019–2023, of which
43 / 108 / 91 / 106 / 70 with an exact Konghucu count. 51 exact pairs for 2021–2023; 102
upper-bound pairs after 8 units with an exact count in one year and Lainnya in the other were
dropped. BKPM names all matched a BPS code.

| Specification | n | China | China + HK | All FDI |
| --- | --- | --- | --- | --- |
| Long diff, exact | 51 | 0.002 (0.023) | −0.004 (0.012) | 0.013 (0.044) |
| + province FE | 51 | 0.013 (0.030) | 0.028 (0.059) | −0.003 (0.037) |
| Δlog(count) | 51 | −0.007 (0.023) | 0.007 (0.015) | 0.010 (0.036) |
| Without Singkawang | 50 | −0.005 (0.012) | −0.007 (0.009) | 0.015 (0.012) |
| Any-investment dummy | 51 | 0.33 (0.32) | 0.34 (0.34) | 0.38 (0.44) |
| Dummy + province FE | 51 | 0.37 (0.41) | 0.45 (0.50) | −0.20 (0.37) |
| Dummy × high baseline | 51 | 0.19 (0.23) | 0.19 (0.27) | — |
| Log flow × high baseline | 51 | −0.003 (0.018) | −0.022 (0.030) | −0.066 (0.100) |
| TWFE 2019–2023, exact | 361 | 0.002 (0.039) | 0.017 (0.055) | 0.142 (0.119) |
| Long diff, upper bound | 102 | 0.029 (0.018) | 0.019 (0.016) | 0.020 (0.017) |
| + province FE | 102 | 0.042 (0.024) | 0.044 (—) | 0.025 (0.026) |
| Any-investment dummy | 102 | 0.30 (0.17) | 0.25 (0.15) | 0.15 (0.14) |
| Dummy + province FE | 102 | 0.36 (0.21) | 0.36 (0.24) | 0.23 (0.21) |
| TWFE 2019–2023, upper bound | 567 | 0.016 (0.034) | 0.033 (0.043) | 0.086 (0.072) |
| Placebo: Buddhist share | 132 | 0.021 (0.034) | −0.001 (0.049) | 0.007 (0.022) |
| Placebo: Protestant share | 139 | −0.01 (0.34) | 0.48 (0.67) | 0.38 (0.62) |
| Placebo: Catholic share | 139 | −0.25 (0.22) | −0.30 (0.16) | −0.03 (0.23) |

Reading:

- **Intensity: null.** In the exact sample the log-flow coefficient changes sign across specifications and never exceeds one standard error. The tightest estimate, without Singkawang, is −0.005 with a standard error of 0.012. At the 5 percent level this rules out effects above roughly 0.025 per 1,000 per log point, so a kabupaten going from zero to USD 10 million of Chinese investment (about 9 log points) adding more than 0.2 Konghucu per 1,000 residents. Typical exact-sample levels are 0.2 to 2 per 1,000.
- **Any investment: a weak, non-significant hint.** Kabupaten with any Chinese investment in 2022 to 2023 gained about 0.3 more per 1,000 in both samples. The point estimate survives province fixed effects (0.37 and 0.36) but the p-values are 0.36 and 0.08. The all-FDI dummy turns negative with province effects, so the hint is somewhat specific to Chinese money. Treated kabupaten are larger and more urban, which the controls only partly absorb.
- **Not where Chinese Indonesians live.** The interaction with a high 2021 Konghucu level is zero or negative for the log flow and positive but imprecise for the dummy (0.19 and 0.10, p ≈ 0.4 to 0.5). The re-registration mechanism predicts the effect should sit in exactly these places.
- **Upper-bound sample.** The p ≈ 0.07 to 0.10 results there do not hold with the China + HK or all-FDI measures or in the TWFE panel, and the Catholic placebo reaches p = 0.07 with the China + HK measure. These are read as noise from the Lainnya column.
- **Placebos.** The Buddhist share, the religion most Chinese Indonesians hold, does not respond to any investment measure, so there is no sign that investment moves Chinese population shares through migration.

Power is the binding constraint: two years, 51 units and a stock outcome that moves little;
the panel needs earlier yearbook years before the null is informative against small effects.

## Review fixes of 2026-10-20 (the results above are from the rerun after them)

An independent code review found, and these commits fixed: the TWFE year dummies were not
demeaned (above); the TWFE upper-bound sample lacked the province exclusion and the
same-definition rule; a printed dash in a BPS table was read as missing rather than zero, so
kabupaten with no Konghucu left the exact sample (selection on the outcome); the
`placeholder` quality rule counted four zeros as a placeholder pattern and dropped the same
kind of cell; percentage-table cells passed the Dukcapil filter mechanically; an interaction
collinear with its main effect would have been reported (now dropped); province-clustered
errors with few provinces over-rejected (HC3 with a 20-cluster guard); BKPM statuses with
stray whitespace, a bare ambiguous kabupaten name, and an empty PMDN USD column were silent.
Still open, by design: when two sources cover a cell, the source preference can pick a table
without a Konghucu column over one with it, so exact-sample coverage depends on which sources
were fetched.

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

## Results (run of 2026-10-19, panel of 2,075 unit-years; `data/konghucu/analysis/regressions.csv`)

Coefficients are the change in registered Konghucu per 1,000 residents (2021→2023) per unit of
Δlog(1 + thousand USD) realised in 2022–2023. BKPM names all matched a BPS code after the
Papua / Selayar / Padang Sidempuan fixes (no "not matched" list printed).

| spec | n | China | China+HK | all FDI |
|---|---|---|---|---|
| long-diff y_exact | 51 | 0.002 (0.013) | −0.004 (0.010) | 0.013 (0.029) |
| … + province FE | 51 | 0.013 (0.024) | 0.028 (0.046) | −0.003 (0.036) |
| … Δlog(count) | 51 | −0.007 (0.022) | 0.007 (0.014) | 0.010 (0.027) |
| … without Singkawang | 50 | −0.005 (0.007) | −0.007 (0.006) | 0.015 (0.009) |
| TWFE y_exact 2019–2023 | 351 | −0.005 (0.033) | 0.007 (0.045) | 0.107 (0.100) |
| … any-investment dummy (per 1,000) | 51 | 0.33 (0.30) | 0.34 (0.32) | 0.38 (0.40) |
| … any-investment dummy + province FE | 51 | 0.37 (0.39) | — | −0.20 (0.20) |
| … any-investment dummy × high baseline | 51 | 0.19 (0.19) | — | 0.07 (0.07) |
| … log flow × high baseline | 51 | −0.004 (0.012) | −0.022 (0.026) | −0.062 (0.071) |
| long-diff y_ub | 113 | 0.023 (0.013) | 0.015 (0.013) | 0.018 (0.012) |
| … any-investment dummy (per 1,000) | 113 | 0.26 (0.13) | 0.23 (0.12) | 0.14 (0.11) |
| … any-investment dummy + province FE | 113 | 0.31 (0.20) | — | 0.12 (0.12) |
| … any-investment dummy × high baseline | 113 | 0.14 (0.13) | — | −0.00 (0.04) |
| … log flow × high baseline | 113 | 0.004 (0.008) | 0.004 (0.010) | −0.013 (0.027) |
| … + province FE | 113 | 0.036 (0.025) | 0.034 (0.028) | 0.013 (0.015) |
| … without Singkawang | 112 | 0.019 (0.012) | 0.014 (0.012) | 0.021 (0.011) |
| TWFE y_ub 2019–2023 | 736 | 0.029 (0.048) | 0.034 (0.051) | −0.072 (0.112) |
| placebo share_buddha | 136 | 0.020 (0.030) | −0.000 (0.042) | 0.007 (0.016) |
| placebo share_kristen | 143 | 0.37 (0.42) | 0.80 (0.61) | 1.54 (1.45) |
| placebo share_katolik | 143 | −0.39 (0.26) | −0.43 (0.22) | 0.08 (0.33) |

Reading: in the exact sample there is no detectable effect of Chinese investment on Konghucu
registration; the point estimates change sign across specifications and are within one standard
error of zero. The exact-sample standard error without Singkawang (0.007) means the design can
rule out, at the 5% level, effects larger than roughly 0.02 per 1,000 residents per log point of
investment, i.e. a kabupaten going from zero to USD 10 million of Chinese investment (about 9 log
points) adding more than 0.2 Konghucu per 1,000 residents; typical exact-sample levels are
0.2–2 per 1,000, Singkawang 10 and rising by 3.9 over the window with no Chinese FDI recorded.
The upper-bound sample gives a marginally positive coefficient (p = 0.09) that does not survive
province fixed effects, the China+HK or all-FDI measures, or the TWFE panel, and is of the same
order as the Catholic-share placebo (p = 0.05 with China+HK); it is read as noise from the
"Lainnya" column. The any-investment dummy gives a positive point estimate of about 0.3 per 1,000 in both
samples (units with any Chinese investment in 2022–2023 versus none), significant only in the
upper-bound sample (p = 0.05) and not specific to Chinese money in the exact sample; the
interaction with a high baseline Konghucu level is zero or negative, so whatever moves is not
concentrated where Chinese Indonesians live, which is the opposite of what the re-registration
mechanism predicts. Treated units are larger and more urban. With province fixed effects the Chinese dummy keeps
its point estimate (0.37 exact, 0.31 upper bound) but loses significance (p = 0.35 and 0.13),
while the all-FDI dummy turns negative in the exact sample; the dummy × high-baseline interaction
is positive but imprecise (0.19 and 0.14, p ≈ 0.3). The honest summary is a null with a weak,
non-significant hint that kabupaten receiving any Chinese investment saw slightly more Konghucu
registration. Power is the binding constraint: two years, 51 units and a stock outcome
that moves little; the panel needs earlier yearbook years and the "any investment" and
"high baseline" specifications above before the null is informative.
