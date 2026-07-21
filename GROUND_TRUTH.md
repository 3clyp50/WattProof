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

## PG&E/3CE support boundary

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

## Provider-neutral public fixture ground truth

Retrieved and hash-checked on **2026-07-21**. These Indiana documents are public
adversarial fixtures for a provider-neutral engine, not a geographic product boundary
and not a tariff catalog. They support visible-evidence extraction and deterministic
internal reconciliation only.

The optional fetcher downloads the documents into ignored `tmp/public-samples/`:

```bash
scripts/fetch-public-samples.sh
```

Third-party PDFs are not tracked. A downloaded or pre-existing file is usable only
when its SHA-256 matches the value recorded below.

### Duke Energy Indiana electricity guide

- Official URL: https://www.duke-energy.com/-/media/pdfs/bill-examples/260482-bill-tutorial-handout-res-dei.pdf
- Local optional filename: `tmp/public-samples/duke-electricity.pdf`
- SHA-256: `b131c36a215762796e72f3d20986fbea7e64e2dd611081d8936f8442102c3e9a`
- Document shape: three native-text pages with a complete illustrative residential
  electricity statement.
- Evidence pages: meter and usage on page 1, current charge lines on page 2, and the
  tax explanation on page 3.
- Highest supported level: `internally_reconciled`.

Visible meter arithmetic:

- Previous reading `137956 kWh`.
- Current reading `138957 kWh`.
- `138957 - 137956 = 1001 kWh`.

Visible pre-tax charge arithmetic:

| Line | Printed operands | Printed amount |
| --- | --- | ---: |
| Connection charge | fixed | $13.70 |
| First energy tier | `300 kWh x $0.186556/kWh` | $55.97 |
| Second energy tier | `700 kWh x $0.135777/kWh` | $95.04 |
| Remaining energy tier | `1 kWh x $0.123051/kWh` | $0.12 |
| Rider 60 | `1001 kWh x $0.006090/kWh` | $6.10 |
| Rider 62 | `1001 kWh x -$0.003619/kWh` | -$3.62 |
| Rider 65 | `1001 kWh x $0.002259/kWh` | $2.26 |
| Rider 66 | `1001 kWh x $0.002717/kWh` | $2.72 |
| Rider 67 | `1001 kWh x -$0.006040/kWh` | -$6.05 |
| Rider 68 | `1001 kWh x $0.001947/kWh` | $1.95 |
| Rider 70 | `1001 kWh x $0.000496/kWh` | $0.50 |
| Rider 73 | `1001 kWh x $0.000036/kWh` | $0.04 |
| Rider 74 | `1001 kWh x -$0.001064/kWh` | -$1.07 |

The pre-tax lines sum to the printed `$167.66`. The guide prints a seven-percent
Indiana state tax over those identified lines: `$167.66 x 0.07 = $11.7362`, rounded
half-up to `$11.74`. The printed total is `$167.66 + $11.74 = $179.40`.

Limitation: the guide explicitly describes its dates and charges as illustrative. Its
printed schedule and rates can test tier and rider arithmetic, but they are not
independent published-tariff evidence. WattProof has no Duke tariff adapter and must
never display **Tariff verified** for this fixture.

### CenterPoint Energy Indiana gas guide

- Official URL: https://www.centerpointenergy.com/en-us/CustomerService/Documents/bill-guides/240312-20-EIP-IN%20Gas-bill-guide.pdf
- Local optional filename: `tmp/public-samples/centerpoint-gas.pdf`
- SHA-256: `c0b7d9b0252226078b39d6760308506c28b388729906d3ac54db950b9f819262`
- Document shape: a two-page guide whose rendered gas statement conflicts with a
  separate invisible example in the native text layer.
- Evidence pages: the visible statement summary uses pages 1-2; all audited gas values
  are visibly supported on rendered page 2.
- Highest supported level: `internally_reconciled`.

Only the rendered gas statement supplies ground truth:

| Line | Deterministic calculation | Printed |
| --- | --- | ---: |
| Therm conversion | `108 CCF x 1.03960 therm/CCF` | 112.277 therms |
| Distribution and service | fixed visible line | $96.03 |
| Gas cost | fixed visible line | $27.51 |
| Indiana state sales tax | `($96.03 + $27.51) x 7%` | $8.65 |
| Current gas charges / amount due | `$96.03 + $27.51 + $8.65` | $132.19 |

The PDF's page-two native text also contains a different invisible combined
electric/gas example. The native-only values `534 kWh`, `6.326 therm`, and `$134.69`
are explicit exclusions: they must not enter fixture facts, warnings, evidence
excerpts, calculations, or the audited statement. This is why rendered pixels are
authoritative and embedded text is only an untrusted hint.

The Review step surfaces the existence of that conflict and states that rendered-page
evidence took precedence. The warning does not repeat or ingest any excluded hidden
value.

Limitation: the visible printed conversion, charges, and tax base support internal
math. No independent CenterPoint tariff source is attached, so this fixture does not
support a tariff claim.

### City of Bloomington water guide

- Official URL: https://bloomington.in.gov/sites/default/files/2026-02/Understanding%20Your%20Water%20Bill%202026%20Accessible.pdf
- Local optional filename: `tmp/public-samples/bloomington-water.pdf`
- SHA-256: `a414c296e3dd71a08aa459bb1a7c38fcdeab0c90aa0bb05f7c4e39ae9d70b79c`
- Document shape: a native-text explanatory wrapper containing the actual utility
  statement as a large raster image.
- Evidence page: all audited statement values are visibly supported on rendered page
  1.
- Highest supported level: `internally_reconciled`.

Visible service arithmetic:

| Section | Printed lines | Section subtotal |
| --- | --- | ---: |
| Water | `2 kgal x $3.73 = $7.46`; service `$7.86`; fire protection `$2.93`; sales tax `$1.28` | $19.53 |
| Wastewater | `2 kgal x $7.76 = $15.52`; service `$7.95` | $23.47 |
| Stormwater | fixed charge `$2.70` | $2.70 |
| Sanitation | one small cart at `$6.22` | $6.22 |

The section rollup is `$19.53 + $23.47 + $2.70 + $6.22 = $51.92`, matching both
printed current charges and amount due.

Limitation: a native-text length test sees the wrapper but misses the raster statement.
Only page rendering establishes these values. The printed rates and tax amount support
internal statement checks, not a generalized Bloomington tariff or municipal-tax rule.

## Multi-utility support boundary

| Fixture | Evidence extracted | Internally reconciled | Tariff verified |
| --- | --- | --- | --- |
| PG&E/3CE authentic | Yes | Yes | Yes, exact 2022 adapter only |
| PG&E/3CE labeled synthetic | Yes | Detects the `$5.00` root discrepancy | Exact adapter applies to the labeled regression data |
| Duke illustrative electricity | Yes | Yes | No adapter; illustrative rates only |
| CenterPoint gas | Yes, rendered visible statement only | Yes | No adapter |
| Bloomington water/city services | Yes, including raster statement | Yes | No adapter |

Provider-neutral evidence and arithmetic do not imply nationwide tariff coverage.
Any future adapter must archive exact provider, jurisdiction, schedule, effective
period, rule, and source-hash evidence and must fail closed outside that boundary.
