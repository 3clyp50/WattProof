"use strict";

const state = {
  extraction: null,
  audit: null,
  previewUrl: null,
  compactAudit: true,
  reviewMode: null,
  extractionRevision: 0,
  auditRevision: 0,
  operationToken: 0,
  activeOperation: null,
  bundle: [],
  currentBundleId: null,
  currentBundleAuditRevision: null,
  replacementBundleId: null,
  replacementArmed: false,
};

const legacyFactDefinitions = [
  ["delivery_provider", "Delivery provider", "text"],
  ["generation_provider", "Generation provider", "text"],
  ["delivery_schedule", "Delivery schedule", "text"],
  ["generation_schedule", "Generation schedule", "text"],
  ["statement_date", "Statement date", "date"],
  ["service_start", "Service start", "date"],
  ["service_end", "Service end", "date"],
  ["billing_days", "Billing days", "number"],
  ["total_usage", "Total usage", "number"],
  ["peak_usage", "Peak usage", "number"],
  ["off_peak_usage", "Off-peak usage", "number"],
  ["baseline_allowance", "Baseline allowance", "number"],
  ["current_charges", "Current charges", "number"],
  ["amount_due", "Amount due", "number"],
];

const serviceLabels = {
  electricity: "Electricity",
  natural_gas: "Natural gas",
  water: "Water",
  wastewater: "Wastewater",
  stormwater: "Stormwater",
  sanitation: "Sanitation",
  other: "Other charges",
};

const verificationLabels = {
  evidence_extracted: "Evidence extracted",
  internally_reconciled: "Internally reconciled",
  tariff_verified: "Tariff verified",
};

const scopeLabels = {
  printed_math: "Printed math",
  statement_reconciliation: "Statement reconciliation",
  published_tariff: "Published tariff",
};

const statusLabels = {
  verified: "Verified",
  discrepancy: "Discrepancy",
  cannot_verify: "Cannot verify",
  needs_review: "Needs review",
};

function auditStatusLabel(line) {
  if (line.status === "verified" && line.scope === "printed_math") {
    return "Math agrees";
  }
  return statusLabels[line.status] || statusLabel(line.status);
}

const byId = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

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

function valueAt(object, path) {
  return path.split(".").reduce((current, key) => current?.[key], object);
}

function safeErrorMessage(error) {
  return error instanceof Error && error.message
    ? error.message
    : "The request could not be completed.";
}

function isAbortError(error) {
  return error?.name === "AbortError";
}

function showMessage(message = "", input = null) {
  const element = byId("global-message");
  document.querySelectorAll('[aria-describedby="global-message"]').forEach((field) => {
    field.removeAttribute("aria-describedby");
    field.removeAttribute("aria-invalid");
  });
  element.textContent = message;
  element.hidden = !message;
  if (!message) return;
  element.scrollIntoView({ block: "center" });
  element.focus({ preventScroll: true });
  if (input) {
    input.setAttribute("aria-invalid", "true");
    input.setAttribute("aria-describedby", "global-message");
    input.focus({ preventScroll: true });
  }
}

function showError(error) {
  const message = safeErrorMessage(error);
  const input = [...document.querySelectorAll("[data-fact-path]")]
    .find((candidate) => message.includes(candidate.dataset.factPath));
  showMessage(message, input || null);
}

function invalidatePendingOperation() {
  state.operationToken += 1;
  const operation = state.activeOperation;
  state.activeOperation = null;
  if (!operation) return;
  operation.controller.abort();
  operation.cleanup();
}

function beginOperation(cleanup) {
  invalidatePendingOperation();
  const operation = {
    token: state.operationToken,
    controller: new AbortController(),
    cleanup,
  };
  state.activeOperation = operation;
  return operation;
}

function isCurrentOperation(operation) {
  return state.activeOperation === operation
    && state.operationToken === operation.token
    && !operation.controller.signal.aborted;
}

function finishOperation(operation) {
  if (!isCurrentOperation(operation)) return;
  state.activeOperation = null;
  operation.cleanup();
}

function replaceExtraction(extraction, mode) {
  const replacementId = state.replacementArmed
    && state.bundle.some((summary) => summary.id === state.replacementBundleId)
    ? state.replacementBundleId
    : null;
  state.extraction = extraction;
  state.audit = null;
  state.currentBundleId = replacementId;
  state.currentBundleAuditRevision = null;
  state.reviewMode = mode;
  state.extractionRevision += 1;
  state.auditRevision = 0;
}

function showStep(step) {
  document.querySelectorAll("[data-step]").forEach((panel) => {
    panel.hidden = Number(panel.dataset.step) !== step;
  });
  document.querySelectorAll("[data-step-indicator]").forEach((indicator) => {
    const indicatorStep = Number(indicator.dataset.stepIndicator);
    indicator.classList.toggle("active", indicatorStep === step);
    indicator.classList.toggle("complete", indicatorStep < step);
    if (indicatorStep === step) indicator.setAttribute("aria-current", "step");
    else indicator.removeAttribute("aria-current");
  });
  const banner = byId("synthetic-banner");
  const notice = state.extraction?.synthetic_notice;
  banner.textContent = notice || "";
  banner.hidden = !(notice && step > 1);
  showMessage();
  window.scrollTo({ top: 0, behavior: "auto" });
  document.querySelector(`[data-step="${step}"] h1`)?.focus({ preventScroll: true });
}

function setLoading(button, loading, label) {
  if (!button.dataset.originalLabel) button.dataset.originalLabel = button.innerHTML;
  button.disabled = loading;
  button.innerHTML = loading ? label : button.dataset.originalLabel;
}

function setReviewPending(pending) {
  byId("review-form")
    .querySelectorAll("[data-fact-path], button[type='submit']")
    .forEach((control) => { control.disabled = pending; });
}

async function responseJson(response) {
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error("The server returned an unreadable response.");
  }
  if (!response.ok) {
    const message = typeof payload?.error === "string"
      ? payload.error
      : "The request could not be completed.";
    throw new Error(message);
  }
  return payload;
}

function statusLabel(status) {
  return String(status || "printed").replaceAll("_", " ");
}

const decimalSpelling = /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?)(\d+))?$/;
const maxDecimalCharacters = 64;
const maxDecimalDigits = 28;
const maxExactInteger = 999999999999;
const minDecimalExponent = -18;
const maxDecimalExponent = 11;
const maxDecimalAdjustedExponent = 11;
const maxDecimalPower = 64;

function parseBoundedDecimalString(value) {
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value) || value < -maxExactInteger || value > maxExactInteger) {
      return null;
    }
    value = String(value);
  }
  if (typeof value !== "string" || value.length > maxDecimalCharacters) return null;
  const match = decimalSpelling.exec(value);
  if (!match) return null;

  const integerDigits = match[2] || "";
  const fractionalDigits = match[3] ?? match[4] ?? "";
  const coefficientSpelling = `${integerDigits}${fractionalDigits}`;
  const significantDigits = coefficientSpelling.replace(/^0+/, "") || "0";
  if (significantDigits.length > maxDecimalDigits) return null;

  const exponentDigits = (match[6] || "0").replace(/^0+/, "") || "0";
  if (exponentDigits.length > 2) return null;
  const exponentMagnitude = exponentDigits.length === 2
    ? (exponentDigits.charCodeAt(0) - 48) * 10 + exponentDigits.charCodeAt(1) - 48
    : exponentDigits.charCodeAt(0) - 48;
  const explicitExponent = match[5] === "-" ? -exponentMagnitude : exponentMagnitude;
  const exponent = explicitExponent - fractionalDigits.length;
  if (exponent < minDecimalExponent || exponent > maxDecimalExponent) return null;
  const isZero = significantDigits === "0";
  const adjustedExponent = exponent + significantDigits.length - 1;
  if (!isZero && adjustedExponent > maxDecimalAdjustedExponent) return null;

  const coefficient = BigInt(significantDigits);
  return {
    coefficient,
    exponent,
    negative: match[1] === "-" && coefficient !== 0n,
    spelling: value,
  };
}

function powerOfTen(exponent) {
  if (!Number.isInteger(exponent) || exponent < 0 || exponent > maxDecimalPower) {
    return null;
  }
  return 10n ** BigInt(exponent);
}

function decimalPlainText(decimal, groupThousands = true) {
  if (!decimal) return "—";
  if (decimal.coefficient === 0n) {
    return decimal.exponent < 0
      ? `0.${"0".repeat(-decimal.exponent)}`
      : "0";
  }

  const digits = decimal.coefficient.toString();
  const point = digits.length + decimal.exponent;
  let integer;
  let fraction = "";
  if (point <= 0) {
    integer = "0";
    fraction = `${"0".repeat(-point)}${digits}`;
  } else if (point >= digits.length) {
    integer = `${digits}${"0".repeat(point - digits.length)}`;
  } else {
    integer = digits.slice(0, point);
    fraction = digits.slice(point);
  }
  if (groupThousands) integer = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${decimal.negative ? "−" : ""}${integer}${fraction ? `.${fraction}` : ""}`;
}

function roundScaledMagnitude(decimal, decimalPlaces) {
  if (!decimal || !Number.isInteger(decimalPlaces) || decimalPlaces < 0 || decimalPlaces > 18) {
    return null;
  }
  const shift = decimal.exponent + decimalPlaces;
  let magnitude;
  if (shift >= 0) {
    const multiplier = powerOfTen(shift);
    if (multiplier === null) return null;
    magnitude = decimal.coefficient * multiplier;
  } else {
    const divisor = powerOfTen(-shift);
    if (divisor === null) return null;
    magnitude = decimal.coefficient / divisor;
    const remainder = decimal.coefficient % divisor;
    if (remainder * 2n >= divisor) magnitude += 1n;
  }
  return {
    magnitude,
    negative: decimal.negative && magnitude !== 0n,
  };
}

function formatMoneyDecimal(decimal, currency = "USD") {
  const rounded = roundScaledMagnitude(decimal, 2);
  if (!rounded) return "—";
  const cents = rounded.magnitude.toString().padStart(3, "0");
  const whole = cents.slice(0, -2) || "0";
  const fraction = cents.slice(-2);
  const sign = rounded.negative ? "−" : "";
  const prefix = currency === "USD" ? "$" : `${String(currency)} `;
  return `${sign}${prefix}${whole}.${fraction}`;
}

function confidencePercentage(value) {
  const decimal = parseBoundedDecimalString(value);
  if (!decimal || decimal.negative) return null;
  if (decimal.coefficient !== 0n) {
    const upperBound = decimal.exponent >= 0
      ? 1n
      : powerOfTen(-decimal.exponent);
    const multiplier = decimal.exponent >= 0 ? powerOfTen(decimal.exponent) : 1n;
    if (upperBound === null || multiplier === null) return null;
    const scaledCoefficient = decimal.coefficient * multiplier;
    if (scaledCoefficient > upperBound) return null;
  }
  const rounded = roundScaledMagnitude(decimal, 2);
  return rounded ? rounded.magnitude.toString() : null;
}

function exactDecimalSum(values) {
  if (!values.length) return null;
  const decimals = values.map(parseBoundedDecimalString);
  if (decimals.some((decimal) => decimal === null)) return null;
  let commonExponent = decimals[0].exponent;
  decimals.forEach((decimal) => {
    if (decimal.exponent < commonExponent) commonExponent = decimal.exponent;
  });
  let total = 0n;
  for (const decimal of decimals) {
    const multiplier = powerOfTen(decimal.exponent - commonExponent);
    if (multiplier === null) return null;
    const scaled = decimal.coefficient * multiplier;
    total += decimal.negative ? -scaled : scaled;
  }
  return {
    coefficient: total < 0n ? -total : total,
    exponent: commonExponent,
    negative: total < 0n,
  };
}

function evidenceMarkup(fact) {
  const evidence = evidenceFor(fact);
  const confidence = confidencePercentage(evidence.confidence);
  const percentage = confidence !== null
    ? `${confidence}% confidence`
    : "confidence unavailable";
  return `<details class="fact-evidence"><summary>Page ${escapeHtml(evidence.page)} · ${percentage}</summary><blockquote>${escapeHtml(evidence.text)}</blockquote></details>`;
}

function factEditor(fact, label, path, type = "text") {
  if (!fact) return "";
  const id = `fact-${path.replaceAll(/[^a-zA-Z0-9_-]/g, "-")}`;
  const unit = fact.unit || fact.currency || "";
  const numericDecimal = type === "number" ? parseBoundedDecimalString(fact.value) : null;
  const numericUnavailable = type === "number" && numericDecimal === null;
  const inputType = type === "number" ? "text" : type;
  const inputValue = type === "number"
    ? (numericDecimal ? numericDecimal.spelling : "")
    : fact.value;
  const corrected = fact.status === "user_corrected"
    ? `<small class="correction-note">Originally ${escapeHtml(fact.original_value)}</small>`
    : "";
  const unavailable = numericUnavailable
    ? `<small class="correction-note">Exact numeric spelling unavailable; enter a reviewed value to replace it.</small>`
    : "";
  return `
    <div class="fact-field">
      <label for="${escapeHtml(id)}">
        <span>${escapeHtml(label)}</span>
        <span class="evidence-type ${escapeHtml(fact.status)}">${escapeHtml(statusLabel(fact.status))}</span>
      </label>
      <div class="typed-input">
        <input id="${escapeHtml(id)}" data-fact-path="${escapeHtml(path)}"${type === "number" ? ` data-exact-number="${numericUnavailable ? "false" : "true"}" inputmode="decimal"` : ""} type="${escapeHtml(inputType)}" value="${escapeHtml(inputValue)}"${numericUnavailable ? ' placeholder="Exact value unavailable"' : ""}>
        ${unit ? `<span>${escapeHtml(unit)}</span>` : ""}
      </div>
      ${corrected}
      ${unavailable}
      ${evidenceMarkup(fact)}
    </div>`;
}

function periodText(start, end) {
  if (start?.value && end?.value) return `${start.value} – ${end.value}`;
  return start?.value || end?.value || "";
}

function renderLegacyReview() {
  const extraction = state.extraction;
  const fields = legacyFactDefinitions.map(([path, label, type]) => (
    factEditor(valueAt(extraction, path), label, path, type)
  ));
  let factCount = fields.length;
  const charges = extraction.charges.map((line, index) => {
    const editors = [];
    if (line.quantity) {
      editors.push(factEditor(line.quantity, "Quantity", `charges.${index}.quantity`, "number"));
      factCount += 1;
    }
    if (line.rate) {
      editors.push(factEditor(line.rate, "Rate", `charges.${index}.rate`, "number"));
      factCount += 1;
    }
    editors.push(factEditor(line.billed_amount, "Printed amount", `charges.${index}.billed_amount`, "number"));
    factCount += 1;
    return `
      <article class="charge-editor">
        <div class="charge-editor-heading"><strong>${escapeHtml(line.label)}</strong>${line.period ? `<span>${escapeHtml(line.period)}</span>` : ""}</div>
        <div class="fact-fields charge-facts">${editors.join("")}</div>
      </article>`;
  }).join("");

  byId("service-review-sections").innerHTML = `
    <article class="service-review-card">
      <header class="service-review-header">
        <div><span class="service-type">Electricity</span><h3>${escapeHtml(extraction.delivery_provider.value)} + ${escapeHtml(extraction.generation_provider.value)}</h3></div>
        <div class="service-chips"><span>${escapeHtml(measurementFactText(extraction.total_usage))}</span><span>${escapeHtml(periodText(extraction.service_start, extraction.service_end))}</span></div>
      </header>
      <div class="fact-fields">${fields.join("")}</div>
      <section class="charge-group"><h4>Printed charge lines</h4>${charges}</section>
    </article>`;
  byId("fact-count").textContent = `${factCount} reviewable facts`;
}

function utilitySectionFacts(section, sectionIndex) {
  const base = `sections.${sectionIndex}`;
  const fields = [
    factEditor(section.provider, "Provider", `${base}.provider`),
    factEditor(section.jurisdiction, "Jurisdiction", `${base}.jurisdiction`),
    factEditor(section.schedule, "Schedule", `${base}.schedule`),
    factEditor(section.service_start, "Service start", `${base}.service_start`, "date"),
    factEditor(section.service_end, "Service end", `${base}.service_end`, "date"),
    factEditor(section.usage, "Service usage", `${base}.usage`, "number"),
  ];
  if (section.meter) {
    fields.push(
      factEditor(section.meter.previous, "Previous meter reading", `${base}.meter.previous`, "number"),
      factEditor(section.meter.current, "Current meter reading", `${base}.meter.current`, "number"),
      factEditor(section.meter.usage, "Metered usage", `${base}.meter.usage`, "number"),
    );
  }
  section.conversions.forEach((conversion, conversionIndex) => {
    fields.push(
      factEditor(conversion.source, `${conversion.label} · source`, `${base}.conversions.${conversionIndex}.source`, "number"),
      factEditor(conversion.factor, `${conversion.label} · factor`, `${base}.conversions.${conversionIndex}.factor`, "number"),
      factEditor(conversion.result, `${conversion.label} · result`, `${base}.conversions.${conversionIndex}.result`, "number"),
    );
  });
  section.supplemental_facts.forEach((namedFact, factIndex) => {
    const type = Object.hasOwn(namedFact.fact, "unit") ? "number" : "text";
    fields.push(factEditor(namedFact.fact, namedFact.id.replaceAll("_", " "), `${base}.supplemental_facts.${factIndex}.fact`, type));
  });
  return fields.filter(Boolean);
}

function renderUtilityReview() {
  const extraction = state.extraction;
  let factCount = 0;
  const sections = extraction.sections.map((section, sectionIndex) => {
    const base = `sections.${sectionIndex}`;
    const facts = utilitySectionFacts(section, sectionIndex);
    factCount += facts.length;
    const charges = section.charges.map((charge, chargeIndex) => {
      const chargeBase = `${base}.charges.${chargeIndex}`;
      const editors = [
        factEditor(charge.quantity, "Quantity", `${chargeBase}.quantity`, "number"),
        factEditor(charge.rate, "Rate", `${chargeBase}.rate`, "number"),
        factEditor(charge.amount, "Printed amount", `${chargeBase}.amount`, "number"),
      ].filter(Boolean);
      factCount += editors.length;
      return `
        <article class="charge-editor">
          <div class="charge-editor-heading"><strong>${escapeHtml(charge.label)}</strong>${charge.period ? `<span>${escapeHtml(charge.period)}</span>` : ""}</div>
          <div class="fact-fields charge-facts">${editors.join("")}</div>
        </article>`;
    }).join("");
    factCount += 1;
    const period = periodText(section.service_start, section.service_end);
    const usage = measurementFactText(section.usage || section.meter?.usage);
    return `
      <article class="service-review-card">
        <header class="service-review-header">
          <div><span class="service-type">${escapeHtml(serviceLabels[section.service_type] || section.service_type)}</span><h3>${escapeHtml(section.provider.value)}</h3></div>
          <div class="service-chips">${section.schedule ? `<span>${escapeHtml(section.schedule.value)}</span>` : ""}${period ? `<span>${escapeHtml(period)}</span>` : ""}${usage ? `<span>${escapeHtml(usage)}</span>` : ""}</div>
        </header>
        <div class="fact-fields">${facts.join("")}</div>
        <section class="charge-group"><h4>Printed charge lines</h4>${charges}</section>
        <div class="subtotal-fact">${factEditor(section.subtotal, "Section subtotal", `${base}.subtotal`, "number")}</div>
      </article>`;
  });

  const documentFacts = [
    factEditor(extraction.statement_date, "Statement date", "statement_date", "date"),
    factEditor(extraction.current_charges, "Current charges", "current_charges", "number"),
    factEditor(extraction.outstanding_balance, "Outstanding balance", "outstanding_balance", "number"),
    factEditor(extraction.amount_due, "Amount due", "amount_due", "number"),
  ].filter(Boolean);
  factCount += documentFacts.length;
  sections.push(`
    <article class="service-review-card statement-review-card">
      <header class="service-review-header"><div><span class="service-type">Statement</span><h3>Document totals</h3></div><div class="service-chips"><span>${escapeHtml(extraction.currency)}</span></div></header>
      <div class="fact-fields">${documentFacts.join("")}</div>
    </article>`);

  byId("service-review-sections").innerHTML = sections.join("");
  byId("fact-count").textContent = `${factCount} reviewable facts`;
}

function renderDocumentPreview(mode) {
  const frame = byId("pdf-preview");
  const placeholder = byId("synthetic-preview");
  const placeholderMark = byId("document-placeholder-mark");
  const placeholderTitle = byId("document-placeholder-title");
  const placeholderCopy = byId("document-placeholder-copy");
  const modeLabels = {
    uploaded: "Uploaded · not retained",
    synthetic: "Labeled synthetic data",
    authentic: "Public anonymized sample",
    duke: "Public Duke sample",
    centerpoint: "Public CenterPoint sample",
    bloomington: "Public Bloomington sample",
  };
  byId("document-mode").textContent = modeLabels[mode] || "Public utility sample";

  if (mode === "synthetic") {
    frame.hidden = true;
    frame.removeAttribute("src");
    placeholder.hidden = false;
    placeholderMark.textContent = "±";
    placeholderTitle.textContent = "Structured synthetic fixture";
    placeholderCopy.textContent = "The authentic public PDF is unchanged. Only the extracted peak-charge value is altered for this detection test.";
    return;
  }

  if (mode !== "uploaded" && isUtilityDocument(state.extraction)) {
    frame.hidden = true;
    frame.removeAttribute("src");
    placeholder.hidden = false;
    placeholderMark.textContent = "✓";
    placeholderTitle.textContent = "Rendered-page evidence recorded";
    placeholderCopy.textContent = "This deterministic public fixture keeps the official sample page, confidence, and visible excerpt with every reviewable fact.";
    return;
  }

  const source = mode === "uploaded"
    ? state.previewUrl
    : "/sample.pdf";
  if (!source) {
    frame.hidden = true;
    frame.removeAttribute("src");
    placeholder.hidden = false;
    placeholderMark.textContent = "?";
    placeholderTitle.textContent = "Rendered source unavailable";
    placeholderCopy.textContent = "Review the page, excerpt, confidence, and provenance attached to each extracted fact.";
    return;
  }
  placeholder.hidden = true;
  frame.hidden = false;
  frame.src = `${source}#page=1&view=FitH`;
}

function renderReview(mode) {
  state.reviewMode = mode;
  if (isUtilityDocument(state.extraction)) renderUtilityReview();
  else renderLegacyReview();
  renderReviewWarnings();
  renderDocumentPreview(mode);
}

function renderReviewWarnings() {
  const container = byId("review-warnings");
  const warnings = Array.isArray(state.extraction?.warnings)
    ? state.extraction.warnings
      .filter((warning) => typeof warning === "string" && warning.trim())
    : [];
  container.hidden = warnings.length === 0;
  container.innerHTML = warnings.length
    ? `<strong>Review before continuing</strong><p>The source reader reported:</p><ul>${warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("")}</ul>`
    : "";
}

async function loadSample(kind, button) {
  prepareForNewDocument();
  showStep(1);
  const operation = beginOperation(() => setLoading(button, false, ""));
  setLoading(button, true, "Loading public fixture…");
  try {
    const payload = await responseJson(await fetch(`/api/sample/${kind}`, {
      signal: operation.controller.signal,
    }));
    if (!isCurrentOperation(operation)) return;
    replaceExtraction(payload.extraction, kind);
    renderReview(kind);
    showStep(2);
  } catch (error) {
    if (!isCurrentOperation(operation) || isAbortError(error)) return;
    showError(error);
  } finally {
    finishOperation(operation);
  }
}

function applyReviewEdits() {
  let changed = false;
  document.querySelectorAll("[data-fact-path]").forEach((input) => {
    const fact = valueAt(state.extraction, input.dataset.factPath);
    if (input.dataset.exactNumber === "false" && input.value === "") return;
    if (fact && String(fact.value) !== input.value) {
      markCorrected(fact, input.value);
      changed = true;
    }
  });
  return changed;
}

function money(value, currency = "USD") {
  return formatMoneyDecimal(parseBoundedDecimalString(value), currency);
}

function decimalValue(value) {
  return decimalPlainText(parseBoundedDecimalString(value));
}

function measurementFactText(fact) {
  if (!fact) return "";
  return `${decimalValue(fact.value)} ${String(fact.unit || "")}`.trim();
}

function auditValue(value, unit, currency) {
  if (value === null || value === undefined) return "—";
  const formatted = unit === currency || /^[A-Z]{3}$/.test(unit)
    ? money(value, unit)
    : `${decimalValue(value)} ${unit}`;
  return escapeHtml(formatted);
}

function summaryDecimalString(value) {
  return parseBoundedDecimalString(value)?.spelling ?? null;
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

function lineRootCauseIds(line) {
  const multiple = Array.isArray(line?.root_cause_ids)
    ? line.root_cause_ids.map(String).filter(Boolean)
    : [];
  if (multiple.length) return [...new Set(multiple)];
  const single = String(line?.root_cause_id || "");
  return single ? [single] : [];
}

function rootIssueCount(lines) {
  let count = 0;
  lines.forEach((line, index) => {
    if (!["discrepancy", "needs_review"].includes(line.status)) return;
    if (lineRootCauseIds(line).length) return;
    if (String(line.id || `issue-${index}`)) count += 1;
  });
  return count;
}

function reviewRequestDrafts(result) {
  if (!Array.isArray(result?.review_requests)) return [];
  return result.review_requests.map((request) => ({
    provider: String(request?.provider || "Provider"),
    subject: String(request?.subject || "Utility bill review request"),
    body: String(request?.body || ""),
  }));
}

function summarizeCurrentBill() {
  const extraction = state.extraction;
  const result = state.audit;
  if (!extraction || !result) return null;
  const utility = isUtilityDocument(extraction);
  const sections = utility && Array.isArray(extraction.sections)
    ? extraction.sections
    : [];
  const bounds = utility
    ? serviceBounds(sections)
    : {
      start: extraction.service_start?.value || null,
      end: extraction.service_end?.value || null,
    };
  const providers = utility
    ? sections.map((section) => section.provider?.value)
    : [extraction.delivery_provider?.value, extraction.generation_provider?.value];
  const usageSummaries = utility
    ? sections
      .filter((section) => section.usage)
      .map((section) => ({
        serviceType: String(section.service_type || "other"),
        value: summaryDecimalString(section.usage.value),
        unit: String(section.usage.unit || ""),
      }))
      .filter((usage) => usage.value !== null)
    : [{
      serviceType: "electricity",
      value: summaryDecimalString(extraction.total_usage?.value),
      unit: String(extraction.total_usage?.unit || "kWh"),
    }].filter((usage) => usage.value !== null);
  const periodStart = bounds.start ? String(bounds.start) : null;
  const periodEnd = bounds.end ? String(bounds.end) : null;
  return {
    id: crypto.randomUUID(),
    providers: [...new Set(providers.filter(Boolean).map(String))],
    serviceTypes: [...new Set((utility
      ? sections.map((section) => section.service_type)
      : ["electricity"]
    ).filter(Boolean).map(String))],
    periodStart,
    periodEnd,
    period: periodStart && periodEnd
      ? `${periodStart} – ${periodEnd}`
      : "Period not printed",
    usageSummaries,
    amountDue: summaryDecimalString(extraction.amount_due?.value),
    currency: String((utility ? extraction.currency : result.currency || "USD") || ""),
    verificationLevel: String(result.verification_level || "evidence_extracted"),
    discrepancyTotal: summaryDecimalString(result.discrepancy_total) ?? "0",
    issueCount: rootIssueCount(Array.isArray(result.lines) ? result.lines : []),
    reviewRequests: reviewRequestDrafts(result),
  };
}

function appendCurrentBillOnce() {
  if (state.currentBundleId !== null) {
    const index = state.bundle.findIndex((summary) => (
      summary.id === state.currentBundleId
    ));
    if (index >= 0 && state.currentBundleAuditRevision === state.auditRevision) {
      return state.bundle[index];
    }
    const replacement = summarizeCurrentBill();
    if (!replacement) return index >= 0 ? state.bundle[index] : null;
    if (index >= 0) {
      replacement.id = state.currentBundleId;
      state.bundle.splice(index, 1, replacement);
      state.currentBundleAuditRevision = state.auditRevision;
      return replacement;
    }
    state.currentBundleId = null;
  }
  const summary = summarizeCurrentBill();
  if (!summary) return null;
  state.bundle.push(summary);
  state.currentBundleId = summary.id;
  state.currentBundleAuditRevision = state.auditRevision;
  return summary;
}

function completeOverlappingPeriods(summaries) {
  if (!summaries.length) return false;
  const periods = summaries.map((summary) => {
    const start = Date.parse(`${summary.periodStart || ""}T00:00:00Z`);
    const end = Date.parse(`${summary.periodEnd || ""}T00:00:00Z`);
    return { start, end };
  });
  if (periods.some(({ start, end }) => (
    !Number.isFinite(start) || !Number.isFinite(end) || start > end
  ))) return false;
  const latestStart = Math.max(...periods.map(({ start }) => start));
  const earliestEnd = Math.min(...periods.map(({ end }) => end));
  return latestStart <= earliestEnd;
}

function combinedBundleAmount() {
  if (state.bundle.length < 2 || !completeOverlappingPeriods(state.bundle)) return null;
  const currencyValues = state.bundle.map((summary) => summary.currency);
  if (currencyValues.some((currency) => (
    typeof currency !== "string" || currency.trim() === ""
  ))) return null;
  const currencies = new Set(currencyValues);
  const amount = exactDecimalSum(state.bundle.map((summary) => summary.amountDue));
  if (currencies.size !== 1 || amount === null) {
    return null;
  }
  return {
    currency: state.bundle[0].currency,
    amount,
  };
}

function verificationSummary(level) {
  return verificationLabels[level] || statusLabel(level || "evidence_extracted");
}

function renderHousehold() {
  const summaryElement = byId("household-summary");
  const billsElement = byId("household-bills");
  if (!state.bundle.length) {
    summaryElement.innerHTML = "";
    billsElement.innerHTML = "";
    return;
  }

  const combined = combinedBundleAmount();
  const countLabel = state.bundle.length === 1
    ? "1 completed bill"
    : `${state.bundle.length} completed bills`;
  summaryElement.innerHTML = `
    <div class="household-summary-copy">
      <span class="card-kicker">Page-memory household</span>
      <h2>${escapeHtml(countLabel)}</h2>
      <p>Only minimized bill summaries and editable review drafts remain in this page.</p>
    </div>
    <div class="combined-amount ${combined ? "available" : "separate"}">
      ${combined
    ? `<span>Combined amount shown</span><strong>${escapeHtml(formatMoneyDecimal(combined.amount, combined.currency))}</strong><small>Printed amounts share one currency and a common service-period overlap.</small>`
    : `<span>Printed amounts remain separate</span><strong>Not combined</strong><small>Every bill needs one currency and a complete, mutually overlapping service period.</small>`}
    </div>`;

  billsElement.innerHTML = state.bundle.map((summary) => {
    const services = summary.serviceTypes
      .map((serviceType) => serviceLabels[serviceType] || serviceType)
      .join(", ");
    const providers = summary.providers.join(" + ") || "Provider not printed";
    const verification = verificationSummary(summary.verificationLevel);
    const levelClass = Object.hasOwn(verificationLabels, summary.verificationLevel)
      ? summary.verificationLevel
      : "evidence_extracted";
    const usage = summary.usageSummaries.length
      ? summary.usageSummaries.map((item) => `
        <li><span>${escapeHtml(serviceLabels[item.serviceType] || item.serviceType)}</span><strong>${escapeHtml(decimalValue(item.value))} ${escapeHtml(item.unit)}</strong></li>`).join("")
      : `<li><span>Usage</span><strong>Not printed</strong></li>`;
    return `
      <article class="household-bill-card">
        <header>
          <div><span class="service-type">${escapeHtml(services || "Utility service")}</span><h3>${escapeHtml(providers)}</h3></div>
          <span class="household-status ${escapeHtml(levelClass)}">${escapeHtml(verification)}</span>
        </header>
        <dl>
          <div><dt>Service period</dt><dd>${escapeHtml(summary.period)}</dd></div>
          <div><dt>Printed amount</dt><dd>${escapeHtml(money(summary.amountDue, summary.currency))}</dd></div>
          <div><dt>Discrepancy total</dt><dd>${escapeHtml(money(summary.discrepancyTotal, summary.currency))}</dd></div>
          <div><dt>Root issues</dt><dd>${escapeHtml(summary.issueCount)}</dd></div>
        </dl>
        <div class="household-usage"><span>Usage summaries</span><ul>${usage}</ul></div>
      </article>`;
  }).join("");
}

function summariesForRequests(result = null) {
  if (state.bundle.length) return state.bundle;
  if (!result || !state.extraction) return [];
  const summary = summarizeCurrentBill();
  return summary ? [summary] : [];
}

function renderProviderReviewRequests(result = null) {
  const entries = summariesForRequests(result).flatMap((summary) => (
    summary.reviewRequests.map((request, requestIndex) => ({
      summary,
      request,
      requestIndex,
    }))
  ));
  byId("provider-review-requests").innerHTML = entries.length
    ? entries.map(({ summary, request, requestIndex }, index) => {
      const subjectId = `letter-subject-${index}`;
      const bodyId = `letter-body-${index}`;
      const services = summary.serviceTypes
        .map((serviceType) => serviceLabels[serviceType] || serviceType)
        .join(", ");
      return `
        <article class="provider-request-card">
          <div class="request-editor">
            <span class="card-kicker">${escapeHtml(request.provider)}</span>
            <label for="${subjectId}">Subject</label><input id="${subjectId}" data-bundle-id="${escapeHtml(summary.id)}" data-request-index="${requestIndex}" data-request-field="subject" type="text" value="${escapeHtml(request.subject)}">
            <label for="${bodyId}">Message</label><textarea id="${bodyId}" data-bundle-id="${escapeHtml(summary.id)}" data-request-index="${requestIndex}" data-request-field="body" rows="12">${escapeHtml(request.body)}</textarea>
            <div class="letter-actions"><button class="button primary" type="button" data-copy-request="${index}">Copy request</button><button class="button secondary" type="button" data-download-request="${index}">Download .txt</button></div>
            <p class="review-note"><span aria-hidden="true">!</span><strong>User review required.</strong> Edits stay in this page. WattProof never sends messages or adds account details automatically.</p>
          </div>
          <aside class="request-grounding"><span class="card-kicker">Completed summary</span><h2>Draft boundary</h2><div class="grounded-claim"><strong>${escapeHtml(summary.providers.join(" + ") || request.provider)}</strong><br>${escapeHtml(services || "Utility service")} · ${escapeHtml(summary.period)} · ${escapeHtml(verificationSummary(summary.verificationLevel))}</div><p class="grounding-limit">Only the provider, subject, and message draft are retained for this request.</p></aside>
        </article>`;
    }).join("")
    : `<div class="household-placeholder"><h2>No provider request is needed</h2><p>The completed summaries contain no review request draft.</p></div>`;
}

function updateReviewRequestDraft(bundleId, requestIndex, field, value) {
  if (!["subject", "body"].includes(field)) return;
  const summary = state.bundle.find((candidate) => candidate.id === bundleId);
  const request = summary?.reviewRequests?.[Number(requestIndex)];
  if (!request) return;
  request[field] = String(value);
}

function announceBundle(message) {
  byId("bundle-status").textContent = message;
}

function safeSourceUrl(value) {
  const url = String(value || "").trim();
  return /^https?:\/\//i.test(url) ? escapeHtml(url) : "";
}

function serviceResultCards(extraction) {
  if (isUtilityDocument(extraction)) {
    return extraction.sections.map((section) => {
      const period = periodText(section.service_start, section.service_end);
      const usage = section.usage || section.meter?.usage || null;
      return `
        <article class="service-result-card">
          <header><span>${escapeHtml(serviceLabels[section.service_type] || section.service_type)}</span><strong>${escapeHtml(section.provider.value)}</strong></header>
          <dl>
            ${section.schedule ? `<div><dt>Schedule</dt><dd>${escapeHtml(section.schedule.value)}</dd></div>` : ""}
            ${period ? `<div><dt>Service period</dt><dd>${escapeHtml(period)}</dd></div>` : ""}
            ${usage ? `<div><dt>Usage</dt><dd>${escapeHtml(measurementFactText(usage))}</dd></div>` : ""}
            <div><dt>Printed subtotal</dt><dd>${escapeHtml(money(section.subtotal.value, section.subtotal.currency))}</dd></div>
          </dl>
        </article>`;
    });
  }

  const period = periodText(extraction.service_start, extraction.service_end);
  return [
    [extraction.delivery_provider, extraction.delivery_schedule, extraction.delivery_subtotal],
    [extraction.generation_provider, extraction.generation_schedule, extraction.generation_subtotal],
  ].map(([provider, schedule, subtotal]) => `
    <article class="service-result-card">
      <header><span>Electricity</span><strong>${escapeHtml(provider.value)}</strong></header>
      <dl>
        <div><dt>Schedule</dt><dd>${escapeHtml(schedule.value)}</dd></div>
        <div><dt>Service period</dt><dd>${escapeHtml(period)}</dd></div>
        <div><dt>Usage</dt><dd>${escapeHtml(measurementFactText(extraction.total_usage))}</dd></div>
        <div><dt>Printed subtotal</dt><dd>${escapeHtml(money(subtotal.value, subtotal.unit))}</dd></div>
      </dl>
    </article>`);
}

function lineEvidence(line) {
  const evidence = line.evidence?.[0];
  if (!evidence) return "No rendered-page excerpt is attached.";
  return `Page ${escapeHtml(evidence.page)}: “${escapeHtml(evidence.text)}”`;
}

function renderPriorityFindings(result) {
  const findings = result.lines.filter((line) => (
    line.status === "discrepancy" || line.status === "needs_review"
  ));
  const rootFindings = findings.filter((line) => !lineRootCauseIds(line).length);
  byId("priority-findings").innerHTML = rootFindings.length
    ? rootFindings.map((line) => `
      <article class="priority-finding ${escapeHtml(line.status)}">
        <span class="status-pill ${escapeHtml(line.status)}">${escapeHtml(auditStatusLabel(line))}</span>
        <div><h3>${escapeHtml(line.label)}</h3><p>${escapeHtml(line.limitation || line.formula)}</p><small>${lineEvidence(line)}</small></div>
        <strong>${auditValue(line.delta, line.unit, result.currency)}</strong>
      </article>`).join("")
    : `<p class="priority-empty"><strong>No high-priority findings.</strong> Review the ledger for checks that remain outside supported verification.</p>`;
}

function renderAuditLedger(result) {
  byId("audit-lines").innerHTML = result.lines.map((line) => {
    const optional = line.scope === "statement_reconciliation" && line.status === "verified";
    const links = (line.citations || []).map((citation) => {
      const sourceUrl = safeSourceUrl(citation.source_url);
      return sourceUrl
        ? `<a href="${sourceUrl}" target="_blank" rel="noreferrer">${escapeHtml(citation.label)} ↗</a>`
        : `<span>${escapeHtml(citation.label)}</span>`;
    }).join("");
    const rootIds = lineRootCauseIds(line);
    const dependencyTrace = rootIds.length
      ? `<div class="evidence-line dependency-line"><strong>Derived from roots:</strong> ${escapeHtml(rootIds.join(", "))}</div>`
      : "";
    return `
      <tr class="${optional ? "optional-line" : ""}" ${optional && state.compactAudit ? "hidden" : ""}>
        <td data-label="Status"><span class="status-pill ${escapeHtml(line.status)}">${escapeHtml(auditStatusLabel(line))}</span></td>
        <td data-label="Line" class="charge-label">${escapeHtml(line.label)}</td>
        <td data-label="Scope"><span class="scope-chip">${escapeHtml(scopeLabels[line.scope] || line.scope)}</span></td>
        <td data-label="Billed">${auditValue(line.billed_amount, line.unit, result.currency)}</td>
        <td data-label="Expected">${auditValue(line.expected_amount, line.unit, result.currency)}</td>
        <td data-label="Delta">${auditValue(line.delta, line.unit, result.currency)}</td>
        <td data-label="Trace and evidence"><div class="trace">${escapeHtml(line.formula)}</div>${dependencyTrace}<div class="evidence-line">${lineEvidence(line)}</div>${line.limitation ? `<div class="evidence-line"><strong>Limit:</strong> ${escapeHtml(line.limitation)}</div>` : ""}<div class="citation-links">${links}</div></td>
      </tr>`;
  }).join("");
  byId("show-all-lines").textContent = state.compactAudit ? "Show all checks" : "Compact view";
}

function renderComparison(comparison) {
  const container = byId("optional-comparison");
  if (!comparison) {
    container.hidden = true;
    container.innerHTML = "";
    return;
  }
  container.hidden = false;
  container.innerHTML = `
    <div class="comparison-card">
      <div class="insufficiency-mark" aria-hidden="true"><span>?</span></div>
      <div><span class="status-pill cannot_verify">More data needed</span><h2 id="comparison-title">${escapeHtml(comparison.headline)}</h2><p>${escapeHtml(comparison.explanation)}</p></div>
      <div class="needed-data"><h3>What unlocks a real comparison</h3><ul>${comparison.required_data.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul><p>WattProof does not turn missing interval or historical usage into a savings claim.</p></div>
    </div>`;
}

function renderAudit() {
  const result = state.audit;
  const verificationLabel = verificationLabels[result.verification_level] || "Evidence extracted";
  const level = byId("verification-level");
  level.className = `verification-level ${escapeHtml(result.verification_level)}`;
  level.innerHTML = `<span>Verification level</span><strong>${escapeHtml(verificationLabel)}</strong><small>${escapeHtml(result.headline)}</small>`;

  const discrepancy = result.verdict === "possible_discrepancy";
  const needsReview = result.verdict === "needs_review";
  const verdict = byId("verdict-card");
  verdict.className = `verdict-card${discrepancy ? " discrepancy" : needsReview ? " needs-review" : ""}`;
  let explanation = "Visible facts were extracted for review; unsupported checks remain explicit.";
  if (result.verification_level === "tariff_verified") {
    explanation = "At least one governing charge matched an exact, period-bound published-tariff adapter.";
  } else if (result.verification_level === "internally_reconciled") {
    explanation = "Only deterministic relationships supported by printed or explicitly labeled inferred operands were checked. Unsupported lines remain explicitly unverified; this does not claim tariff truth.";
  }
  verdict.innerHTML = `
    <div class="verdict-icon" aria-hidden="true">${discrepancy || needsReview ? "!" : "✓"}</div>
    <div class="verdict-copy"><span>${escapeHtml(discrepancy ? "Review recommended" : needsReview ? "Evidence needs review" : "Result ready")}</span><h2>${escapeHtml(result.headline)}</h2><p>${escapeHtml(explanation)}</p></div>`;

  const cards = serviceResultCards(state.extraction);
  byId("service-results").innerHTML = cards.join("");
  renderPriorityFindings(result);
  renderAuditLedger(result);
  renderComparison(result.comparison);
  renderProviderReviewRequests(result);
}

function releasePreview() {
  const previewUrl = state.previewUrl;
  state.previewUrl = null;
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  const preview = byId("pdf-preview");
  preview.removeAttribute("src");
  preview.hidden = true;
}

function hasCurrentDocument() {
  return state.extraction !== null
    || state.audit !== null
    || state.previewUrl !== null
    || state.reviewMode !== null;
}

function clearCurrentDocument({ resetUpload = true } = {}) {
  invalidatePendingOperation();
  releasePreview();
  state.extraction = null;
  state.audit = null;
  state.compactAudit = true;
  state.reviewMode = null;
  state.extractionRevision += 1;
  state.auditRevision = 0;
  state.currentBundleAuditRevision = null;
  if (resetUpload) {
    byId("upload-form").reset();
    byId("file-label").textContent = "Choose a utility bill";
  }
  byId("synthetic-preview").hidden = true;
  for (const id of (
    [
      "service-review-sections",
      "review-warnings",
      "verification-level",
      "verdict-card",
      "service-results",
      "priority-findings",
      "audit-lines",
      "optional-comparison",
      "provider-review-requests",
    ]
  )) byId(id).innerHTML = "";
  byId("review-warnings").hidden = true;
  byId("optional-comparison").hidden = true;
  byId("calculation-ledger").open = false;
}

function resetCurrentBundleIdentity() {
  state.currentBundleId = null;
  state.currentBundleAuditRevision = null;
}

function resetReplacementIdentity() {
  state.replacementBundleId = null;
  state.replacementArmed = false;
}

function prepareForNewDocument(options) {
  clearCurrentDocument(options);
  resetCurrentBundleIdentity();
  if (!state.replacementArmed) resetReplacementIdentity();
}

function discardCurrentDocument() {
  prepareForNewDocument();
  showStep(1);
  const retained = state.bundle.length;
  if (retained) {
    announceBundle(`${retained} completed ${retained === 1 ? "bill" : "bills"} retained in this page.`);
  }
}

function addAnotherBill() {
  const summary = appendCurrentBillOnce();
  if (!summary) return;
  renderHousehold();
  renderProviderReviewRequests();
  const count = state.bundle.length;
  clearCurrentDocument();
  resetCurrentBundleIdentity();
  resetReplacementIdentity();
  showStep(1);
  announceBundle(`${count} completed ${count === 1 ? "bill" : "bills"} retained in this page.`);
}

function finishHouseholdReview() {
  const summary = appendCurrentBillOnce();
  if (!summary && !state.bundle.length) return;
  const completedId = summary?.id || state.replacementBundleId;
  renderHousehold();
  const count = state.bundle.length;
  if (hasCurrentDocument()) clearCurrentDocument();
  resetCurrentBundleIdentity();
  state.replacementBundleId = state.bundle.some((item) => item.id === completedId)
    ? completedId
    : null;
  state.replacementArmed = false;
  showStep(4);
  announceBundle(`Household now contains ${count} completed ${count === 1 ? "bill" : "bills"}.`);
}

function beginHouseholdReplacement() {
  if (!state.replacementBundleId
      || !state.bundle.some((summary) => summary.id === state.replacementBundleId)) {
    showMessage("Choose a completed bill to replace.");
    return;
  }
  state.replacementArmed = true;
  if (hasCurrentDocument()) clearCurrentDocument();
  resetCurrentBundleIdentity();
  showStep(1);
  announceBundle("Replace / re-upload is armed for the last completed bill. Review and verify the replacement before finishing.");
}

function showProviderReviewRequests() {
  renderProviderReviewRequests();
  showStep(5);
}

function clearHousehold() {
  state.bundle = [];
  resetCurrentBundleIdentity();
  resetReplacementIdentity();
  clearCurrentDocument();
  byId("household-bills").innerHTML = "";
  byId("household-summary").innerHTML = "";
  byId("provider-review-requests").innerHTML = "";
  showStep(1);
  announceBundle("Household cleared. No completed bill summaries remain in this page.");
}

function requestText(index) {
  return `Subject: ${byId(`letter-subject-${index}`).value}\n\n${byId(`letter-body-${index}`).value}`;
}

byId("authentic-sample").addEventListener("click", (event) => loadSample("authentic", event.currentTarget));
byId("synthetic-sample").addEventListener("click", (event) => loadSample("synthetic", event.currentTarget));
byId("duke-sample").addEventListener("click", (event) => loadSample("duke", event.currentTarget));
byId("centerpoint-sample").addEventListener("click", (event) => loadSample("centerpoint", event.currentTarget));
byId("bloomington-sample").addEventListener("click", (event) => loadSample("bloomington", event.currentTarget));

byId("bill-file").addEventListener("change", (event) => {
  const returnToUpload = document.querySelector('[data-step="1"]')?.hidden;
  prepareForNewDocument({ resetUpload: false });
  if (returnToUpload) showStep(1);
  else showMessage();
  byId("file-label").textContent = event.target.files[0]?.name || "Choose a utility bill";
});

byId("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button[type='submit']");
  const file = byId("bill-file").files[0];
  if (!file) {
    invalidatePendingOperation();
    showMessage("Choose a PDF bill first.", byId("bill-file"));
    return;
  }
  const operation = beginOperation(() => setLoading(button, false, ""));
  releasePreview();
  state.previewUrl = URL.createObjectURL(file);
  setLoading(button, true, "Reading rendered pages…");
  try {
    const form = new FormData();
    form.append("bill", file);
    const payload = await responseJson(await fetch("/api/extract", {
      method: "POST",
      body: form,
      signal: operation.controller.signal,
    }));
    if (!isCurrentOperation(operation)) return;
    replaceExtraction(payload.extraction, "uploaded");
    renderReview("uploaded");
    showStep(2);
  } catch (error) {
    if (!isCurrentOperation(operation) || isAbortError(error)) return;
    const message = safeErrorMessage(error);
    finishOperation(operation);
    prepareForNewDocument();
    showStep(1);
    showMessage(message, byId("bill-file"));
  } finally {
    finishOperation(operation);
  }
});

byId("review-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button[type='submit']");
  if (applyReviewEdits()) {
    state.extractionRevision += 1;
    renderReview(state.reviewMode);
  }
  const extractionAtStart = state.extraction;
  const revisionAtStart = state.extractionRevision;
  const operation = beginOperation(() => {
    setReviewPending(false);
    setLoading(button, false, "");
  });
  setLoading(button, true, "Running deterministic checks…");
  setReviewPending(true);
  try {
    const response = await fetch("/api/audit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.extraction),
      signal: operation.controller.signal,
    });
    const payload = await responseJson(response);
    if (!isCurrentOperation(operation)
        || state.extraction !== extractionAtStart
        || state.extractionRevision !== revisionAtStart) return;
    state.audit = payload.audit;
    state.auditRevision += 1;
    state.compactAudit = true;
    renderAudit();
    showStep(3);
  } catch (error) {
    if (!isCurrentOperation(operation) || isAbortError(error)) return;
    finishOperation(operation);
    showError(error);
  } finally {
    finishOperation(operation);
  }
});

document.querySelectorAll("[data-back]").forEach((button) => {
  button.addEventListener("click", () => {
    invalidatePendingOperation();
    showStep(Number(button.dataset.back));
  });
});

byId("discard-current-document").addEventListener("click", discardCurrentDocument);

document.querySelectorAll("[data-next]").forEach((button) => {
  button.addEventListener("click", () => showStep(Number(button.dataset.next)));
});

byId("show-all-lines").addEventListener("click", () => {
  state.compactAudit = !state.compactAudit;
  document.querySelectorAll(".optional-line").forEach((row) => {
    row.hidden = state.compactAudit;
  });
  byId("show-all-lines").textContent = state.compactAudit ? "Show all checks" : "Compact view";
});

byId("provider-review-requests").addEventListener("click", async (event) => {
  const copyButton = event.target.closest("[data-copy-request]");
  const downloadButton = event.target.closest("[data-download-request]");
  if (copyButton) {
    const index = copyButton.dataset.copyRequest;
    try {
      await navigator.clipboard.writeText(requestText(index));
    } catch {
      byId(`letter-body-${index}`).select();
      document.execCommand("copy");
    }
    copyButton.textContent = "Copied";
  }
  if (downloadButton) {
    const index = downloadButton.dataset.downloadRequest;
    const url = URL.createObjectURL(new Blob([requestText(index)], { type: "text/plain" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `wattproof-review-request-${Number(index) + 1}.txt`;
    link.click();
    URL.revokeObjectURL(url);
  }
});

byId("provider-review-requests").addEventListener("input", (event) => {
  const input = event.target.closest("[data-request-field]");
  if (!input) return;
  updateReviewRequestDraft(
    input.dataset.bundleId,
    input.dataset.requestIndex,
    input.dataset.requestField,
    input.value,
  );
});

byId("add-another-bill").addEventListener("click", addAnotherBill);
byId("finish-household").addEventListener("click", finishHouseholdReview);
byId("replace-household-bill").addEventListener("click", beginHouseholdReplacement);
byId("clear-household").addEventListener("click", clearHousehold);
byId("review-next-steps").addEventListener("click", showProviderReviewRequests);
byId("restart").addEventListener("click", () => {
  clearHousehold();
  window.location.reload();
});
