# BillHawk Codex Build Log

This log records the primary OpenAI Build Week implementation session for BillHawk, built with Codex and GPT-5.6.

## 2026-07-19 - Session start

### Prompt 001

Build the smallest trustworthy BillHawk vertical slice in `~/a0/BillHawk`: inspect `PLAN.md`, `TODO.md`, `README.md`, and the sanitized PG&E sources; establish tariff ground truth before implementing formulas; keep arithmetic deterministic; preserve uncertainty and source evidence; create golden fixtures and tests before UI polish.

### Decisions

- Treat `/home/eclypso/a0/BillHawk` as the project root.
- Use repository-relative asset paths so clean clones do not depend on an Agent Zero workdir or one developer's home directory.
- Defer stack selection and tariff-engine code until the sample bill period, schedule, charge structure, and matching rate provenance are documented.
- Keep CPUC rate-case, EIA, climate, rebate, and optional utility sources outside the core audit until the PG&E fixture works.

### Verification

- Confirmed the required public/sanitized PDFs exist under `assets/`.
- Found stale Agent Zero workdir paths only in `README.md` and `asset-manifest.json`.
- DeepAPI request `affcc99a-4c4a-4f9a-a545-9c83a51efb30` verified the live Devpost requirements and deadline.
- Rendered and text-inspected the supplied PG&E bill, pricing sheet, SJCE explainer, and optional VCE sample.
- Rejected the supplied PG&E layout explainer as non-auditable and the VCE sample as internally period-inconsistent.
- Selected 3CE's official public anonymized December 2022 PG&E statement as the auditable fixture.
- Matched its E-TOU-C and baseline values against PG&E's official historic workbooks and its generation rates against 3CE's effective March 2022 sheet.
- Hand-checked all supported multiplication and quantity invariants with decimal arithmetic; `GROUND_TRUTH.md` records unsupported lines without guessing.

### Architecture decision

- One Python/Flask process, Pydantic contracts, native `pdftotext`, deterministic `Decimal` arithmetic, server-rendered UI, and no database.
- Sample mode remains fully runnable without an API key. GPT-5.6 is reserved for strict-schema mapping of other native PDFs and grounded prose; it never calculates money.
- Skipped React/Next.js, separate services, OCR, URDB, authentication, and persistence until the judged vertical slice passes.

### Feedback session

- Session ID: pending; run `/feedback` in this primary session before submission.

## 2026-07-19 - Goal and current-source refresh

### Prompt 002

Set an explicit completion goal, follow through efficiently and thoroughly, prefer the most up-to-date data when it can be supported, and make periodic repository commits so the build remains traceable.

### Decisions

- Created one goal covering the complete judged upload-to-action vertical slice, verification, documentation, and periodic commits.
- Initialized `/home/eclypso/a0/BillHawk` as the standalone Git repository; it no longer inherits the unrelated parent repository.
- Prefer the newest *coherent* primary-source bill-and-tariff pair, not a newer rate sheet applied outside its effective period.

### Current-source verification

- DeepAPI searches `ab653280-b289-433b-9ed9-c2f13348005a`, `887f8dc8-14e5-4891-af60-e918750d5186`, and `260aa254-3e53-438f-b8d3-3f1fa206cfaf` looked for complete official 2025/2026 PG&E residential samples.
- The searches found current PG&E tariff material and a March 2026 NEM explainer, but no newer complete ordinary residential sample with auditable line items and a matching effective-period source.
- Retained the December 2022 PG&E/3CE statement as the authentic golden path. The March 2026 PG&E pricing sheet is context only and must never be used to calculate that bill.

## 2026-07-19 - Milestone B headless audit

### Generated components

- Versioned Pydantic contracts for extraction evidence, tariff provenance, audit lines, comparison insufficiency, and review requests.
- Immutable machine-readable rate rules tied to four archived source snapshots; every calculation verifies snapshot hashes before running.
- Native-PDF boundary checks, known-fixture hashing, explicit rejection of the two unsuitable supplied samples, and a GPT-5.6 strict-output path for other native PDFs.
- Decimal half-up reconciliation for ten supported tariff lines plus section, current-charge, amount-due, and meter-data checks.
- A clearly labeled structured synthetic fixture that changes the PG&E peak charge from `$36.44` to `$41.44` and expects one `$5.00` tariff discrepancy.
- A CLI proof through `python3 -m billhawk` and JSON output through `--json`.

### Failure and correction

- The first review-letter grounding test exposed a display bug: the formula formatted the official `$0.39193/kWh` rate as `$0.39/kWh`. The calculation itself was exact, but the visible trace was not. The formula now preserves all published rate digits, and the grounding test checks every dollar token against its cited audit line.

### Verification

- `14 passed` across golden extraction, hand-checked audit values, snapshot hashes, Decimal boundaries, synthetic discrepancy, insufficiency, unsupported-provider, invalid-file, rejected-source, CLI, and review-letter grounding tests.
- Authentic CLI verdict: `Reconciled where the archived sources support a calculation`.
- Synthetic CLI verdict: `Possible $5.00 source-supported discrepancy`; the delivery-subtotal inconsistency corroborates the altered charge but is not double-counted.
- Python bytecode compilation and JSON parsing passed.

## 2026-07-19 - Milestone C product flow

### Generated components

- Stateless Flask routes for the landing page, public sample, temporary native-PDF extraction, and reviewed-extraction audit.
- A framework-free five-step browser flow: upload, evidence review, audit, plan sufficiency, and grounded action.
- Editable facts and line amounts with source page, exact quote, confidence, and printed/inferred status.
- Responsive result treatments for verified, discrepancy, and cannot-verify states; exact source links remain beside each calculation.
- Copy and text-download actions that never send a message and keep the user-review requirement visible.

### Failures and corrections

- The in-app browser control transport closed during two initialization attempts. Switched to the local Playwright CLI harness and preserved the same rendered-browser verification scope.
- CSS `display` rules overrode the native `hidden` attribute, stacking old steps in the page and accessibility tree. Added an explicit `[hidden]` rule and re-ran the complete path.
- The authentic action-screen claim ledger initially said every request had a published source, even though its purpose is to ask for missing component sources. Reworded the ledger and grounded the agreement claim in the three verified PG&E rate lines as well as every unsupported line named.
- The copy button held `event.currentTarget` across an asynchronous clipboard call; the browser cleared it and the success label threw. Stored the button reference before the await and verified the visible `Copied` state with zero console errors.
- Preserved exact credit-rate sign formatting as `-$0.09054/kWh` and listed both period-crossing PG&E workbooks in the synthetic request.

### Browser verification

- Authentic sample: upload → editable evidence review → 14 verified checks / 6 unavailable → honest interval-data state → grounded action request.
- Actual `assets/pge-anonymous-3ce-sample-bill.pdf` upload completed the same five-step path without an API key.
- Synthetic sample kept its no-real-customer banner on every result screen and reported one counted `$5.00` discrepancy plus the corroborating `-$5.00` subtotal inconsistency.
- The supplied non-auditable PG&E layout explainer returned a useful visible rejection message.
- Desktop and 390 × 844 mobile Chromium renders were visually inspected; keyboard-addressable controls and semantic snapshots exposed the intended headings, labels, alert/note roles, and progress states.
- Final clean browser session: zero console errors or warnings through the complete authentic flow and copy action.

### Verification

- `19 passed` after adding Flask route, actual upload, validation, and authentic-letter grounding coverage.
- `node --check`, Python bytecode compilation, JSON parsing, and whitespace checks passed.
- Rendered screenshots are saved under `output/playwright/` for README and judging evidence.

## 2026-07-19 - Milestone D release preparation

### Generated components

- Added effective-period boundary coverage on both sides of the archived tariff window and a duplicate-charge-ID schema rejection case.
- Drafted the Devpost narrative, technical explanation, differentiation, lessons, explicit submission blanks, and a timed 2:35 demo script in `SUBMISSION.md`.

### Verification

- `22 passed` across the expanded deterministic, schema, extraction, API, and web contract suite.
- A fresh clone of milestone commit `ab62720` ran all then-current 19 tests and the Flask smoke path using the existing host dependencies; a true dependency install plus Ruff/MyPy run remains pending permission to create the local development environment.
- A second fresh clone of submission commit `31b4cf7` ran all 22 tests, started the server, rendered the landing route, and returned the authentic sample API payload using only tracked repository files.

### Failure and correction

- The first clean-clone server harness set `BILLHAWK_PORT`, while `run.py` correctly reads the conventional `PORT` variable. The harness failed its probe, stopped the process, and was rerun successfully with `PORT=8877`; no product change was required.
- A manual strict-typing pass identified untyped Flask route returns, charge parameters, and the test line-map helper. Those interfaces were annotated and their normal and error paths reran with 22 passing tests while the actual Ruff/MyPy install remained permission-gated.
