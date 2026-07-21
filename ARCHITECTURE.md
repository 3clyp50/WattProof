# WattProof architecture

WattProof is one Flask process plus a framework-free browser client. The server is
stateless across requests; the browser may retain minimized results only for the life
of the current page.

```text
PDF upload or deterministic public sample
                  |
                  v
         signature, size, and exact SHA-256
                  |
          +-------+------------------------+
          |                                |
   known document                  unknown document
          |                                |
  local typed fixture          page-count preflight and
          |                     render every PDF page
          |                                |
          |                     GPT-5.6 strict visual mapping
          |                (rendered images first, native hint last,
          |                         store=False, no calculation)
          +---------------+----------------+
                          v
        provider-neutral UtilityDocument + evidence review
                          |
                          v
             deterministic Decimal reconciliation
                          |
                          v
          exact, fail-closed tariff adapter registry
             | matched                     | unmatched
             v                             v
     published-tariff checks      explicit coverage limitation
             +---------------+-------------+
                             v
                         bill result
                             |
                             v
          privacy-minimized browser-memory household bundle
```

## Evidence boundary

Rendered pages are authoritative. Every material fact must cite a visible page and
excerpt with `rendered_page` provenance. PDF-native text is always labeled
`UNTRUSTED_NATIVE_TEXT_HINT` and is never sufficient evidence by itself. If native
text conflicts with a rendered page, the visible value wins and the conflict becomes
a review warning.

This is necessary for both adversarial public examples:

- CenterPoint's rendered gas statement contains `112.277 therms` and `$132.19`, while
  the invisible text layer contains a different `$134.69` example.
- Bloomington's wrapper contains native text, but its statement and `$51.92` total are
  raster content.

`wattproof/extract.py` enforces a PDF signature and 10 MB upload limit before hash
routing. The unknown-document path adds a 20-page limit, bounded Poppler subprocesses,
an 8 MB per-page render limit, a 64 MB aggregate render budget, and a process-local
concurrency guard. Uploads use temporary files and rendered images are encoded before
their temporary directory closes.

## Extraction paths

### Hash-known public fixtures

The PG&E/3CE, Duke, CenterPoint, and Bloomington public documents have exact SHA-256
mappings to deterministic typed fixtures. This path is keyless and network-free. The
repository retains structured facts, visible evidence references, source URLs, and
hashes; the optional Duke, CenterPoint, and Bloomington PDFs download only into ignored
`tmp/public-samples/`.

### Configured unknown documents

When an operator provides `OPENAI_API_KEY`, GPT-5.6 receives rendered page images in
page order, followed by the bounded and explicitly untrusted native-text hint. The
Responses API uses strict `UtilityDocument` structured output and `store=False`.
Instructions forbid calculation, repair, invention, and native-only facts. Trusted
local code replaces model-returned fixture identity, digest, and page count before
schema validation.

Without a configured reader, an unknown document fails with a controlled,
actionable extraction-unavailable response. The public keyless deployment does not
spend API credits on arbitrary uploads.

## Provider-neutral core

`wattproof/utility_models.py` models documents as service sections rather than as one
provider-specific bill shape. A section identifies service type, printed and normalized
provider names, jurisdiction, schedule, dates, usage, meter or conversion facts,
charges, subtotal, and rendered evidence. One document may contain multiple providers
or multiple service types.

`wattproof/reconcile.py` executes declared rules with `Decimal` values:

- meter or counter difference;
- quantity multiplied by a printed rate;
- component and cross-section sums;
- a printed percentage over explicitly identified charge IDs;
- a printed unit-conversion factor;
- tier totals and statement roll-forward.

The engine does not invent an absent operand or tax base. Money rounds half-up only at
the declared bill boundary. Downstream percentage, subtotal, current-charge, and
amount-due symptoms carry every independent root that exactly explains them, in stable
audit-line order, so amounts are not double-counted. `root_cause_ids` is the canonical
dependency set; `root_cause_id` remains populated for a single dependency so existing
consumers keep working. Dependencies must reference present, distinct, independent
discrepancy lines and may never reference the dependent line itself.

The highest cumulative verification level is one of `evidence_extracted`,
`internally_reconciled`, or `tariff_verified`. A printed rate can establish only
internal reconciliation unless independent source coverage is available.
The highest level does not override line-level scope: every `published_tariff` line
must carry a citation present in the attached tariff archive metadata. An uncited line
inside an otherwise exact adapter remains `printed_math` and states its limitation.

## Exact tariff adapters

`wattproof/audit_service.py` accepts both the legacy PG&E `BillExtraction` schema and
provider-neutral `UtilityDocument`. It sends exact legacy matches through the adapter
registry and all unsupported shapes through generic reconciliation.

The registry currently contains one adapter: the historical PG&E delivery + Central
Coast Community Energy E-TOU-C/MBRETCH1 bundle. `wattproof/adapters.py` fails closed on
the complete provider identity, California jurisdiction, schedule, service period,
required printed operands, and immutable source structure. `wattproof/tariffs.py`
refuses calculation if an archived source hash changes.

The 3CE utility-users-tax relationships are intentionally not published-tariff rules.
WattProof recomputes them from the printed percentage and printed base lines, labels
them `printed_math`, and does not attach citations or call them published-tariff
matches.

There is no fuzzy provider matching, Duke adapter, or nationwide tariff table. The
Duke guide is illustrative evidence for internal tier/rider arithmetic only.

## Web and household state

`wattproof/app.py` exposes the page, health check, public fixture API, extraction API,
and audit API. Each upload is processed inside a temporary file and the Flask service
stores no bill database or account record.

`wattproof/static/app.js` owns the five-step browser journey:

1. Upload
2. Review
3. Verify
4. Household
5. Next steps

After a completed audit, **Add another bill** clears the current document and retains
only a summary allowlist: provider display name, service types, period, currency,
printed amount, usage summary, verification level, root discrepancy total/count, and
sanitized provider review drafts. Raw documents, blob URLs, account identity, meter
IDs, evidence excerpts, citations, and full audit payloads are excluded.

The bundle lives only in JavaScript memory. Refresh, close, **Clear household**, or
**Start over** removes it. Provider drafts remain separate, editable, and unsent.

## Deliberately absent

The current architecture has no React/Next.js layer, separate API service, database,
accounts, queues, persistent household history, provider login, payment flow,
automatic messaging, generalized tax engine, nationwide rate catalog, or Duke tariff
verification. These are not implied by provider-neutral extraction.

## Verification and deployment boundary

`make verify` runs pytest, Ruff, strict MyPy, and bytecode compilation. The opt-in real
Chromium test runs all five samples, the sequential household path, responsive states,
privacy clearing, request isolation, and inert rendering.

Production deployment remains eligible only for verified pushes to `main`; review
branches do not trigger the production job. Real application screenshots and their
reproduction record live in `docs/screenshots/`.
