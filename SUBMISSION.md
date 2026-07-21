# WattProof submission draft

This file is the source of truth for the Devpost entry and demo recording. Replace every `TODO(submission)` value with the final public artifact before submitting.

## Devpost fields

- **Project name:** WattProof
- **Tagline:** Review electric, gas, water, and sanitation bills from rendered-page evidence. Deterministic code checks printed math, and exact adapters verify published tariffs only where archived sources support them.
- **Submitter type:** Team of Individuals
- **Team:** Primary submitter and [Chadwick Jones (`@TerminallyLazy`)](https://devpost.com/TerminallyLazy) — invitation accepted; confirmed WattProof teammate
- **Countries of residence:** Italy; United States (multi-select field)
- **Category:** Apps for Your Life
- **Repository:** https://github.com/3clyp50/WattProof
- **Live demo:** https://wattproof.tech
- **Devpost project:** https://devpost.com/software/wattproof-xtw6ib
- **Demo video:** `TODO(submission): public YouTube URL, under three minutes`
- **Primary Codex feedback Session ID:** `TODO(submission): run /feedback in the main build session`
- **Judge testing instructions:** Open https://wattproof.tech and choose **Audit authentic sample**, **Duke Electric**, **CenterPoint Gas**, or **Bloomington Water**. All five bundled sample paths are deterministic and keyless. Review each statement separately, then add its minimized summary to the temporary Household bundle. For local verification, clone the repository, install `poppler-utils`, create a Python 3.12+ virtual environment, install `requirements.txt`, run `make run`, and open `http://127.0.0.1:8000`.

## Live Devpost requirements

Verified and refreshed through the connected Devpost source on July 19, 2026:

- submissions are open until **July 21 at 5:00 PM PT** (`2026-07-22T00:00:00Z`);
- **Apps for Your Life** is an exact category option (field `27947`);
- the repository URL is required (field `27948`);
- the primary `/feedback` Session ID is required (field `27950`);
- a viewable YouTube video under three minutes is required, with audio explaining both Codex and GPT-5.6; the July 18 organizer announcement confirms **Unlisted is acceptable**;
- a hosted website and ZIP upload are not required.

## Project description

Households receive separate electric, gas, water, wastewater, stormwater, and sanitation statements. Each uses different units, conversions, tiers, taxes, riders, and subtotal relationships. Generic summaries can restate the amount due, but they rarely preserve enough visible evidence to prove the printed arithmetic—or distinguish that internal check from an independently sourced tariff claim.

The problem is both personal and widespread. A nationally representative [Consumer Reports survey](https://advocacy.consumerreports.org/press_release/new-survey-from-consumer-reports-finds-majority-of-households-strained-by-energy-bills-concerned-over-data-centerss-impact-on-bills/) of 2,146 U.S. adults found that 68% said home energy costs strained their household finances to some degree. [PG&E says](https://www.pge.com/en/about/company-information/company-profile.html) its gas and electric service reaches approximately 16 million people. Dedicated tariff-audit products exist for organizations; WattProof brings that line-by-line discipline into a consumer-readable flow.

WattProof renders accepted PDF pages and turns visible page evidence into a reviewable, provider-neutral record. A user confirms each material fact beside its page and printed quote, then deterministic `Decimal` code checks declared meter differences, conversions, rates, percentages, subtotals, and totals. Each line says whether it is **Printed math**, **Statement reconciliation**, or **Published tariff**. Published-tariff scope requires an exact provider, jurisdiction, schedule, period, archived citation, and matching source hash; otherwise the result remains an internal check or `cannot verify`.

The provider-neutral fixtures cover an illustrative Duke electricity guide, a CenterPoint gas statement with CCF-to-therm conversion, and a raster Bloomington water/city-services statement. They reconcile visible printed math without making Indiana or nationwide tariff claims. The narrower exact adapter covers one public anonymized 2022 PG&E delivery and Central Coast Community Energy generation statement. A clearly labeled synthetic version changes one cited peak charge by exactly $5.00 to prove root-cause detection without suggesting it occurred on a real customer's bill.

The complete flow is upload, evidence review, deterministic audit, a temporary Household bundle, and editable provider review requests grounded only in audit facts. Bills are processed sequentially. Only minimized summaries are retained in page memory for the bundle; raw extractions and PDFs are discarded, nothing is written to local or session storage, and refresh clears the bundle. WattProof never contacts a provider or sends a request automatically.

## How it was built

WattProof is a small Python application: Flask serves a framework-free responsive interface; Pydantic defines the versioned extraction, evidence, tariff, audit, comparison, and review-request contracts; and Python `Decimal` code performs all money arithmetic with explicit half-up rounding. Official source snapshots are committed with retrieval metadata and SHA-256 hashes, and the engine refuses to calculate if a source changes.

For an unknown accepted document, WattProof renders every bounded page before GPT-5.6 uses schema-constrained OpenAI Responses API output to map the visible page images into typed evidence. Rendered pixels are authoritative; embedded PDF text is only an explicitly untrusted hint and cannot become evidence by itself. GPT-5.6 does not choose rates, calculate charges, or invent missing data, and API storage is disabled. Hash-known public fixtures run locally without a key.

Codex drove the primary build session: it rendered and inspected the supplied documents, rejected unsuitable sample paths, researched matching effective-period sources, independently checked tariff math, designed the smallest architecture, implemented the engine and five-step UI, created golden and synthetic regression fixtures, diagnosed browser failures, and verified the final flow. `CODEX_LOG.md` preserves prompts, decisions, failures, corrections, verification results, and milestone commits.

## What makes it different

- **Effective-period truth:** a newer tariff is not treated as better when it did not govern the bill.
- **Provider-neutral evidence:** electric, gas, water, and city-service sections share one typed contract without pretending their tariffs are interchangeable.
- **Evidence before automation:** users can correct extracted facts before any conclusion is calculated.
- **Deterministic money:** GPT-5.6 reads evidence; typed code owns arithmetic.
- **Private sequential bundle:** page-memory summaries combine reviewed bills without retaining raw documents or surviving refresh.
- **Visible uncertainty:** unsupported riders and insufficient interval data remain explicit limitations.
- **Action without overclaiming:** the final request asks for review and cites the exact lines and sources involved.

## Challenges and lessons

The hardest problem was not PDF parsing or interface polish. It was establishing trustworthy ground truth. I initially expected the newest rate source to be the best one, but the supplied current PG&E pricing summary is effective in 2026 while the auditable statement is from 2022. Applying the current rates would have produced a polished but false demo. A July 19, 2026 search found newer guidance but no newer complete ordinary residential sample with a coherent matching rate source, so WattProof uses the newest coherent public bill-and-tariff pair found and explains that choice.

That constraint shaped the product: provenance is executable, arithmetic is reproducible, uncertainty survives extraction, and the comparison step refuses to annualize one aggregate month or reconstruct time windows it cannot observe.

## Demo script — target 2:45

The quoted lines are a speaking guide, not something to recite mechanically. Keep the human pauses; rehearse toward **2:35–2:45** so YouTube processing cannot push the result over three minutes.

### 0:00–0:10 — Start with the question

*Show the WattProof landing page. Let the name and promise settle before clicking.*

> Most bill apps tell you what you paid. WattProof asks a harder question across electric, gas, water, and city services: what can this statement actually prove?

### 0:10–0:32 — The discovery that shaped the product

*Show the electric, gas, and water public-sample choices, then keep the PG&E sample's December 2022 label visible.*

> The same evidence contract reviews electric, gas, water, and sanitation statements, but tariff coverage is deliberately narrower. Codex caught a real audit trap: the complete PG&E sample is from 2022, so WattProof uses its matching historical sources instead of a newer, inapplicable rate sheet.

### 0:32–0:58 — Evidence before conclusions

*Click **Audit authentic sample**. Move slowly across the service dates, E-TOU-C schedule, providers, confidence, page number, and printed quote.*

> This is a public anonymized PG&E and Central Coast Community Energy statement. Before math runs, WattProof creates a reviewable evidence record. Dates, schedule, providers, usage, and charges keep their confidence, page number, and printed quote. The user can correct any field. AI does not get the last word.

### 0:58–1:25 — Show the arithmetic, including its boundary

*Click **Confirm & run audit**. Show the green verdict, then expand the PG&E peak-energy calculation so the rate, formula, effective dates, and source are readable.*

> Once confirmed, typed Decimal code takes over. Eight charge lines match attached published sources, two utility-tax lines agree only as printed math, and four statement totals reconcile. Six lines remain cannot verify. The ledger keeps those scopes separate, so one exact adapter never turns an uncited rate into tariff truth.

### 1:25–1:43 — Let an honest “no” be a feature

*Click **Check plan fit** and hold on “More data needed” and the Green Button requirement.*

> The same honesty applies to savings. This bill only reports aggregate peak and off-peak usage, so it cannot reconstruct another plan's hours. Instead of inventing a dollar figure, WattProof asks for interval data. If the evidence stops, the claim stops.

### 1:43–2:08 — Prove discrepancy detection

*Restart, choose **Detect a labeled $5 synthetic error**, keep the synthetic warning visible, and continue to its red audit verdict.*

> Now I’ll switch to the clearly labeled synthetic fixture. It changes one printed peak charge from thirty-six dollars and forty-four cents to forty-one dollars and forty-four cents. WattProof finds exactly the five-dollar error. The subtotal mismatch confirms the alteration, but is not double-counted. This never appeared on a real bill; it exists to prove the detector works.

### 2:08–2:25 — Build a private household view

*Add the reviewed result to Household and show the prepared multi-utility bundle screenshot or a second reviewed sample summary.*

> Bills are reviewed one at a time, then only minimized summaries enter this temporary household view. Raw bills are not stored, refresh clears everything, and compatible overlapping amounts are combined only when the currency and service periods support it. Provider requests remain editable and are never sent automatically.

### 2:25–2:42 — Explain the collaboration clearly

*Show a prepared terminal with the green `make verify` result, then `CODEX_LOG.md` or the README's “Codex and GPT-5.6” section.*

> I built WattProof with Codex and GPT-5.6. Codex helped inspect the source documents, expose hidden-text and date traps, implement and debug the product, and capture seven reproducible desktop and mobile screenshots. GPT-5.6 maps rendered pages into a strict schema. It never chooses rates or calculates money; deterministic code does that.

### 2:42–2:48 — Close on the principle

*Return to the result or hold on the WattProof mark.*

> WattProof is not pretending to know everything. It shows what can be proven, what cannot, and what to ask next.

## Pre-submission proof

- [ ] Replace the remaining `TODO(submission)` fields above.
- [x] Run `make verify` in a fresh environment.
- [x] Confirm the authentic and synthetic demo paths in Chromium.
- [x] Preserve the seven real-app desktop/mobile captures and reproduction steps in `docs/screenshots/`.
- [ ] Record at 1080p with readable text and no private tabs, keys, or notifications.
- [ ] Keep the final video under 3:00 after YouTube processing, with audio covering both Codex and GPT-5.6.
- [ ] Open the processed YouTube URL in an incognito window and confirm it plays without authentication.
- [x] Make the repository accessible to judges and confirm setup from its public URL.
- [x] Populate the Build Week submission draft with the write-up, repository, stack, and thumbnail.
- [x] Confirm Chadwick has accepted the WattProof project invitation and appears as a teammate.
- [ ] Confirm Chadwick's OpenAI Build Week registration and eligibility details are complete.
- [ ] In this primary Codex session, run `/feedback`, choose to share the existing session, submit the feedback, and preserve the returned Session ID.
- [ ] Submit before Tuesday, July 21, 2026 at 5:00 PM PT with upload buffer.
