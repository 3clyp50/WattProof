# WattProof Ground Truth

Retrieved and checked on **2026-07-19**. No tariff formula is implemented unless its inputs and effective source are listed here.

## Freshness check

Three independent public-web searches on 2026-07-19 looked for a 2025 or 2026 official, complete, anonymized PG&E residential statement with enough detail to audit against a period-matched tariff. They found current PG&E tariff sheets and a March 2026 NEM billing explainer, but no newer complete ordinary residential statement with a coherent rate period. The search request IDs were:

- `ab653280-b289-433b-9ed9-c2f13348005a`
- `887f8dc8-14e5-4891-af60-e918750d5186`
- `260aa254-3e53-438f-b8d3-3f1fa206cfaf`

The supplied PG&E residential pricing summary is current to March 1, 2026 and remains useful context, but applying it to a 2022 bill would be wrong. WattProof therefore uses the newest public fixture found that forms a coherent, reproducible bill-and-rate pair: the December 2022 PG&E/3CE statement and its official 2022 sources. Freshness never overrides effective-period correctness.

## Supplied fixture audit

### `assets/pge-sample-consolidated-bill.pdf`

- SHA-256: `7e61bcc3e961edea79f63b9263007b473a40d16b08d884c4d363c507abab782e`
- Result: not an auditable electricity bill.
- It is a one-page August 2024 consolidated-billing layout explainer with placeholder dates, a summary-only electric amount, and no service period, rate schedule, usage, meter readings, or electricity charge detail.

### `assets/pge-residential-rate-plan-pricing.pdf`

- SHA-256: `4e5bf98acab8e84c558ce9c7e0924dc2333de841ce74066cd4a126f1a453ddf1`
- Effective date printed by the source: March 1, 2026.
- Result: it cannot match the undated supplied layout explainer and is not used for historical calculation.

### `assets/optional-valley-clean-energy-sample-bill.pdf`

- SHA-256: `e33ba91e68f2746eba65fc47c4b5a949dc128d5e984844886f8b26daca4f500b`
- Nominal service period: June 1-30, 2018; schedule E-1.
- Result: excluded from the authentic golden path. Its detailed sections retain March 2017 date bands, and its printed E-1 rates (`$0.19979`, `$0.27612`) do not match PG&E's official March-August 2018 workbook (`$0.21169`, `$0.27993`). It remains useful only as an example of why effective-period validation matters.

## Selected public fixture

`assets/pge-anonymous-3ce-sample-bill.pdf` is the primary auditable fixture.

- Publisher: Central Coast Community Energy (3CE), a California Community Choice Aggregator.
- Source: https://3cenergy.org/wp-content/uploads/2023/01/PGE-Example-RES-Bill-Anonymous.pdf
- SHA-256: `50cb3a012f46d2ae478079e28b7b109d08fc74ae098d95317a97c2b99175a9e6`
- Statement date: December 9, 2022.
- Service period: November 8-December 8, 2022 (31 billing days).
- Delivery utility: Pacific Gas and Electric Company.
- Generation provider: Central Coast Community Energy, branded `3Cchoice`.
- PG&E schedule printed on the bill: `Time-of-Use (Peak Pricing 4 - 9 p.m. Every Day)`, corresponding to E-TOU-C.
- 3CE schedule printed on the bill: `MBRETCH1 3Cchoice Time-of-Use (Peak Pricing 4 - 9 p.m. Every Day)`.
- Meter readings: current/prior readings and actual-versus-estimated status are not printed. Meter-delta verification must return `cannot_verify`.

The statement is publicly distributed and anonymized: account, meter, service-agreement, and customer identifiers are placeholders.

## Printed quantities

| Field | Printed value | Evidence |
| --- | ---: | --- |
| Total usage | 327.119 kWh | Page 3 |
| Peak usage | 92.965 kWh | Page 3 |
| Off-peak usage | 234.154 kWh | Page 3 |
| Baseline territory | T | Page 3 |
| Heat source | Basic / not electric | Page 3 |
| Baseline allowance | 232.50 kWh | Page 3 |
| Daily baseline quantity | 7.5 kWh/day | Page 3 |
| November 3CE peak | 66.850 kWh | Page 4 |
| November 3CE off-peak | 180.769 kWh | Page 4 |
| December 3CE peak | 26.115 kWh | Page 4 |
| December 3CE off-peak | 53.385 kWh | Page 4 |

Quantity invariants:

- `92.965 + 234.154 = 327.119 kWh`
- `31 x 7.5 = 232.50 kWh`
- `66.850 + 180.769 + 26.115 + 53.385 = 327.119 kWh`

## Applicable official rate sources

| Source | Effective range | Local snapshot | SHA-256 |
| --- | --- | --- | --- |
| PG&E historic residential inclusive TOU rates | 2022-06-01 through 2022-11-30 | `sources/pge-residential-inclu-tou-2022-06-01-to-2022-11-30.xlsx` | `d25d2042a895e1715fd0bdd5166cfa513d5aa1c715ab0dc51382e034dd093958` |
| PG&E historic residential inclusive TOU rates | 2022-12-01 through 2022-12-31 | `sources/pge-residential-inclu-tou-2022-12-01-to-2022-12-31.xlsx` | `2bae786f92efa2eba420adc35e50b80dab71726a43d45f664283fbf744981589` |
| PG&E baseline quantities | 2022-06-01 onward; winter quantities from 2022-10-01 | `sources/pge-residential-baseline-2022-06-01-present.xlsx` | `f9069d80c963341d81adcac87684c6a4b0893b9d6fda21cba11fb2f34dc36bfe` |
| 3CE residential generation rates | Effective 2022-03-01 | `sources/3ce-residential-rate-sheet-effective-2022-03-01.pdf` | `774a4f035824713acb0671935f6276516ff33f30026cd008947b170b2543b279` |

PG&E source index: https://www.pge.com/tariffs/en/rate-information/electric-rates.html

PG&E's December workbook explicitly says there was no E-TOU-C rate change from June 1 through December 31, 2022. Both PG&E workbooks list winter E-TOU-C peak at `$0.39193/kWh`, off-peak at `$0.37460/kWh`, and the baseline credit at `-$0.09054/kWh`. PG&E's baseline workbook lists `7.5 kWh/day` for winter, territory T, individually metered basic-electric service. The 3CE sheet lists winter E-TOU-C peak at `$0.13800/kWh`, off-peak at `$0.09000/kWh`, and a 2020-vintage franchise fee at `$0.00099/kWh`.

## Hand-checked supported calculations

Currency lines round the unrounded product to cents using decimal half-up unless the printed line itself demonstrates another rule.

| Line | Deterministic calculation | Expected | Printed | Status |
| --- | --- | ---: | ---: | --- |
| PG&E peak energy | `92.965 x 0.39193` | $36.44 | $36.44 | calculable |
| PG&E off-peak energy | `234.154 x 0.37460` | $87.71 | $87.71 | calculable |
| PG&E baseline credit | `232.50 x -0.09054` | -$21.05 | -$21.05 | calculable |
| 3CE Nov peak | `66.850 x 0.13800` | $9.23 | $9.23 | calculable |
| 3CE Nov off-peak | `180.769 x 0.09000` | $16.27 | $16.27 | calculable |
| 3CE Dec peak | `26.115 x 0.13800` | $3.60 | $3.60 | calculable |
| 3CE Dec off-peak | `53.385 x 0.09000` | $4.80 | $4.80 | calculable |
| Franchise fee | `327.119 x 0.00099` | $0.32 | $0.32 | calculable |

The authentic fixture reconciles internally:

- PG&E detail lines sum to `$62.11`.
- 3CE detail lines sum to `$34.33`.
- Current electricity charges are `$62.11 + $34.33 = $96.44`.
- The prior `$0.20` credit produces the printed amount due: `$96.44 - $0.20 = $96.24`.

## Support boundary

| Bill line | MVP treatment | Reason |
| --- | --- | --- |
| PG&E peak, off-peak, baseline credit | `calculable` | Exact quantities and effective official rates are available. |
| 3CE peak/off-peak generation | `calculable` | Exact period quantities and effective official rates are available. |
| Franchise fee surcharge | `calculable` | Exact total usage and the published 2020-vintage rate are available. |
| Section subtotals and amount due | `reconcilable_only` | Printed arithmetic can be checked independently of tariff eligibility. |
| 3CE utility users' tax | `calculable` | The bill prints the 1.000% rate and the taxable period charges. |
| Generation credit | `unsupported` | The matching PG&E generation-credit component source is not archived. |
| PCIA | `unsupported` | The 3CE sheet's 2020-vintage rate calculates `$4.50`, not the printed `$4.53`; WattProof must not force a match. |
| Energy Commission tax | `unsupported` | The exact effective tax source has not been archived. |
| PG&E utility users' tax | `reconcilable_only` | The precise taxable base and utility rounding rule are not sourced. |
| Meter delta / actual-estimated status | `cannot_verify` | The sample omits both meter readings and status. |
| Alternative-plan savings | `cannot_verify` | Aggregate 4-9 p.m. usage cannot reconstruct 5-8 p.m. or hourly usage; interval data is required. |

This boundary is intentional: WattProof reports unsupported lines and still verifies every supported dollar without inventing the rest.
