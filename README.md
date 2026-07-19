# BillHawk

**BillHawk checks the math on household electricity bills.** It extracts billed usage and charges with page evidence, lets the user review the facts, deterministically recomputes every supported tariff line, preserves unsupported or uncertain items, and drafts a neutral bill-review request.

> GPT-5.6 reads and drafts. Typed decimal code calculates.

## Build status

The tariff-ground-truth and headless-audit milestones are runnable. The five-step browser experience is being built next. See:

- [`GROUND_TRUTH.md`](GROUND_TRUTH.md) for the selected bill, rate periods, hand calculations, and support boundary.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) for the deliberately small implementation plan.
- [`PLAN.md`](PLAN.md) and [`TODO.md`](TODO.md) for product scope and release gates.
- [`CODEX_LOG.md`](CODEX_LOG.md) for prompts, decisions, failures, verification, and eventual `/feedback` Session ID.

## Authentic demo fixture

The primary fixture is `assets/pge-anonymous-3ce-sample-bill.pdf`, a public anonymized PG&E delivery plus Central Coast Community Energy generation statement dated December 9, 2022. Its E-TOU-C delivery rates, baseline allowance, and 3CE generation rates have period-matched official source snapshots under `sources/`.

The supplied March 2026 PG&E pricing summary is newer, but it does not govern the 2022 statement and is not used to calculate it. The demo favors effective-period correctness over false freshness.

## Privacy and integrity

- Only public, anonymized, or clearly synthetic data belongs in this repository.
- The authentic fixture is expected to reconcile.
- A separate altered fixture will be clearly labeled synthetic and will demonstrate discrepancy detection.
- BillHawk never invents a rate, a cause, or a savings estimate when the required data is absent.

Full browser setup and demo instructions will replace this build-status note when the vertical slice is complete.

## Headless proof

The current machine already has the runtime dependencies. From the repository root:

```bash
python3 -m billhawk --sample authentic
python3 -m billhawk --sample synthetic
python3 -m billhawk --sample authentic --json
python3 -m pytest
```

The authentic sample must reconcile every supported calculation. The synthetic sample must report exactly `$5.00` and visibly state that the error did not occur on a real customer bill.
