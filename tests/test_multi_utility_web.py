from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pytest
from werkzeug.serving import make_server

from wattproof.app import create_app
from wattproof.audit_service import audit_extraction
from wattproof.cli import main
from wattproof.utility_fixtures import load_utility_sample
from wattproof.utility_models import UtilityAuditResult, UtilityDocument

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_JAVASCRIPT = PROJECT_ROOT / "wattproof" / "static" / "app.js"

REAL_BROWSER_HARNESS = r"""
const fs = require("node:fs");
const { spawn } = require("node:child_process");
const { mkdtemp, rm } = require("node:fs/promises");
const { tmpdir } = require("node:os");
const { join } = require("node:path");

const payload = JSON.parse(fs.readFileSync(0, "utf8"));

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function waitForDebugTarget(port, process, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = "Chromium did not expose a debug target";
  while (Date.now() < deadline) {
    if (process.spawnError) throw process.spawnError;
    if (process.exitCode !== null) {
      throw new Error(`Chromium exited before startup (${process.exitCode})`);
    }
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`);
      if (response.ok) {
        const targets = await response.json();
        const page = targets.find((target) => target.type === "page");
        if (page?.webSocketDebuggerUrl) return page.webSocketDebuggerUrl;
      }
    } catch (error) {
      lastError = String(error);
    }
    await delay(50);
  }
  throw new Error(lastError);
}

async function connectDevTools(url) {
  const socket = new WebSocket(url);
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error("DevTools WebSocket timed out")), 10000);
    socket.addEventListener("open", () => {
      clearTimeout(timeout);
      resolve();
    }, { once: true });
    socket.addEventListener("error", () => {
      clearTimeout(timeout);
      reject(new Error("DevTools WebSocket connection failed"));
    }, { once: true });
  });

  let nextId = 0;
  const pending = new Map();
  const protocolErrors = [];
  const externalRequests = [];

  socket.addEventListener("message", (event) => {
    const message = JSON.parse(typeof event.data === "string"
      ? event.data
      : Buffer.from(event.data).toString("utf8"));
    if (message.id && pending.has(message.id)) {
      const request = pending.get(message.id);
      pending.delete(message.id);
      clearTimeout(request.timeout);
      if (message.error) request.reject(new Error(JSON.stringify(message.error)));
      else request.resolve(message.result || {});
      return;
    }

    if (message.method === "Runtime.exceptionThrown") {
      const details = message.params?.exceptionDetails || {};
      protocolErrors.push(details.exception?.description || details.text || "Runtime exception");
    }
    if (message.method === "Runtime.consoleAPICalled" && message.params?.type === "error") {
      const text = (message.params.args || [])
        .map((argument) => argument.value ?? argument.description ?? argument.type)
        .join(" ");
      protocolErrors.push(`console.error: ${text}`);
    }
    if (message.method === "Log.entryAdded" && message.params?.entry?.level === "error") {
      protocolErrors.push(`browser log: ${message.params.entry.text}`);
    }
    if (message.method === "Network.requestWillBeSent") {
      const requestUrl = message.params?.request?.url;
      if (requestUrl?.startsWith("http://") || requestUrl?.startsWith("https://")) {
        const hostname = new URL(requestUrl).hostname;
        if (hostname !== "127.0.0.1" && hostname !== "localhost") {
          externalRequests.push(requestUrl);
        }
      }
    }
  });

  function command(method, params = {}, timeoutMs = 15000) {
    return new Promise((resolve, reject) => {
      const id = ++nextId;
      const timeout = setTimeout(() => {
        pending.delete(id);
        reject(new Error(`DevTools command timed out: ${method}`));
      }, timeoutMs);
      pending.set(id, { resolve, reject, timeout });
      socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async function evaluate(expression) {
    const result = await command("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
      userGesture: true,
    });
    if (result.exceptionDetails) {
      throw new Error(
        result.exceptionDetails.exception?.description || result.exceptionDetails.text,
      );
    }
    return result.result?.value;
  }

  async function waitFor(expression, timeoutMs = 15000) {
    const deadline = Date.now() + timeoutMs;
    let lastValue;
    while (Date.now() < deadline) {
      lastValue = await evaluate(expression);
      if (lastValue) return lastValue;
      await delay(40);
    }
    throw new Error(`Timed out waiting for: ${expression}; last value: ${lastValue}`);
  }

  return { socket, command, evaluate, waitFor, protocolErrors, externalRequests };
}

async function closeProcess(process) {
  if (!process.pid || process.exitCode !== null || process.signalCode !== null) return;
  process.kill("SIGTERM");
  const exited = await Promise.race([
    new Promise((resolve) => process.once("exit", () => resolve(true))),
    delay(3000).then(() => false),
  ]);
  if (!exited && process.exitCode === null) {
    process.kill("SIGKILL");
    await new Promise((resolve) => process.once("exit", resolve));
  }
}

async function main() {
  if (typeof WebSocket !== "function") {
    throw new Error("The opt-in real-browser test requires Node.js with global WebSocket support");
  }

  const profileDirectory = await mkdtemp(join(tmpdir(), "wattproof-chromium-"));
  const arguments = [
    "--headless=new",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-sync",
    "--metrics-recording-only",
    "--no-default-browser-check",
    "--no-first-run",
    `--remote-debugging-port=${payload.debugPort}`,
    "--remote-debugging-address=127.0.0.1",
    "--remote-allow-origins=*",
    `--user-data-dir=${profileDirectory}`,
    "about:blank",
  ];
  if (payload.noSandbox) arguments.unshift("--no-sandbox");

  const chromium = spawn(payload.browser, arguments, { stdio: ["ignore", "ignore", "pipe"] });
  chromium.spawnError = null;
  chromium.on("error", (error) => {
    chromium.spawnError = error;
  });
  let browserStderr = "";
  chromium.stderr.on("data", (chunk) => {
    if (browserStderr.length < 12000) browserStderr += chunk.toString("utf8");
  });

  let devtools;
  try {
    const target = await waitForDebugTarget(payload.debugPort, chromium);
    devtools = await connectDevTools(target);
    const { command, evaluate, waitFor } = devtools;

    await command("Page.enable");
    await command("Runtime.enable");
    await command("Log.enable");
    await command("Network.enable");
    await command("Page.addScriptToEvaluateOnNewDocument", {
      source: `(() => {
        const errors = [];
        Object.defineProperty(window, "__wattproofBrowserErrors", { value: errors });
        window.addEventListener("error", (event) => {
          errors.push(String(event.error || event.message));
        });
        window.addEventListener("unhandledrejection", (event) => {
          errors.push(String(event.reason));
        });
      })();`,
    });
    await command("Emulation.setDeviceMetricsOverride", {
      width: 1280,
      height: 900,
      deviceScaleFactor: 1,
      mobile: false,
    });

    async function navigateHome() {
      const navigation = await command("Page.navigate", { url: payload.baseUrl });
      if (navigation.errorText) throw new Error(navigation.errorText);
      await waitFor(`document.readyState === "complete"
        && Boolean(document.getElementById("authentic-sample"))`);
    }

    async function clickById(id) {
      await evaluate(`document.getElementById(${JSON.stringify(id)}).click(); true`);
    }

    async function runFlow(sample) {
      await navigateHome();
      const identity = await evaluate(`({
        title: document.title,
        url: location.href,
        body: document.body.innerText,
      })`);
      await clickById(`${sample}-sample`);
      await waitFor(`(() => {
        const panel = document.querySelector('[data-step="2"]');
        return panel && !panel.hidden && document.activeElement?.id === "review-title";
      })()`);
      const review = await evaluate(`(() => {
        const panel = document.querySelector('[data-step="2"]');
        const rect = panel.getBoundingClientRect();
        return {
          visible: !panel.hidden
            && getComputedStyle(panel).display !== "none"
            && rect.width > 0
            && rect.height > 0,
          focus: document.activeElement?.id,
          text: document.getElementById("service-review-sections").innerText,
          message: document.getElementById("global-message").innerText,
        };
      })()`);

      await evaluate(`document.querySelector('#review-form button[type="submit"]').click(); true`);
      await waitFor(`(() => {
        const panel = document.querySelector('[data-step="3"]');
        return panel && !panel.hidden && document.activeElement?.id === "verify-title"
          && Boolean(document.querySelector("#verification-level strong")?.textContent);
      })()`);
      const result = await evaluate(`(() => {
        const visible = (element) => {
          if (!element || element.hidden) return false;
          const style = getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          return style.display !== "none"
            && style.visibility !== "hidden"
            && rect.width > 0
            && rect.height > 0;
        };
        const comparison = document.getElementById("optional-comparison");
        return {
          focus: document.activeElement?.id,
          verificationVisible: visible(document.getElementById("verification-level")),
          verificationLabel: document.querySelector("#verification-level strong")
            .textContent.trim(),
          servicesText: document.getElementById("service-results").innerText,
          comparisonHidden: comparison.hidden,
          comparisonVisible: visible(comparison),
          requestCount: document.querySelectorAll(".provider-request-card").length,
          message: document.getElementById("global-message").innerText,
        };
      })()`);

      await clickById("finish-household-review");
      await waitFor(`!document.querySelector('[data-step="4"]').hidden
        && document.activeElement?.id === "household-title"`);
      await evaluate(`document.querySelector('[data-next="5"]').click(); true`);
      await waitFor(`!document.querySelector('[data-step="5"]').hidden
        && document.activeElement?.id === "next-steps-title"`);
      const requests = await evaluate(`(() => {
        const cards = [...document.querySelectorAll(".provider-request-card")];
        return {
          focus: document.activeElement?.id,
          count: cards.length,
          visibleCount: cards.filter((card) => {
            const rect = card.getBoundingClientRect();
            return getComputedStyle(card).display !== "none" && rect.width > 0 && rect.height > 0;
          }).length,
          text: document.getElementById("provider-review-requests").innerText,
          pageErrors: [...window.__wattproofBrowserErrors],
        };
      })()`);
      return { sample, identity, review, result, requests };
    }

    const flows = [];
    for (const sample of ["authentic", "synthetic", "duke", "centerpoint", "bloomington"]) {
      flows.push(await runFlow(sample));
    }

    await command("Emulation.setDeviceMetricsOverride", {
      width: 390,
      height: 844,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await navigateHome();
    await clickById("bloomington-sample");
    await waitFor(`!document.querySelector('[data-step="2"]').hidden
      && document.activeElement?.id === "review-title"`);
    const mobileReview = await evaluate(`(() => {
      const layout = document.querySelector(".review-layout");
      return {
        focus: document.activeElement?.id,
        columns: getComputedStyle(layout).gridTemplateColumns.trim().split(/\\s+/).length,
        noHorizontalOverflow:
          document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      };
    })()`);
    await evaluate(`document.querySelector('#review-form button[type="submit"]').click(); true`);
    await waitFor(`!document.querySelector('[data-step="3"]').hidden
      && document.activeElement?.id === "verify-title"`);
    await evaluate(`document.querySelector("#calculation-ledger summary").click(); true`);
    await waitFor(`document.getElementById("calculation-ledger").open`);
    const mobileResult = await evaluate(`(() => {
      const results = document.getElementById("service-results");
      const cards = [...results.querySelectorAll(".service-result-card")];
      const row = document.querySelector("#audit-lines tr:not([hidden])");
      const cell = row?.querySelector("td");
      return {
        width: innerWidth,
        height: innerHeight,
        verificationLabel: document.querySelector("#verification-level strong").textContent.trim(),
        serviceColumns: getComputedStyle(results).gridTemplateColumns.trim().split(/\\s+/).length,
        maxCardWidth: Math.max(...cards.map((card) => card.getBoundingClientRect().width)),
        clientWidth: document.documentElement.clientWidth,
        noHorizontalOverflow:
          document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        actionDirection: getComputedStyle(
          document.querySelector(".result-actions > div"),
        ).flexDirection,
        ledgerOpen: document.getElementById("calculation-ledger").open,
        rowDisplay: getComputedStyle(row).display,
        cellDisplay: getComputedStyle(cell).display,
        pageErrors: [...window.__wattproofBrowserErrors],
      };
    })()`);

    await evaluate(`new Promise((resolve) => setTimeout(() => resolve(true), 100))`);
    return {
      flows,
      mobileReview,
      mobileResult,
      protocolErrors: devtools.protocolErrors,
      externalRequests: devtools.externalRequests,
    };
  } finally {
    if (devtools) devtools.socket.close();
    await closeProcess(chromium);
    await rm(profileDirectory, { recursive: true, force: true });
    if (chromium.exitCode && browserStderr) process.stderr.write(browserStderr);
  }
}

main()
  .then((evidence) => process.stdout.write(JSON.stringify(evidence)))
  .catch((error) => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exitCode = 1;
  });
"""


def _exercise_javascript_contract(
    extraction: dict[str, Any],
    audit: dict[str, Any],
    *,
    mode: str,
) -> dict[str, Any]:
    harness = r"""
const fs = require("node:fs");
const vm = require("node:vm");

class FakeElement {
  constructor(id) {
    this.id = id;
    this.innerHTML = "";
    this.textContent = "";
    this.value = "";
    this.hidden = false;
    this.disabled = false;
    this.files = [];
    this.dataset = {};
    this.className = "";
    this.src = "";
    this.listeners = {};
    this.attributes = {};
    this.classList = {
      toggle() {},
      add() {},
      remove() {},
    };
  }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  querySelector() { return new FakeElement(`${this.id}-child`); }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) {
    delete this.attributes[name];
    if (name === "src") this.src = "";
  }
  scrollIntoView() {}
  select() {}
  click() {}
}

const elements = new Map();
const element = (id) => {
  if (!elements.has(id)) elements.set(id, new FakeElement(id));
  return elements.get(id);
};
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const context = {
  Blob,
  console,
  elements,
  FormData,
  payload,
  URL: { createObjectURL: () => "blob:test", revokeObjectURL() {} },
  navigator: { clipboard: { writeText: async () => {} } },
  fetch: async () => { throw new Error("Unexpected fetch in renderer contract"); },
  document: {
    createElement: (tag) => element(`created-${tag}`),
    execCommand: () => true,
    getElementById: element,
    querySelector: () => null,
    querySelectorAll: () => [],
  },
  window: {
    location: { reload() {} },
    scrollTo() {},
  },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(payload.appPath, "utf8"), context);

const output = vm.runInContext(`(() => {
  state.extraction = payload.extraction;
  renderReview(payload.mode);
  state.audit = payload.audit;
  state.compactAudit = true;
  renderAudit();

  const corrected = { value: 10, status: "printed" };
  markCorrected(corrected, "11");
  markCorrected(corrected, "12");
  const legacyEvidence = evidenceFor({
    source_page: 4,
    source_text: "Legacy rendered evidence",
    confidence: 0.75,
  });

  return {
    utilityDocument: isUtilityDocument(payload.extraction),
    reviewHtml: byId("service-review-sections").innerHTML,
    verificationHtml: byId("verification-level").innerHTML,
    verificationText: byId("verification-level").textContent,
    servicesHtml: byId("service-results").innerHTML,
    auditHtml: byId("audit-lines").innerHTML,
    comparisonHtml: byId("optional-comparison").innerHTML,
    comparisonHidden: byId("optional-comparison").hidden,
    requestsHtml: byId("provider-review-requests").innerHTML,
    corrected,
    legacyEvidence,
  };
})()` , context);
process.stdout.write(JSON.stringify(output));
"""
    payload = {
        "appPath": str(APP_JAVASCRIPT),
        "extraction": extraction,
        "audit": audit,
        "mode": mode,
    }
    completed = subprocess.run(
        ["node", "-e", harness],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )
    result: dict[str, Any] = json.loads(completed.stdout)
    return result


@pytest.mark.parametrize(
    ("kind", "schema_version"),
    [
        ("authentic", "1.0"),
        ("synthetic", "1.0"),
        ("duke", "2.0"),
        ("centerpoint", "2.0"),
        ("bloomington", "2.0"),
    ],
)
def test_web_exposes_all_deterministic_samples(
    kind: str,
    schema_version: str,
) -> None:
    response = create_app().test_client().get(f"/api/sample/{kind}")

    assert response.status_code == 200
    assert response.get_json()["extraction"]["schema_version"] == schema_version


def test_web_sample_not_found_is_controlled() -> None:
    response = create_app().test_client().get("/api/sample/not-a-sample")

    assert response.status_code == 404
    assert response.is_json
    error = response.get_json()["error"]
    for kind in ("authentic", "synthetic", "duke", "centerpoint", "bloomington"):
        assert kind in error
    assert "Traceback" not in response.get_data(as_text=True)


def test_web_audits_legacy_authentic_payload() -> None:
    client = create_app().test_client()
    extraction_response = client.get("/api/sample/authentic")
    extraction = extraction_response.get_json()["extraction"]

    response = client.post("/api/audit", json=extraction)

    assert extraction_response.status_code == 200
    assert response.status_code == 200
    result = response.get_json()["audit"]
    assert result["fixture_kind"] == "authentic"
    assert result["verification_level"] == "tariff_verified"
    assert result["tariff"] is not None
    assert result["comparison"] is not None


@pytest.mark.parametrize("kind", ["duke", "centerpoint", "bloomington"])
def test_web_audits_provider_neutral_payload_without_tariff_claim(kind: str) -> None:
    client = create_app().test_client()
    extraction = client.get(f"/api/sample/{kind}").get_json()["extraction"]

    response = client.post("/api/audit", json=extraction)

    assert response.status_code == 200
    result = response.get_json()["audit"]
    assert result["verification_level"] == "internally_reconciled"
    assert result["tariff"] is None
    assert result["comparison"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": "9.0", "account_number": "private-account-123"},
        {"account_number": "private-account-123"},
    ],
)
def test_web_rejects_unknown_or_missing_schema_without_echoing_payload(
    payload: dict[str, str],
) -> None:
    response = create_app().test_client().post("/api/audit", json=payload)

    assert response.status_code == 422
    assert response.is_json
    body = response.get_data(as_text=True)
    assert "schema_version" in response.get_json()["error"]
    assert "private-account-123" not in body
    assert "Traceback" not in body


def test_web_rejects_malformed_schema_two_payload_without_sensitive_detail() -> None:
    payload = load_utility_sample("duke").model_dump(mode="json")
    payload["sections"][0]["charges"][0]["amount"]["value"] = (
        "private-account-123"
    )

    response = create_app().test_client().post("/api/audit", json=payload)

    assert response.status_code == 422
    assert response.is_json
    body = response.get_data(as_text=True)
    assert "sections.0.charges.0.amount.value" in response.get_json()["error"]
    assert "private-account-123" not in body
    assert "Traceback" not in body


def test_web_does_not_echo_unknown_charge_reference() -> None:
    payload = load_utility_sample("duke").model_dump(mode="json")
    payload["sections"][1]["charges"][0]["calculation"]["charge_ids"] = [
        "private-account-123"
    ]

    response = create_app().test_client().post("/api/audit", json=payload)

    assert response.status_code == 422
    assert response.is_json
    body = response.get_data(as_text=True)
    assert "unknown charge ID" in response.get_json()["error"]
    assert "private-account-123" not in body
    assert "Traceback" not in body


def test_web_upload_returns_provider_neutral_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "wattproof.app.extract_pdf",
        lambda _path: load_utility_sample("duke"),
    )

    response = create_app().test_client().post(
        "/api/extract",
        data={"bill": (BytesIO(b"%PDF-placeholder"), "duke.pdf")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.get_json()["extraction"]["schema_version"] == "2.0"


def test_page_uses_provider_neutral_five_step_language() -> None:
    page = create_app().test_client().get("/").get_data(as_text=True)
    for label in ("Upload", "Review", "Verify", "Household", "Next steps"):
        assert f"<b>{label}</b>" in page
    assert "Choose a utility bill" in page
    assert "Your utility bill has a formula." in page
    assert "PG&amp;E-first" not in page
    assert "Indiana-only" not in page
    for sample_id in ("duke-sample", "centerpoint-sample", "bloomington-sample"):
        assert f'id="{sample_id}"' in page
    assert page.index('id="authentic-sample"') < page.index('id="duke-sample"')
    assert page.index('id="synthetic-sample"') < page.index('id="duke-sample"')


def test_result_markup_exposes_neutral_contract() -> None:
    page = create_app().test_client().get("/").get_data(as_text=True)
    for element_id in (
        "verification-level",
        "service-results",
        "optional-comparison",
        "service-review-sections",
        "provider-review-requests",
        "add-another-bill",
        "finish-household-review",
    ):
        assert f'id="{element_id}"' in page
    assert 'id="optional-comparison"' in page
    assert "hidden" in page[page.index('id="optional-comparison"') :][:160]


def test_javascript_keeps_exact_schema_and_correction_helpers() -> None:
    source = APP_JAVASCRIPT.read_text(encoding="utf-8")
    for helper in (
        '''function isUtilityDocument(extraction) {
  return extraction?.schema_version === "2.0";
}''',
        '''function evidenceFor(fact) {
  return fact.evidence || {
    page: fact.source_page,
    text: fact.source_text,
    confidence: fact.confidence,
  };
}''',
        '''function markCorrected(fact, nextValue) {
  if (fact.status !== "user_corrected") fact.original_value = String(fact.value);
  fact.value = nextValue;
  fact.status = "user_corrected";
}''',
    ):
        assert helper in source


@pytest.mark.parametrize(
    ("kind", "mode", "verification_label", "expected_units"),
    [
        ("authentic", "authentic", "Tariff verified", ("kWh",)),
        ("synthetic", "synthetic", "Tariff verified", ("kWh",)),
        ("duke", "uploaded", "Internally reconciled", ("kWh",)),
        ("centerpoint", "centerpoint", "Internally reconciled", ("therm", "CCF")),
        ("bloomington", "bloomington", "Internally reconciled", ("kgal",)),
    ],
)
def test_javascript_renders_both_schemas_and_unified_results_without_crashing(
    kind: str,
    mode: str,
    verification_label: str,
    expected_units: tuple[str, ...],
) -> None:
    client = create_app().test_client()
    extraction = client.get(f"/api/sample/{kind}").get_json()["extraction"]
    audit = client.post("/api/audit", json=extraction).get_json()["audit"]

    rendered = _exercise_javascript_contract(extraction, audit, mode=mode)

    assert rendered["utilityDocument"] is (extraction["schema_version"] == "2.0")
    assert verification_label in (
        rendered["verificationHtml"] + rendered["verificationText"]
    )
    for unit in expected_units:
        assert unit in rendered["reviewHtml"] + rendered["servicesHtml"]
    assert audit["headline"] in rendered["verificationHtml"] + rendered["servicesHtml"]
    assert rendered["comparisonHidden"] is (audit["comparison"] is None)
    if audit["comparison"] is not None:
        assert audit["comparison"]["headline"] in rendered["comparisonHtml"]
    for request in audit["review_requests"]:
        assert escape(request["provider"]) in rendered["requestsHtml"]
        assert escape(request["subject"]) in rendered["requestsHtml"]
    assert rendered["corrected"] == {
        "value": "12",
        "status": "user_corrected",
        "original_value": "10",
    }
    assert rendered["legacyEvidence"] == {
        "page": 4,
        "text": "Legacy rendered evidence",
        "confidence": 0.75,
    }


def test_schema_two_review_is_grouped_by_service_sections() -> None:
    client = create_app().test_client()
    extraction = client.get("/api/sample/bloomington").get_json()["extraction"]
    audit = client.post("/api/audit", json=extraction).get_json()["audit"]

    rendered = _exercise_javascript_contract(extraction, audit, mode="uploaded")

    review = rendered["reviewHtml"]
    for service in ("Water", "Wastewater", "Stormwater", "Sanitation"):
        assert service in review
    assert "City of Bloomington Utilities" in review
    assert "Page 1" in review
    assert "printed" in review
    assert "inferred" in review


@pytest.mark.parametrize(
    ("kind", "label", "has_comparison"),
    [
        ("authentic", "Tariff verified", True),
        ("synthetic", "Tariff verified", True),
        ("duke", "Internally reconciled", False),
        ("centerpoint", "Internally reconciled", False),
        ("bloomington", "Internally reconciled", False),
    ],
)
def test_cli_exposes_all_samples_with_approved_verification_labels(
    kind: str,
    label: str,
    has_comparison: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--sample", kind]) == 0

    captured = capsys.readouterr()
    assert f"Verification level: {label}" in captured.out
    assert ("Plan comparison:" in captured.out) is has_comparison
    if kind in {"duke", "centerpoint", "bloomington"}:
        assert "tariff verified" not in captured.out.lower()
    assert captured.err == ""


def test_cli_prints_evidence_extracted_label(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = audit_extraction(load_utility_sample("duke")).model_dump(mode="json")
    payload["verification_level"] = "evidence_extracted"
    payload["headline"] = "Evidence extracted for review"
    result = UtilityAuditResult.model_validate(payload)

    def return_result(_extraction: object) -> UtilityAuditResult:
        return result

    monkeypatch.setattr("wattproof.cli.audit_extraction", return_result)

    assert main(["--sample", "duke"]) == 0
    assert "Verification level: Evidence extracted" in capsys.readouterr().out


def test_cli_audits_extracted_provider_neutral_document(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "wattproof.cli.extract_pdf",
        lambda _path: load_utility_sample("duke"),
    )

    assert main(["--file", "duke.pdf"]) == 0
    output = capsys.readouterr()
    assert "Verification level: Internally reconciled" in output.out
    assert "tariff verified" not in output.out.lower()
    assert output.err == ""


def test_cli_returns_nonzero_for_sample_validation_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def invalid_sample(_kind: object) -> UtilityDocument:
        return UtilityDocument.model_validate({"schema_version": "2.0"})

    monkeypatch.setattr("wattproof.cli.load_utility_sample", invalid_sample)

    assert main(["--sample", "duke"]) == 2
    captured = capsys.readouterr()
    assert "WattProof could not audit this document" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def _find_real_browser_binary() -> str:
    configured = os.environ.get("AGENT_BROWSER_BIN")
    if configured:
        configured_path = Path(configured).expanduser()
        if configured_path.is_file() and os.access(configured_path, os.X_OK):
            return str(configured_path)
        configured_command = shutil.which(configured)
        if configured_command:
            return configured_command
        raise AssertionError(
            f"AGENT_BROWSER_BIN does not identify an executable browser: {configured}"
        )

    for command in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
        "chrome",
        "microsoft-edge",
    ):
        installed = shutil.which(command)
        if installed:
            return installed

    if sys.platform == "darwin":
        for candidate in (
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        ):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)

    raise AssertionError(
        "no Chromium browser found; set AGENT_BROWSER_BIN to a Chrome, Chromium, "
        "or Edge executable"
    )


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return cast(int, listener.getsockname()[1])


def _run_real_browser_smoke() -> dict[str, Any]:
    server = make_server("127.0.0.1", 0, create_app(), threaded=True)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        node = shutil.which("node")
        assert node, "the opt-in real-browser test requires Node.js"
        completed = subprocess.run(
            [node, "-e", REAL_BROWSER_HARNESS],
            input=json.dumps(
                {
                    "baseUrl": f"http://127.0.0.1:{server.server_port}/",
                    "browser": _find_real_browser_binary(),
                    "debugPort": _unused_local_port(),
                    "noSandbox": hasattr(os, "geteuid") and os.geteuid() == 0,
                }
            ),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        assert completed.returncode == 0, (
            "real Chromium harness failed\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
        evidence = json.loads(completed.stdout)
        assert isinstance(evidence, dict)
        return cast(dict[str, Any], evidence)
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)


def test_real_chromium_sample_review_and_audit_flows() -> None:
    if os.environ.get("WATTPROOF_REAL_BROWSER") != "1":
        pytest.skip(
            "set WATTPROOF_REAL_BROWSER=1 to run the real Chromium UI smoke test"
        )

    evidence = _run_real_browser_smoke()
    expectations: dict[str, dict[str, Any]] = {
        "authentic": {
            "verification": "Tariff verified",
            "comparison": True,
            "requests": 2,
            "review_units": ("kWh",),
            "result_units": ("kWh",),
        },
        "synthetic": {
            "verification": "Tariff verified",
            "comparison": True,
            "requests": 1,
            "review_units": ("kWh",),
            "result_units": ("kWh",),
        },
        "duke": {
            "verification": "Internally reconciled",
            "comparison": False,
            "requests": 1,
            "review_units": ("kWh",),
            "result_units": ("kWh",),
        },
        "centerpoint": {
            "verification": "Internally reconciled",
            "comparison": False,
            "requests": 1,
            "review_units": ("CCF", "therm"),
            "result_units": ("therm",),
        },
        "bloomington": {
            "verification": "Internally reconciled",
            "comparison": False,
            "requests": 1,
            "review_units": ("kgal",),
            "result_units": ("kgal",),
        },
    }

    flows = evidence["flows"]
    assert [flow["sample"] for flow in flows] == list(expectations)
    for flow in flows:
        expected = expectations[flow["sample"]]
        assert flow["identity"]["title"] == (
            "WattProof — Check the math on your utility bill"
        )
        assert flow["identity"]["url"].startswith("http://127.0.0.1:")
        assert "Your utility bill has a formula" in flow["identity"]["body"]
        assert flow["review"]["visible"] is True
        assert flow["review"]["focus"] == "review-title"
        assert flow["review"]["message"] == ""
        for unit in expected["review_units"]:
            assert unit in flow["review"]["text"]

        result = flow["result"]
        assert result["focus"] == "verify-title"
        assert result["verificationVisible"] is True
        assert result["verificationLabel"] == expected["verification"]
        assert result["comparisonHidden"] is (not expected["comparison"])
        assert result["comparisonVisible"] is expected["comparison"]
        assert result["requestCount"] == expected["requests"]
        assert result["message"] == ""
        for unit in expected["result_units"]:
            assert unit in result["servicesText"]

        requests = flow["requests"]
        assert requests["focus"] == "next-steps-title"
        assert requests["count"] == expected["requests"]
        assert requests["visibleCount"] == expected["requests"]
        assert requests["pageErrors"] == []

    assert flows[0]["requests"]["count"] > 1
    assert all(
        flow["result"]["verificationLabel"] != "Tariff verified"
        for flow in flows
        if flow["sample"] not in {"authentic", "synthetic"}
    )
    assert evidence["protocolErrors"] == []
    assert evidence["externalRequests"] == []

    mobile_review = evidence["mobileReview"]
    assert mobile_review == {
        "focus": "review-title",
        "columns": 1,
        "noHorizontalOverflow": True,
    }
    mobile_result = evidence["mobileResult"]
    assert mobile_result["width"] == 390
    assert mobile_result["height"] == 844
    assert mobile_result["verificationLabel"] == "Internally reconciled"
    assert mobile_result["serviceColumns"] == 1
    assert mobile_result["maxCardWidth"] <= mobile_result["clientWidth"]
    assert mobile_result["noHorizontalOverflow"] is True
    assert mobile_result["actionDirection"] == "column"
    assert mobile_result["ledgerOpen"] is True
    assert mobile_result["rowDisplay"] == "block"
    assert mobile_result["cellDisplay"] == "grid"
    assert mobile_result["pageErrors"] == []
