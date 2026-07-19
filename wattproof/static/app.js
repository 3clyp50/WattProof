"use strict";

const state = {
  extraction: null,
  audit: null,
  previewUrl: null,
  compactAudit: true,
};

const factDefinitions = [
  ["delivery_provider.value", "Delivery provider", "text"],
  ["generation_provider.value", "Generation provider", "text"],
  ["delivery_schedule.value", "PG&E schedule", "text"],
  ["statement_date.value", "Statement date", "date"],
  ["service_start.value", "Service start", "date"],
  ["service_end.value", "Service end", "date"],
  ["billing_days.value", "Billing days", "number"],
  ["total_usage.value", "Total usage (kWh)", "number"],
  ["peak_usage.value", "Peak usage (kWh)", "number"],
  ["off_peak_usage.value", "Off-peak usage (kWh)", "number"],
  ["baseline_allowance.value", "Baseline allowance (kWh)", "number"],
  ["amount_due.value", "Amount due (USD)", "number"],
];

const byId = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function valueAt(object, path) {
  return path.split(".").reduce((current, key) => current[key], object);
}

function factAt(object, path) {
  const keys = path.split(".");
  return keys.slice(0, -1).reduce((current, key) => current[key], object);
}

function setValueAt(object, path, value) {
  const keys = path.split(".");
  const target = keys.slice(0, -1).reduce((current, key) => current[key], object);
  target[keys.at(-1)] = value;
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
  if (step > 1) document.querySelector(`[data-step="${step}"] h1`)?.focus();
}

function setLoading(button, loading, label) {
  if (!button.dataset.originalLabel) button.dataset.originalLabel = button.innerHTML;
  button.disabled = loading;
  button.innerHTML = loading ? label : button.dataset.originalLabel;
}

async function responseJson(response) {
  const payload = await response.json().catch(() => ({ error: "Unexpected server response." }));
  if (!response.ok) throw new Error(payload.error || "The request could not be completed.");
  return payload;
}

function renderReview(mode) {
  const extraction = state.extraction;
  const fields = factDefinitions.map(([path, label, type]) => {
    const fact = factAt(extraction, path);
    const inferred = fact.status === "inferred";
    return `
      <div class="fact-field">
        <label for="fact-${escapeHtml(path)}">
          <span>${escapeHtml(label)}</span>
          <span class="evidence-type ${inferred ? "inferred" : ""}">${escapeHtml(fact.status)}</span>
        </label>
        <input id="fact-${escapeHtml(path)}" data-fact-path="${escapeHtml(path)}" type="${type}" step="any" value="${escapeHtml(valueAt(extraction, path))}">
        <details><summary>Page ${fact.source_page} evidence · ${Math.round(fact.confidence * 100)}%</summary><blockquote>${escapeHtml(fact.source_text)}</blockquote></details>
      </div>`;
  });
  byId("fact-fields").innerHTML = fields.join("");
  byId("fact-count").textContent = `${fields.length} material facts`;

  byId("charge-fields").innerHTML = extraction.charges.map((line, index) => {
    const input = (fact, field, unit) => fact
      ? `<input aria-label="${escapeHtml(line.label)} ${field}" data-charge-index="${index}" data-charge-field="${field}" type="number" step="any" value="${escapeHtml(fact.value)}"><small>${unit}</small>`
      : "—";
    const evidence = line.billed_amount;
    return `
      <tr>
        <td class="charge-label">${escapeHtml(line.label)}</td>
        <td>${input(line.quantity, "quantity", " kWh")}</td>
        <td>${input(line.rate, "rate", "")}</td>
        <td>${input(line.billed_amount, "billed_amount", " USD")}</td>
        <td><details><summary>Page ${evidence.source_page}</summary><blockquote>${escapeHtml(evidence.source_text)}</blockquote></details></td>
      </tr>`;
  }).join("");

  const frame = byId("pdf-preview");
  const synthetic = byId("synthetic-preview");
  byId("document-mode").textContent = mode === "uploaded" ? "Uploaded · not retained" : mode === "synthetic" ? "Labeled synthetic data" : "Public anonymized sample";
  if (mode === "synthetic") {
    frame.hidden = true;
    frame.removeAttribute("src");
    synthetic.hidden = false;
  } else {
    synthetic.hidden = true;
    frame.hidden = false;
    frame.src = mode === "uploaded" ? state.previewUrl : "/sample.pdf#page=1&view=FitH";
  }
}

async function loadSample(kind, button) {
  setLoading(button, true, "Loading verified fixture…");
  try {
    const payload = await responseJson(await fetch(`/api/sample/${kind}`));
    state.extraction = payload.extraction;
    state.audit = null;
    renderReview(kind);
    showStep(2);
  } catch (error) {
    showMessage(error.message);
  } finally {
    setLoading(button, false, "");
  }
}

function applyReviewEdits() {
  document.querySelectorAll("[data-fact-path]").forEach((input) => {
    const path = input.dataset.factPath;
    const value = path === "billing_days.value" ? Number(input.value) : input.value;
    setValueAt(state.extraction, path, value);
  });
  document.querySelectorAll("[data-charge-index]").forEach((input) => {
    const line = state.extraction.charges[Number(input.dataset.chargeIndex)];
    line[input.dataset.chargeField].value = input.value;
  });
}

function money(value) {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  return `${number < 0 ? "−" : ""}$${Math.abs(number).toFixed(2)}`;
}

function auditValue(value, unit) {
  if (value === null || value === undefined) return "—";
  return unit === "USD" ? money(value) : `${Number(value).toFixed(3)} kWh`;
}

function renderAudit() {
  const result = state.audit;
  const discrepancy = result.verdict === "possible_discrepancy";
  const verdict = byId("verdict-card");
  verdict.className = `verdict-card${discrepancy ? " discrepancy" : ""}`;
  verdict.innerHTML = `
    <div class="verdict-icon" aria-hidden="true">${discrepancy ? "!" : "✓"}</div>
    <div class="verdict-copy"><span>${discrepancy ? "Review recommended" : "Supported math agrees"}</span><h2>${escapeHtml(result.headline)}</h2><p>${discrepancy ? "A tariff line and the printed subtotal both expose the alteration." : "Unsupported riders remain unverified rather than being forced to match."}</p></div>`;

  const verified = result.lines.filter((line) => line.status === "verified").length;
  const unavailable = result.lines.filter((line) => line.status === "cannot_verify").length;
  byId("audit-metrics").innerHTML = `
    <div class="metric"><span>Current charges</span><strong>${money(state.extraction.current_charges.value)}</strong></div>
    <div class="metric"><span>Verified checks</span><strong>${verified}</strong></div>
    <div class="metric"><span>Cannot verify</span><strong>${unavailable}</strong></div>
    <div class="metric"><span>Counted discrepancy</span><strong>${money(result.discrepancy_total)}</strong></div>`;

  byId("audit-lines").innerHTML = result.lines.map((line) => {
    const optional = line.category === "reconciliation" && line.status === "verified";
    const links = line.citations.map((citation) => `<a href="${escapeHtml(citation.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(citation.label)} ↗</a>`).join("");
    return `
      <tr class="${optional ? "optional-line" : ""}" ${optional && state.compactAudit ? "hidden" : ""}>
        <td><span class="status-pill ${line.status}">${escapeHtml(line.status.replaceAll("_", " "))}</span></td>
        <td class="charge-label">${escapeHtml(line.label)}</td>
        <td>${auditValue(line.billed_amount, line.unit)}</td>
        <td>${auditValue(line.expected_amount, line.unit)}</td>
        <td>${auditValue(line.delta, line.unit)}</td>
        <td><div class="trace">${escapeHtml(line.formula)}</div><div class="evidence-line">Page ${line.source_page}: “${escapeHtml(line.source_text)}”</div>${line.limitation ? `<div class="evidence-line"><strong>Limit:</strong> ${escapeHtml(line.limitation)}</div>` : ""}<div class="citation-links">${links}</div></td>
      </tr>`;
  }).join("");
  byId("show-all-lines").textContent = state.compactAudit ? "Show all checks" : "Compact view";

  byId("comparison-headline").textContent = result.comparison.headline;
  byId("comparison-explanation").textContent = result.comparison.explanation;
  byId("comparison-data").innerHTML = result.comparison.required_data
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");

  byId("letter-subject").value = result.review_request.subject;
  byId("letter-body").value = result.review_request.body;
  const lines = new Map(result.lines.map((line) => [line.id, line]));
  byId("grounded-lines").innerHTML = result.review_request.grounded_audit_line_ids
    .map((id) => `<div class="grounded-claim"><strong>${escapeHtml(lines.get(id).label)}</strong><br>${escapeHtml(lines.get(id).formula)}</div>`)
    .join("");
}

byId("authentic-sample").addEventListener("click", (event) => loadSample("authentic", event.currentTarget));
byId("synthetic-sample").addEventListener("click", (event) => loadSample("synthetic", event.currentTarget));

byId("bill-file").addEventListener("change", (event) => {
  byId("file-label").textContent = event.target.files[0]?.name || "Choose a PG&E bill";
});

byId("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button[type='submit']");
  const file = byId("bill-file").files[0];
  if (!file) return showMessage("Choose a PDF bill first.");
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.previewUrl = URL.createObjectURL(file);
  setLoading(button, true, "Extracting native PDF…");
  try {
    const form = new FormData();
    form.append("bill", file);
    const payload = await responseJson(await fetch("/api/extract", { method: "POST", body: form }));
    state.extraction = payload.extraction;
    state.audit = null;
    renderReview("uploaded");
    showStep(2);
  } catch (error) {
    showMessage(error.message);
  } finally {
    setLoading(button, false, "");
  }
});

byId("review-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button[type='submit']");
  applyReviewEdits();
  setLoading(button, true, "Running exact tariff math…");
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
    showMessage(error.message);
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

byId("copy-letter").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const text = `Subject: ${byId("letter-subject").value}\n\n${byId("letter-body").value}`;
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = "Copied";
  } catch {
    byId("letter-body").select();
    document.execCommand("copy");
    button.textContent = "Copied";
  }
});

byId("download-letter").addEventListener("click", () => {
  const text = `Subject: ${byId("letter-subject").value}\n\n${byId("letter-body").value}`;
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "wattproof-review-request.txt";
  link.click();
  URL.revokeObjectURL(url);
});

byId("restart").addEventListener("click", () => window.location.reload());
