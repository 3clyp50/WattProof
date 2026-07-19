# BillHawk — Execution Checklist

Deadline: **Tuesday, July 21, 2026 at 5:00 PM PT**. Work in priority order. Do not begin stretch work until the judged vertical slice is runnable and tested.

## P0 — Preserve the Codex build evidence

- [x] Start the main implementation in one primary Codex session.
- [x] Tell Codex explicitly that this is an OpenAI Build Week project using Codex and GPT-5.6.
- [x] Keep most core implementation work in that session so its `/feedback` ID is representative.
- [ ] Run `/feedback` before submission and record the Session ID.
- [x] Create `CODEX_LOG.md` and record major prompts, architectural decisions, Codex-generated components, human corrections, failed approaches, and verification results.
- [x] Never place API keys, account data, addresses, meter numbers, or unredacted bills in the repository or Codex prompt.

## P0 — Bootstrap the repository

- [x] Create or select the final Git repository for BillHawk.
- [x] Copy in `PLAN.md`, `TODO.md`, and only the sanitized/public assets needed for development.
- [x] Add `.gitignore`, `.env.example`, license, and a placeholder `README.md`.
- [x] Choose the smallest viable stack and document the decision in `CODEX_LOG.md`.
- [x] Add one-command development startup.
- [x] Add scripts for test, lint, type-check, and build.
- [ ] Verify a clean clone can install and start without undocumented local state.

## P0 — Establish ground truth before coding the engine

- [x] Inspect `assets/pge-sample-consolidated-bill.pdf` and identify:
  - [x] billing period;
  - [x] rate schedule;
  - [x] delivery utility;
  - [x] generation provider/CCA;
  - [x] all printed quantities and charge lines;
  - [x] actual versus estimated meter readings.
- [x] Determine whether the existing pricing PDF matches the sample bill's effective period.
- [x] Download/archive the exact official tariff or rate source that governed the sample period.
- [x] Record source URL, retrieval date, effective dates, and file hash.
- [x] Mark each bill line as `calculable`, `reconcilable only`, or `unsupported`.
- [x] Hand-calculate at least one complete supported charge path.
- [x] Have a second pass—human or Codex—independently check the hand calculation.
- [x] Save expected extraction and expected audit fixtures as JSON.

## P0 — Define trustworthy data contracts

- [x] Define and version `BillExtraction`.
- [x] Preserve page number, quoted source text, confidence, units, and printed/inferred status for material fields.
- [x] Define `TariffVersion` with schedule, jurisdiction, effective range, source, snapshot hash, and retrieval date.
- [x] Define `AuditLine` with billed amount, expected amount, delta, formula, inputs, citation, status, and limitations.
- [x] Define explicit statuses: `verified`, `discrepancy`, `estimated`, `cannot_verify`, and `needs_review`.
- [x] Use decimal currency arithmetic and document rounding tolerances.
- [x] Reject impossible or internally inconsistent extracted data.

## P0 — Build the headless vertical slice

- [x] Extract native PDF text before invoking vision.
- [x] Use GPT-5.6 structured output to map bill evidence into `BillExtraction`.
- [x] Validate line-item, subtotal, total, and meter-usage invariants.
- [x] Return low-confidence or inconsistent fields for user correction.
- [x] Implement the first PG&E tariff adapter for the exact sample schedule and period.
- [x] Produce a calculation trace for every supported charge.
- [x] Reconcile expected versus printed amounts within explicit tolerances.
- [x] Label unsupported fees/riders without guessing.
- [x] Expose the flow through a CLI or API before building the polished UI.
- [x] Verify the authentic sanitized fixture produces the hand-checked result.

## P0 — Prove discrepancy detection honestly

- [x] Create a clearly labeled synthetic altered fixture derived from sanitized data.
- [x] Change one auditable input or charge by a known amount.
- [x] Record the expected discrepancy and rationale.
- [x] Add a regression test that catches the exact discrepancy.
- [x] Ensure the UI and demo never imply the synthetic error was found on a real customer's bill.

## P0 — Build the coherent product flow

- [x] Upload screen with supported-provider notice and truthful privacy copy.
- [x] Sample-mode button so judges can run the demo instantly.
- [x] Extraction-review screen with bill evidence and editable low-confidence fields.
- [x] Audit screen with a plain-language verdict and line-by-line calculation traces.
- [x] Visible source/effective-date citations for rates.
- [x] Distinct visual treatment for verified facts, possible discrepancies, estimates, and unsupported checks.
- [x] Rate-plan comparison screen or a clear missing-data explanation.
- [x] Evidence-grounded review-request screen with editable copy.
- [x] Loading, invalid-file, partial-extraction, unsupported-provider, and API-error states.
- [x] Responsive layout and keyboard-accessible primary flow.

## P0 — Ground the generated review request

- [x] Keep the MVP request deterministic; any future GPT-5.6 drafting path may receive only structured verified audit facts.
- [x] Require neutral language asking the provider to clarify or review the bill.
- [x] Include tariff citation, disputed/reviewed line, expected amount, billed amount, and delta.
- [x] Prevent the model from adding amounts, causes, laws, or accusations absent from the audit.
- [x] Add a test ensuring every material claim maps to an `AuditLine`.
- [x] Require user review before copy/download; do not send automatically.

## P0 — Testing and release gate

- [x] Unit tests for decimal and rounding behavior.
- [x] Boundary tests for billing dates and tariff effective dates; tiers and alternate TOU windows are outside this single-period adapter.
- [x] Golden extraction test using the sanitized sample.
- [x] Golden audit test using the hand-checked fixture.
- [x] Synthetic discrepancy regression test.
- [x] Missing-data test that refuses an invalid plan comparison.
- [x] Unsupported-provider test with a useful result.
- [x] Letter-grounding test.
- [x] Browser-level happy path from sample upload to review request.
- [ ] Run test, lint, type-check, and production build.
- [ ] Test from a clean clone/environment.
- [x] Confirm no secrets or personal data are tracked.

## P1 — Rate-plan comparison

- [ ] Implement a second supported PG&E schedule only after the initial audit is correct.
- [x] Define the usage detail required for a valid comparison.
- [ ] Compare a bill period using actual printed buckets where available.
- [x] Do not annualize a single month without an explicit, defensible method and disclaimer.
- [ ] Show assumptions, source, effective date, and calculation trace.
- [x] If source data is insufficient, explain how the user can obtain interval usage instead of estimating silently.

## P1 — GPT-5.6 extraction robustness

- [ ] Add rendered-page vision fallback for scanned PDFs/images.
- [ ] Compare native text values with vision values when both are available.
- [ ] Retry or request correction on disagreement rather than choosing silently.
- [ ] Test digit transpositions, missing negative signs, duplicated lines, and unreadable scans.
- [x] Establish file-size, page-count, and supported-format limits.

## P1 — README and judge experience

- [x] Explain the problem, audience, differentiation, and PG&E-first scope.
- [x] Include architecture diagram or concise architecture section.
- [x] Document setup, environment variables, run, test, and sample-mode steps.
- [x] State which utilities, schedules, and effective periods are actually supported.
- [x] Document known limitations and privacy behavior.
- [x] Explain: GPT-5.6 reads and drafts; deterministic code validates and calculates.
- [x] Explain how Codex accelerated tariff implementation, schemas, tests, debugging, and product development.
- [x] Include sample screenshots/GIF only after the UI is final.
- [x] Provide a hosted demo or a judge-friendly local/sandbox route.

## P1 — Submission package

- [ ] Select **Apps for Your Life**.
- [x] Draft the Devpost project description around the consumer tariff-audit whitespace.
- [ ] Verify the code repository is public with suitable licensing, or share a private repository with the required judging addresses.
- [x] Ensure sample data and complete setup instructions are committed.
- [ ] Record the primary Codex `/feedback` Session ID in the submission form.
- [ ] Produce a public YouTube demo under three minutes.
- [ ] In the video, explain both Codex use and GPT-5.6 use.
- [ ] Demonstrate a working product, not slides or mockups.
- [ ] Rehearse the final video against the judging criteria.
- [ ] Submit before Tuesday, July 21 at 5:00 PM PT; leave buffer for upload and Devpost issues.

## P2 — Stretch only after submission readiness

- [ ] OpenEI URDB lookup for utility/schedule discovery, with freshness shown.
- [ ] Second utility adapter backed by official tariff snapshots.
- [ ] Downloadable audit report.
- [ ] Visual bounding-box highlights linking results to bill evidence.
- [ ] Shareable redacted result.
- [ ] Additional accessibility polish and screen-reader testing.
- [ ] Lightweight telemetry only if consented, privacy-preserving, and useful for the demo.

## Cut list if time is short

Cut in this order:

1. URDB/nationwide discovery.
2. Second utility.
3. OCR/image fallback.
4. Downloadable reports and sharing.
5. Rate-plan optimizer if the sample lacks sufficient interval/tier data.

Never cut:

- exact tariff provenance;
- deterministic calculation;
- extraction review and uncertainty states;
- the authentic and synthetic golden fixtures;
- meaningful automated tests;
- a complete upload-to-action product flow;
- Codex session evidence and `/feedback` ID.

## Final go/no-go checklist

Do not record the final demo until all answers are **yes**:

- [ ] Can a fresh user run the sample in under five minutes?
- [x] Can every displayed dollar amount be traced to a printed input and rate source?
- [x] Does the authentic fixture produce the hand-checked result?
- [x] Does the labeled synthetic fixture produce the exact expected discrepancy?
- [x] Does missing data lead to an honest limitation rather than a guess?
- [x] Does the product visibly feel complete across all five steps?
- [ ] Do test, lint, type-check, and build pass?
- [x] Does the README describe exact support and limitations?
- [ ] Does the video show substantive Codex and GPT-5.6 use?
- [ ] Is the `/feedback` Session ID saved?
