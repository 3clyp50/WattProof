# Screenshot evidence

These seven PNGs are direct viewport captures of the real Flask application at merged
application source commit
`af5f2dd147872b6e484ea5c72690df6d57060210` (`Merge origin/main into provider-neutral
multi-utility`). No production UI or backend file differed from that commit during
capture. The complete set therefore shows the merged WattProof logo and accessibility
contract alongside the provider-neutral multi-utility flow; it is review evidence, not
a claim of WAVE or other third-party certification.

Every image was produced by Chromium from the real Flask application on a loopback
test server after activating the visible application controls. The manual procedure
below uses `http://127.0.0.1:8000/`. The captures are not mockups, generated images,
composites, crops, or retouched frames. Only built-in public deterministic fixtures
were used; no upload, account identity, private bill, or personal data appears.

## Capture manifest

| File | Exact viewport | Public sample(s) | Navigation and frame position | Visible verification level | Capture source | SHA-256 | Real-app and no-PII confirmation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `multi-utility-upload-desktop.png` | `1440 × 1000` | None selected; all public fixture controls visible | Open `/`; keep Upload at `scrollY=0` | N/A — Upload | `af5f2dd147872b6e484ea5c72690df6d57060210` | `9b97956c7b7497240cba3aab061f94e941857d5f072144ccf2f5a44e14d971b6` | Real Flask/Chrome viewport; merged logo and public controls only; no PII |
| `pge-tariff-verified-desktop.png` | `1440 × 1000` | Public anonymized PG&E/3CE authentic fixture | Upload → **Audit authentic sample** → Review → **Confirm & run checks**; capture the top of Verify | **Tariff verified** — partial, period-bound coverage only | `af5f2dd147872b6e484ea5c72690df6d57060210` | `963a3610debc00fb91f32f79cc7c59321ef451c815d3f13327be646f251fab49` | Real Flask/Chrome clicks; cited tariff lines and UUT printed-math limitation verified in the same browser run; no PII |
| `duke-internal-reconciliation-desktop.png` | `1440 × 1000` | Public illustrative Duke electricity fixture | Upload → **Duke Electric** → Review → **Confirm & run checks**; capture the top of Verify | **Internally reconciled** only | `af5f2dd147872b6e484ea5c72690df6d57060210` | `bfaeefdba41da32bb7edcf4fd15938b87f95dcc4f023d527d276817d4039af27` | Real Flask/Chrome clicks; printed or explicitly labeled inferred operands only; no tariff claim; no PII |
| `centerpoint-gas-desktop.png` | `1440 × 1000` | Public CenterPoint gas fixture | Upload → **CenterPoint Gas** → Review → **Confirm & run checks**; capture the top of Verify | **Internally reconciled** only | `af5f2dd147872b6e484ea5c72690df6d57060210` | `27270e9689f0ee9f70316b987e0ba404f1778d1907d00a25ad61392972f8476c` | Real Flask/Chrome clicks; rendered public values only; excluded hidden text-layer values remain absent; no PII |
| `household-bundle-desktop.png` | `1440 × 1000` | Duke → CenterPoint → Bloomington | Complete Duke → **Add another bill** → complete CenterPoint → **Add another bill** → complete Bloomington → **Finish household review**; capture Household at the top | **Internally reconciled** on all three retained cards | `af5f2dd147872b6e484ea5c72690df6d57060210` | `4188dcc663394b6da4bb4df32ec51778669efe4acf124ac6a4b55cf336998527` | Real sequential Flask/Chrome flow; three minimized public summaries; no PII |
| `water-review-mobile.png` | `390 × 844` | Public Bloomington water/city-services fixture | Upload → **Bloomington Water**; wait for Review, return to a settled `scrollY=0`, and capture | N/A — Review | `af5f2dd147872b6e484ea5c72690df6d57060210` | `e6a617832438a5195d1d60e7855cf002e2c37f98a754df6d2ec5753f9b9d371c` | Real responsive Flask/Chrome viewport; public raster fixture; no sideways overflow or PII |
| `household-result-mobile.png` | `390 × 844` | Duke → CenterPoint → Bloomington | Repeat the sequential household flow; after the responsive layout settles, align the first Duke card with `scrollIntoView({block: "start"})` and scroll back 12 px | **Internally reconciled** visibly shown on Duke and CenterPoint cards | `af5f2dd147872b6e484ea5c72690df6d57060210` | `40c9fc37228206e7b2c103b862bc83ed7a1306abd007c5b3e679d087d289905d` | Real responsive Flask/Chrome viewport; public minimized summaries; no sideways overflow or PII |

The mobile household capture is intentionally a scrolled viewport, not a crop: its
native PNG remains exactly `390 × 844` and shows complete result cards with their
verification badges.

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
git diff --exit-code af5f2dd147872b6e484ea5c72690df6d57060210 -- \
  wattproof run.py tests/test_multi_utility_web.py
WATTPROOF_REAL_BROWSER=1 WATTPROOF_SCREENSHOT_DIR="$PWD/docs/screenshots" \
  .venv/bin/python -m pytest \
  tests/test_multi_utility_web.py::test_real_chromium_sample_review_and_audit_flows -q
```

Set `AGENT_BROWSER_BIN` only if Chrome/Chromium/Edge is not discovered automatically.
When `WATTPROOF_SCREENSHOT_DIR` is present, the harness uses Chromium's DevTools
`Page.captureScreenshot` with `format: "png"` after fonts and two animation frames
settle. Chrome writes only to a temporary sibling staging directory, never directly
to these tracked PNG paths. The harness requires the exact seven filenames, validates
every PNG signature, byte size, and viewport dimensions, and only then publishes each
file with atomic replacement. Incomplete or interrupted captures publish nothing;
publication errors roll back prior replacements; staging is always removed. The
manifest remains untouched.

The smoke test verifies the same five sample paths, the exact sequential household
order, step-heading focus, the `1440 × 1000` desktop capture, the `390 × 844` mobile
contract, no sideways overflow, no page errors, and no external browser requests.

The post-capture interactive pass also exercised forward and reverse keyboard focus,
the loading button's `aria-busy` lifecycle, the polite copy confirmation, and reduced-
motion media emulation before resetting the browser preference. The corresponding
static shell and script contracts can be rerun with:

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

Expected: five desktop files at `1440x1000`, two mobile files at `390x844`, and every
file larger than 10,000 bytes.

Compare the generated checksums with the manifest:

```bash
shasum -a 256 docs/screenshots/*.png
```
