# BillHawk MVP Architecture

The smallest complete judged slice is one Python process and a browser.

```text
PDF upload or Sample mode
        |
        v
native pdftotext extraction
        |
        +-- known public fixture -> checked golden extraction
        |
        `-- other native PDF -> GPT-5.6 strict-schema mapping when configured
        |
        v
Pydantic BillExtraction + user review
        |
        v
Decimal audit engine + immutable local rate snapshots
        |
        +-- transparent line results and insufficiency states
        `-- grounded review-request facts
        |
        v
Flask-rendered five-step web flow
```

## Why this shape

- **One Flask service:** upload, review, audit, comparison, and action stay in one deployable process.
- **No database or accounts:** the demo request holds one extraction in memory and retains no upload after processing.
- **Native text first:** `pdftotext` handles the selected text-based fixture; OCR is a P1 fallback.
- **GPT-5.6 reads, typed code calculates:** the model may map unknown native PDF text into a strict schema and draft neutral prose, but it never supplies or changes arithmetic.
- **Golden sample path:** judges can run the complete product without an API key or network dependency.
- **Immutable sources:** calculations load versioned local metadata that points to archived, hashed official snapshots.
- **Honest comparison:** the current fixture returns an interval-data requirement instead of guessed savings.

## Deliberately absent

React/Next.js, a separate API service, SQLite, authentication, queues, OCR, URDB, nationwide adapters, and automatic email sending do not improve the first auditable fixture. Add them only after the vertical slice and release gates pass.
