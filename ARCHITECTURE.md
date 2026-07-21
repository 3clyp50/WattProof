# WattProof MVP Architecture

The smallest complete judged slice is one Python process and a browser.

```text
PDF upload or public sample
        |
        +-- known public fixture -> checked golden extraction
        |
        `-- other native PDF -> native pdftotext extraction
                    |
                    v
             official Codex device sign-in
                    |
                    v
             isolated App Server + GPT-5.6 Luna
             strict-schema mapping, zero-tool result
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

- **One Flask service:** upload, Codex connection, review, audit, comparison, and action stay in one deployable service.
- **No WattProof account or database:** the browser holds the reviewed extraction and the server retains no upload after processing.
- **Official account handoff:** App Server's device-login endpoint supplies a one-time OpenAI code. The browser stores only an opaque signed session cookie; isolated Codex credentials stay on the server's production tmpfs and are deleted on disconnect or expiry.
- **Native text first:** `pdftotext` handles the selected text-based fixture; OCR is a P1 fallback.
- **GPT-5.6 reads, typed code calculates:** Luna may map unknown native PDF text into a strict schema, but it never supplies or changes arithmetic.
- **Constrained execution:** every browser session gets a separate ephemeral Codex process with no approvals, web search, apps, hooks, memories, or tool network; the filesystem profile denies root and allows read-only access only to an empty workspace and the minimum runtime files.
- **Bounded lifecycle:** pending sign-ins expire after 10 minutes, connected sessions after 30 minutes of inactivity, and the service admits eight concurrent sessions.
- **Golden sample path:** judges can run the complete product without an API key or network dependency.
- **Immutable sources:** calculations load versioned local metadata that points to archived, hashed official snapshots.
- **Honest comparison:** the current fixture returns an interval-data requirement instead of guessed savings.

## Deliberately absent

React/Next.js, a separate API service, SQLite, WattProof user accounts, queues, OCR, URDB, nationwide adapters, and automatic email sending do not improve the first auditable fixture. Add them only after the vertical slice and release gates pass.
