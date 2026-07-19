# BillHawk submission draft

This file is the source of truth for the Devpost entry and demo recording. Replace every `TODO(submission)` value with the final public artifact before submitting.

## Devpost fields

- **Project name:** BillHawk
- **Tagline:** Check the math on your electricity bill.
- **Category:** Apps for Your Life
- **Repository:** `TODO(submission): public repository URL`
- **Demo video:** `TODO(submission): public YouTube URL, under three minutes`
- **Primary Codex feedback Session ID:** `TODO(submission): run /feedback in the main build session`

## Project description

Electricity bills combine meter data, time-of-use buckets, delivery rates, generation rates, credits, taxes, and riders into a document most households cannot independently check. Generic bill summaries can restate the total, but they rarely prove whether a charge follows the tariff that governed that exact billing period.

BillHawk turns a bill into a reviewable evidence record, then checks supported charges with deterministic arithmetic. A user uploads a native PDF, confirms every material extracted fact beside its page and printed quote, and receives a line-by-line reconciliation against archived official rate sources. Every supported result exposes its inputs, full-precision rate, formula, rounding rule, effective dates, and source. When BillHawk lacks a governing rule or sufficient usage detail, it says `cannot verify` instead of inventing a rate or savings estimate.

The MVP deliberately handles one public anonymized PG&E delivery and Central Coast Community Energy generation statement exceptionally well. The authentic statement reconciles against its 2022 sources. A separate fixture is clearly labeled synthetic and changes one auditable peak charge by exactly $5.00, proving that the engine detects a known discrepancy without suggesting it occurred on a real customer's bill.

The complete flow is upload, evidence review, deterministic audit, honest plan-comparison sufficiency, and an editable review request grounded only in audit facts. Uploaded files are temporary, the app stores no customer data, and it never contacts a provider or sends the request automatically.

## How it was built

BillHawk is a small Python application: Flask serves a framework-free responsive interface; Pydantic defines the versioned extraction, evidence, tariff, audit, comparison, and review-request contracts; and Python `Decimal` code performs all money arithmetic with explicit half-up rounding. Official source snapshots are committed with retrieval metadata and SHA-256 hashes, and the engine refuses to calculate if a source changes.

GPT-5.6 uses schema-constrained OpenAI Responses API output to map unknown native-PDF text into typed evidence. It does not choose rates, calculate charges, or invent missing data. The bundled public sample is recognized by hash and runs entirely locally without an API key.

Codex drove the primary build session: it rendered and inspected the supplied documents, rejected unsuitable sample paths, researched matching effective-period sources, independently checked tariff math, designed the smallest architecture, implemented the engine and five-step UI, created golden and synthetic regression fixtures, diagnosed browser failures, and verified the final flow. `CODEX_LOG.md` preserves prompts, decisions, failures, corrections, verification results, and milestone commits.

## What makes it different

- **Effective-period truth:** a newer tariff is not treated as better when it did not govern the bill.
- **Evidence before automation:** users can correct extracted facts before any conclusion is calculated.
- **Deterministic money:** GPT-5.6 reads evidence; typed code owns arithmetic.
- **Visible uncertainty:** unsupported riders and insufficient interval data remain explicit limitations.
- **Action without overclaiming:** the final request asks for review and cites the exact lines and sources involved.

## Challenges and lessons

The hardest problem was not PDF parsing or interface polish. It was establishing trustworthy ground truth. The supplied current PG&E pricing summary is effective in 2026, while the supplied consolidated-bill document is a layout explainer rather than a complete statement. Applying the current rates would have produced a polished but false demo. A July 19, 2026 search found newer guidance but no newer complete ordinary residential sample with a coherent matching rate source, so BillHawk uses the newest coherent public bill-and-tariff pair found and explains that choice.

That constraint shaped the product: provenance is executable, arithmetic is reproducible, uncertainty survives extraction, and the comparison step refuses to annualize one aggregate month or reconstruct time windows it cannot observe.

## Demo script — target 2:35

### 0:00–0:20 — Problem and promise

“Electricity bills mix time-of-use rates, credits, taxes, and multiple providers. BillHawk does not merely summarize the bill—it checks every charge that the evidence and governing tariff can actually support.”

Show the landing page and the three trust promises: evidence, deterministic math, and honest limitations.

### 0:20–0:50 — Authentic evidence review

Click **Audit authentic sample**. On Review, point out the service period, E-TOU-C schedule, PG&E and 3CE providers, confidence, page number, and exact printed quotes. Editability is the human checkpoint before calculation.

### 0:50–1:20 — Deterministic audit

Continue to Audit. Show the authentic reconciled verdict, then expand one PG&E peak-energy trace. Call out the printed kWh, full-precision published rate, formula, expected amount, effective dates, and official source. Mention that `Decimal` code—not GPT—performed the arithmetic.

### 1:20–1:45 — Honest insufficiency

Continue to Compare. Show that BillHawk refuses to claim plan savings because the bill's aggregate peak/off-peak buckets cannot reconstruct a different plan's hourly window. Point to the requested hourly or 15-minute interval data.

### 1:45–2:10 — Synthetic discrepancy

Restart with **Try the labeled $5 synthetic error**. Keep the synthetic banner visible. Continue through Review to Audit and show the one counted $5.00 discrepancy. Explain that the subtotal mismatch corroborates the altered line but is not double-counted.

### 2:10–2:25 — Grounded action

Continue to Act. Show the neutral, editable review request and its claim ledger. Copy it, emphasizing that BillHawk never sends automatically and requires user review.

### 2:25–2:35 — Codex and GPT-5.6

Show a terminal with `make verify`, then briefly show `CODEX_LOG.md`: “Codex helped research provenance, implement and debug the product, and build the test evidence. GPT-5.6 maps document evidence; deterministic code validates and calculates.”

## Pre-submission proof

- [ ] Replace every `TODO(submission)` field above.
- [ ] Run `make verify` in a fresh environment.
- [ ] Confirm the authentic and synthetic demo paths in Chromium.
- [ ] Record at 1080p with readable text and no private tabs, keys, or notifications.
- [ ] Keep the final video under 3:00 after YouTube processing.
- [ ] Make the repository accessible to judges and confirm setup from its public URL.
- [ ] Run `/feedback` in the primary Codex session and preserve its Session ID.
- [ ] Submit before Tuesday, July 21, 2026 at 5:00 PM PT with upload buffer.
