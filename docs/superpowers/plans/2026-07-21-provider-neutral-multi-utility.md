# Provider-Neutral Multi-Utility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand WattProof from one PG&E/3CE electricity shape into a provider-neutral utility-bill checker with rendered-page evidence, deterministic internal reconciliation, exact tariff adapters, a temporary multi-bill household flow, and review-ready screenshots.

**Architecture:** Keep the existing PG&E audit intact behind a compatibility adapter. Add a versioned provider-neutral document model, deterministic reconciliation engine, rendered-document extraction boundary, and unified audit service. The framework-free Flask/HTML/CSS/JavaScript UI consumes the unified result contract and holds bundle summaries only in page memory.

**Tech Stack:** Python 3.12, Flask, Pydantic 2, `Decimal`, Poppler (`pdfinfo`, `pdftotext`, `pdftoppm`), OpenAI Responses structured output, vanilla HTML/CSS/JavaScript, pytest, Ruff, strict mypy.

---

## Scope and file map

This remains one plan because the browser work consumes the exact schema and API
produced by the core work; splitting it would leave either plan without working
end-to-end software.

### New files

- `wattproof/utility_models.py` — schema 2.0 facts, service sections, audit lines, and results.
- `wattproof/legacy.py` — translation from `BillExtraction` 1.0 to `UtilityDocument` 2.0.
- `wattproof/reconcile.py` — provider-neutral printed-math and statement reconciliation.
- `wattproof/utility_fixtures.py` — deterministic Duke, CenterPoint, and Bloomington fixtures.
- `wattproof/adapters.py` — exact tariff-adapter protocol and PG&E/3CE adapter.
- `wattproof/audit_service.py` — one audit entry point for schema 1.0 and 2.0 inputs.
- `tests/test_utility_models.py`, `tests/test_reconcile.py`, `tests/test_utility_fixtures.py`.
- `tests/test_rendered_extraction.py`, `tests/test_audit_service.py`, `tests/test_multi_utility_web.py`.
- `scripts/fetch-public-samples.sh` — optional hash-checked public-guide download.
- `docs/screenshots/README.md` and seven real application PNGs.

### Modified files

- `wattproof/extract.py`, `wattproof/audit.py`, `wattproof/app.py`, `wattproof/cli.py`.
- `wattproof/templates/index.html`, `wattproof/static/app.js`, `wattproof/static/app.css`.
- `tests/test_wattproof.py`, `README.md`, `ARCHITECTURE.md`, and `GROUND_TRUTH.md`.

No database, account system, persistence layer, nationwide tariff table, or Duke tariff
adapter is added.

Run all commands from the repository root with:

```bash
PATH="$PWD/.venv/bin:$PATH" make verify
```

The clean baseline at `e1e1b90` is 28 passing tests, Ruff clean, strict mypy clean, and
compileall clean.

## Task 1: Add schema 2.0 and the legacy translator

**Files:**

- Create: `wattproof/utility_models.py`
- Create: `wattproof/legacy.py`
- Create: `tests/test_utility_models.py`
- Modify: `wattproof/models.py` only if an existing shared type must be exported.

- [ ] **Step 1: Write the failing schema tests**

Create `tests/test_utility_models.py` with these exact behaviors:

```python
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from wattproof.fixtures import load_sample
from wattproof.legacy import translate_legacy_bill
from wattproof.utility_models import (
    CalculationSpec,
    DateFactV2,
    EvidenceRef,
    MoneyFactV2,
    ServiceSection,
    TextFactV2,
    UtilityCharge,
    UtilityDocument,
)


def evidence() -> EvidenceRef:
    return EvidenceRef(page=1, text="visible statement text", confidence=Decimal("1"))


def test_document_supports_multiple_service_sections() -> None:
    provider = TextFactV2(value="Example Utility", status="printed", evidence=evidence())
    start = DateFactV2(value=date(2026, 1, 1), status="printed", evidence=evidence())
    end = DateFactV2(value=date(2026, 1, 31), status="printed", evidence=evidence())
    amount = MoneyFactV2(
        value=Decimal("10.00"), currency="USD", status="printed", evidence=evidence()
    )
    section = ServiceSection(
        id="water",
        service_type="water",
        provider=provider,
        service_start=start,
        service_end=end,
        charges=(UtilityCharge(id="water_service", label="Water service", amount=amount),),
        subtotal=amount,
    )
    document = UtilityDocument(
        schema_version="2.0",
        fixture_kind="uploaded",
        document_sha256="a" * 64,
        page_count=1,
        statement_date=end,
        currency="USD",
        sections=(section,),
        current_charges=amount,
        amount_due=amount,
    )
    assert document.sections[0].service_type == "water"


def test_user_correction_requires_original_value() -> None:
    with pytest.raises(ValidationError, match="original_value"):
        TextFactV2(value="Corrected Utility", status="user_corrected", evidence=evidence())


def test_legacy_translation_preserves_pg_and_e_statement() -> None:
    translated = translate_legacy_bill(load_sample("authentic"))
    assert [section.id for section in translated.sections] == [
        "pge_delivery", "cca_generation"
    ]
    assert translated.sections[0].usage is not None
    assert translated.sections[0].usage.value == Decimal("327.119")
    assert translated.current_charges.value == Decimal("96.44")
    assert translated.amount_due.value == Decimal("96.24")


def test_document_rejects_duplicate_charge_ids() -> None:
    bill = translate_legacy_bill(load_sample("authentic"))
    duplicate = bill.sections[0].charges[0].model_copy(
        update={"id": bill.sections[1].charges[0].id}
    )
    changed = bill.sections[0].model_copy(
        update={"charges": (duplicate,) + bill.sections[0].charges[1:]}
    )
    with pytest.raises(ValidationError, match="charge IDs must be unique"):
        UtilityDocument.model_validate(
            bill.model_copy(update={"sections": (changed, bill.sections[1])}).model_dump()
        )


def test_percent_calculation_requires_charge_ids() -> None:
    with pytest.raises(ValidationError, match="charge_ids"):
        CalculationSpec(kind="percent_of_charges")


def test_quantity_times_rate_rejects_charge_ids() -> None:
    with pytest.raises(ValidationError, match="charge_ids"):
        CalculationSpec(kind="quantity_times_rate", charge_ids=("other_charge",))


def test_document_rejects_evidence_after_last_page() -> None:
    bill = translate_legacy_bill(load_sample("authentic"))
    payload = bill.model_dump()
    payload["sections"][0]["provider"]["evidence"]["page"] = bill.page_count + 1
    with pytest.raises(ValidationError, match="page_count"):
        UtilityDocument.model_validate(payload)
```

- [ ] **Step 2: Run the tests and verify the missing-module failure**

```bash
PATH="$PWD/.venv/bin:$PATH" pytest tests/test_utility_models.py -q
```

Expected: collection fails because `wattproof.utility_models` and `wattproof.legacy` do
not exist.

- [ ] **Step 3: Implement the provider-neutral public contract**

Create `wattproof/utility_models.py` with these exact public types and fields:

```python
FactStatus = Literal["printed", "inferred", "user_corrected"]
ServiceType = Literal[
    "electricity", "natural_gas", "water", "wastewater",
    "stormwater", "sanitation", "other",
]
AuditStatusV2 = Literal["verified", "discrepancy", "cannot_verify", "needs_review"]
AuditScope = Literal["printed_math", "statement_reconciliation", "published_tariff"]
VerificationLevel = Literal[
    "evidence_extracted", "internally_reconciled", "tariff_verified"
]


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    page: int = Field(ge=1)
    text: str = Field(min_length=1)
    confidence: Decimal = Field(ge=0, le=1)
    provenance: Literal["rendered_page"] = "rendered_page"


class FactBaseV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: FactStatus
    evidence: EvidenceRef
    original_value: str | None = None

    @model_validator(mode="after")
    def validate_correction(self) -> Self:
        if self.status == "user_corrected" and self.original_value is None:
            raise ValueError("user-corrected facts require original_value")
        if self.status != "user_corrected" and self.original_value is not None:
            raise ValueError("original_value is only valid for user-corrected facts")
        return self


class TextFactV2(FactBaseV2):
    value: str = Field(min_length=1)


class DateFactV2(FactBaseV2):
    value: date


class DecimalFactV2(FactBaseV2):
    value: Decimal
    unit: str = Field(min_length=1)


class MoneyFactV2(FactBaseV2):
    value: Decimal
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class CalculationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["quantity_times_rate", "percent_of_charges"]
    charge_ids: tuple[str, ...] = ()


class UtilityCharge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    label: str = Field(min_length=1)
    quantity: DecimalFactV2 | None = None
    rate: DecimalFactV2 | None = None
    amount: MoneyFactV2
    calculation: CalculationSpec | None = None


class MeterCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    previous: DecimalFactV2
    current: DecimalFactV2
    usage: DecimalFactV2


class ConversionCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    label: str
    source: DecimalFactV2
    factor: DecimalFactV2
    result: DecimalFactV2


class ServiceSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    service_type: ServiceType
    provider: TextFactV2
    normalized_provider: str | None = None
    jurisdiction: TextFactV2 | None = None
    schedule: TextFactV2 | None = None
    service_start: DateFactV2 | None = None
    service_end: DateFactV2 | None = None
    usage: DecimalFactV2 | None = None
    meter: MeterCheck | None = None
    conversions: tuple[ConversionCheck, ...] = ()
    charges: tuple[UtilityCharge, ...]
    subtotal: MoneyFactV2


class UtilityDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["2.0"]
    fixture_kind: Literal[
        "authentic", "synthetic", "duke", "centerpoint", "bloomington", "uploaded"
    ]
    document_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_count: int = Field(ge=1, le=20)
    source_url: str | None = None
    statement_date: DateFactV2 | None = None
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    sections: tuple[ServiceSection, ...] = Field(min_length=1)
    current_charges: MoneyFactV2
    outstanding_balance: MoneyFactV2 | None = None
    amount_due: MoneyFactV2
    warnings: tuple[str, ...] = ()
```

Add model validators for correction provenance, calculation operands (`percent_of_charges`
requires at least one `charge_id`; `quantity_times_rate` permits none), unique section IDs,
globally unique charge IDs, increasing service dates, consistent currencies, and every
nested evidence page being no greater than the document's trusted `page_count`. Also
define:

```python
class UtilityAuditLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    section_id: str | None
    label: str
    scope: AuditScope
    unit: str
    billed_amount: Decimal | None
    expected_amount: Decimal | None
    delta: Decimal | None
    formula: str
    inputs: dict[str, str]
    evidence: tuple[EvidenceRef, ...]
    citations: tuple[Citation, ...] = ()
    status: AuditStatusV2
    limitation: str | None = None
    root_cause_id: str | None = None


class ProviderReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: str
    subject: str
    body: str
    grounded_audit_line_ids: tuple[str, ...]
    requires_user_review: Literal[True] = True


class UtilityAuditResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["2.0"]
    fixture_kind: str
    verdict: Literal["reconciled", "possible_discrepancy", "needs_review"]
    verification_level: VerificationLevel
    headline: str
    discrepancy_total: Decimal
    currency: str
    lines: tuple[UtilityAuditLine, ...]
    tariff: TariffVersion | None = None
    comparison: PlanComparison | None = None
    review_requests: tuple[ProviderReviewRequest, ...] = ()
```

Import `Citation`, `PlanComparison`, and `TariffVersion` from `wattproof.models`.

- [ ] **Step 4: Implement lossless legacy translation**

Create `translate_legacy_bill(bill: BillExtraction) -> UtilityDocument` in
`wattproof/legacy.py`. Use small evidence/fact conversion helpers. Build sections
`pge_delivery` and `cca_generation`. Translate quantity/rate lines to
`quantity_times_rate`. Translate only `cca_nov_uut` and `cca_dec_uut` to
`percent_of_charges` with their two period charge IDs. Preserve all printed values,
status, page, source text, confidence, dates, digest, fixture kind, and totals. This
function must not load tariffs or calculate.

- [ ] **Step 5: Verify and commit Task 1**

```bash
PATH="$PWD/.venv/bin:$PATH" pytest tests/test_utility_models.py -q
PATH="$PWD/.venv/bin:$PATH" make verify
git add wattproof/utility_models.py wattproof/legacy.py tests/test_utility_models.py wattproof/models.py
git commit -m "Add provider-neutral utility document schema"
```

## Task 2: Build deterministic internal reconciliation

**Files:**

- Create: `wattproof/reconcile.py`
- Create: `tests/test_reconcile.py`

- [ ] **Step 1: Write failing arithmetic tests**

Create `tests/test_reconcile.py` with a local `water_document()` factory containing
`2 kgal × 3.73 USD/kgal = 7.46`, service `7.86`, fire `2.93`, seven-percent tax over
those three IDs `1.28`, and total `19.53`. Add:

```python
def test_reconciles_products_percentages_and_totals() -> None:
    result = reconcile_document(water_document())
    lines = {line.id: line for line in result.lines}
    assert result.verification_level == "internally_reconciled"
    assert lines["charge::water_usage"].expected_amount == Decimal("7.46")
    assert lines["charge::sales_tax"].expected_amount == Decimal("1.28")
    assert lines["subtotal::water"].expected_amount == Decimal("19.53")


def test_reconciles_meter_difference_and_conversion() -> None:
    result = reconcile_document(gas_document_with_meter_and_conversion())
    lines = {line.id: line for line in result.lines}
    assert lines["meter::gas"].expected_amount == Decimal("108")
    assert lines["conversion::gas::therms"].expected_amount == Decimal("112.277")


def test_counts_root_discrepancy_once() -> None:
    result = reconcile_document(water_document(printed_usage_charge=Decimal("8.46")))
    lines = {line.id: line for line in result.lines}
    assert lines["charge::water_usage"].delta == Decimal("1.00")
    assert lines["subtotal::water"].root_cause_id == "charge::water_usage"
    assert result.discrepancy_total == Decimal("1.00")


def test_incompatible_units_need_review() -> None:
    result = reconcile_document(water_document(rate_unit="USD/kWh"))
    line = next(line for line in result.lines if line.id == "charge::water_usage")
    assert line.status == "needs_review"
    assert line.expected_amount is None


def test_round_money_is_decimal_half_up() -> None:
    assert round_money(Decimal("1.005")) == Decimal("1.01")


def test_provider_request_is_grounded_to_root_discrepancy() -> None:
    result = reconcile_document(water_document(printed_usage_charge=Decimal("8.46")))
    request = result.review_requests[0]
    assert request.grounded_audit_line_ids == ("charge::water_usage",)
    assert "$1.00" in request.body
```

- [ ] **Step 2: Run tests and confirm the missing-engine failure**

```bash
PATH="$PWD/.venv/bin:$PATH" pytest tests/test_reconcile.py -q
```

- [ ] **Step 3: Implement the minimal reconciliation engine**

Create `reconcile_document(document: UtilityDocument) -> UtilityAuditResult` in
`wattproof/reconcile.py`. Use:

```python
CENT = Decimal("0.01")
MONEY_TOLERANCE = Decimal("0.01")


def round_money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def compatible_rate(quantity_unit: str, rate_unit: str, currency: str) -> bool:
    return rate_unit == f"{currency}/{quantity_unit}"
```

Rules are: compatible quantity × rate; fraction × explicitly referenced printed charge
amounts; current meter minus previous meter; source × conversion factor quantized to the
result's printed precision; sum charges to section subtotal; sum section subtotals to
current charges; current charges plus optional outstanding balance to amount due.

Stable IDs are `charge::<charge_id>`, `meter::<section_id>`,
`conversion::<section_id>::<conversion_id>`, `subtotal::<section_id>`,
`statement::current_charges`, and `statement::amount_due`. Invalid units return
`needs_review`, never a guessed conversion. Propagate a direct discrepancy ID to
subtotal/current/due symptoms through `root_cause_id`. Sum USD root discrepancies only.

Reach `internally_reconciled` whenever at least one rule produced an expected value.
Create one neutral provider request per provider, grounded to root lines: describe a
discrepancy when present; otherwise state that printed math reconciled while published
rates remain independently unverified.

- [ ] **Step 4: Verify and commit Task 2**

```bash
PATH="$PWD/.venv/bin:$PATH" pytest tests/test_reconcile.py -q
PATH="$PWD/.venv/bin:$PATH" make verify
git add wattproof/reconcile.py tests/test_reconcile.py
git commit -m "Add deterministic utility statement reconciliation"
```

## Task 3: Add deterministic electric, gas, and water fixtures

**Files:**

- Create: `wattproof/utility_fixtures.py`
- Create: `tests/test_utility_fixtures.py`

- [ ] **Step 1: Write failing fixture acceptance tests**

```python
def test_duke_fixture_reconciles_without_tariff_claim() -> None:
    document = load_utility_sample("duke")
    result = reconcile_document(document)
    lines = {line.id: line for line in result.lines}
    assert document.sections[0].usage is not None
    assert document.sections[0].usage.value == Decimal("1001")
    assert lines["meter::electricity"].expected_amount == Decimal("1001")
    assert lines["charge::energy_tier_1"].expected_amount == Decimal("55.97")
    assert lines["charge::energy_tier_2"].expected_amount == Decimal("95.04")
    assert lines["charge::energy_tier_3"].expected_amount == Decimal("0.12")
    assert [lines[f"charge::rider_{number}"].expected_amount for number in (
        60, 62, 65, 66, 67, 68, 70, 73, 74
    )] == [
        Decimal("6.10"), Decimal("-3.62"), Decimal("2.26"),
        Decimal("2.72"), Decimal("-6.05"), Decimal("1.95"),
        Decimal("0.50"), Decimal("0.04"), Decimal("-1.07"),
    ]
    assert lines["charge::rider_67"].expected_amount == Decimal("-6.05")
    assert lines["charge::state_tax"].expected_amount == Decimal("11.74")
    assert document.current_charges.value == Decimal("167.66")
    assert document.amount_due.value == Decimal("179.40")
    assert result.tariff is None


def test_centerpoint_fixture_excludes_invisible_statement() -> None:
    document = load_utility_sample("centerpoint")
    result = reconcile_document(document)
    lines = {line.id: line for line in result.lines}
    serialized = document.model_dump_json()
    assert lines["conversion::gas::therms"].expected_amount == Decimal("112.277")
    assert document.amount_due.value == Decimal("132.19")
    assert all(value not in serialized for value in ("534", "6.326", "134.69"))


def test_bloomington_fixture_has_four_service_sections() -> None:
    document = load_utility_sample("bloomington")
    result = reconcile_document(document)
    lines = {line.id: line for line in result.lines}
    assert [section.service_type for section in document.sections] == [
        "water", "wastewater", "stormwater", "sanitation"
    ]
    assert lines["charge::water_usage"].expected_amount == Decimal("7.46")
    assert lines["charge::water_service"].billed_amount == Decimal("7.86")
    assert lines["charge::fire_protection"].billed_amount == Decimal("2.93")
    assert lines["charge::sales_tax"].expected_amount == Decimal("1.28")
    assert lines["charge::wastewater_usage"].expected_amount == Decimal("15.52")
    assert lines["charge::wastewater_service"].billed_amount == Decimal("7.95")
    assert lines["charge::stormwater"].billed_amount == Decimal("2.70")
    assert lines["charge::sanitation"].billed_amount == Decimal("6.22")
    assert document.amount_due.value == Decimal("51.92")
```

- [ ] **Step 2: Run tests and confirm the missing-loader failure**

```bash
PATH="$PWD/.venv/bin:$PATH" pytest tests/test_utility_fixtures.py -q
```

- [ ] **Step 3: Implement exact fixture data and provenance**

Create `load_utility_sample(kind)` using validated Task 1 models and helpers. Use the
exact data below:

| Fixture | Visible operands | Printed total |
| --- | --- | ---: |
| Duke | meter `137956 → 138957 = 1001 kWh`; connection `13.70`; tiers `300×.186556=55.97`, `700×.135777=95.04`, `1×.123051=.12`; riders 60 `.006090=6.10`, 62 `-.003619=-3.62`, 65 `.002259=2.26`, 66 `.002717=2.72`, 67 `-.006040=-6.05`, 68 `.001947=1.95`, 70 `.000496=.50`, 73 `.000036=.04`, 74 `-.001064=-1.07`; seven-percent tax over every pre-tax ID `11.74` | `179.40` |
| CenterPoint | `108 CCF × 1.03960 = 112.277 therm`; distribution/service `96.03`; gas cost `27.51`; seven-percent tax over those IDs `8.65` | `132.19` |
| Bloomington | water `2 kgal × 3.73 = 7.46`, service `7.86`, fire `2.93`, seven-percent tax `1.28`; wastewater `2 × 7.76 = 15.52`, service `7.95`; stormwater `2.70`; sanitation `6.22` | `51.92` |

Duke meter evidence is rendered page 1; charge evidence is page 2; the tax explanation
is page 3. CenterPoint visible summary uses pages 1–2. Bloomington values use page 1.
Include the source URLs and three digests from the approved design. Include none of the
hidden CenterPoint values in data, warnings, excerpts, or helper tables.

- [ ] **Step 4: Verify and commit Task 3**

```bash
PATH="$PWD/.venv/bin:$PATH" pytest tests/test_utility_fixtures.py tests/test_reconcile.py -q
PATH="$PWD/.venv/bin:$PATH" make verify
git add wattproof/utility_fixtures.py tests/test_utility_fixtures.py
git commit -m "Add deterministic multi-utility fixtures"
```

## Task 4: Make rendered pages authoritative during extraction

**Files:**

- Modify: `wattproof/extract.py`
- Create: `tests/test_rendered_extraction.py`
- Modify: `tests/test_wattproof.py`

- [ ] **Step 1: Write failing extraction-boundary tests**

Create tests proving the approved trust boundary:

```python
def test_known_multi_utility_hash_uses_local_fixture(monkeypatch, tmp_path) -> None:
    candidate = tmp_path / "bill.pdf"
    candidate.write_bytes(b"%PDF-placeholder")
    monkeypatch.setattr("wattproof.extract._sha256_bytes", lambda _data: DUKE_SHA256)
    extracted = extract_pdf(candidate)
    assert isinstance(extracted, UtilityDocument)
    assert extracted.fixture_kind == "duke"


def test_short_native_text_is_an_untrusted_hint(monkeypatch) -> None:
    monkeypatch.setattr(
        "wattproof.extract.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="small text\f", stderr=""
        ),
    )
    assert "[PAGE 1]" in _native_text(Path("bill.pdf"))


def test_gpt_receives_images_before_labeled_native_hint(monkeypatch) -> None:
    extracted = _extract_with_gpt(
        rendered_pages=(
            RenderedPage(page=1, data_url="data:image/png;base64,AA=="),
        ),
        native_hint="[PAGE 1]\nUNTRUSTED VALUE 999",
        document_sha256="f" * 64,
        page_count=1,
    )
    content = captured_call["input"][0]["content"]
    assert content[0]["type"] == "input_image"
    assert content[-1]["type"] == "input_text"
    assert "UNTRUSTED_NATIVE_TEXT_HINT" in content[-1]["text"]
    assert captured_call["store"] is False
    assert captured_call["text_format"] is UtilityDocument
    assert extracted.fixture_kind == "uploaded"
```

Mock `OpenAI.responses.parse` as the existing extraction-contract test does and return
`load_utility_sample("duke")`. Retain a focused assertion that the authentic PG&E hash
still returns the exact legacy fixture without an API key.

- [ ] **Step 2: Run tests and confirm text-only behavior fails**

```bash
PATH="$PWD/.venv/bin:$PATH" pytest tests/test_rendered_extraction.py -q
```

Expected: missing `RenderedPage`, missing hash mapping, and the old short-text rejection.

- [ ] **Step 3: Implement bounded page rendering and vision input**

In `wattproof/extract.py`:

- Add the three approved SHA-256 constants and map them to `load_utility_sample` kinds.
- Add frozen `RenderedPage(page: int, data_url: str)`.
- Keep 10 MB and 20-page limits.
- Render each unknown page with `pdftoppm -png -scale-to 2200` inside a
  `TemporaryDirectory`, using `shell=False` and a 30-second timeout.
- Base64-encode each PNG before the temporary directory closes. Reject failed commands,
  missing pages, or an individual PNG larger than 8 MB.
- Convert `subprocess.TimeoutExpired`, malformed/encrypted-PDF failures from `pdfinfo`,
  `pdftotext`, or `pdftoppm`, and unusable render output into actionable
  `InvalidDocumentError` messages; do not leak a raw subprocess exception.
- Make `_native_text` return labeled text even when short or empty and cap the hint at
  100,000 characters.
- Change `_extract_with_gpt` to take rendered pages, native hint, digest, and page count.
  Place image blocks first. The final input-text block begins:
  `UNTRUSTED_NATIVE_TEXT_HINT — never extract a fact unless it is also visibly present on a rendered page.`
- Keep the configured model default `gpt-5.6`, `store=False`, strict
  `text_format=UtilityDocument`, and the instruction never to calculate, repair, or
  invent.
- Tell the model to record a warning when rendered content conflicts with the native
  hint, while keeping only the rendered value and rendered evidence in facts.
- Replace model-returned fixture kind, digest, and page count with trusted local values
  before validation.

Change `extract_pdf` return type to `BillExtraction | UtilityDocument`. Known hash paths
remain deterministic and keyless.

- [ ] **Step 4: Verify and commit Task 4**

```bash
PATH="$PWD/.venv/bin:$PATH" pytest tests/test_rendered_extraction.py tests/test_wattproof.py -q
PATH="$PWD/.venv/bin:$PATH" make verify
git add wattproof/extract.py tests/test_rendered_extraction.py tests/test_wattproof.py
git commit -m "Use rendered PDF pages as extraction evidence"
```

## Task 5: Add exact adapter selection and one audit service

**Files:**

- Create: `wattproof/adapters.py`
- Create: `wattproof/audit_service.py`
- Create: `tests/test_audit_service.py`
- Modify: `wattproof/audit.py`

- [ ] **Step 1: Write failing adapter tests**

```python
def test_exact_pg_and_e_bill_keeps_tariff_verified_result() -> None:
    result = audit_extraction(load_sample("authentic"))
    assert result.schema_version == "2.0"
    assert result.verification_level == "tariff_verified"
    assert result.tariff is not None
    assert result.tariff.id == "pge_3ce_e_tou_c_2022_h2"
    assert result.discrepancy_total == Decimal("0.00")


def test_synthetic_error_remains_exactly_five_dollars() -> None:
    result = audit_extraction(load_sample("synthetic"))
    assert result.verification_level == "tariff_verified"
    assert result.discrepancy_total == Decimal("5.00")


def test_unsupported_legacy_provider_falls_back_to_internal() -> None:
    bill = load_sample("authentic")
    changed = bill.model_copy(update={"delivery_provider": TextFact(
        value="Example Utility", source_page=3, source_text="Example Utility",
        confidence=1, status="printed"
    )})
    result = audit_extraction(changed)
    assert result.verification_level == "internally_reconciled"
    assert result.tariff is None


def test_duke_never_matches_pg_and_e_adapter() -> None:
    result = audit_extraction(load_utility_sample("duke"))
    assert result.verification_level == "internally_reconciled"
    assert result.tariff is None
```

- [ ] **Step 2: Run tests and confirm the missing-service failure**

```bash
PATH="$PWD/.venv/bin:$PATH" pytest tests/test_audit_service.py -q
```

- [ ] **Step 3: Expose exact PG&E validation without weakening it**

Rename `_validate_supported_bill` in `wattproof/audit.py` to
`validate_pge_3ce_bill`. Update its internal caller. Do not change provider, schedule,
generation provider, effective period, source integrity, or arithmetic rules.

- [ ] **Step 4: Implement adapter protocol and unified output**

Create a `TariffAdapter` protocol and frozen `Pge3ceAdapter` in
`wattproof/adapters.py`. `matches` runs exact validation and returns false on
`UnsupportedBillError`. `audit` calls existing `audit_bill`, then maps it to
`UtilityAuditResult`:

- tariff category → `published_tariff`; reconciliation category →
  `statement_reconciliation`;
- preserve amounts, deltas, formulas, inputs, citations, limitations, and statuses;
- convert page/text to one `EvidenceRef`;
- mark downstream subtotal symptoms with the direct tariff discrepancy ID;
- preserve tariff version, comparison, and the grounded review request;
- translate the legacy review request to a one-item tuple with
  `provider=bill.delivery_provider.value`, preserving its subject, body, grounded audit
  line IDs, and required user-review flag;
- set `verification_level="tariff_verified"`.

Create `wattproof/audit_service.py` with this complete routing rule:

```python
Extraction = BillExtraction | UtilityDocument


def audit_extraction(extraction: Extraction) -> UtilityAuditResult:
    if isinstance(extraction, BillExtraction):
        if PGE_3CE_ADAPTER.matches(extraction):
            return PGE_3CE_ADAPTER.audit(extraction)
        return reconcile_document(translate_legacy_bill(extraction))
    return reconcile_document(extraction)
```

The registry contains only PG&E/3CE. Do not add fuzzy provider matching or Duke rates.

- [ ] **Step 5: Verify and commit Task 5**

```bash
PATH="$PWD/.venv/bin:$PATH" pytest tests/test_audit_service.py tests/test_wattproof.py -q
PATH="$PWD/.venv/bin:$PATH" make verify
git add wattproof/audit.py wattproof/adapters.py wattproof/audit_service.py tests/test_audit_service.py
git commit -m "Route audits through exact tariff adapters"
```

## Task 6: Generalize Flask and CLI entry points

**Files:**

- Modify: `wattproof/app.py`
- Modify: `wattproof/cli.py`
- Create: `tests/test_multi_utility_web.py`
- Modify: `tests/test_wattproof.py`

- [ ] **Step 1: Write failing API and CLI tests**

```python
@pytest.mark.parametrize("kind", ["duke", "centerpoint", "bloomington"])
def test_web_exposes_deterministic_samples(kind: str) -> None:
    response = create_app().test_client().get(f"/api/sample/{kind}")
    assert response.status_code == 200
    assert response.get_json()["extraction"]["schema_version"] == "2.0"


def test_web_audits_provider_neutral_payload() -> None:
    client = create_app().test_client()
    extraction = client.get("/api/sample/duke").get_json()["extraction"]
    response = client.post("/api/audit", json=extraction)
    result = response.get_json()["audit"]
    assert response.status_code == 200
    assert result["verification_level"] == "internally_reconciled"
    assert result["tariff"] is None


def test_web_rejects_unknown_schema() -> None:
    response = create_app().test_client().post(
        "/api/audit", json={"schema_version": "9"}
    )
    assert response.status_code == 422
    assert "schema_version" in response.get_json()["error"]


def test_cli_runs_duke_without_tariff_claim(capsys) -> None:
    assert main(["--sample", "duke"]) == 0
    output = capsys.readouterr().out
    assert "Internally reconciled" in output
    assert "tariff verified" not in output.lower()
```

- [ ] **Step 2: Run tests and verify the old support boundary fails**

```bash
PATH="$PWD/.venv/bin:$PATH" pytest tests/test_multi_utility_web.py -q
```

- [ ] **Step 3: Route both schemas through the audit service**

In `wattproof/app.py`, permit all five sample kinds. Use `load_sample` for authentic and
synthetic, `load_utility_sample` for the three new guides. In `/api/audit`, inspect
`schema_version`: validate `1.0` with `BillExtraction`, `2.0` with `UtilityDocument`, and
return a field-specific 422 otherwise. Call `audit_extraction`. Preserve upload limits,
temporary-file deletion, error handlers, and `/healthz`.

In `wattproof/cli.py`, expose all sample choices, call `audit_extraction`, print the
verification level through an explicit label map (`evidence_extracted` → “Evidence
extracted,” `internally_reconciled` → “Internally reconciled,” `tariff_verified` →
“Tariff verified”), and print comparison only when non-null.

- [ ] **Step 4: Verify and commit Task 6**

```bash
PATH="$PWD/.venv/bin:$PATH" pytest tests/test_multi_utility_web.py tests/test_wattproof.py -q
PATH="$PWD/.venv/bin:$PATH" make verify
git add wattproof/app.py wattproof/cli.py tests/test_multi_utility_web.py tests/test_wattproof.py
git commit -m "Expose provider-neutral audit APIs"
```

## Task 7: Render provider-neutral review and result screens

**Files:**

- Modify: `wattproof/templates/index.html`
- Modify: `wattproof/static/app.js`
- Modify: `wattproof/static/app.css`
- Modify: `tests/test_multi_utility_web.py`

- [ ] **Step 1: Add failing page-contract tests**

```python
def test_page_uses_provider_neutral_five_step_language() -> None:
    page = create_app().test_client().get("/").get_data(as_text=True)
    for label in ("Upload", "Review", "Verify", "Household", "Next steps"):
        assert f"<b>{label}</b>" in page
    assert "Choose a utility bill" in page
    assert "PG&E-first" not in page
    for sample_id in ("duke-sample", "centerpoint-sample", "bloomington-sample"):
        assert f'id="{sample_id}"' in page


def test_result_markup_exposes_neutral_contract() -> None:
    page = create_app().test_client().get("/").get_data(as_text=True)
    assert 'id="verification-level"' in page
    assert 'id="service-results"' in page
    assert 'id="optional-comparison"' in page
    assert 'id="service-review-sections"' in page
```

- [ ] **Step 2: Run tests and confirm electricity-only markup fails**

```bash
PATH="$PWD/.venv/bin:$PATH" pytest tests/test_multi_utility_web.py -q
```

- [ ] **Step 3: Replace the electricity-only hierarchy**

In `index.html`:

- Keep the paper/navy/amber/green identity, geometric mark, editorial headings, and
  evidence-first tone.
- Change the steps to Upload, Review, Verify, Household, Next steps.
- Use “Your utility bill has a formula. WattProof shows its work.”
- Present authentic PG&E and labeled synthetic first, followed by compact Duke Electric,
  CenterPoint Gas, and Bloomington Water sample controls with the tested IDs.
- Change upload text to “Choose a utility bill” and accurately disclose known fixtures
  versus configured unknown-document reading.
- Replace the hard-coded review grid/table with `service-review-sections` and grouped
  charge containers.
- Add `verification-level`, `service-results`, and `optional-comparison` (hidden by
  default) to Verify.
- Add **Add another bill** and **Finish household review** actions.

In `app.js`, keep escaping and response handling, then add these exact helpers:

```javascript
function isUtilityDocument(extraction) {
  return extraction?.schema_version === "2.0";
}

function evidenceFor(fact) {
  return fact.evidence || {
    page: fact.source_page,
    text: fact.source_text,
    confidence: fact.confidence,
  };
}

function markCorrected(fact, nextValue) {
  if (fact.status !== "user_corrected") fact.original_value = String(fact.value);
  fact.value = nextValue;
  fact.status = "user_corrected";
}
```

Retain a schema-1 review renderer and add a schema-2 renderer grouped by service
section. Show provider, service type, schedule/period when present, typed units, fact
status, confidence, page, and excerpt. Apply user edits with `markCorrected`.

Render the unified audit result as follows:

- map verification levels to “Evidence extracted,” “Internally reconciled,” and
  “Tariff verified”;
- derive service cards from the current extraction;
- render line `scope`, generic `unit`, and first `evidence` item without assuming kWh;
- show discrepancies and needs-review lines before the expandable ledger;
- display comparison only when `result.comparison` is non-null.

In `app.css`, add service cards/chips and verification-level styles. Replace the body
`Inter` preference with an offline editorial pairing led by `Avenir Next`/`Avenir` and
system fallbacks, retaining a Georgia/Baskerville display face. Preserve visible focus,
high contrast, reduced motion, and the restrained utility-receipt aesthetic.

- [ ] **Step 4: Verify and commit Task 7**

```bash
PATH="$PWD/.venv/bin:$PATH" pytest tests/test_multi_utility_web.py -q
PATH="$PWD/.venv/bin:$PATH" make verify
git add wattproof/templates/index.html wattproof/static/app.js wattproof/static/app.css tests/test_multi_utility_web.py
git commit -m "Generalize utility review and result screens"
```

Before commit, exercise authentic, synthetic, Duke, CenterPoint, and Bloomington in the
real app. Only PG&E may display Tariff verified; gas and water units must remain correct.

## Task 8: Add the memory-only household bundle and responsive next steps

**Files:**

- Modify: `wattproof/templates/index.html`
- Modify: `wattproof/static/app.js`
- Modify: `wattproof/static/app.css`
- Modify: `tests/test_multi_utility_web.py`

- [ ] **Step 1: Write failing household-flow contracts**

```python
def test_household_and_next_steps_have_required_controls() -> None:
    page = create_app().test_client().get("/").get_data(as_text=True)
    for element_id in (
        "add-another-bill", "finish-household", "household-bills",
        "household-summary", "clear-household", "provider-requests",
    ):
        assert f'id="{element_id}"' in page


def test_bundle_uses_page_memory_only() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "wattproof" / "static" / "app.js").read_text()
    assert "bundle: []" in script
    assert "sessionStorage" not in script
    assert "localStorage" not in script
```

- [ ] **Step 2: Run tests and verify controls/state are missing**

```bash
PATH="$PWD/.venv/bin:$PATH" pytest tests/test_multi_utility_web.py -q
```

- [ ] **Step 3: Implement privacy-minimized summaries**

Add `bundle: []` and `currentBundleId: null` to state. Implement:

```javascript
function summarizeCurrentBill() {
  const extraction = state.extraction;
  const result = state.audit;
  const utility = isUtilityDocument(extraction);
  const sections = utility ? extraction.sections : [];
  const bounds = utility
    ? serviceBounds(sections)
    : { start: extraction.service_start.value, end: extraction.service_end.value };
  return {
    id: crypto.randomUUID(),
    providers: utility
      ? [...new Set(sections.map((section) => section.provider.value))]
      : [extraction.delivery_provider.value, extraction.generation_provider.value],
    serviceTypes: utility
      ? [...new Set(sections.map((section) => section.service_type))]
      : ["electricity"],
    periodStart: bounds.start,
    periodEnd: bounds.end,
    period: bounds.start && bounds.end
      ? `${bounds.start} – ${bounds.end}`
      : "Period not printed",
    usageSummaries: utility
      ? sections
          .filter((section) => section.usage)
          .map((section) => ({
            serviceType: section.service_type,
            value: section.usage.value,
            unit: section.usage.unit,
          }))
      : [{
          serviceType: "electricity",
          value: extraction.total_usage.value,
          unit: "kWh",
        }],
    amountDue: extraction.amount_due.value,
    currency: utility ? extraction.currency : "USD",
    verificationLevel: result.verification_level,
    discrepancyTotal: result.discrepancy_total,
    issueCount: result.lines.filter((line) =>
      ["discrepancy", "needs_review"].includes(line.status)
    ).length,
    reviewRequests: result.review_requests,
  };
}


function serviceBounds(sections) {
  const starts = sections
    .map((section) => section.service_start?.value)
    .filter(Boolean)
    .sort();
  const ends = sections
    .map((section) => section.service_end?.value)
    .filter(Boolean)
    .sort();
  return {
    start: starts.length ? starts[0] : null,
    end: ends.length ? ends.at(-1) : null,
  };
}


function clearCurrentDocument() {
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.previewUrl = null;
  state.extraction = null;
  state.audit = null;
  byId("upload-form").reset();
  byId("file-label").textContent = "Choose a utility bill";
}
```

Never retain raw extraction, evidence excerpts, identities, account numbers, meter IDs,
PDF blobs, or full audit lines in the bundle. `usageSummaries` retains only service type,
numeric consumption, and unit.

- Add another appends one summary, clears the current document, and returns to Upload.
- On either action, append only when `currentBundleId` is null, then set it to the new
  summary ID. “Add another bill” and “Clear household” reset it to null after clearing
  the current document; repeated “Finish” clicks therefore cannot duplicate a bill.
- Finish appends exactly once, renders Household, and combines printed amounts only
  when currencies match and all summaries have overlapping `periodStart`/`periodEnd`
  ranges. Label it “Combined amount shown,” never savings.
- Household cards show providers, services, period, amount, verification level,
  consumption summaries, discrepancy, and issue count.
- Next steps renders separate editable cards from each summary's review requests.
- Clear household empties state, revokes preview, clears markup, and returns to Upload.
- Failure on a later bill leaves completed summaries intact.

- [ ] **Step 4: Make audit rows mobile-native and accessible**

At `max-width: 640px`, render each audit row as a stacked card using `data-label`; do not
require horizontal scrolling. Keep the desktop table. Focus each step heading, announce
bundle changes through `aria-live`, retain visible focus, use text plus color for status,
and respect reduced motion. Validate at `390 × 844`.

- [ ] **Step 5: Verify and commit Task 8**

```bash
PATH="$PWD/.venv/bin:$PATH" pytest tests/test_multi_utility_web.py -q
PATH="$PWD/.venv/bin:$PATH" make verify
git add wattproof/templates/index.html wattproof/static/app.js wattproof/static/app.css tests/test_multi_utility_web.py
git commit -m "Add temporary household utility bundle"
```

Real-browser acceptance: sequentially add Duke, CenterPoint, and Bloomington; verify
three retained cards, refresh-clears behavior, `112.277 therms`, `$132.19`, no mobile
sideways scroll, and separate provider requests.

## Task 9: Document, capture screenshots, and verify the handoff

**Files:**

- Create: `scripts/fetch-public-samples.sh`
- Create: `docs/screenshots/README.md`
- Create: `docs/screenshots/multi-utility-upload-desktop.png`
- Create: `docs/screenshots/pge-tariff-verified-desktop.png`
- Create: `docs/screenshots/duke-internal-reconciliation-desktop.png`
- Create: `docs/screenshots/centerpoint-gas-desktop.png`
- Create: `docs/screenshots/household-bundle-desktop.png`
- Create: `docs/screenshots/water-review-mobile.png`
- Create: `docs/screenshots/household-result-mobile.png`
- Modify: `README.md`, `ARCHITECTURE.md`, `GROUND_TRUTH.md`, `tests/test_multi_utility_web.py`

- [ ] **Step 1: Add the failing artifact contract**

```python
def test_review_artifacts_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = (
        "multi-utility-upload-desktop.png",
        "pge-tariff-verified-desktop.png",
        "duke-internal-reconciliation-desktop.png",
        "centerpoint-gas-desktop.png",
        "household-bundle-desktop.png",
        "water-review-mobile.png",
        "household-result-mobile.png",
    )
    for name in expected:
        image = root / "docs" / "screenshots" / name
        assert image.is_file()
        assert image.stat().st_size > 10_000
    assert (root / "docs" / "screenshots" / "README.md").is_file()
```

Run it and confirm failure because the artifacts are absent.

- [ ] **Step 2: Add optional hash-checked sample fetching**

Create `scripts/fetch-public-samples.sh` with `set -euo pipefail`. Download into ignored
`tmp/public-samples/`. Refuse to continue if an existing or downloaded file does not
match:

```text
b131c36a215762796e72f3d20986fbea7e64e2dd611081d8936f8442102c3e9a  duke-electricity.pdf
c0b7d9b0252226078b39d6760308506c28b388729906d3ac54db950b9f819262  centerpoint-gas.pdf
a414c296e3dd71a08aa459bb1a7c38fcdeab0c90aa0bb05f7c4e39ae9d70b79c  bloomington-water.pdf
```

Use the exact official URLs from the design spec. Do not track third-party PDFs.

- [ ] **Step 3: Update documentation without broad tariff claims**

Document the three verification levels, provider-neutral internal engine, exact adapter
boundary, rendered-page authority, CenterPoint hidden-text hazard, raster Bloomington
fixture, illustrative Duke limitation, memory-only bundle, keyless known fixtures,
configured GPT-5.6 path, new CLI samples, and verification command. Extend
`GROUND_TRUTH.md` with exact values, URLs, and hashes. Never claim Duke tariff or
nationwide tariff support.

- [ ] **Step 4: Capture seven real application screenshots**

Run the actual app. Use public samples only. Capture desktop at `1440 × 1000` and mobile
at `390 × 844`. Exercise real controls; do not compose or generate mockups. Visually
inspect each PNG. In `docs/screenshots/README.md`, record filename, viewport, sample,
navigation steps, visible verification level, commit SHA, and no-PII confirmation.

- [ ] **Step 5: Run complete verification and privacy checks**

```bash
PATH="$PWD/.venv/bin:$PATH" make verify
git diff --check main...HEAD
git status --short
rg "github.ref == 'refs/heads/main'" .github/workflows/verify.yml
if git diff --name-only main...HEAD | rg '\.env$|tmp/public-samples|\.pdf$'; then exit 1; fi
```

Expected: tests, Ruff, mypy, compileall, whitespace, and privacy checks pass; no fetched
PDF is tracked, and the production deployment guard remains restricted to `main`.

- [ ] **Step 6: Commit Task 9**

```bash
git add scripts/fetch-public-samples.sh docs/screenshots README.md ARCHITECTURE.md GROUND_TRUTH.md tests/test_multi_utility_web.py
git commit -m "Document and capture multi-utility review flow"
```

## Final cross-task verification

After Task 9 and both of its reviews:

```bash
PATH="$PWD/.venv/bin:$PATH" make verify
git diff --check main...HEAD
git status --short --branch
git log --oneline main..HEAD
```

Dispatch one final reviewer over `main...HEAD`. Fix and re-review every Critical or
Important finding before invoking `superpowers:finishing-a-development-branch`. No
implementation agent may merge or push to upstream `main`.
