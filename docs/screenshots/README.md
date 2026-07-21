# Screenshot evidence

These eight PNGs are direct viewport captures of the real Flask application at merged
application source commit
`2031700c1d9ca12ad39caeb7f8343cbce410bd4d` (`Merge current main into
provider-neutral audit`). No production UI or backend file differed from that commit
during capture. The evidence-only browser harness adds the anchored validation frame
to the exact artifact set. The complete set therefore shows the merged WattProof logo,
Codex-aware disconnected header, and accessibility contract alongside the
provider-neutral multi-utility flow; it is review evidence, not a claim of WAVE or
other third-party certification.

Every image was produced by Chromium from the real Flask application on a loopback
test server after activating the visible application controls. The manual procedure
below uses `http://127.0.0.1:8000/`. The captures are not mockups, generated images,
composites, crops, or retouched frames. Only built-in public deterministic fixtures
were used; no upload, account identity, private bill, or personal data appears.

## Capture manifest

| File | Exact viewport | Public sample(s) | Navigation and frame position | Visible verification level | Capture source | SHA-256 | Real-app and no-PII confirmation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `multi-utility-upload-desktop.png` | `1440 × 1000` | None selected; all public fixture controls visible | Open `/`; keep Upload at `scrollY=0` | N/A — Upload | `2031700c1d9ca12ad39caeb7f8343cbce410bd4d` | `752297eb49aa50a9b275c778841aad9bd3e02c744c42274e54351f9c99d1c809` | Real Flask/Chrome viewport; disconnected Codex header and public controls only; no PII |
| `anchored-no-file-error-desktop.png` | `1440 × 1000` | None selected | Open `/` → **Extract visible bill facts** without choosing a file; capture the settled source-anchored callout | N/A — local validation | `2031700c1d9ca12ad39caeb7f8343cbce410bd4d` | `1362facd925387feb6a5901ca78cf94eec29da143279929b4004093cf60d9ee1` | Real Flask/Chrome click; callout remains anchored to the file target and the file input receives invalid/focus semantics; no PII |
| `pge-tariff-verified-desktop.png` | `1440 × 1000` | Public anonymized PG&E/3CE authentic fixture | Upload → **Audit authentic sample** → Review → **Confirm & run checks**; capture the top of Verify | **Tariff verified** — partial, period-bound coverage only | `2031700c1d9ca12ad39caeb7f8343cbce410bd4d` | `504b745d11def280d651e1598a99d0b2b388c1a62503b2a835f957ce745a4b94` | Real Flask/Chrome clicks; cited tariff lines and UUT printed-math limitation verified in the same browser run; no PII |
| `duke-internal-reconciliation-desktop.png` | `1440 × 1000` | Public illustrative Duke electricity fixture | Upload → **Duke Electric** → Review → **Confirm & run checks**; capture the top of Verify | **Internally reconciled** only | `2031700c1d9ca12ad39caeb7f8343cbce410bd4d` | `13c7a779cfa658ea4b00df080372e638cb7ab8bf0dce6c50c404b7f88a0a2d12` | Real Flask/Chrome clicks; printed or explicitly labeled inferred operands only; no tariff claim; no PII |
| `centerpoint-gas-desktop.png` | `1440 × 1000` | Public CenterPoint gas fixture | Upload → **CenterPoint Gas** → Review → **Confirm & run checks**; capture the top of Verify | **Internally reconciled** only | `2031700c1d9ca12ad39caeb7f8343cbce410bd4d` | `252ab4413ab621a86d1d2a0502432aa29c6460bd35b4055588ae869def359463` | Real Flask/Chrome clicks; rendered public values only; excluded hidden text-layer values remain absent; no PII |
| `household-bundle-desktop.png` | `1440 × 1000` | Duke → CenterPoint → Bloomington | Complete Duke → **Add another bill** → complete CenterPoint → **Add another bill** → complete Bloomington → **Finish household review**; capture Household at the top | **Internally reconciled** on all three retained cards | `2031700c1d9ca12ad39caeb7f8343cbce410bd4d` | `bf8137731c95d0d7a5e5881cda3e130ca659c8f49762794752d867783fc16202` | Real sequential Flask/in-app Chrome flow; three minimized public summaries and the disconnected Codex header are visibly complete; no PII |
| `water-review-mobile.png` | `390 × 844` | Public Bloomington water/city-services fixture | Upload → **Bloomington Water**; wait for Review, return to a settled `scrollY=0`, and capture | N/A — Review | `2031700c1d9ca12ad39caeb7f8343cbce410bd4d` | `63783c6001c53e858e5e16d32326c0a6a35ba25a601cb86063591a75afb97221` | Real responsive Flask/Chrome viewport; public raster fixture and responsive Codex header; no sideways overflow or PII |
| `household-result-mobile.png` | `390 × 844` | Duke → CenterPoint → Bloomington | Repeat the sequential household flow; after the responsive layout settles, align the first Duke card with `scrollIntoView({block: "start"})` and scroll back 12 px | **Internally reconciled** visibly shown on Duke and CenterPoint cards | `2031700c1d9ca12ad39caeb7f8343cbce410bd4d` | `5c04158b986616dfefaf522833f61eca328d1245730f02c8acb5dd07b60af37a` | Real responsive Flask/Chrome viewport; public minimized summaries; no sideways overflow or PII |

The mobile household capture is intentionally a scrolled viewport, not a crop: its
native PNG remains exactly `390 × 844` and shows complete result cards with their
verification badges.

During the bounded recapture pass, headless Chromium intermittently omitted only the
Codex header's glyph layer while its DOM, dimensions, and computed styles remained
correct. The final household desktop frame was therefore recaptured through the same
real in-app Chromium session, source commit, viewport, and exact visible sequence; no
page state or pixels were edited after capture.

## Reproduce the captures

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
make run
```

Then:

1. Open `http://127.0.0.1:8000/` in Chrome or Chromium.
2. In DevTools device emulation, set a responsive viewport of exactly `1440 × 1000`
   for desktop or `390 × 844` for mobile, with device scale factor `1`.
3. Follow the manifest's visible button sequence. Wait for the destination heading and
   verification badge to finish rendering before capture.
4. Use Chrome's **Capture screenshot** command for the current viewport, not a
   full-page capture. Do not crop or composite the result.
5. Save the image with the exact manifest filename under `docs/screenshots/`.

At the evidence commit, first confirm that the application and capture harness still
match the recorded source commit, then reproduce the exact PNG set and browser
regression together:

```bash
git diff --exit-code 2031700c1d9ca12ad39caeb7f8343cbce410bd4d -- \
  wattproof run.py
WATTPROOF_REAL_BROWSER=1 WATTPROOF_SCREENSHOT_DIR="$PWD/docs/screenshots" \
  .venv/bin/python -m pytest \
  tests/test_multi_utility_web.py::test_real_chromium_sample_review_and_audit_flows -q
```

Set `AGENT_BROWSER_BIN` only if Chrome/Chromium/Edge is not discovered automatically.
When `WATTPROOF_SCREENSHOT_DIR` is present, the harness uses Chromium's DevTools
`Page.captureScreenshot` with `format: "png"` after fonts and two animation frames
settle. Chrome writes only to a temporary sibling staging directory, never directly
to these tracked PNG paths. The harness requires the exact eight filenames, validates
every PNG signature, byte size, and viewport dimensions, and only then publishes each
file with atomic replacement. Incomplete or interrupted captures publish nothing;
publication errors roll back prior replacements; staging is always removed. The
manifest remains untouched.

The smoke test verifies the same five sample paths, the exact sequential household
order, step-heading focus, the `1440 × 1000` desktop capture, the `390 × 844` mobile
contract, no sideways overflow, no page errors, and no external browser requests.

The post-capture interactive pass also exercised step-heading and source-error focus,
the loading button's `aria-busy` lifecycle, the polite copy confirmation, and reduced-
motion media emulation before resetting the browser preference. The disconnected Codex
header was checked throughout the flow. Its modal was exercised with a session-only
intercepted `TEST-ONLY` response so no live device code, account, token, browser storage,
or external OpenAI navigation was involved; the modal is intentionally not a screenshot
artifact. The corresponding static shell and script contracts can be rerun with:

```bash
.venv/bin/python -m pytest \
  tests/test_wattproof.py::test_web_shell_keeps_provider_neutral_accessibility_contract \
  tests/test_wattproof.py::test_web_script_announces_loading_and_provider_copy_feedback \
  tests/test_multi_utility_web.py::test_global_error_alert_is_keyboard_focusable -q
```

These checks are focused regression evidence; they do not substitute for third-party
accessibility certification.

## Verify the artifacts

The focused artifact test checks the exact filenames and a minimum of 10,000 bytes:

```bash
.venv/bin/python -m pytest \
  tests/test_multi_utility_web.py::test_review_artifacts_exist -q
```

Verify dimensions from PNG headers without image-library dependencies:

```bash
python3 - <<'PY'
from pathlib import Path
from struct import unpack

for image in sorted(Path("docs/screenshots").glob("*.png")):
    data = image.read_bytes()
    width, height = unpack(">II", data[16:24])
    print(f"{image.name}: {width}x{height}, {len(data)} bytes")
PY
```

Expected: six desktop files at `1440x1000`, two mobile files at `390x844`, and every
file larger than 10,000 bytes.

Compare the generated checksums with the manifest:

```bash
shasum -a 256 docs/screenshots/*.png
```
