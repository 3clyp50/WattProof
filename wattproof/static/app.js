"use strict";

const state = {
  extraction: null,
  audit: null,
  previewUrl: null,
  compactAudit: true,
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

function showMessage(message = "") {
  const element = byId("global-message");
  element.textContent = message;
  element.hidden = !message;
  if (message) element.scrollIntoView({ block: "center" });
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
  if (step > 1) {
    document.querySelector(`[data-step="${step}"] h1`)?.focus({ preventScroll: true });
  }
}

function setLoading(button, loading, label) {
  if (!button.dataset.originalLabel) button.dataset.originalLabel = button.innerHTML;
  button.disabled = loading;
  button.innerHTML = loading ? label : button.dataset.originalLabel;
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

function evidenceMarkup(fact) {
  const evidence = evidenceFor(fact);
  const confidence = Number(evidence.confidence);
  const percentage = Number.isFinite(confidence)
    ? `${Math.round(confidence * 100)}% confidence`
    : "confidence unavailable";
  return `<details class="fact-evidence"><summary>Page ${escapeHtml(evidence.page)} · ${percentage}</summary><blockquote>${escapeHtml(evidence.text)}</blockquote></details>`;
}

function factEditor(fact, label, path, type = "text") {
  if (!fact) return "";
  const id = `fact-${path.replaceAll(/[^a-zA-Z0-9_-]/g, "-")}`;
  const unit = fact.unit || fact.currency || "";
  const corrected = fact.status === "user_corrected"
    ? `<small class="correction-note">Originally ${escapeHtml(fact.original_value)}</small>`
    : "";
  return `
    <div class="fact-field">
      <label for="${escapeHtml(id)}">
        <span>${escapeHtml(label)}</span>
        <span class="evidence-type ${escapeHtml(fact.status)}">${escapeHtml(statusLabel(fact.status))}</span>
      </label>
      <div class="typed-input">
        <input id="${escapeHtml(id)}" data-fact-path="${escapeHtml(path)}" type="${escapeHtml(type)}" step="any" value="${escapeHtml(fact.value)}">
        ${unit ? `<span>${escapeHtml(unit)}</span>` : ""}
      </div>
      ${corrected}
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
        <div class="service-chips"><span>${escapeHtml(extraction.total_usage.value)} ${escapeHtml(extraction.total_usage.unit)}</span><span>${escapeHtml(periodText(extraction.service_start, extraction.service_end))}</span></div>
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
    fields.push(factEditor(namedFact.fact, namedFact.id.replaceAll("_", " "), `${base}.supplemental_facts.${factIndex}.fact`));
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
    const usage = section.usage
      ? `${section.usage.value} ${section.usage.unit}`
      : section.meter?.usage
        ? `${section.meter.usage.value} ${section.meter.usage.unit}`
        : "";
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
  if (isUtilityDocument(state.extraction)) renderUtilityReview();
  else renderLegacyReview();
  renderDocumentPreview(mode);
}

async function loadSample(kind, button) {
  setLoading(button, true, "Loading public fixture…");
  try {
    const payload = await responseJson(await fetch(`/api/sample/${kind}`));
    state.extraction = payload.extraction;
    state.audit = null;
    renderReview(kind);
    showStep(2);
  } catch (error) {
    showMessage(safeErrorMessage(error));
  } finally {
    setLoading(button, false, "");
  }
}

function applyReviewEdits() {
  document.querySelectorAll("[data-fact-path]").forEach((input) => {
    const fact = valueAt(state.extraction, input.dataset.factPath);
    if (fact && String(fact.value) !== input.value) markCorrected(fact, input.value);
  });
}

function money(value, currency = "USD") {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  const sign = number < 0 ? "−" : "";
  const prefix = currency === "USD" ? "$" : `${currency} `;
  return `${sign}${prefix}${Math.abs(number).toFixed(2)}`;
}

function decimalValue(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return number.toLocaleString(undefined, { maximumFractionDigits: 6 });
}

function auditValue(value, unit, currency) {
  if (value === null || value === undefined) return "—";
  if (unit === currency || /^[A-Z]{3}$/.test(unit)) return money(value, unit);
  return `${decimalValue(value)} ${unit}`;
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
            ${usage ? `<div><dt>Usage</dt><dd>${escapeHtml(usage.value)} ${escapeHtml(usage.unit)}</dd></div>` : ""}
            <div><dt>Printed subtotal</dt><dd>${money(section.subtotal.value, section.subtotal.currency)}</dd></div>
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
        <div><dt>Usage</dt><dd>${escapeHtml(extraction.total_usage.value)} ${escapeHtml(extraction.total_usage.unit)}</dd></div>
        <div><dt>Printed subtotal</dt><dd>${money(subtotal.value, subtotal.unit)}</dd></div>
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
  byId("priority-findings").innerHTML = findings.length
    ? findings.map((line) => `
      <article class="priority-finding ${escapeHtml(line.status)}">
        <span class="status-pill ${escapeHtml(line.status)}">${escapeHtml(statusLabels[line.status])}</span>
        <div><h3>${escapeHtml(line.label)}</h3><p>${escapeHtml(line.limitation || line.formula)}</p><small>${lineEvidence(line)}</small></div>
        <strong>${auditValue(line.delta, line.unit, result.currency)}</strong>
      </article>`).join("")
    : `<p class="priority-empty"><strong>No high-priority findings.</strong> Review the ledger for checks that remain outside supported verification.</p>`;
}

function renderAuditLedger(result) {
  byId("audit-lines").innerHTML = result.lines.map((line) => {
    const optional = line.scope === "statement_reconciliation" && line.status === "verified";
    const links = (line.citations || []).map((citation) => `<a href="${escapeHtml(citation.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(citation.label)} ↗</a>`).join("");
    return `
      <tr class="${optional ? "optional-line" : ""}" ${optional && state.compactAudit ? "hidden" : ""}>
        <td data-label="Status"><span class="status-pill ${escapeHtml(line.status)}">${escapeHtml(statusLabels[line.status] || statusLabel(line.status))}</span></td>
        <td data-label="Line" class="charge-label">${escapeHtml(line.label)}</td>
        <td data-label="Scope"><span class="scope-chip">${escapeHtml(scopeLabels[line.scope] || line.scope)}</span></td>
        <td data-label="Billed">${auditValue(line.billed_amount, line.unit, result.currency)}</td>
        <td data-label="Expected">${auditValue(line.expected_amount, line.unit, result.currency)}</td>
        <td data-label="Delta">${auditValue(line.delta, line.unit, result.currency)}</td>
        <td data-label="Trace and evidence"><div class="trace">${escapeHtml(line.formula)}</div><div class="evidence-line">${lineEvidence(line)}</div>${line.limitation ? `<div class="evidence-line"><strong>Limit:</strong> ${escapeHtml(line.limitation)}</div>` : ""}<div class="citation-links">${links}</div></td>
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

function renderProviderReviewRequests(result) {
  const requests = Array.isArray(result.review_requests) ? result.review_requests : [];
  const lines = new Map(result.lines.map((line) => [line.id, line]));
  byId("provider-review-requests").innerHTML = requests.length
    ? requests.map((request, index) => {
      const grounded = request.grounded_audit_line_ids
        .map((id) => lines.get(id))
        .filter(Boolean);
      const grounding = grounded.length
        ? grounded.map((line) => `<div class="grounded-claim"><strong>${escapeHtml(line.label)}</strong><br>${escapeHtml(line.formula)}</div>`).join("")
        : `<p class="grounding-limit">This request asks for missing source coverage and does not claim a provider error.</p>`;
      return `
        <article class="provider-request-card">
          <div class="request-editor">
            <span class="card-kicker">${escapeHtml(request.provider)}</span>
            <label for="letter-subject-${index}">Subject</label><input id="letter-subject-${index}" type="text" value="${escapeHtml(request.subject)}">
            <label for="letter-body-${index}">Message</label><textarea id="letter-body-${index}" rows="12">${escapeHtml(request.body)}</textarea>
            <div class="letter-actions"><button class="button primary" type="button" data-copy-request="${index}">Copy request</button><button class="button secondary" type="button" data-download-request="${index}">Download .txt</button></div>
            <p class="review-note"><span aria-hidden="true">!</span><strong>User review required.</strong> WattProof never sends messages or adds account details automatically.</p>
          </div>
          <aside class="request-grounding"><span class="card-kicker">Claim ledger</span><h2>Why this wording is bounded</h2>${grounding}</aside>
        </article>`;
    }).join("")
    : `<div class="household-placeholder"><h2>No provider request is needed</h2><p>The current evidence produced no grounded request draft.</p></div>`;
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
    explanation = "Printed meter, unit, rate, tax, subtotal, and total math was checked without claiming tariff truth.";
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

function clearCurrentDocument() {
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.extraction = null;
  state.audit = null;
  state.previewUrl = null;
  state.compactAudit = true;
  byId("upload-form").reset();
  byId("file-label").textContent = "Choose a utility bill";
  showStep(1);
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
  byId("file-label").textContent = event.target.files[0]?.name || "Choose a utility bill";
});

byId("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button[type='submit']");
  const file = byId("bill-file").files[0];
  if (!file) return showMessage("Choose a PDF bill first.");
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.previewUrl = URL.createObjectURL(file);
  setLoading(button, true, "Reading rendered pages…");
  try {
    const form = new FormData();
    form.append("bill", file);
    const payload = await responseJson(await fetch("/api/extract", { method: "POST", body: form }));
    state.extraction = payload.extraction;
    state.audit = null;
    renderReview("uploaded");
    showStep(2);
  } catch (error) {
    showMessage(safeErrorMessage(error));
  } finally {
    setLoading(button, false, "");
  }
});

byId("review-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button[type='submit']");
  applyReviewEdits();
  setLoading(button, true, "Running deterministic checks…");
  try {
    const response = await fetch("/api/audit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.extraction),
    });
    const payload = await responseJson(response);
    state.audit = payload.audit;
    state.compactAudit = true;
    renderAudit();
    showStep(3);
  } catch (error) {
    showMessage(safeErrorMessage(error));
  } finally {
    setLoading(button, false, "");
  }
});

document.querySelectorAll("[data-back]").forEach((button) => {
  button.addEventListener("click", () => showStep(Number(button.dataset.back)));
});

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

byId("add-another-bill").addEventListener("click", clearCurrentDocument);
byId("finish-household-review").addEventListener("click", () => showStep(4));
byId("restart").addEventListener("click", () => window.location.reload());
