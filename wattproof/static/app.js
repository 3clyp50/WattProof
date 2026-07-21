"use strict";

const state = {
  extraction: null,
  audit: null,
  previewUrl: null,
  codex: {
    state: "disconnected",
    planType: null,
  },
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

let messageAnchor = null;

function positionMessage() {
  const element = byId("global-message");
  if (element.hidden || !messageAnchor) return;
  const anchorRect = messageAnchor.getBoundingClientRect();
  const messageRect = element.getBoundingClientRect();
  const margin = 12;
  const gap = 12;
  const above = anchorRect.top >= messageRect.height + gap + margin;
  const top = above ? anchorRect.top - messageRect.height - gap : anchorRect.bottom + gap;
  const idealLeft = anchorRect.left + (anchorRect.width - messageRect.width) / 2;
  const left = Math.max(margin, Math.min(idealLeft, window.innerWidth - messageRect.width - margin));
  const caret = Math.max(20, Math.min(anchorRect.left + anchorRect.width / 2 - left, messageRect.width - 20));
  element.dataset.side = above ? "above" : "below";
  element.style.top = `${Math.round(top)}px`;
  element.style.left = `${Math.round(left)}px`;
  element.style.setProperty("--caret-left", `${Math.round(caret)}px`);
}

function showMessage(message = "", anchor = null) {
  const element = byId("global-message");
  messageAnchor?.removeAttribute("aria-describedby");
  messageAnchor = message ? anchor : null;
  byId("global-message-text").textContent = message;
  element.hidden = !message;
  if (!message) return;
  messageAnchor?.setAttribute("aria-describedby", "global-message-text");
  positionMessage();
}

window.addEventListener("resize", positionMessage);
window.addEventListener("scroll", positionMessage, true);

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
  document.querySelector(`[data-step="${step}"] h1`)?.focus();
}

function setLoading(button, loading, label) {
  if (!button.dataset.originalLabel) button.dataset.originalLabel = button.innerHTML;
  button.disabled = loading;
  button.toggleAttribute("aria-busy", loading);
  button.innerHTML = loading ? label : button.dataset.originalLabel;
  if (!loading && messageAnchor === button) button.focus({ preventScroll: true });
}

async function responseJson(response) {
  const payload = await response.json().catch(() => ({ error: "Unexpected server response." }));
  if (!response.ok) {
    const error = new Error(payload.error || "The request could not be completed.");
    error.code = payload.code;
    throw error;
  }
  return payload;
}

let codexPollTimer = null;
let codexPollDeadline = 0;

function codexProgress(message, mode = "") {
  const progress = byId("codex-login-progress");
  progress.className = `codex-login-progress${mode ? ` ${mode}` : ""}`;
  progress.querySelector("span:last-child").textContent = message;
}

function renderCodexStatus(payload) {
  state.codex.state = payload.state;
  state.codex.planType = payload.plan_type || null;
  const connected = payload.state === "connected";
  byId("codex-connect").hidden = connected;
  byId("codex-connected").hidden = !connected;
  byId("codex-plan").textContent = connected
    ? `${payload.plan_type ? `${payload.plan_type[0].toUpperCase()}${payload.plan_type.slice(1)} · ` : ""}${payload.model}`
    : payload.model;
  byId("codex-note").classList.toggle("connected", connected);
  byId("codex-note-text").textContent = connected
    ? `${payload.model} is ready for this PDF.`
    : "Personal PDFs use your Codex access.";
  byId("codex-note").querySelector("button").hidden = connected;

  if (connected) {
    codexProgress("Connected. GPT-5.6 Luna is ready.", "connected");
    window.clearInterval(codexPollTimer);
    codexPollTimer = null;
    window.setTimeout(() => {
      if (byId("codex-dialog").open) byId("codex-dialog").close();
    }, 750);
  } else if (payload.state === "failed") {
    codexProgress("OpenAI could not complete that sign-in. Please try again.", "failed");
    window.clearInterval(codexPollTimer);
    codexPollTimer = null;
  }
}

async function refreshCodexStatus() {
  try {
    const payload = await responseJson(await fetch("/api/codex/status", { cache: "no-store" }));
    renderCodexStatus(payload);
    if (codexPollTimer && Date.now() >= codexPollDeadline) {
      window.clearInterval(codexPollTimer);
      codexPollTimer = null;
      codexProgress("The sign-in code expired. Close this window and try again.", "failed");
    }
  } catch {
    if (codexPollTimer) codexProgress("Connection check interrupted. Retrying…");
  }
}

function pollCodexStatus() {
  window.clearInterval(codexPollTimer);
  codexPollDeadline = Date.now() + 10 * 60 * 1000;
  codexPollTimer = window.setInterval(refreshCodexStatus, 1500);
}

async function startCodexLogin(button) {
  showMessage();
  setLoading(button, true, "Opening secure sign-in…");
  try {
    const payload = await responseJson(await fetch("/api/codex/login", {
      method: "POST",
      headers: { "X-WattProof-Request": "1" },
    }));
    byId("codex-user-code").textContent = payload.user_code;
    byId("codex-open-login").href = payload.verification_url;
    codexProgress("Waiting for OpenAI confirmation…");
    const dialog = byId("codex-dialog");
    if (!dialog.open) dialog.showModal();
    pollCodexStatus();
  } catch (error) {
    showMessage(error.message, button);
  } finally {
    setLoading(button, false, "");
  }
}

document.querySelectorAll("[data-codex-connect]").forEach((button) => {
  button.addEventListener("click", () => startCodexLogin(button));
});

byId("codex-disconnect").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const payload = await responseJson(await fetch("/api/codex/logout", {
      method: "POST",
      headers: { "X-WattProof-Request": "1" },
    }));
    renderCodexStatus({ ...payload, model: "GPT-5.6 Luna", plan_type: null });
  } catch (error) {
    showMessage(error.message, button);
  } finally {
    button.disabled = false;
  }
});

byId("copy-codex-code").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const code = byId("codex-user-code").textContent;
  let copied = false;
  try {
    await navigator.clipboard.writeText(code);
    copied = true;
  } catch {
    const selection = window.getSelection();
    if (selection) {
      const range = document.createRange();
      range.selectNodeContents(byId("codex-user-code"));
      selection.removeAllRanges();
      selection.addRange(range);
      copied = document.execCommand("copy");
      selection.removeAllRanges();
    }
  }
  button.textContent = copied ? "Copied" : "Copy manually";
  window.setTimeout(() => { button.textContent = "Copy code"; }, 1800);
});

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
  byId("charge-count").textContent = `${extraction.charges.length} lines`;
  byId("charge-review").open = false;

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
  showMessage();
  setLoading(button, true, "Loading verified fixture…");
  try {
    const payload = await responseJson(await fetch(`/api/sample/${kind}`));
    state.extraction = payload.extraction;
    state.audit = null;
    renderReview(kind);
    showStep(2);
  } catch (error) {
    showMessage(error.message, button);
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
  const needsReview = result.verdict === "needs_review";
  const synthetic = result.fixture_kind === "synthetic";
  const verified = result.lines.filter((line) => line.status === "verified").length;
  const unavailable = result.lines.filter((line) => ["cannot_verify", "estimated", "needs_review"].includes(line.status)).length;
  const flagged = result.lines.filter((line) => ["discrepancy", "needs_review"].includes(line.status)).length;
  const verdict = byId("verdict-card");
  const verdictTitle = discrepancy
    ? `We found a ${money(result.discrepancy_total)} difference.`
    : needsReview ? "The printed totals need review." : "The supported charges add up.";
  const verdictLabel = discrepancy
    ? "Review recommended"
    : needsReview ? "Check the printed totals" : "Supported checks agree";
  const verdictDetail = discrepancy
    ? synthetic
      ? "The altered peak charge and its subtotal both expose the labeled test change."
      : "Supported rate math differs from a printed amount. Review the evidence before contacting your provider."
    : needsReview
      ? "A subtotal or balance does not reconcile, but WattProof has no source-supported dollar difference to claim."
      : `${verified} checks match. ${unavailable} items need more evidence, so WattProof does not claim them.`;
  verdict.className = `verdict-card${discrepancy ? " discrepancy" : needsReview ? " review" : ""}`;
  verdict.innerHTML = `
    <div class="verdict-icon" aria-hidden="true">${discrepancy || needsReview ? "!" : "✓"}</div>
    <div class="verdict-copy"><span>${verdictLabel}</span><h2>${verdictTitle}</h2><p>${verdictDetail}</p></div>`;

  byId("audit-metrics").innerHTML = `
    <div class="metric"><span>Current charges</span><strong>${money(state.extraction.current_charges.value)}</strong></div>
    <div class="metric"><span>Verified checks</span><strong>${verified}</strong></div>
    <div class="metric"><span>Need more evidence</span><strong>${unavailable}</strong></div>
    <div class="metric"><span>Supported difference</span><strong>${money(result.discrepancy_total)}</strong></div>`;

  byId("audit-lines").innerHTML = result.lines.map((line) => {
    const links = line.citations.map((citation) => `<a href="${escapeHtml(citation.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(citation.label)} ↗</a>`).join("");
    const status = {
      verified: "Verified",
      discrepancy: "Mismatch",
      estimated: "Estimated",
      cannot_verify: "Needs source",
      needs_review: "Needs review",
    }[line.status];
    return `
      <tr>
        <td><span class="status-pill ${line.status}">${status}</span></td>
        <td class="charge-label">${escapeHtml(line.label)}</td>
        <td>${auditValue(line.billed_amount, line.unit)}</td>
        <td>${auditValue(line.expected_amount, line.unit)}</td>
        <td>${auditValue(line.delta, line.unit)}</td>
        <td><div class="trace">${escapeHtml(line.formula)}</div><div class="evidence-line">Page ${line.source_page}: “${escapeHtml(line.source_text)}”</div>${line.limitation ? `<div class="evidence-line"><strong>Limit:</strong> ${escapeHtml(line.limitation)}</div>` : ""}<div class="citation-links">${links}</div></td>
      </tr>`;
  }).join("");
  byId("audit-line-summary").textContent = `${result.lines.length} checks · ${verified} verified · ${unavailable} need more evidence${flagged ? ` · ${flagged} flagged` : ""}`;
  byId("audit-details").open = false;

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
  if (event.target.files[0]) showMessage();
});

byId("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button[type='submit']");
  const file = byId("bill-file").files[0];
  if (!file) return showMessage("Choose a PDF bill first.", button);
  showMessage();
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.previewUrl = URL.createObjectURL(file);
  const loadingLabel = state.codex.state === "connected"
    ? "Codex is mapping the evidence…"
    : "Reading the verified PDF…";
  setLoading(button, true, loadingLabel);
  try {
    const form = new FormData();
    form.append("bill", file);
    const payload = await responseJson(await fetch("/api/extract", {
      method: "POST",
      headers: { "X-WattProof-Request": "1" },
      body: form,
    }));
    state.extraction = payload.extraction;
    state.audit = null;
    renderReview("uploaded");
    showStep(2);
  } catch (error) {
    showMessage(error.message, button);
  } finally {
    setLoading(button, false, "");
  }
});

byId("review-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button[type='submit']");
  showMessage();
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
    renderAudit();
    showStep(3);
  } catch (error) {
    showMessage(error.message, button);
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

byId("copy-letter").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const text = `Subject: ${byId("letter-subject").value}\n\n${byId("letter-body").value}`;
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = "Copied — review before sending";
  } catch {
    byId("letter-body").select();
    document.execCommand("copy");
    button.textContent = "Copied — review before sending";
  }
  window.setTimeout(() => { button.textContent = "Copy request"; }, 2500);
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

refreshCodexStatus();
