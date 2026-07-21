# WattProof submission draft

This file is the source of truth for the Devpost entry and demo recording. Replace every `TODO(submission)` value with the final public artifact before submitting.

## Devpost fields

- **Project name:** WattProof
- **Tagline:** Upload an electricity bill to WattProof. GPT-5.6 extracts evidence, while deterministic code checks each charge against the tariff in effect, flags errors, and drafts a review request.
- **Submitter type:** Team of Individuals
- **Team:** Primary submitter and [Chadwick Jones (`@TerminallyLazy`)](https://devpost.com/TerminallyLazy) — U.S. electricity-billing research and domain specification
- **Countries of residence:** Italy; United States (multi-select field)
- **Category:** Apps for Your Life
- **Repository:** https://github.com/3clyp50/WattProof
- **Live demo:** https://wattproof.tech
- **Devpost project:** https://devpost.com/software/wattproof-xtw6ib
- **Demo video:** `TODO(submission): public YouTube URL, under three minutes`
- **Primary Codex feedback Session ID:** `TODO(submission): run /feedback in the main build session`
- **Judge testing instructions:** Open https://wattproof.tech and click **Audit authentic sample**; no credentials or API key are required for the complete authentic and labeled-synthetic paths. The known public PDF can also be uploaded directly. For local verification, clone the repository, install `poppler-utils`, create a Python 3.12+ virtual environment, install `requirements.txt`, run `make run`, and open `http://127.0.0.1:8000`.

## Live Devpost requirements

Verified and refreshed through the connected Devpost source on July 19, 2026:

- submissions are open until **July 21 at 5:00 PM PT** (`2026-07-22T00:00:00Z`);
- **Apps for Your Life** is an exact category option (field `27947`);
- the repository URL is required (field `27948`);
- the primary `/feedback` Session ID is required (field `27950`);
- a viewable YouTube video under three minutes is required, with audio explaining both Codex and GPT-5.6; the July 18 organizer announcement confirms **Unlisted is acceptable**;
- a hosted website and ZIP upload are not required.

## Project description

Electricity bills combine meter data, time-of-use buckets, delivery rates, generation rates, credits, taxes, and riders into a document most households cannot independently check. Generic bill summaries can restate the total, but they rarely prove whether a charge follows the tariff that governed that exact billing period.

The problem is both personal and widespread. A nationally representative [Consumer Reports survey](https://advocacy.consumerreports.org/press_release/new-survey-from-consumer-reports-finds-majority-of-households-strained-by-energy-bills-concerned-over-data-centerss-impact-on-bills/) of 2,146 U.S. adults found that 68% said home energy costs strained their household finances to some degree. [PG&E says](https://www.pge.com/en/about/company-information/company-profile.html) its gas and electric service reaches approximately 16 million people. Dedicated tariff-audit products exist for organizations; WattProof brings that line-by-line discipline into a consumer-readable flow.

WattProof turns a bill into a reviewable evidence record, then checks supported charges with deterministic arithmetic. A user uploads a native PDF, confirms every material extracted fact beside its page and printed quote, and receives a line-by-line reconciliation against archived official rate sources. Every supported result exposes its inputs, full-precision rate, formula, rounding rule, effective dates, and source. When WattProof lacks a governing rule or sufficient usage detail, it says `cannot verify` instead of inventing a rate or savings estimate.

The MVP deliberately handles one public anonymized PG&E delivery and Central Coast Community Energy generation statement exceptionally well. The authentic statement reconciles against its 2022 sources. A separate fixture is clearly labeled synthetic and changes one auditable peak charge by exactly $5.00, proving that the engine detects a known discrepancy without suggesting it occurred on a real customer's bill.

The complete flow is upload, evidence review, deterministic audit, honest plan-comparison sufficiency, and an editable review request grounded only in audit facts. Uploaded files are temporary, the app stores no customer data, and it never contacts a provider or sends the request automatically.

## How it was built

WattProof is a small Python application: Flask serves a framework-free responsive interface; Pydantic defines the versioned extraction, evidence, tariff, audit, comparison, and review-request contracts; and Python `Decimal` code performs all money arithmetic with explicit half-up rounding. Official source snapshots are committed with retrieval metadata and SHA-256 hashes, and the engine refuses to calculate if a source changes.

GPT-5.6 uses schema-constrained OpenAI Responses API output to map unknown native-PDF text into typed evidence. It does not choose rates, calculate charges, or invent missing data. The bundled public sample is recognized by hash and runs entirely locally without an API key. A focused regression proves the model, strict Pydantic schema, disabled API storage, and trusted document-metadata boundary.

Codex drove the primary build session: it rendered and inspected the supplied documents, rejected unsuitable sample paths, researched matching effective-period sources, independently checked tariff math, designed the smallest architecture, implemented the engine and five-step UI, created golden and synthetic regression fixtures, diagnosed browser failures, and verified the final flow. `CODEX_LOG.md` preserves prompts, decisions, failures, corrections, verification results, and milestone commits.

## What makes it different

- **Effective-period truth:** a newer tariff is not treated as better when it did not govern the bill.
- **Evidence before automation:** users can correct extracted facts before any conclusion is calculated.
- **Deterministic money:** GPT-5.6 reads evidence; typed code owns arithmetic.
- **Visible uncertainty:** unsupported riders and insufficient interval data remain explicit limitations.
- **Action without overclaiming:** the final request asks for review and cites the exact lines and sources involved.

## Challenges and lessons

The hardest problem was not PDF parsing or interface polish. It was establishing trustworthy ground truth. I initially expected the newest rate source to be the best one, but the supplied current PG&E pricing summary is effective in 2026 while the auditable statement is from 2022. Applying the current rates would have produced a polished but false demo. A July 19, 2026 search found newer guidance but no newer complete ordinary residential sample with a coherent matching rate source, so WattProof uses the newest coherent public bill-and-tariff pair found and explains that choice.

That constraint shaped the product: provenance is executable, arithmetic is reproducible, uncertainty survives extraction, and the comparison step refuses to annualize one aggregate month or reconstruct time windows it cannot observe.

## Demo script — target 2:45

The quoted lines are a speaking guide, not something to recite mechanically. Keep the human pauses; rehearse toward **2:35–2:45** so YouTube processing cannot push the result over three minutes.

### 0:00–0:10 — Start with the question

*Show the WattProof landing page. Let the name and promise settle before clicking.*

> Most bill apps tell you what you paid. WattProof asks a harder question: was the bill calculated correctly?

### 0:10–0:32 — The discovery that shaped the product

*Keep the public-sample card and its December 2022 label visible.*

> Before I wrote the calculator, Codex caught a real audit trap: the supplied pricing sheet is from 2026, while the complete public statement is from 2022. No newer public sample I found had the full matching evidence. WattProof therefore uses the newest coherent bill-and-tariff pair—because current is not the same as correct.

### 0:32–0:58 — Evidence before conclusions

*Click **Audit authentic sample**. Move slowly across the service dates, E-TOU-C schedule, providers, confidence, page number, and printed quote.*

> This is a public anonymized PG&E and Central Coast Community Energy statement. Before math runs, WattProof creates a reviewable evidence record. Dates, schedule, providers, usage, and charges keep their confidence, page number, and printed quote. The user can correct any field. AI does not get the last word.

### 0:58–1:25 — Show the arithmetic, including its boundary

*Click **Confirm & run audit**. Show the green verdict, then expand the PG&E peak-energy calculation so the rate, formula, effective dates, and source are readable.*

> Once confirmed, typed Decimal code takes over. The authentic bill reconciles wherever archived sources support a calculation: fourteen checks verified, with inputs, full-precision rates, formulas, rounding, and effective dates visible line by line. Six lines remain cannot verify because the exact rule or required evidence is unavailable. WattProof never forces them to match.

### 1:25–1:43 — Let an honest “no” be a feature

*Click **Check plan fit** and hold on “More data needed” and the Green Button requirement.*

> The same honesty applies to savings. This bill only reports aggregate peak and off-peak usage, so it cannot reconstruct another plan's hours. Instead of inventing a dollar figure, WattProof asks for interval data. If the evidence stops, the claim stops.

### 1:43–2:08 — Prove discrepancy detection

*Restart, choose **Detect a labeled $5 synthetic error**, keep the synthetic warning visible, and continue to its red audit verdict.*

> Now I’ll switch to the clearly labeled synthetic fixture. It changes one printed peak charge from thirty-six dollars and forty-four cents to forty-one dollars and forty-four cents. WattProof finds exactly the five-dollar error. The subtotal mismatch confirms the alteration, but is not double-counted. This never appeared on a real bill; it exists to prove the detector works.

### 2:08–2:25 — Turn proof into a useful next step

*Continue to **Prepare review request**. Show the editable message and claim ledger; do not linger on every sentence.*

> Finally, WattProof turns evidence into a calm review request. It asks the provider to confirm missing components, maps each claim back to the audit, and never sends anything automatically.

### 2:25–2:42 — Explain the collaboration clearly

*Show a prepared terminal with the green `make verify` result, then `CODEX_LOG.md` or the README's “Codex and GPT-5.6” section.*

> I built WattProof with Codex and GPT-5.6. Codex helped inspect the source documents, expose the date mismatch, implement and debug the product, and create the regression evidence. GPT-5.6 maps unfamiliar PDF text into a strict schema. It never chooses rates or calculates money; deterministic code does that.

### 2:42–2:48 — Close on the principle

*Return to the result or hold on the WattProof mark.*

> WattProof is not pretending to know everything. It shows what can be proven, what cannot, and what to ask next.

## Pre-submission proof

- [ ] Replace the remaining `TODO(submission)` fields above.
- [x] Run `make verify` in a fresh environment.
- [x] Confirm the authentic and synthetic demo paths in Chromium.
- [ ] Record at 1080p with readable text and no private tabs, keys, or notifications.
- [ ] Keep the final video under 3:00 after YouTube processing, with audio covering both Codex and GPT-5.6.
- [ ] Open the processed YouTube URL in an incognito window and confirm it plays without authentication.
- [x] Make the repository accessible to judges and confirm setup from its public URL.
- [x] Populate the Build Week submission draft with the write-up, repository, stack, and thumbnail.
- [x] Confirm Chadwick has accepted the WattProof project invitation and appears as a teammate.
- [ ] Confirm Chadwick's OpenAI Build Week registration and eligibility details are complete.
- [ ] In this primary Codex session, run `/feedback`, choose to share the existing session, submit the feedback, and preserve the returned Session ID.
- [ ] Submit before Tuesday, July 21, 2026 at 5:00 PM PT with upload buffer.
