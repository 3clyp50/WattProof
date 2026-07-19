# WattProof — Product and Build Plan

## 1. Product thesis

**WattProof checks the math on household electricity bills.** A user uploads a bill; WattProof extracts the billed usage and charges, identifies the applicable published tariff, deterministically recomputes the expected charges, explains any discrepancy, compares supported rate plans, and prepares an evidence-backed review request.

> Rocket Money negotiates the price. WattProof verifies the math.

### Target user

A US residential electricity customer who cannot confidently interpret a utility bill, especially a California customer whose consolidated bill includes utility delivery and Community Choice Aggregation (CCA) generation charges.

### Core user outcome

Within two minutes, the user should know:

1. whether the printed line items reconcile;
2. whether the supported tariff math agrees with the bill;
3. whether another supported rate plan could be cheaper, with assumptions clearly stated; and
4. what evidence to send when asking the provider to review the bill.

### Why now

Consumer bill services mostly cancel subscriptions or negotiate discounts. Tariff auditing exists mainly for enterprises. WattProof applies transparent, deterministic bill verification to consumers and uses an LLM only where language and document understanding are appropriate.

## 2. Hackathon constraints and submission requirements

- Track: **Apps for Your Life**.
- Build must use **Codex with GPT-5.6**.
- Submit a working project, category, description, public demo video under three minutes, and a testable code repository.
- Repository must include setup instructions, sample data, and clear run guidance.
- Explain where Codex accelerated development, where key decisions were made, and how GPT-5.6 and Codex were used.
- Preserve the `/feedback` Codex Session ID from the session where most core functionality is built.
- If judges cannot safely reproduce the demo, provide a hosted instance, sandbox, or simple local demo path.

## 3. Judging strategy

| Criterion | What WattProof must demonstrate |
| --- | --- |
| Technological Implementation | Native-PDF and scanned-document extraction into a strict schema; deterministic tariff engines; reconciliation invariants; provenance for every rate; tests built from tariff examples; graceful uncertainty handling. Codex should materially help implement, test, and verify the system—not merely scaffold a landing page. |
| Design | A coherent five-step flow: upload → extraction review → audit result → plan comparison → action letter. Results must be understandable to a non-expert and distinguish verified facts, estimates, assumptions, and unsupported checks. |
| Potential Impact | A concrete consumer problem, a specific initial market (PG&E residential customers), measurable findings in dollars, and a credible path from one utility to nationwide coverage through adapters and URDB. |
| Quality of the Idea | The novel position is consumer-facing tariff verification, not generic bill summarization or negotiation. The product shows its math and cites the governing rate source. |

## 4. MVP scope

### Must work in the judged demo

1. Accept a native PDF and, if practical, an image/scan.
2. Extract into a versioned `BillExtraction` schema:
   - provider and service territory;
   - billing period and number of billing days;
   - tariff/rate-plan identifier;
   - total usage;
   - peak/off-peak or tier quantities when printed;
   - meter reads and whether they are actual or estimated when shown;
   - delivery, generation/CCA, credits, fees, taxes, and printed total;
   - source page and confidence for each material field.
3. Display an extraction-review screen before making conclusions.
4. Verify internal arithmetic:
   - extracted line items sum to section subtotals;
   - section subtotals sum to the printed total;
   - meter delta and printed usage agree when both are available.
5. Support one polished utility adapter: **PG&E residential electricity**, initially the exact schedule represented by the sanitized sample bill.
6. Recompute only charges supported by the available bill data and tariff source.
7. Produce a line-by-line result classified as:
   - verified;
   - discrepancy;
   - estimated;
   - cannot verify from this bill.
8. Show tariff name, effective date, source URL/file, formula, inputs, expected charge, billed charge, and delta.
9. Compare supported alternative PG&E plans only when the bill provides sufficient time/tier data. Otherwise explain what interval data is required—do not invent savings.
10. Generate a calm **bill-review request**, not an accusation, containing only verified evidence.
11. Ship with sanitized sample data and a one-command local run path.

### Nice MVP, after the vertical slice works

- OCR/image upload fallback.
- OpenEI Utility Rate Database lookup to identify candidate utilities and schedules outside PG&E.
- A second PG&E schedule or second utility adapter.
- Downloadable audit report.
- Side-by-side visual highlighting of bill evidence.
- Shareable redacted result.
- Optional user correction of extracted fields followed by deterministic recalculation.

### Explicitly out of scope for the hackathon

- Automatic provider login or payment.
- Sending disputes without user review.
- Claims of nationwide verification from URDB alone.
- Medical billing, telecom billing, or broad financial management.
- Guaranteed savings.
- Year-over-year anomaly detection requiring a long bill history.
- Legal advice or a conclusion that the utility committed wrongdoing.

## 5. Product experience

### Screen 1 — Upload

- A single clear upload target.
- Supported demo provider and schedules stated up front.
- Privacy note: sample mode available; uploads are not retained beyond processing unless the implementation actually guarantees otherwise.

### Screen 2 — Review extracted facts

- Bill preview beside editable extracted fields.
- Low-confidence fields highlighted.
- A visible distinction between printed facts and inferred metadata.
- User confirms or corrects fields before audit.

### Screen 3 — Audit

- Hero result such as `Reconciled`, `Possible $X discrepancy`, or `Insufficient information`.
- A transparent line-item table with formula and citation.
- No red warning language when the result is only uncertain.

### Screen 4 — Compare plans

- Compare only schedules the engine supports.
- State whether the estimate uses actual TOU buckets, aggregate usage, or assumptions.
- Show annualized numbers only when there is enough representative data; otherwise show a bill-period comparison.

### Screen 5 — Take action

- Generate an editable bill-review email/call script.
- Include account-safe placeholders, disputed line, calculated amount, tariff citation, and a request for clarification or correction.
- Copy/download action with a reminder to verify personal details.

## 6. Technical architecture

### Recommended stack

Choose the stack Codex can complete and verify fastest. A pragmatic default:

- Front end: Next.js/React with a small component system.
- API: Next.js server routes or a compact Python/FastAPI service if PDF and tariff tooling is materially easier in Python.
- Data: local files/SQLite for the demo; no account system.
- PDF extraction: native text extraction first, rendered-page vision fallback second.
- LLM: GPT-5.6 structured output for classification/extraction and review-letter wording.
- Calculation: deterministic typed code, never LLM arithmetic.

Do not introduce distributed services, authentication, billing, queues, or a production database unless the core flow is already complete.

### Proposed modules

```text
app/
  upload and results UI
lib/
  extraction/       PDF text, page rendering, GPT schema mapping
  schemas/          bill and audit types with validation
  tariffs/          versioned provider adapters and source metadata
  reconciliation/   invariants and expected-vs-billed calculations
  optimization/     supported-plan comparison with sufficiency checks
  letters/          evidence-grounded review request generation
fixtures/
  sanitized bills, expected extraction JSON, expected audit JSON
sources/
  immutable tariff snapshots plus provenance metadata
tests/
  unit, golden-fixture, and one end-to-end happy path
```

### Data contracts

`BillExtraction` should preserve raw evidence rather than flattening everything into prose. Every material value should support:

```json
{
  "value": 123.45,
  "unit": "USD",
  "sourcePage": 2,
  "sourceText": "Total Electric Charges $123.45",
  "confidence": 0.99,
  "status": "printed"
}
```

`TariffVersion` should include provider, schedule, jurisdiction, effective start/end, source URL, local snapshot hash, retrieval date, and supported calculation rules.

`AuditLine` should include billed amount, expected amount, delta, formula, inputs, tariff citation, status, and limitation text.

### Reliability rules

1. Native PDF text and deterministic parsing are preferred when available.
2. GPT-5.6 returns schema-constrained data and quoted evidence/page references.
3. Validation rejects impossible dates, non-numeric quantities, duplicate lines, and totals outside tolerance.
4. If extraction invariants fail, the UI asks for correction; it does not silently continue.
5. Rates are loaded from versioned snapshots, not scraped live during the judged demo.
6. Calculation code uses decimal arithmetic and explicit rounding rules.
7. Unsupported riders or missing interval data are labeled `cannot verify`.
8. Generated prose receives only structured audit facts; it cannot create a new discrepancy.

## 7. Rate-engine plan

### Initial vertical slice

Implement the schedule and bill composition present in `assets/pge-sample-consolidated-bill.pdf`. Before coding formulas:

1. identify the schedule and effective date printed on the fixture;
2. obtain the matching official tariff/rate source for that exact period;
3. document delivery versus CCA generation responsibility;
4. enumerate each charge and whether it can be independently recomputed from the bill;
5. create a hand-checked expected calculation fixture.

### Adapter interface

Each adapter should answer:

- Can it support this provider, schedule, and billing date?
- What required inputs are present or missing?
- Which charges can it calculate?
- What sources and tariff versions govern those charges?
- What is the expected amount and exact calculation trace?

### URDB positioning

Use OpenEI URDB as discovery/coverage infrastructure, not unquestioned ground truth. Any non-PG&E result sourced only from URDB should be labeled best-effort and show data vintage. Official utility/commission tariffs remain authoritative for polished adapters.

## 8. Testing and proof

### Required checks

- Schema validation for complete, partial, malformed, and corrected extraction.
- Decimal/rounding tests at tier and billing-period boundaries.
- Golden test: sample PDF → expected structured extraction.
- Golden test: expected extraction + tariff snapshot → expected audit lines.
- Negative fixture with a deliberately changed charge that produces a known discrepancy.
- Missing-data test that refuses a false TOU comparison.
- Unsupported-provider test that returns a useful limitation instead of crashing.
- Review-letter test proving every amount and citation comes from the audit result.
- One browser-level happy path covering upload through generated review request.

### Demo integrity

Use one authentic sanitized sample and one clearly labeled synthetic altered fixture. Do not imply that a synthetic discrepancy occurred on a real customer's bill. If the authentic sample reconciles, that is still a successful verification; use the altered fixture to demonstrate detection.

## 9. Codex usage strategy

The submission should show Codex participating across the engineering lifecycle:

1. inspect tariff and bill artifacts and produce implementation notes;
2. define schemas and invariants;
3. implement provider adapters and calculation traces;
4. generate edge-case and golden-fixture tests;
5. debug discrepancies between hand calculations and code;
6. build the product flow and accessibility states;
7. run tests, linting, type checks, and an end-to-end scenario;
8. review for unsupported claims, privacy leaks, and missing citations.

Maintain `CODEX_LOG.md` or a submission notes section recording major prompts, decisions, generated components, human corrections, test failures, and the final `/feedback` Session ID. This is evidence of skillful use, not just a claim that Codex wrote the code.

## 10. Milestones

### Milestone A — Ground truth

- Exact sample schedule and billing period identified.
- Matching tariff sources archived with provenance.
- Hand-worked calculation and extraction schema approved.

**Exit criterion:** one human-verifiable expected audit fixture exists.

### Milestone B — Headless audit engine

- Sample PDF extraction works.
- Validation and user-correction data path exists.
- PG&E adapter creates deterministic audit lines.
- Core tests pass.

**Exit criterion:** a CLI or API turns the sample into a correct structured audit.

### Milestone C — Complete product flow

- Upload, extraction review, audit, comparison, and letter screens work.
- Limitations and citations are visible.
- Responsive and accessible states are acceptable.

**Exit criterion:** a new tester can complete the flow without explanation.

### Milestone D — Submission readiness

- Hosted or one-command test path works from a clean environment.
- README, architecture notes, sample data, screenshots, and license are present.
- Under-three-minute demo is rehearsed.
- Codex usage and `/feedback` Session ID are preserved.

**Exit criterion:** repository and video satisfy every submission requirement.

## 11. Three-minute demo narrative

1. **0:00–0:20 — Problem:** utility bills mix tariff math, fees, credits, and CCA charges; consumers cannot check them.
2. **0:20–0:40 — Upload:** use the sanitized PG&E sample and show structured extraction with page evidence.
3. **0:40–1:20 — Verify:** show deterministic reconciliation and exact tariff citations. Emphasize that GPT-5.6 reads; code calculates.
4. **1:20–1:50 — Detect:** use the clearly labeled altered demo fixture and reveal a known discrepancy with formula and delta.
5. **1:50–2:15 — Optimize:** show an eligible rate-plan comparison or honestly explain why more interval data is needed.
6. **2:15–2:35 — Act:** generate the evidence-backed review request.
7. **2:35–2:50 — Codex:** show tests, adapter architecture, and how Codex accelerated implementation and verification.
8. **2:50–3:00 — Vision:** start with PG&E, extend through auditable utility adapters nationwide.

## 12. Success metrics

For the hackathon, success means:

- the sample bill extracts without manual data entry or with clearly surfaced corrections;
- all displayed arithmetic is reproducible from visible inputs;
- the engine catches the synthetic known discrepancy exactly;
- no unsupported charge is presented as verified;
- a judge can run the full flow in under five minutes;
- the repository demonstrates meaningful tests and Codex-assisted engineering;
- the product feels like a trustworthy consumer tool rather than an invoice-parser demo.

## 13. Source starting points

- PG&E bill explanation: https://www.pge.com/en/account/billing-and-assistance/understand-your-bill.html
- PG&E tariff book, E-TOU-C: https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-TOU-C.pdf
- PG&E residential rate-plan pricing: https://www.pge.com/en/account/rate-plans/find-your-best-rate-plan.html
- OpenEI Utility Rate Database: https://openei.org/wiki/Utility_Rate_Database
- OpenEI utility-rates API: https://apps.openei.org/services/doc/rest/util_rates/
- CPUC CCA consumer information: https://www.cpuc.ca.gov/consumer-support/consumer-programs-and-services/electrical-energy-and-energy-efficiency/community-choice-aggregation-and-direct-access-/consumer-information-on-ccas---frequently-asked-questions
- Arcadia Signal cost calculation reference, as B2B prior art: https://docs.arcadia.com/v2022-12-21-Signal/reference/calculate

Verify the effective dates and contents of all rate sources during implementation. URLs alone are not calculation provenance.