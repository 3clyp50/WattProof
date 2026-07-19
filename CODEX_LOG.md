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
