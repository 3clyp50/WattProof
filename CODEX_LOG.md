# WattProof Codex Build Log

This log records the primary OpenAI Build Week implementation session for WattProof, built with Codex and GPT-5.6. Earlier entries have been normalized to the final product name and current checkout path.

## 2026-07-19 - Session start

### Prompt 001

Build the smallest trustworthy WattProof vertical slice in `~/a0/WattProof`: inspect `PLAN.md`, `TODO.md`, `README.md`, and the sanitized PG&E sources; establish tariff ground truth before implementing formulas; keep arithmetic deterministic; preserve uncertainty and source evidence; create golden fixtures and tests before UI polish.

### Decisions

- Treat `/home/eclypso/a0/WattProof` as the project root.
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
- Initialized `/home/eclypso/a0/WattProof` as the standalone Git repository; it no longer inherits the unrelated parent repository.
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
- A CLI proof through `python3 -m wattproof` and JSON output through `--json`.

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
- The electricity-only screenshots saved under `output/playwright/` were historical README and judging evidence for that UI. They are retained in commit history, not presented as current provider-neutral proof.

## 2026-07-19 - Milestone D release preparation

### Generated components

- Added effective-period boundary coverage on both sides of the archived tariff window and a duplicate-charge-ID schema rejection case.
- Drafted the Devpost narrative, technical explanation, differentiation, lessons, explicit submission blanks, and a timed 2:35 demo script in `SUBMISSION.md`.

### Verification

- `22 passed` across the expanded deterministic, schema, extraction, API, and web contract suite.
- A fresh clone of milestone commit `ab62720` ran all then-current 19 tests and the Flask smoke path using the existing host dependencies; a true dependency install plus Ruff/MyPy run remains pending permission to create the local development environment.
- A second fresh clone of submission commit `31b4cf7` ran all 22 tests, started the server, rendered the landing route, and returned the authentic sample API payload using only tracked repository files.

### Failure and correction

- The first clean-clone server harness set `WATTPROOF_PORT`, while `run.py` correctly reads the conventional `PORT` variable. The harness failed its probe, stopped the process, and was rerun successfully with `PORT=8877`; no product change was required.
- A manual strict-typing pass identified untyped Flask route returns, charge parameters, and the test line-map helper. Those interfaces were annotated and their normal and error paths reran with 22 passing tests while the actual Ruff/MyPy install remained permission-gated.
- A support-contract review found that the adapter enforced PG&E and E-TOU-C but did not yet reject a different generation provider or schedule. Added explicit Central Coast Community Energy and MBRETCH1 3Cchoice guards, plus 10 MB and 20-page boundary regressions; all 26 tests pass.
- A release audit tried building the dormant setuptools metadata and exposed ambiguous flat-layout discovery. Explicit discovery made a wheel, but the wheel correctly revealed a deeper mismatch: the supported audit depends on repository-level immutable sources and fixtures that were never intended as Python package data. Removed the unused build metadata and console-script claim rather than ship a misleading partial distribution; the documented repository commands remain the single supported path and all 26 tests/build checks still pass.
- Read-only Devpost verification at `2026-07-19T21:41Z` confirmed that submissions remain open through July 21 at 5:00 PM PT, Apps for Your Life is field `27947`, the repository URL is field `27948`, `/feedback` is required in field `27950`, and the required public sub-three-minute YouTube demo needs audio covering both Codex and GPT-5.6. A hosted website and ZIP are not required. The connected account had no WattProof draft at that point; no Devpost project was created or changed.

## 2026-07-20 - Full static release gate

### Environment

- Created the ignored repository-local `.venv` with Python 3.13.11 after explicit approval and installed `requirements-dev.txt` without changing declared dependency ranges.
- Resolved Flask 3.1.3, OpenAI 1.109.1, Pydantic 2.13.4, Pytest 9.1.1, Ruff 0.15.22, and MyPy 1.20.2.

### Failures and corrections

- The first `make verify` found eight mechanical import-order findings; Ruff's import fixer corrected only those blocks.
- Strict MyPy then found two narrowing gaps. The audit now stores only non-null discrepancy deltas, and the validated Flask sample route explicitly narrows its value to the two accepted fixture literals.

### Verification

- `make verify` passes in the isolated environment: 26 tests, zero Ruff findings, zero MyPy issues across 10 source files, and successful bytecode compilation.
- Fresh clone `4721e62` created a new Python 3.13 virtual environment, installed only `requirements-dev.txt`, passed unchanged `make verify`, started the Flask app, rendered the landing page, and returned the authentic E-TOU-C sample API payload. The complete install-and-verify portion finished well inside the five-minute judge target and left the clone clean.
- The first HTTP harness used an obsolete hero-text assertion after receiving a valid `200`; its cleanup trap stopped the server. Re-running against the stable `Audit authentic sample` control and API value passed without a product change.
- A separate clean Python 3.12.3 environment installed `requirements-dev.txt` and passed the same 26 tests, Ruff, strict MyPy, and build gates, proving the README's stated minimum interpreter version.

## 2026-07-20 - WattProof rebrand

### Decision

- The user selected **WattProof** for its compact combination of electricity and evidence. Live screening found no exact public GitHub repository match for WattProof; `ClearCurrent`, `TariffLens`, and `GridProof` were rejected after collision checks.
- Renamed the product surfaces, Python package, CLI, configuration prefix, tests, downloads, submission copy, local checkout, and Codex project to WattProof. The checkout now lives at `/home/eclypso/a0/WattProof`, matching the public repository.

### Verification

- DeepAPI GitHub request `6efb03c9-2099-4d94-8a90-5308106b8cde` returned zero public repository matches for WattProof; `gh repo view 3clyp50/WattProof` independently confirmed that the target repository did not exist before publication.
- Both Python 3.13.11 and Python 3.12.3 pass 26 tests, Ruff, strict MyPy across 10 source files, and bytecode compilation after the package rename.
- Regenerated all five tracked screenshots from the real WattProof UI. Authentic and labeled-synthetic desktop flows plus the 390 × 844 synthetic audit remain visually coherent and produce zero browser console errors or warnings.
- Current-facing tracked text has no remaining former product identifier. JavaScript syntax, JSON parsing, whitespace, and tracked secret-pattern scans pass.

### Publication

- Committed the full product rename as `e463468` and created the standalone public repository at https://github.com/3clyp50/WattProof.
- Added the repository as `origin`; the submission source now records the confirmed public URL rather than a placeholder.
- Created standalone Devpost project `1354055` before the user surfaced their separately created Build Week submission draft `1105838`, backed by project `1354058`. The duplicate was detected through the connected account rather than guessed from the two URLs.
- Preserved the user's more specific tagline and copied the completed write-up, repository link, technology list, and real landing-page screenshot into project `1354058`. Verification returned the OpenAI Build Week relationship with `submitted_at: null`, so it remains editable and has not been prematurely submitted. Project `1354055` remains unattached to any hackathon and is not used by the submission.

### Checkout normalization

- After the user renamed the checkout and Codex project to WattProof, normalized the remaining historical log references to the final name and current path.
- Removed ignored test, type-check, lint, build, bytecode, and Playwright caches that retained obsolete generated identifiers. These are reproducible artifacts, not source evidence.
- The first post-relocation `make verify` included the new untracked `.codex/skills` bundle and Ruff correctly reported 280 findings in those third-party local tools. Added `.codex/` to `.gitignore` so local Codex project state stays intact but outside the application release and lint boundary.

### Human-led demo narrative

- The user chose to record the demo personally rather than use generated narration. Replaced the mechanical feature tour with a 364-word human script centered on the effective-period discovery, reviewable evidence, deterministic arithmetic, honest insufficiency, labeled synthetic proof, and calm next action.
- The timed script targets 2:35–2:48 and explicitly covers both Codex and GPT-5.6 while keeping the working product on screen. At 135–145 spoken words per minute, the narration runs approximately 2:30–2:41 before brief pauses.

## 2026-07-20 - Judging optimization

### Live rubric and market evidence

- Refreshed the connected Devpost source. The four criteria remain Technological Implementation, Design, Potential Impact, and Quality of the Idea; submissions remain open through `2026-07-22T00:00:00Z`. The latest organizer reminder emphasizes the working demo, explicit Codex and GPT-5.6 use, public video visibility, repository access, and `/feedback` ID.
- DeepAPI searches `a5cfd8f6-d779-4ccf-97cf-a8c95f3070ec`, `feb9f917-6f71-4645-b253-1474cf833ebc`, and `bc32aa0a-13b9-4dc4-b9da-daa6766e5230` found dedicated tariff-audit products aimed primarily at organizations, while consumer-facing utility tools emphasize bill or rate-plan comparison.
- Current-impact searches `c55befb8-7801-4d8b-9f20-97a1b52aaa63`, `960b5fe6-1f10-4439-a507-4476cf7e40ed`, and `6834198e-fe1e-453b-a0aa-8e296bc69895` located the strongest current audience evidence. Direct DeepAPI source reads `b19d501c-1486-4e33-8bb4-674d30cbd3db` and `2da1b895-d98c-4ed8-bc5e-4b3351f83950` verified Consumer Reports' 68% household-strain result and PG&E's approximately 16-million-person service footprint.

### High-leverage proof

- Added one mocked regression for the GPT-5.6 extraction boundary: strict `BillExtraction` output, `store=False`, no calculation or repair instruction, and server-controlled fixture kind, notice, and document hash.
- Added a public GitHub Actions matrix for Python 3.12 and 3.13 using the latest verified major releases of `actions/checkout` and `actions/setup-python`. Local verification now passes 27 tests, Ruff, strict MyPy, and compilation.
- Strengthened the README and submission source with current impact evidence, the consumer-versus-enterprise wedge, and a first-person account of the effective-period decision. Recast unsupported rate optimization and scanned-PDF vision as deliberate post-MVP exclusions rather than ambiguous unfinished work.
- Synced the improved 4,725-character write-up into the correct Devpost project (`1354058`, version 4) and verified its repository URL, impact evidence, Codex explanation, GPT-5.6 explanation, and differentiation. `submitted_at` remains null and `video_url` remains empty, so the entry is still safely editable.
- A final rendered-artifact audit found two ignored local screenshots that predated the rebrand even though searchable source text was clean. Recreated the authentic audit and synthetic action screens at 1440 px from the live app to verify those endpoints, then removed the non-release artifacts. The first reused browser profile also restored unrelated text into an editable textarea; a direct API check proved the generated request was clean, and an isolated fresh browser session reproduced the correct grounded letter. Both verified paths have zero console warnings or errors.

### Final current-bill challenge

- Re-ran three current open-web searches (`fcf0f528-83ea-49e3-b2cb-5f9b22a66768`, `c13d5afb-b4ab-466c-b388-b7ca434db71e`, and `d57c4e17-ede7-4208-a995-500c6886927e`) and a focused DeepAPI research pass (`674dcbc7-0816-4750-9d26-6a65a195f1f7`) for a complete 2024–2026 public residential PG&E/CCA statement with matching effective-period sources.
- Current official PG&E and 3CE tariff sheets, joint rate comparisons, and blank statement forms are available, but no newer public candidate exposes the complete service dates, schedule, quantities, unit rates, line charges, and corresponding CCA evidence required for deterministic reconciliation. The 2022 3CE-hosted anonymized statement remains the newest coherent public pair found.
- Kept the fixture and reframed the demo insight as an audit principle: current is not the same as correct. A newer tariff applied to an older statement would reduce—not improve—the technical validity of the submission.

### Team submission update

- The submission will be made by a Team of Individuals: the primary submitter in Italy and Chadwick Jones (`@TerminallyLazy`) in the United States. The live Devpost country field accepts multiple selections, so both countries will be declared.
- The official eligibility data includes both Italy and the United States. The primary submitter will act as the team's authorized representative. The user confirmed that Chadwick accepted the project invitation and now appears as a WattProof teammate; the project-scoped secret join link remains outside the public repository.

## 2026-07-20 - Production judge demo

### Deployment

- Pointed `wattproof.tech` and `www.wattproof.tech` at the Debian 13 Google Cloud VM and verified both DNS answers. The provider's 900-second TTL is short enough for launch and requires no special handling.
- Built a non-root Python 3.13 and Gunicorn container with Poppler, bound it only to the VM loopback interface, and placed Caddy in front for automatic HTTPS and security headers.
- Added a minimal GitHub Actions deployment job. A push to `main` can reach production only after both Python verification jobs pass; the server then checks out the exact verified commit before rebuilding the container.
- Kept `OPENAI_API_KEY` unset on the public host. Authentic, synthetic, and known-public-PDF paths remain fully functional, while unknown documents fail safely instead of exposing an unauthenticated paid inference endpoint.

### Verification

- The production container reported healthy and served the committed `/healthz` response through both loopback and `https://wattproof.tech`.
- HTTPS returned HTTP/2 `200` for both apex and `www`; plain HTTP returned a permanent redirect to HTTPS. The served sample PDF's SHA-256 matched the tracked source exactly.
- The real public endpoints reconciled the authentic fixture, returned `cannot_verify` for unsupported plan comparison, preserved required user review, detected exactly `$5.00` in the labeled synthetic fixture, and extracted E-TOU-C from an actual upload of the known public PDF.
- A fresh Chromium production pass completed the authentic review-to-audit interaction at desktop width, rendered the landing page at 390 px, and reported zero console errors or warnings.
- Three pushes during GitHub's July 20 Actions incident were recorded as zero-job `startup_failure` runs while Actions and API Requests were degraded. Repository Actions permissions, four deployment secrets, and the workflow's independent Actionlint validation were all correct; no product or workflow change was made for the external outage.
- After GitHub returned to operational status, retry commit `ae92e51` created run [`29722762233`](https://github.com/3clyp50/WattProof/actions/runs/29722762233). Python 3.12 and 3.13 verification passed, the dependent deployment job passed, the VM checked out the exact commit, and the public health and authentic-audit probes remained green.

## 2026-07-21 - Calm, accessible audit experience

> **Historical proof scope:** This section records the electricity-only interface deployed at commit `c51bf9d`. Its browser, screenshot, and WAVE results do not verify the later provider-neutral merged DOM; that interface requires a fresh screenshot and accessibility pass.

### Human direction and design decisions

- Removed the complete `Local sample mode · deterministic math` header treatment, including its status dot. The header now holds only the WattProof identity.
- Replaced the CSS placeholder with a generated symbol-only mark: a restrained `W` waveform/check with receipt-line detail. WattProof remains live text for crisp rendering and accessibility. The source was generated with the built-in image tool, chroma-keyed to transparency with the provided helper, and optimized to a 512 px RGBA PNG.
- Kept the landing headline and lede typography, while removing decorative result rings, gradient page effects, redundant pills, and other dashboard-template cues.
- Preserved the twelve material facts as the required human-review surface. Moved the fifteen printed charge rows and the full twenty-check calculation ledger into closed native disclosures so the default path explains the result before exposing dense evidence.
- Raised the smallest evidence, table, label, status, trace, citation, note, and footer text. Added explicit mobile scroll cues and kept wide tables inside keyboard-focusable local regions rather than widening the page.
- Added Chadwick Jones (`@TerminallyLazy`) to the README and submission source for the U.S. electricity-billing research and domain specification that shaped the charge model, support boundary, and review language.

### Emotional design and interaction craft

- Direct source read `49fc7231-edeb-4d66-9f59-fa129cfb561f` confirmed the useful emotional-design pattern for WattProof: respectful waiting language, low-friction behavior, collapsible depth, tone matched to the consequence, and a clear human handoff.
- Chose a calm corporate motion identity: one 260 ms decelerating step entrance, 120 ms button/file/disclosure feedback, and no bounce, particles, ambient loops, or animation library.
- Loading states already explained the work in progress (`Extracting native PDF…`, `Running exact tariff math…`), so they were retained and now expose `aria-busy`. Copying a review request gives the warmer temporary confirmation `Copied — review before sending`.
- Added a complete `prefers-reduced-motion` path that disables transitions and animation and restores non-smooth scrolling.

### Reliability and accessibility corrections

- A read-only review found that a reconciliation-only mismatch could be described as a `$0.00` discrepancy and that generic uploaded discrepancies inherited synthetic-specific wording. Reconciliation-only failures now use the existing `needs_review` verdict, no unsupported amount claim, and fixture-aware copy. Every permitted line status has an explicit visible label.
- A second end-to-end review followed that state through Act and found the draft still fell back to a missing-rate request. Reconciliation-only failures now produce a separate printed-total request grounded in the exact mismatched audit line and its printed inputs; the regression asserts every amount in the draft.
- The pre-change public WAVE report scored 7.3/10 and mapped one empty heading, one skipped heading, five low-contrast elements, and thirteen small-text alerts. The worktree fixes supply the dynamic heading fallback, repair heading order, darken inactive progress/divider text, and raise all flagged text floors.
- Mobile progress names remain available to assistive technology, active-step navigation returns focus to the visible `h1`, fact and disclosure summaries have strong focus rings, and the decorative logo image stays silent inside the named home link.
- Expanded mobile tables remain locally scrollable: at a 390 px viewport the document/body width is 375 px, while the charge-table region is 283/760 px. Reduced-motion emulation reports a 0.01 ms animation duration and automatic scroll behavior.
- Keyboard Space toggled the native charge disclosure, the reconciliation-only review state was exercised through the browser, the copy confirmation was exposed in the accessibility tree, and the complete local flow produced zero console warnings or errors.

### Verification

- `make verify` passes with 29 tests, zero Ruff findings, strict MyPy clean across 10 source files, and successful bytecode compilation.
- The final production-equivalent Docker image builds successfully, JavaScript syntax and whitespace checks pass, and the existing-source secret-pattern scan is clean.
- Regenerated all five tracked desktop/mobile Playwright artifacts from the real application after the layout and typography changes.
- The first deployed WAVE re-analysis reduced the landing page from the 7.3/10 baseline to 0 errors, 3 contrast errors, 0 alerts, and 8.8/10. WAVE traced all three remaining findings to the amber `01`, `02`, and `03` proof-list numerals.
- Darkened only those numerals from `#eca72c` (1.85:1) to `#765414` (6.16:1 against the paper background), retaining the brighter amber for non-text brand accents. An independent read-only accessibility pass confirmed WCAG AA contrast with no layout, motion, focus, or responsive side effects.
- GitHub Actions run [`29861714811`](https://github.com/3clyp50/WattProof/actions/runs/29861714811) passed both Python verification jobs and deployed exact commit `c51bf9d314e119c86930c80271499c4b29705af2`.
- A fresh cache-busted WAVE evaluation of the deployed domain returned **0 errors, 0 contrast errors, 0 alerts, and an AIM score of 10/10**. WAVE correctly retains the intentionally empty alternative text on the decorative logo image as a feature inside the named `WattProof home` link, not an error.

## 2026-07-21 - Origin-anchored error callouts

> **Historical proof scope:** The deployment, browser, and WAVE claims in this section
> apply to electricity-only commit `52dd69b`. The provider-neutral merge retains the
> anchored-callout behavior but requires its own post-merge browser and screenshot
> evidence before equivalent production claims can be made.

### Notification inventory and interaction decision

- A dedicated read-only subagent traced every user-visible notification and every backend string that can reach it. WattProof has exactly one toast-like renderer: the global error surface used by sample, upload, extraction, and audit failures. Synthetic provenance, loading labels, copied-state feedback, verdicts, line statuses, comparison limitations, and the user-review warning are contextual or inline and remain in place.
- Replaced the detached page-wide error banner with one compact rounded callout that positions above or below the triggering control, clamps within the viewport, and points back with a centered caret. No toast dependency, severity framework, timer, or field-error parser was added.
- Preserved `role="alert"`, associated the visible text with its trigger through `aria-describedby`, retained or restored trigger focus after synchronous and asynchronous failures, and cleared the relationship on retry, file selection, or step change. Errors remain visible until the user acts rather than disappearing on a timer.
- Applied the existing corporate motion identity: a 120 ms decelerating position-and-scale entrance with no bounce. The global reduced-motion rule collapses it to `0.01 ms`.

### Error quality and verification

- Cleaned model-level Pydantic wording from `Review : Value error, …` to a direct `Review: …` message. Added a dedicated 503 response for tariff-source integrity failures so an internal filesystem path can never be exposed in the callout.
- Browser checks covered the no-file error, a long rejected-document explanation, an audit validation failure, an intercepted async sample failure, both above/below caret orientations, scroll and resize tracking, file-selection clearing, keyboard Enter activation, async focus restoration, and a 390 px mobile viewport with no body overflow.
- The authentic review-to-audit path remains console-clean. Intentional 422/503 test responses create only the browser's expected failed-resource network entry; no JavaScript exception or warning occurs.
- `make verify` passes with 30 tests, Ruff clean, strict MyPy clean across 10 source files, successful compilation, clean JavaScript syntax, and no whitespace errors.
- GitHub Actions run [`29867999090`](https://github.com/3clyp50/WattProof/actions/runs/29867999090) passed Python 3.12 and 3.13 verification and deployed exact commit `52dd69bfc42cdcfb580b0f4c5be8ba1c310971d0`.
- A fresh production WAVE evaluation of `wattproof.tech/?wave=52dd69b` retained **0 errors, 0 contrast errors, 0 alerts, and an AIM score of 10/10**. The deployed missing-PDF interaction also retained button focus, its alert description, correct caret geometry, and zero console messages.

## 2026-07-21 - Continue with Codex

> **Historical proof scope:** The deployment and production checks below apply to
> electricity-only commit `9533b08`. That release mapped native PDF text into schema
> 1.0. The provider-neutral merge changes personal extraction to strict schema 2.0
> multimodal rendered-page input with native text only as an untrusted locator hint;
> its verification is recorded separately by the merge commit and current test run.

### Human direction and product decision

- The user rejected an API-key-shaped public experience and proposed a much stronger product moment: let a visitor bring existing Codex access into WattProof through OpenAI's official sign-in. The public authentic and labeled-synthetic paths remain instant and local; the connection exists only for a personal native PDF.
- Removed the legacy operator-side Responses API fallback, its environment variables, and the OpenAI Python SDK dependency. WattProof now has one unambiguous personal-PDF path and no hidden or shared API-key configuration.
- Official Codex documentation confirmed that App Server custom clients can call `account/login/start` with `chatgptDeviceCode`, receive the one-time `https://auth.openai.com/codex/device` handoff, and observe account notifications. Chose this supported device ceremony instead of copying a CLI credential, inventing an OAuth callback, or adding an API-key field.
- Selected GPT-5.6 Luna because the current official model guidance specifically positions it for repeatable structured work such as extraction and classification. The model maps evidence; the existing tariff engine still owns every calculation.

### Protocol failures and corrections

- The first schema-constrained App Server extraction was rejected because Pydantic's Decimal regex uses lookaround that the model schema validator does not support. The strict-schema adapter now preserves validation while removing only unsupported lookaround patterns, removing defaults, requiring every property, and denying additional properties. A recursive regression locks that transformation.
- An initial strict Codex configuration named an unsupported `tools.view_image` key. Removed it, then disabled the supported browser, computer-use, image-generation, shell, unified-exec, multi-agent, plugin, app, hook, memory, goal, and workspace-dependency features instead.
- A real full-bill Luna turn then completed in roughly 95 seconds with 26 top-level fields, all 28 printed charge lines, the trusted document digest, and zero tool calls. Any future turn that reports command, file-change, MCP, browser, image, collaboration, dynamic-tool, or web-search activity is rejected rather than accepted as extraction evidence.

### Isolation and interface

- Added one Codex App Server process per signed opaque browser session. Every process gets a private temporary `CODEX_HOME`, an empty read-only workspace, a deny-by-default filesystem profile, disabled tool networking and web search, no approvals, and an ephemeral extraction thread. Document content is delimited as untrusted evidence and cannot become instructions.
- The browser receives only the one-time code, official OpenAI URL, connection state, model label, and plan label. Passwords and tokens never enter browser storage. Production keeps Codex credentials on `/tmp` tmpfs; logout, a hard 10-minute pending-login limit, or 30 minutes of connected inactivity destroys the process and directory. The service admits eight sessions and a background reaper enforces expiry even when no later request arrives.
- Added a restrained header control, native accessible dialog, copyable device code, connection progress, connected state, disconnect action, concise upload-card status, and exact privacy copy. Desktop and 390 px mobile render cleanly, initial dialog focus lands on Close, Escape works, and the accessibility snapshot exposes the dialog name, code, official link, progress status, and privacy note.

### Verification before deployment

- `make verify` passes with 35 tests, Ruff clean, strict MyPy clean across 11 source files, and successful bytecode compilation. JavaScript syntax and whitespace checks pass.
- The production image pins the official Codex 0.145.0 standalone release by SHA-256 rather than carrying Node/npm or the unused Python SDK. The resulting image is 185 MB and runs as UID 10001.
- An exact production-security container smoke (`read_only`, all capabilities dropped, `no-new-privileges`, PID limit, tmpfs) issued a real OpenAI device code, reported pending status, logged out, and left no Codex temporary directory.
- The browser pass repeated the device-code flow against that container at desktop and mobile sizes, returned the temporary server session to `disconnected`, and recorded zero console errors or warnings. Screenshot evidence replaced the live code with the inert placeholder `ABCD-EFGH` before capture.

### Production verification

- Commit `9533b08aaaa5567c4213c7a242e7dee3a50cf86c` triggered GitHub Actions run [`29871750262`](https://github.com/3clyp50/WattProof/actions/runs/29871750262). Python 3.12 and 3.13 both passed the full gate, and the dependent deployment job placed that exact commit on the VM.
- The deployed read-only container reports Codex 0.145.0. HTTPS checks confirmed a secure, HTTP-only, SameSite=Lax session cookie; real device-code issuance on the official OpenAI URL; pending status; logout; and the unchanged local authentic fixture.
- A fresh 390 px production browser pass confirmed the explicit `Continue with Codex — official OpenAI sign-in` accessible name, initial Close focus, Escape behavior, ten- and thirty-minute privacy copy, successful server cleanup, and zero console errors or warnings.
- A cache-busted WAVE analysis of the deployed release retained **0 errors, 0 contrast errors, 0 alerts, and an AIM score of 10/10**. WAVE also recognizes the new control's explicit label and popup relationship.

## 2026-07-22 - Provider-neutral PR integration

### Chadwick's implementation contribution

- Treated Chadwick Jones's actively updated PR #1 as the source of truth rather than
  overwriting it with a parallel integration. At review snapshot `ab27371`, his branch
  contains 56 commits across 56 changed files and implements the provider-neutral
  schema and invariants, deterministic multi-utility reconciliation and fixtures,
  exact tariff-adapter boundaries, household flow, resource and numeric hardening, and
  eight reproducible real-browser evidence captures.
- Updated the README and submission source to credit that implementation work directly,
  in addition to his U.S. utility-billing research and domain specification.
- Preserved the branch's stronger raw-JSON decimal spelling checks, rendered-page
  validation, Codex schema 2.0 boundary, exact root-cause tracking, accessibility
  contracts, and refreshed screenshot manifest.

### Integration corrections

- The provider-neutral merge had reintroduced an operator-managed Responses API path
  beside the already shipped official Codex device flow. That contradicted the user's
  explicit product decision and this log's earlier record. Removed the duplicate
  transport, `OPENAI_API_KEY` and `OPENAI_MODEL` configuration, compose variables,
  OpenAI Python SDK dependency, API-specific tests, and stale current documentation.
  Unknown personal PDFs now have one clear model route: a temporary visitor-connected
  Codex App Server session. Known public fixtures remain local and keyless.
- Kept rendered pages authoritative and made the validated, numerically ordered page
  tuple the exact input to the connected Codex extractor. Unknown documents without a
  connected session still stop before Poppler work.
- Reworked the large-output Poppler test harness to carry fixture bytes through stdin
  instead of one base64 command-line argument. This avoids Linux's per-argument limit
  on GitHub's Python 3.12 runner without weakening the production resource tests.
- Added superseding notes to historical design and plan documents instead of erasing
  the decision trail. Updated the current architecture, privacy, setup, checklist, and
  submission text to match the single-path runtime.

### Verification

- `PATH="$PWD/.venv/bin:$PATH" WATTPROOF_REAL_BROWSER=1 make verify` passes **575
  tests**, including real Chromium; Ruff is clean; strict MyPy is clean across 28
  source files; and bytecode compilation succeeds.
- A clean production image builds without the OpenAI Python SDK. Under the deployment's
  read-only, capability-dropped, no-new-privileges, PID-limited, tmpfs-backed security
  profile, it passes health, schema 2.0 sample, real official device-code issuance,
  pending status, logout, Codex 0.145.0, and temporary-session cleanup checks.
- The latest fetched PR head remained exactly `ab27371` during integration; its prior
  Python 3.12/3.13 checks and CodeRabbit status were green. No force-push or history
  rewrite was used.
- Public WAVE evaluation of the currently deployed pre-PR site remains **0 errors, 0
  contrast errors, 0 alerts, and 10/10 AIM**. This is a production-baseline result, not
  certification of the provider-neutral branch; that branch requires a fresh public
  WAVE run after deployment. Its current local accessibility evidence is the real-
  browser suite and the eight explicitly non-certification screenshots.

### Merge and deployed accessibility follow-up

- Merged PR #1 with merge commit `0eb82e779e0652de8c48929e794f4a8d465c78df`,
  preserving Chadwick's complete 56-commit branch ancestry. GitHub now recognizes him
  as a repository contributor. The merge-triggered Python 3.12, Python 3.13, and deploy
  jobs all passed in Actions run
  [`29876294564`](https://github.com/3clyp50/WattProof/actions/runs/29876294564).
- Verified the deployed provider-neutral release through its health endpoint, schema
  2.0 Duke sample endpoint, landing-page utility choices, and official Codex sign-in
  affordance.
- A new public WAVE evaluation of that deployed merge found **1 error, 0 contrast
  errors, 0 alerts, and 9.7/10 AIM**. The error was an empty hidden comparison section
  whose initial `aria-labelledby` value referenced a heading created only when a
  comparison is rendered.
- Corrected the relationship at its lifecycle boundary: the label is now added only
  after the heading exists and removed whenever comparison content is cleared. Static
  and real-Chromium tests lock both states. The full verification gate again passes
  **575 tests**, Ruff, strict MyPy across 28 source files, and bytecode compilation.
- Commit `fe21dd1d341fc7dd576a8f4eb26e9226d29ccca1` passed Python 3.12,
  Python 3.13, and deployment in Actions run
  [`29876549181`](https://github.com/3clyp50/WattProof/actions/runs/29876549181).
  A cache-busted public WAVE rerun of that deployed commit reports **0 errors, 0
  contrast errors, 0 alerts, and 10/10 AIM**. This is automated evaluation evidence,
  not a substitute for manual accessibility testing.

## 2026-07-22 - Friendlier first screen and collapsible printed charges

### Product and implementation decisions

- Rewrote the upload screen in direct consumer language while keeping its established
  headline. Replaced implementation terms such as schema versions, keyless fixtures,
  Decimal arithmetic, and internal reconciliation with three plain promises: see the
  source, check the math, and no guesswork. Kept the Codex requirement, temporary-file
  deletion, 30-minute session expiry, and clearly labeled synthetic error explicit.
- Wrapped each service's printed charge editors in a native HTML `details` disclosure,
  closed by default. The summary states how many printed lines remain available; no
  charge data or editable evidence was removed. Native disclosure behavior supplies
  keyboard and accessibility semantics without a new JavaScript component or
  dependency.

### Corrections and verification

- A first focused test command used the stale `.venv/bin/pytest` launcher and reached
  the host Python before collection. Re-ran through `.venv/bin/python -m pytest`, the
  repository's actual interpreter. A layout-rectangle assertion also misclassified a
  control inside closed native `details`; the real-browser regression now uses
  Chromium's visibility API and exercises closed, opened, and re-closed states.
- At 1440 px, the authentic review fell from approximately **4,708 px to 1,918 px**
  tall while retaining all 15 printed lines. At 390 px, the landing and collapsed
  review have no horizontal overflow. The accessibility snapshot names the disclosure
  “Printed charges — 15 lines found on this bill”; click opens it, Space closes it, and
  focus remains on the summary.
- `PATH="$PWD/.venv/bin:$PATH" WATTPROOF_REAL_BROWSER=1 make verify` passes **575
  tests**, including all five sample flows in real Chromium; Ruff is clean; strict MyPy
  is clean across 28 source files; and bytecode compilation succeeds.
- Commit `e0195c500b4a1234249cadc3f59a23d141c246f3` passed Python 3.12,
  Python 3.13, and deployment in Actions run
  [`29877145997`](https://github.com/3clyp50/WattProof/actions/runs/29877145997).
  Production retained all 15 authentic-sample charge editors behind the initially
  closed disclosure, measured 1,918 px tall at a 1440 px viewport, had no horizontal
  overflow, and produced no browser console errors or warnings.
- A cache-busted public WAVE evaluation of the deployed release reports **0 errors, 0
  contrast errors, 0 alerts, and 10/10 AIM**. This remains automated evaluation
  evidence rather than a substitute for manual accessibility testing.
