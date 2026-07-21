# Screenshot evidence

These seven PNGs are direct viewport captures of the real Flask application running
from UI source commit
`9a5611880a0f9ee0e4fdfe6cb04a706304c4905c` (`Refresh bundle summaries and release
previews`). No production UI or backend file differed from that commit during capture.

Every image was produced by Chromium from the real Flask application on a loopback
test server after activating the visible application controls. The manual procedure
below uses `http://127.0.0.1:8000/`. The captures are not mockups, generated images,
composites, crops, or retouched frames. Only built-in public deterministic fixtures
were used; no upload, account identity, private bill, or personal data appears.

## Capture manifest

| File | Exact viewport | Public sample(s) | Navigation and frame position | Visible verification level | Capture source | Real-app and no-PII confirmation |
| --- | --- | --- | --- | --- | --- | --- |
| `multi-utility-upload-desktop.png` | `1440 × 1000` | None selected; all public fixture controls visible | Open `/`; keep Upload at `scrollY=0` | N/A — Upload | `9a5611880a0f9ee0e4fdfe6cb04a706304c4905c` | Real Flask/Chrome viewport; public controls only; no PII |
| `pge-tariff-verified-desktop.png` | `1440 × 1000` | Public anonymized PG&E/3CE authentic fixture | Upload → **Audit authentic sample** → Review → **Confirm & run checks**; capture the top of Verify | **Tariff verified** | `9a5611880a0f9ee0e4fdfe6cb04a706304c4905c` | Real Flask/Chrome clicks; anonymized public fixture; no PII |
| `duke-internal-reconciliation-desktop.png` | `1440 × 1000` | Public illustrative Duke electricity fixture | Upload → **Duke Electric** → Review → **Confirm & run checks**; capture the top of Verify | **Internally reconciled** | `9a5611880a0f9ee0e4fdfe6cb04a706304c4905c` | Real Flask/Chrome clicks; public illustrative fixture; no PII |
| `centerpoint-gas-desktop.png` | `1440 × 1000` | Public CenterPoint gas fixture | Upload → **CenterPoint Gas** → Review → **Confirm & run checks**; capture the top of Verify | **Internally reconciled** | `9a5611880a0f9ee0e4fdfe6cb04a706304c4905c` | Real Flask/Chrome clicks; rendered public values only; no PII |
| `household-bundle-desktop.png` | `1440 × 1000` | Duke → CenterPoint → Bloomington | Complete Duke → **Add another bill** → complete CenterPoint → **Add another bill** → complete Bloomington → **Finish household review**; capture Household at the top | **Internally reconciled** on all three retained cards | `9a5611880a0f9ee0e4fdfe6cb04a706304c4905c` | Real sequential Flask/Chrome flow; three public fixtures; no PII |
| `water-review-mobile.png` | `390 × 844` | Public Bloomington water/city-services fixture | Upload → **Bloomington Water**; wait for Review, return to a settled `scrollY=0`, and capture | N/A — Review | `9a5611880a0f9ee0e4fdfe6cb04a706304c4905c` | Real responsive Flask/Chrome viewport; public raster fixture; no PII |
| `household-result-mobile.png` | `390 × 844` | Duke → CenterPoint → Bloomington | Repeat the sequential household flow; after the responsive layout settles, align the first Duke card with `scrollIntoView({block: "start"})` and scroll back 12 px | **Internally reconciled** visibly shown on Duke and CenterPoint cards | `9a5611880a0f9ee0e4fdfe6cb04a706304c4905c` | Real responsive Flask/Chrome viewport; public fixtures; no PII |

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

The exact PNG set and the actual browser regression can be reproduced together with:

```bash
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
order, the `1440 × 1000` desktop capture, the `390 × 844` mobile contract, no sideways
overflow, no page errors, and no external browser requests.

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
