from __future__ import annotations

import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from html import escape
from html.parser import HTMLParser
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
REVIEW_SCREENSHOT_SPECS = {
    "multi-utility-upload-desktop.png": (1440, 1000),
    "pge-tariff-verified-desktop.png": (1440, 1000),
    "duke-internal-reconciliation-desktop.png": (1440, 1000),
    "centerpoint-gas-desktop.png": (1440, 1000),
    "household-bundle-desktop.png": (1440, 1000),
    "water-review-mobile.png": (390, 844),
    "household-result-mobile.png": (390, 844),
}


class _MarkupProbe(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.attributes: list[tuple[str, str | None]] = []
        self.text: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.tags.append(tag)
        self.attributes.extend(attrs)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        self.text.append(data)

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
      width: 1440,
      height: 1000,
      deviceScaleFactor: 1,
      mobile: false,
    });

    async function captureViewport(filename) {
      if (!payload.captureDirectory) return;
      fs.mkdirSync(payload.captureDirectory, { recursive: true });
      await command("Page.bringToFront");
      const focusedElementId = await evaluate(`document.activeElement?.id || null`);
      await evaluate(`(() => {
        if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
        return true;
      })()`);
      await evaluate(`document.fonts.ready.then(() => new Promise((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
      }))`);
      await delay(500);
      const capture = await command("Page.captureScreenshot", {
        format: "png",
        fromSurface: true,
        captureBeyondViewport: false,
      });
      fs.writeFileSync(
        join(payload.captureDirectory, filename),
        Buffer.from(capture.data, "base64"),
      );
      if (focusedElementId) {
        await evaluate(
          `document.getElementById(${JSON.stringify(focusedElementId)})?.focus(); true`,
        );
      }
    }

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
      if (sample === "centerpoint") {
        await evaluate(`(() => {
          window.__wattproofWarningEvent = 0;
          state.extraction.warnings = [
            "Rendered/native text conflict requires review.",
            "<img id=warning-real src=x onerror=window.__wattproofWarningEvent+=1>",
          ];
          renderReview("centerpoint");
          return true;
        })()`);
        await delay(100);
      }
      const review = await evaluate(`(() => {
        const panel = document.querySelector('[data-step="2"]');
        const rect = panel.getBoundingClientRect();
        const billingDays = document.getElementById("fact-billing_days");
        return {
          visible: !panel.hidden
            && getComputedStyle(panel).display !== "none"
            && rect.width > 0
            && rect.height > 0,
          focus: document.activeElement?.id,
          text: document.getElementById("service-review-sections").innerText,
          warningHidden: document.getElementById("review-warnings").hidden,
          warningText: document.getElementById("review-warnings").innerText,
          warningInjectedElements: document.querySelectorAll("#warning-real").length,
          warningEventCount: window.__wattproofWarningEvent || 0,
          billingDays: billingDays ? {
            value: billingDays.value,
            exactNumber: billingDays.dataset.exactNumber,
            unavailable: billingDays.closest(".fact-field")
              .innerText.includes("Exact numeric spelling unavailable"),
          } : null,
          message: document.getElementById("global-message").innerText,
        };
      })()`);

      let correction = null;
      if (sample === "duke") {
        await evaluate(`(() => {
          const input = document.getElementById("fact-sections-0-usage");
          input.value = "1002";
          input.dispatchEvent(new Event("input", { bubbles: true }));
          return true;
        })()`);
      }

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
          verdictText: document.getElementById("verdict-card").innerText,
          comparisonHidden: comparison.hidden,
          comparisonVisible: visible(comparison),
          requestCount: document.querySelectorAll(".provider-request-card").length,
          message: document.getElementById("global-message").innerText,
        };
      })()`);

      if (sample === "duke") {
        await evaluate(`document.querySelector('[data-step="3"] [data-back="2"]').click(); true`);
        await waitFor(`!document.querySelector('[data-step="2"]').hidden
          && document.activeElement?.id === "review-title"`);
        correction = await evaluate(`(() => {
          const input = document.getElementById("fact-sections-0-usage");
          const field = input.closest(".fact-field");
          return {
            value: input.value,
            badge: field.querySelector(".evidence-type").textContent.trim(),
            note: field.querySelector(".correction-note")?.textContent.trim() || "",
            evidenceText: field.querySelector(".fact-evidence")?.textContent || "",
          };
        })()`);
        await evaluate(
          `document.querySelector('#review-form button[type="submit"]').click(); true`,
        );
        await waitFor(`!document.querySelector('[data-step="3"]').hidden
          && document.activeElement?.id === "verify-title"`);
      }

      await clickById("finish-household");
      await waitFor(`!document.querySelector('[data-step="4"]').hidden
        && document.activeElement?.id === "household-title"`);
      await clickById("review-next-steps");
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
      return { sample, identity, review, result, requests, correction };
    }

    async function captureSampleResult(sample, filename) {
      await navigateHome();
      await clickById(`${sample}-sample`);
      await waitFor(`!document.querySelector('[data-step="2"]').hidden
        && document.activeElement?.id === "review-title"`);
      await evaluate(`document.querySelector('#review-form button[type="submit"]').click(); true`);
      await waitFor(`!document.querySelector('[data-step="3"]').hidden
        && document.activeElement?.id === "verify-title"`);
      await evaluate(`window.scrollTo(0, 0); true`);
      await delay(250);
      await captureViewport(filename);
    }

    if (payload.captureDirectory) {
      await navigateHome();
      await evaluate(`window.scrollTo(0, 0); true`);
      await delay(250);
      await captureViewport("multi-utility-upload-desktop.png");
      await captureSampleResult("authentic", "pge-tariff-verified-desktop.png");
      await captureSampleResult("duke", "duke-internal-reconciliation-desktop.png");
      await captureSampleResult("centerpoint", "centerpoint-gas-desktop.png");
    }

    const flows = [];
    for (const sample of ["authentic", "synthetic", "duke", "centerpoint", "bloomington"]) {
      flows.push(await runFlow(sample));
    }

    async function completeSample(sample, completionId) {
      await clickById(`${sample}-sample`);
      await waitFor(`!document.querySelector('[data-step="2"]').hidden
        && document.activeElement?.id === "review-title"`);
      await evaluate(`document.querySelector('#review-form button[type="submit"]').click(); true`);
      await waitFor(`!document.querySelector('[data-step="3"]').hidden
        && document.activeElement?.id === "verify-title"`);
      await clickById(completionId);
    }

    await navigateHome();
    await completeSample("duke", "add-another-bill");
    await waitFor(`!document.querySelector('[data-step="1"]').hidden
      && document.activeElement?.id === "upload-title"`);
    await completeSample("centerpoint", "add-another-bill");
    await waitFor(`!document.querySelector('[data-step="1"]').hidden
      && document.activeElement?.id === "upload-title"`);
    await completeSample("bloomington", "finish-household");
    await waitFor(`!document.querySelector('[data-step="4"]').hidden
      && document.activeElement?.id === "household-title"`);
    const sequentialDesktop = await evaluate(`(() => {
      const cards = [...document.querySelectorAll(".household-bill-card")];
      return {
        focus: document.activeElement?.id,
        bundleLength: state.bundle.length,
        currentBundleId: state.currentBundleId,
        replacementBundleId: state.replacementBundleId,
        replacementArmed: state.replacementArmed,
        extractionCleared: state.extraction === null,
        auditCleared: state.audit === null,
        previewCleared: state.previewUrl === null,
        cardCount: cards.length,
        text: document.getElementById("household-bills").innerText,
        summaryText: document.getElementById("household-summary").innerText,
        uniqueIds: new Set(state.bundle.map((summary) => summary.id)).size,
        noHorizontalOverflow:
          document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        pageErrors: [...window.__wattproofBrowserErrors],
      };
    })()`);

    if (payload.captureDirectory) {
      await evaluate(`window.scrollTo(0, 0); true`);
      await delay(250);
      await captureViewport("household-bundle-desktop.png");
      await command("Emulation.setDeviceMetricsOverride", {
        width: 390,
        height: 844,
        deviceScaleFactor: 1,
        mobile: false,
      });
      await delay(500);
      await evaluate(`(() => {
        const firstCard = document.querySelector(".household-bill-card");
        firstCard.scrollIntoView({ block: "start", behavior: "instant" });
        window.scrollBy(0, -12);
        return true;
      })()`);
      await delay(500);
      await captureViewport("household-result-mobile.png");
      await command("Emulation.setDeviceMetricsOverride", {
        width: 1440,
        height: 1000,
        deviceScaleFactor: 1,
        mobile: false,
      });
      await evaluate(`window.scrollTo(0, 0); true`);
      await delay(250);
    }

    await clickById("review-next-steps");
    await waitFor(`!document.querySelector('[data-step="5"]').hidden
      && document.activeElement?.id === "next-steps-title"`);
    await evaluate(`(() => {
      const drafts = [...document.querySelectorAll('[data-request-field="body"]')];
      const draft = drafts.at(-1);
      draft.value = "Stale page-memory draft";
      draft.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    })()`);
    await evaluate(`document.querySelector('[data-step="5"] [data-back="4"]').click(); true`);
    await waitFor(`!document.querySelector('[data-step="4"]').hidden`);
    const bundleIdsBeforeReaudit = await evaluate(
      `state.bundle.map((summary) => summary.id)`,
    );
    await clickById("replace-household-bill");
    await waitFor(`!document.querySelector('[data-step="1"]').hidden
      && document.activeElement?.id === "upload-title"`);
    await clickById("bloomington-sample");
    await waitFor(`!document.querySelector('[data-step="2"]').hidden
      && document.activeElement?.id === "review-title"`);
    const reauditEdited = await evaluate(`(() => {
      state.extraction.sections[0].usage.evidence.confidence = "0.145";
      renderReview("bloomington");
      const usage = document.getElementById("fact-sections-0-usage");
      const amount = document.getElementById("fact-amount_due");
      usage.value = "5.750000123456789012";
      amount.value = "100.005";
      usage.dispatchEvent(new Event("input", { bubbles: true }));
      amount.dispatchEvent(new Event("input", { bubbles: true }));
      return {
        usage: usage.value,
        amount: amount.value,
        confidence: usage.closest(".fact-field")
          .querySelector(".fact-evidence summary").textContent.trim(),
      };
    })()`);
    await evaluate(`document.querySelector('#review-form button[type="submit"]').click(); true`);
    await waitFor(`!document.querySelector('[data-step="3"]').hidden
      && document.activeElement?.id === "verify-title"`);
    const reauditExpected = await evaluate(`(() => {
      const amountLine = state.audit.lines.find((line) => line.id === "statement::amount_due");
      return {
        verification: state.audit.verification_level,
        discrepancy: state.audit.discrepancy_total,
        discrepancyType: typeof state.audit.discrepancy_total,
        amountBilled: amountLine?.billed_amount,
        amountExpected: amountLine?.expected_amount,
        amountDelta: amountLine?.delta,
        ledgerText: document.getElementById("audit-lines").textContent,
        serviceText: document.getElementById("service-results").innerText,
        issues: new Set(state.audit.lines
          .filter((line) => ["discrepancy", "needs_review"].includes(line.status))
          .map((line, index) => String(line.root_cause_id || line.id || "issue-" + index)))
          .size,
      };
    })()`);
    await evaluate(`document.querySelector('[data-step="3"] [data-back="2"]').click(); true`);
    await waitFor(`!document.querySelector('[data-step="2"]').hidden
      && document.activeElement?.id === "review-title"`);
    const reauditRerendered = await evaluate(`(() => {
      const usage = document.getElementById("fact-sections-0-usage");
      const amount = document.getElementById("fact-amount_due");
      return {
        usage: usage.value,
        amount: amount.value,
        confidence: usage.closest(".fact-field")
          .querySelector(".fact-evidence summary").textContent.trim(),
      };
    })()`);
    await evaluate(`document.querySelector('#review-form button[type="submit"]').click(); true`);
    await waitFor(`!document.querySelector('[data-step="3"]').hidden
      && document.activeElement?.id === "verify-title"`);
    await clickById("finish-household");
    await waitFor(`!document.querySelector('[data-step="4"]').hidden`);
    const reauditReplacement = await evaluate(`(() => {
      const summary = structuredClone(state.bundle.at(-1));
      return {
        bundleLength: state.bundle.length,
        ids: state.bundle.map((candidate) => candidate.id),
        summary,
        currentBundleId: state.currentBundleId,
        replacementBundleId: state.replacementBundleId,
        replacementArmed: state.replacementArmed,
        extractionCleared: state.extraction === null,
        auditCleared: state.audit === null,
        previewCleared: state.previewUrl === null,
        householdText: document.getElementById("household-bills").innerText,
      };
    })()`);
    Object.assign(reauditReplacement, {
      expectedVerification: reauditExpected.verification,
      expectedDiscrepancy: reauditExpected.discrepancy,
      expectedIssues: reauditExpected.issues,
      expectedAmountBilled: reauditExpected.amountBilled,
      expectedAmountExpected: reauditExpected.amountExpected,
      expectedAmountDelta: reauditExpected.amountDelta,
    });
    await clickById("review-next-steps");
    await waitFor(`!document.querySelector('[data-step="5"]').hidden`);
    reauditReplacement.requestText = await evaluate(
      `document.getElementById("provider-review-requests").innerText`,
    );
    await evaluate(`document.querySelector('[data-step="5"] [data-back="4"]').click(); true`);
    await evaluate(`finishHouseholdReview(); true`);
    await waitFor(`!document.querySelector('[data-step="4"]').hidden`);
    const repeatedFinish = await evaluate(`({
      count: state.bundle.length,
      summary: structuredClone(state.bundle.at(-1)),
    })`);

    await command("Emulation.setDeviceMetricsOverride", {
      width: 390,
      height: 844,
      deviceScaleFactor: 1,
      mobile: false,
    });
    const mobileHousehold = await evaluate(`(() => {
      const container = document.getElementById("household-bills");
      const cards = [...container.querySelectorAll(".household-bill-card")];
      return {
        width: innerWidth,
        height: innerHeight,
        columns: getComputedStyle(container).gridTemplateColumns.trim().split(/\\s+/).length,
        cardCount: cards.length,
        maxCardWidth: Math.max(...cards.map((card) => card.getBoundingClientRect().width)),
        clientWidth: document.documentElement.clientWidth,
        noHorizontalOverflow:
          document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      };
    })()`);

    await clickById("review-next-steps");
    await waitFor(`!document.querySelector('[data-step="5"]').hidden
      && document.activeElement?.id === "next-steps-title"`);
    const mobileRequests = await evaluate(`(() => {
      const cards = [...document.querySelectorAll(".provider-request-card")];
      return {
        focus: document.activeElement?.id,
        count: cards.length,
        text: document.getElementById("provider-review-requests").innerText,
        cardColumns: cards.map((card) =>
          getComputedStyle(card).gridTemplateColumns.trim().split(/\\s+/).length),
        noHorizontalOverflow:
          document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      };
    })()`);
    await evaluate(`(() => {
      const input = document.querySelector('[data-request-field="subject"]');
      input.value = "Edited only in this page";
      input.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    })()`);
    await evaluate(`document.querySelector('[data-step="5"] [data-back="4"]').click(); true`);
    await waitFor(`!document.querySelector('[data-step="4"]').hidden`);
    await clickById("review-next-steps");
    await waitFor(`!document.querySelector('[data-step="5"]').hidden`);
    const editedDraft = await evaluate(
      `document.querySelector('[data-request-field="subject"]').value`,
    );

    await evaluate(`document.querySelector('[data-step="5"] [data-back="4"]').click(); true`);
    await clickById("replace-household-bill");
    await waitFor(`!document.querySelector('[data-step="1"]').hidden
      && document.activeElement?.id === "upload-title"`);
    await evaluate(`document.querySelector('#upload-form button[type="submit"]').click(); true`);
    await waitFor(`document.getElementById("global-message").textContent
      === "Choose a PDF bill first."`);
    const laterFailure = await evaluate(`({
      bundleLength: state.bundle.length,
      currentBundleId: state.currentBundleId,
      replacementBundleId: state.replacementBundleId,
      replacementArmed: state.replacementArmed,
      extractionCleared: state.extraction === null,
      auditCleared: state.audit === null,
      retainedCardCount: document.querySelectorAll(".household-bill-card").length,
      message: document.getElementById("global-message").textContent,
      focus: document.activeElement?.id,
      pageErrors: [...window.__wattproofBrowserErrors],
    })`);

    await navigateHome();
    const refreshClears = await evaluate(`({
      bundleLength: state.bundle.length,
      currentBundleId: state.currentBundleId,
      cardCount: document.querySelectorAll(".household-bill-card").length,
      requestsCount: document.querySelectorAll(".provider-request-card").length,
      pageErrors: [...window.__wattproofBrowserErrors],
    })`);

    const previewBeforeDiscard = await evaluate(`(async () => {
      window.__wattproofRevokedPreviews = [];
      const nativeRevoke = URL.revokeObjectURL.bind(URL);
      URL.revokeObjectURL = (url) => {
        window.__wattproofRevokedPreviews.push(String(url));
        return nativeRevoke(url);
      };
      const response = await fetch("/sample.pdf");
      const source = await response.blob();
      const transfer = new DataTransfer();
      transfer.items.add(new File([source], "discard-me.pdf", { type: "application/pdf" }));
      const input = document.getElementById("bill-file");
      input.files = transfer.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
      document.querySelector('#upload-form button[type="submit"]').click();
      return true;
    })()`);
    if (!previewBeforeDiscard) throw new Error("Could not stage uploaded preview");
    await waitFor(`!document.querySelector('[data-step="2"]').hidden
      && document.activeElement?.id === "review-title"
      && state.previewUrl?.startsWith("blob:")`, 30000);
    const uploadedPreviewUrl = await evaluate(`state.previewUrl`);
    await clickById("discard-current-document");
    await waitFor(`!document.querySelector('[data-step="1"]').hidden
      && document.activeElement?.id === "upload-title"`);
    const previewDiscard = await evaluate(`({
      previewUrl: state.previewUrl,
      extractionCleared: state.extraction === null,
      auditCleared: state.audit === null,
      iframeHasSource: document.getElementById("pdf-preview").hasAttribute("src"),
      revokedUrls: [...window.__wattproofRevokedPreviews],
      fileCount: document.getElementById("bill-file").files.length,
      focus: document.activeElement?.id,
      pageErrors: [...window.__wattproofBrowserErrors],
    })`);
    previewDiscard.uploadedPreviewUrl = uploadedPreviewUrl;

    await navigateHome();
    await evaluate(`(async () => {
      window.__wattproofFinishRevokedPreviews = [];
      const nativeRevoke = URL.revokeObjectURL.bind(URL);
      URL.revokeObjectURL = (url) => {
        window.__wattproofFinishRevokedPreviews.push(String(url));
        return nativeRevoke(url);
      };
      const response = await fetch("/sample.pdf");
      const source = await response.blob();
      const transfer = new DataTransfer();
      transfer.items.add(new File([source], "finish-me.pdf", { type: "application/pdf" }));
      const input = document.getElementById("bill-file");
      input.files = transfer.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
      document.querySelector('#upload-form button[type="submit"]').click();
      return true;
    })()`);
    await waitFor(`!document.querySelector('[data-step="2"]').hidden
      && state.previewUrl?.startsWith("blob:")`, 30000);
    const finishPreviewUrl = await evaluate(`state.previewUrl`);
    await evaluate(`document.querySelector('#review-form button[type="submit"]').click(); true`);
    await waitFor(`!document.querySelector('[data-step="3"]').hidden
      && state.audit !== null`);
    await clickById("finish-household");
    await waitFor(`!document.querySelector('[data-step="4"]').hidden`);
    const previewFinish = await evaluate(`({
      bundleLength: state.bundle.length,
      summary: structuredClone(state.bundle[0]),
      extractionCleared: state.extraction === null,
      auditCleared: state.audit === null,
      previewUrl: state.previewUrl,
      currentBundleId: state.currentBundleId,
      replacementBundleId: state.replacementBundleId,
      replacementArmed: state.replacementArmed,
      reviewCleared: document.getElementById("service-review-sections").innerHTML === "",
      auditClearedFromDom: document.getElementById("audit-lines").innerHTML === "",
      iframeHasSource: document.getElementById("pdf-preview").hasAttribute("src"),
      revokedUrls: [...window.__wattproofFinishRevokedPreviews],
      fileCount: document.getElementById("bill-file").files.length,
      focus: document.activeElement?.id,
      pageErrors: [...window.__wattproofBrowserErrors],
    })`);
    previewFinish.uploadedPreviewUrl = finishPreviewUrl;

    await navigateHome();
    const exactBundleRendering = await evaluate(`(() => {
      const summary = (id, amountDue) => ({
        id,
        providers: ["Exact Decimal Utility"],
        serviceTypes: ["electricity"],
        periodStart: "2024-01-01",
        periodEnd: "2024-01-31",
        period: "2024-01-01 – 2024-01-31",
        usageSummaries: [{
          serviceType: "electricity",
          value: "1002.123456789012345678",
          unit: "kWh",
        }],
        amountDue,
        currency: "USD",
        verificationLevel: "evidence_extracted",
        discrepancyTotal: "0",
        issueCount: 0,
        reviewRequests: [],
      });
      state.bundle = [summary("exact-a", "0.1"), summary("exact-b", "0.2")];
      renderHousehold();
      showStep(4);
      const exactAddition = {
        summaryText: document.getElementById("household-summary").innerText,
        billsText: document.getElementById("household-bills").innerText,
        amountTypes: state.bundle.map((entry) => typeof entry.amountDue),
      };
      state.bundle = [summary("round-a", "0.005"), summary("round-b", "0.005")];
      renderHousehold();
      const noEarlyRounding = document.getElementById("household-summary").innerText;
      state.bundle[0].amountDue = 0.1 + 0.2;
      renderHousehold();
      const numberFallback = {
        summaryText: document.getElementById("household-summary").innerText,
        billsText: document.getElementById("household-bills").innerText,
      };
      return {
        exactAddition,
        noEarlyRounding,
        numberFallback,
        pageErrors: [...window.__wattproofBrowserErrors],
      };
    })()`);

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
    if (payload.captureDirectory) {
      await evaluate(`window.scrollTo(0, 0); true`);
      await delay(250);
      await captureViewport("water-review-mobile.png");
    }
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
        tableScrollOverflowX: getComputedStyle(
          document.querySelector(".table-scroll"),
        ).overflowX,
        pageErrors: [...window.__wattproofBrowserErrors],
      };
    })()`);

    const hostileDom = await evaluate(`new Promise((resolve) => {
      window.__wattproofHostileEvent = 0;
      const marker = "<img id=hostile-real src=x onerror=window.__wattproofHostileEvent+=1>";
      state.extraction.sections[0].provider.value = marker;
      state.extraction.sections[0].subtotal.currency = marker;
      state.audit.lines[0].status = "discrepancy";
      state.audit.lines[0].label = marker;
      state.audit.lines[0].unit = marker;
      state.audit.lines[0].formula = marker;
      state.audit.lines[0].evidence = [{ page: marker, text: marker }];
      state.audit.lines[0].citations = [{
        label: marker,
        source_url: "javascript:window.__wattproofHostileEvent+=10",
      }];
      state.audit.review_requests = [{
        provider: marker,
        subject: marker,
        body: marker,
        grounded_audit_line_ids: [state.audit.lines[0].id],
      }];
      renderAudit();
      setTimeout(() => resolve({
        injectedElements: document.querySelectorAll("#hostile-real").length,
        eventCount: window.__wattproofHostileEvent,
        textRendered: document.body.innerText.includes(marker),
        javascriptLinks: [...document.querySelectorAll("a")]
          .filter((link) => /^(javascript|data):/i.test(link.getAttribute("href") || ""))
          .length,
      }), 100);
    })`);

    await evaluate(`new Promise((resolve) => setTimeout(() => resolve(true), 100))`);
    return {
      flows,
      sequentialDesktop,
      bundleIdsBeforeReaudit,
      reauditEdited,
      reauditRerendered,
      reauditExpected,
      reauditReplacement,
      repeatedFinish,
      mobileHousehold,
      mobileRequests,
      editedDraft,
      laterFailure,
      refreshClears,
      previewDiscard,
      previewFinish,
      exactBundleRendering,
      mobileReview,
      mobileResult,
      hostileDom,
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

ASYNC_STATE_HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");

class FakeElement {
  constructor(id) {
    this.id = id;
    this.innerHTML = id.endsWith("submit") ? "Submit" : "";
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
    this.resetCount = 0;
    this.classList = { toggle() {}, add() {}, remove() {} };
  }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  querySelector(selector) {
    if (selector.includes("button[type='submit']")) return element(`${this.id}-submit`);
    return null;
  }
  querySelectorAll(selector) {
    if (this.id === "review-form" && selector.includes("data-fact-path")) {
      return [...factInputs, element("review-form-submit")];
    }
    return [];
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) {
    delete this.attributes[name];
    if (name === "src") this.src = "";
  }
  getAttribute(name) { return this.attributes[name] ?? null; }
  scrollIntoView() {}
  focus() { document.activeElement = this; }
  reset() {
    this.resetCount += 1;
    if (this.id === "upload-form") element("bill-file").files = [];
  }
  select() {}
  click() { return this.listeners.click?.({ currentTarget: this, target: this }); }
}

const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const elements = new Map();
const element = (id) => {
  if (!elements.has(id)) elements.set(id, new FakeElement(id));
  return elements.get(id);
};
let factInputs = [];
let reloadCount = 0;
const stepPanels = [1, 2, 3, 4, 5].map((step) => {
  const panel = element(`step-${step}`);
  panel.dataset.step = String(step);
  return panel;
});
const stepHeadings = new Map(stepPanels.map((panel) => {
  const heading = element(`heading-${panel.dataset.step}`);
  heading.id = ({ 1: "upload-title", 2: "review-title", 3: "verify-title" })[panel.dataset.step]
    || `heading-${panel.dataset.step}`;
  return [panel.dataset.step, heading];
}));
const indicators = [1, 2, 3, 4, 5].map((step) => {
  const indicator = element(`indicator-${step}`);
  indicator.dataset.stepIndicator = String(step);
  return indicator;
});
const backToReview = element("back-to-review");
backToReview.dataset.back = "2";
const backToVerify = element("back-to-verify");
backToVerify.dataset.back = "3";
const backButtons = [backToReview, backToVerify];

const document = {
  activeElement: null,
  createElement: (tag) => element(`created-${tag}`),
  execCommand: () => true,
  getElementById: element,
  querySelector(selector) {
    const headingMatch = selector.match(/^\[data-step="(\d)"\] h1$/);
    if (headingMatch) return stepHeadings.get(headingMatch[1]);
    return null;
  },
  querySelectorAll(selector) {
    if (selector === "[data-step]") return stepPanels;
    if (selector === "[data-step-indicator]") return indicators;
    if (selector === "[data-back]") return backButtons;
    if (selector === "[data-next]" || selector === ".optional-line") return [];
    if (selector === "[data-fact-path]") return factInputs;
    if (selector.includes("aria-describedby")) {
      return factInputs.filter((input) => input.attributes["aria-describedby"]);
    }
    return [];
  },
};

const requests = [];
const createdUrls = [];
const revokedUrls = [];
let nextBundleId = 0;
let nextPreviewId = 0;
function deferredFetch(url, options = {}) {
  return new Promise((resolve, reject) => {
    const request = { url: String(url), options, resolve, reject, settled: false };
    requests.push(request);
    if (payload.abortAware && options.signal) {
      options.signal.addEventListener("abort", () => {
        if (request.settled) return;
        request.settled = true;
        const error = new Error("aborted");
        error.name = "AbortError";
        reject(error);
      }, { once: true });
    }
  });
}

function settle(url, body, ok = true) {
  const request = requests.find((candidate) => candidate.url === url && !candidate.settled);
  if (!request) throw new Error(`No pending request for ${url}`);
  request.settled = true;
  request.resolve({ ok, json: async () => body });
}

const context = {
  AbortController,
  Blob,
  console,
  crypto: { randomUUID: () => `bundle-id-${++nextBundleId}` },
  document,
  elements,
  fetch: deferredFetch,
  FormData,
  navigator: { clipboard: { writeText: async () => {} } },
  structuredClone,
  payload,
  URL: {
    createObjectURL: () => {
      const url = `blob:test-${++nextPreviewId}`;
      createdUrls.push(url);
      return url;
    },
    revokeObjectURL: (url) => revokedUrls.push(url),
  },
  window: {
    location: { reload() { reloadCount += 1; } },
    scrollTo() {},
  },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(payload.appPath, "utf8"), context);

function invoke(expression) {
  return vm.runInContext(expression, context);
}

function submitReview() {
  const form = element("review-form");
  return form.listeners.submit({
    preventDefault() {},
    currentTarget: form,
  });
}

function currentState() {
  return invoke(`({
    extraction: state.extraction,
    audit: state.audit,
    bundle: state.bundle,
    currentBundleId: state.currentBundleId,
    currentBundleAuditRevision: state.currentBundleAuditRevision,
    replacementBundleId: state.replacementBundleId,
    replacementArmed: state.replacementArmed,
    auditRevision: state.auditRevision,
    previewUrl: state.previewUrl,
    operationToken: state.operationToken,
  })`);
}

async function run() {
  if (payload.scenario === "sample_race") {
    const first = invoke(`loadSample("authentic", byId("authentic-sample"))`);
    const second = invoke(`loadSample("duke", byId("duke-sample"))`);
    settle("/api/sample/duke", { extraction: payload.extractionB });
    await second;
    if (requests.some((request) => request.url === "/api/sample/authentic" && !request.settled)) {
      settle("/api/sample/authentic", { extraction: payload.extractionA });
    }
    await first;
    return {
      ...currentState(),
      reviewHtml: element("service-review-sections").innerHTML,
      message: element("global-message").textContent,
      firstDisabled: element("authentic-sample").disabled,
      secondDisabled: element("duke-sample").disabled,
    };
  }

  if (payload.scenario === "general_error") {
    const request = invoke(`loadSample("authentic", byId("authentic-sample"))`);
    settle("/api/sample/authentic", { error: "Reader temporarily unavailable" }, false);
    await request;
    return {
      activeElement: document.activeElement?.id || null,
      message: element("global-message").textContent,
      alertHidden: element("global-message").hidden,
    };
  }

  if (payload.scenario === "upload_then_sample") {
    element("bill-file").files = [new Blob(["%PDF"], { type: "application/pdf" })];
    const form = element("upload-form");
    const upload = form.listeners.submit({ preventDefault() {}, currentTarget: form });
    const sample = invoke(`loadSample("duke", byId("duke-sample"))`);
    settle("/api/sample/duke", { extraction: payload.extractionB });
    await sample;
    settle("/api/extract", { extraction: payload.extractionA });
    await upload;
    return {
      ...currentState(),
      reviewHtml: element("service-review-sections").innerHTML,
      message: element("global-message").textContent,
      uploadDisabled: element("upload-form-submit").disabled,
      sampleDisabled: element("duke-sample").disabled,
      createdUrls,
      revokedUrls,
    };
  }

  if (payload.scenario === "upload_failure") {
    element("bill-file").files = [new Blob(["%PDF"], { type: "application/pdf" })];
    const form = element("upload-form");
    const upload = form.listeners.submit({ preventDefault() {}, currentTarget: form });
    settle("/api/extract", { error: "Rendered page reader failed" }, false);
    await upload;
    const beforeSecondClear = {
      state: currentState(),
      revokedUrls: [...revokedUrls],
      fileCount: element("bill-file").files.length,
      uploadResetCount: form.resetCount,
      reviewHtml: element("service-review-sections").innerHTML,
      auditHtml: element("audit-lines").innerHTML,
      previewSrc: element("pdf-preview").src,
      previewHidden: element("pdf-preview").hidden,
      uploadHidden: element("step-1").hidden,
      message: element("global-message").textContent,
      activeElement: document.activeElement?.id || null,
      fileInvalid: element("bill-file").attributes["aria-invalid"] || null,
    };
    invoke("clearCurrentDocument()");
    return {
      beforeSecondClear,
      createdUrls,
      revokedUrls,
      resetAfterSecondClear: form.resetCount,
    };
  }

  if (payload.scenario === "uploaded_review_discard") {
    element("bill-file").files = [new Blob(["%PDF"], { type: "application/pdf" })];
    const form = element("upload-form");
    const upload = form.listeners.submit({ preventDefault() {}, currentTarget: form });
    settle("/api/extract", { extraction: payload.extractionA });
    await upload;
    const previewBeforeDiscard = currentState().previewUrl;
    element("discard-current-document").listeners.click({
      currentTarget: element("discard-current-document"),
      target: element("discard-current-document"),
    });
    return {
      ...currentState(),
      previewBeforeDiscard,
      createdUrls,
      revokedUrls,
      fileCount: element("bill-file").files.length,
      uploadResetCount: form.resetCount,
      reviewHtml: element("service-review-sections").innerHTML,
      previewSrc: element("pdf-preview").src,
      previewHidden: element("pdf-preview").hidden,
      uploadHidden: element("step-1").hidden,
      activeElement: document.activeElement?.id || null,
    };
  }

  if (payload.scenario === "uploaded_review_then_sample") {
    element("bill-file").files = [new Blob(["%PDF"], { type: "application/pdf" })];
    const form = element("upload-form");
    const upload = form.listeners.submit({ preventDefault() {}, currentTarget: form });
    settle("/api/extract", { extraction: payload.extractionA });
    await upload;
    const uploadedPreview = currentState().previewUrl;
    const sample = invoke(`loadSample("duke", byId("duke-sample"))`);
    settle("/api/sample/duke", { extraction: payload.extractionB });
    await sample;
    return {
      ...currentState(),
      uploadedPreview,
      createdUrls,
      revokedUrls,
      fileCount: element("bill-file").files.length,
      uploadResetCount: form.resetCount,
      reviewHtml: element("service-review-sections").innerHTML,
    };
  }

  invoke(`state.extraction = payload.extractionA; renderReview(payload.mode); showStep(2)`);

  if (payload.scenario === "audit_then_sample") {
    const audit = submitReview();
    const sample = invoke(`loadSample("duke", byId("duke-sample"))`);
    settle("/api/sample/duke", { extraction: payload.extractionB });
    await sample;
    settle("/api/audit", { audit: payload.auditA });
    await audit;
    return {
      ...currentState(),
      reviewHtml: element("service-review-sections").innerHTML,
      verifyHidden: element("step-3").hidden,
      message: element("global-message").textContent,
    };
  }

  if (payload.scenario === "audit_then_navigation") {
    const audit = submitReview();
    if (payload.navigation === "restart") element("restart").listeners.click();
    else element("discard-current-document").listeners.click();
    settle("/api/audit", { audit: payload.auditA });
    await audit;
    return {
      ...currentState(),
      reloadCount,
      uploadHidden: element("step-1").hidden,
      verifyHidden: element("step-3").hidden,
      message: element("global-message").textContent,
    };
  }

  if (payload.scenario === "correction") {
    const input = element("corrected-input");
    input.dataset.factPath = payload.factPath;
    input.value = payload.nextValue;
    factInputs = [input];
    const audit = submitReview();
    if (payload.outcome === "error") {
      settle("/api/audit", { error: `${payload.factPath}: invalid corrected value` }, false);
    } else {
      settle("/api/audit", { audit: payload.auditA });
    }
    await audit;
    if (payload.outcome === "success") backToReview.listeners.click();
    const fact = invoke(`valueAt(state.extraction, payload.factPath)`);
    return {
      ...currentState(),
      fact,
      reviewHtml: element("service-review-sections").innerHTML,
      reviewHidden: element("step-2").hidden,
      activeElement: document.activeElement?.id || null,
      inputInvalid: input.attributes["aria-invalid"] || null,
      inputDescribedBy: input.attributes["aria-describedby"] || null,
      message: element("global-message").textContent,
    };
  }

  if (payload.scenario === "finish_reaudit_refinish") {
    invoke(`state.previewUrl = "blob:completed-upload"`);
    const firstAudit = submitReview();
    settle("/api/audit", { audit: payload.auditA });
    await firstAudit;
    invoke("finishHouseholdReview()");
    const first = invoke("structuredClone(state.bundle[0])");
    const afterFirstFinish = {
      state: currentState(),
      revokedUrls: [...revokedUrls],
      reviewHtml: element("service-review-sections").innerHTML,
      warningsHtml: element("review-warnings").innerHTML,
      verificationHtml: element("verification-level").innerHTML,
      auditHtml: element("audit-lines").innerHTML,
      previewSrc: element("pdf-preview").src,
      uploadResetCount: element("upload-form").resetCount,
    };
    invoke(`state.bundle[0].reviewRequests[0].body = "Page-memory draft"`);
    invoke("finishHouseholdReview()");
    const idempotent = invoke("structuredClone(state.bundle[0])");

    element("replace-household-bill").listeners.click();
    const armedReplacement = currentState();
    const replacementLoad = invoke(`loadSample("duke", byId("duke-sample"))`);
    settle("/api/sample/duke", { extraction: payload.extractionB });
    await replacementLoad;
    const afterExplicitReload = currentState();
    const usage = element("corrected-usage");
    usage.dataset.factPath = "sections.0.usage";
    usage.value = payload.nextUsage;
    const amount = element("corrected-amount");
    amount.dataset.factPath = "amount_due";
    amount.value = payload.nextAmount;
    factInputs = [usage, amount];
    const secondAudit = submitReview();
    settle("/api/audit", { audit: payload.auditB });
    await secondAudit;
    invoke("finishHouseholdReview()");
    const replaced = invoke("structuredClone(state.bundle[0])");
    const afterReplacementFinish = currentState();
    invoke("finishHouseholdReview()");
    const repeated = invoke("structuredClone(state.bundle[0])");
    invoke("renderProviderReviewRequests()");
    const replacementRequestsHtml = element("provider-review-requests").innerHTML;

    element("replace-household-bill").listeners.click();
    const addAnotherLoad = invoke(`loadSample("duke", byId("duke-sample"))`);
    settle("/api/sample/duke", { extraction: payload.extractionB });
    await addAnotherLoad;
    factInputs = [];
    const thirdAudit = submitReview();
    settle("/api/audit", { audit: payload.auditB });
    await thirdAudit;
    invoke("addAnotherBill()");
    const afterReplacementAddAnother = currentState();
    return {
      ...currentState(),
      first,
      afterFirstFinish,
      idempotent,
      armedReplacement,
      afterExplicitReload,
      replaced,
      afterReplacementFinish,
      repeated,
      afterReplacementAddAnother,
      revokedUrls,
      householdHtml: element("household-bills").innerHTML,
      requestsHtml: replacementRequestsHtml,
    };
  }

  if (payload.scenario === "bundle_then_sample_error") {
    invoke(`state.audit = payload.auditA; addAnotherBill(); renderHousehold()`);
    const request = invoke(`loadSample("duke", byId("duke-sample"))`);
    settle("/api/sample/duke", { error: "Fixture temporarily unavailable" }, false);
    await request;
    return {
      ...currentState(),
      householdHtml: element("household-bills").innerHTML,
      message: element("global-message").textContent,
      activeElement: document.activeElement?.id || null,
      uploadHidden: element("step-1").hidden,
    };
  }

  if (payload.scenario === "bundle_then_upload_error") {
    invoke(`state.audit = payload.auditA; addAnotherBill(); renderHousehold()`);
    element("bill-file").files = [new Blob(["%PDF"], { type: "application/pdf" })];
    const form = element("upload-form");
    const upload = form.listeners.submit({ preventDefault() {}, currentTarget: form });
    settle("/api/extract", { error: "Later rendered page reader failed" }, false);
    await upload;
    return {
      ...currentState(),
      householdHtml: element("household-bills").innerHTML,
      createdUrls,
      revokedUrls,
      fileCount: element("bill-file").files.length,
      message: element("global-message").textContent,
      activeElement: document.activeElement?.id || null,
      uploadHidden: element("step-1").hidden,
    };
  }

  throw new Error(`Unknown scenario: ${payload.scenario}`);
}

run()
  .then((result) => process.stdout.write(JSON.stringify(result)))
  .catch((error) => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exitCode = 1;
  });
"""


HOUSEHOLD_STATE_HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");

class FakeElement {
  constructor(id) {
    this.id = id;
    this.innerHTML = "";
    this.textContent = "";
    this.value = "";
    this.hidden = false;
    this.dataset = {};
    this.attributes = {};
    this.resetCount = 0;
    this.className = "";
    this.src = "";
    this.classList = { toggle() {}, add() {}, remove() {} };
  }
  querySelectorAll() { return []; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) {
    delete this.attributes[name];
    if (name === "src") this.src = "";
  }
  scrollIntoView() {}
  focus() { document.activeElement = this; }
  reset() { this.resetCount += 1; }
}

const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const elements = new Map();
const element = (id) => {
  if (!elements.has(id)) elements.set(id, new FakeElement(id));
  return elements.get(id);
};
const stepPanels = [1, 2, 3, 4, 5].map((step) => {
  const panel = element(`step-${step}`);
  panel.dataset.step = String(step);
  return panel;
});
const indicators = [1, 2, 3, 4, 5].map((step) => {
  const indicator = element(`indicator-${step}`);
  indicator.dataset.stepIndicator = String(step);
  return indicator;
});
const headings = new Map(stepPanels.map((panel) => {
  const heading = element(`heading-${panel.dataset.step}`);
  return [panel.dataset.step, heading];
}));
const revokedUrls = [];
let nextId = 0;
const document = {
  activeElement: null,
  getElementById: element,
  querySelector(selector) {
    const match = selector.match(/^\[data-step="(\d)"\] h1$/);
    return match ? headings.get(match[1]) : null;
  },
  querySelectorAll(selector) {
    if (selector === "[data-step]") return stepPanels;
    if (selector === "[data-step-indicator]") return indicators;
    if (selector.includes("aria-describedby")) return [];
    return [];
  },
};
const context = {
  AbortController,
  Blob,
  console,
  crypto: { randomUUID: () => `bundle-id-${++nextId}` },
  document,
  elements,
  FormData,
  navigator: { clipboard: { writeText: async () => {} } },
  structuredClone,
  URL: {
    createObjectURL: () => "blob:generated",
    revokeObjectURL: (url) => revokedUrls.push(url),
  },
  window: { location: { reload() {} }, scrollTo() {} },
};
vm.createContext(context);
const source = fs.readFileSync(payload.appPath, "utf8");
const bindingStart = source.indexOf('byId("authentic-sample").addEventListener');
if (bindingStart < 0) throw new Error("Could not isolate WattProof UI logic");
vm.runInContext(source.slice(0, bindingStart), context);

function invoke(expression) {
  return vm.runInContext(expression, context);
}

function installDocument(index) {
  context.currentDocument = structuredClone(payload.documents[index]);
  invoke(`(() => {
    state.extraction = currentDocument.extraction;
    state.audit = currentDocument.audit;
    state.reviewMode = currentDocument.mode;
    state.previewUrl = currentDocument.previewUrl;
  })()`);
}

function installReplacementDocument(index) {
  context.currentDocument = structuredClone(payload.documents[index]);
  invoke(`(() => {
    replaceExtraction(currentDocument.extraction, currentDocument.mode);
    state.audit = currentDocument.audit;
    state.auditRevision += 1;
  })()`);
}

function markupCount(markup, className) {
  return (markup.match(new RegExp(`class="[^"]*${className}`, "g")) || []).length;
}

const summaries = payload.documents.map((_entry, index) => {
  installDocument(index);
  return invoke("summarizeCurrentBill()");
});
const firstSummarySnapshot = structuredClone(summaries[0]);
installDocument(0);
invoke(`(() => {
  if (state.extraction.sections?.[0]?.provider) {
    state.extraction.sections[0].provider.value = "mutated provider";
  } else {
    state.extraction.delivery_provider.value = "mutated provider";
  }
  if (state.audit.review_requests?.[0]) {
    state.audit.review_requests[0].body = "mutated request";
  }
})()`);

installDocument(0);
invoke("finishHouseholdReview(); finishHouseholdReview(); showStep(3); finishHouseholdReview()");
const afterRepeatedFinish = invoke(`({
  bundleLength: state.bundle.length,
  currentBundleId: state.currentBundleId,
  replacementBundleId: state.replacementBundleId,
  replacementArmed: state.replacementArmed,
  extraction: state.extraction,
  audit: state.audit,
  previewUrl: state.previewUrl,
})`);
invoke("beginHouseholdReplacement()");
installReplacementDocument(0);
invoke("addAnotherBill()");
const afterAddFollowingFinish = invoke(`({
  bundleLength: state.bundle.length,
  currentBundleId: state.currentBundleId,
  replacementBundleId: state.replacementBundleId,
  replacementArmed: state.replacementArmed,
  extraction: state.extraction,
  audit: state.audit,
  uploadVisible: !document.getElementById("step-1").hidden,
})`);

installDocument(1);
invoke("addAnotherBill()");
installDocument(2);
invoke("finishHouseholdReview(); finishHouseholdReview()");
const bundle = invoke("structuredClone(state.bundle)");
context.savedBundle = structuredClone(bundle);
const householdHtml = element("household-bills").innerHTML;
const householdSummaryHtml = element("household-summary").innerHTML;
invoke("renderProviderReviewRequests()");
const requestsHtml = element("provider-review-requests").innerHTML;
const requestCount = markupCount(requestsHtml, "provider-request-card");

const editedDraft = "Page-memory edit only <draft>";
invoke(`updateReviewRequestDraft(
  state.bundle[0].id,
  0,
  "body",
  ${JSON.stringify(editedDraft)}
); renderProviderReviewRequests()`);
const editedRequestsHtml = element("provider-review-requests").innerHTML;
const editedRequestBody = invoke("state.bundle[0].reviewRequests[0].body");

invoke(`state.bundle = state.bundle.map((summary, index) => ({
  ...summary,
  periodStart: ["2024-01-01", "2024-01-15", "2024-01-20"][index],
  periodEnd: ["2024-01-31", "2024-02-15", "2024-01-25"][index],
  period: "Compatible test period",
  amountDue: ["10.01", "20.02", "30.03"][index],
  currency: "USD",
})); renderHousehold()`);
const compatibleSummaryHtml = element("household-summary").innerHTML;

invoke(`state.bundle = state.bundle.map((summary, index) => ({
  ...summary,
  amountDue: ["0.1", "0.2", "0"][index],
})); renderHousehold()`);
const exactAdditionSummaryHtml = element("household-summary").innerHTML;
invoke(`state.bundle = state.bundle.map((summary, index) => ({
  ...summary,
  amountDue: ["0.005", "0.005", "0"][index],
})); renderHousehold()`);
const noEarlyRoundingSummaryHtml = element("household-summary").innerHTML;
invoke(`state.bundle[0].amountDue = 0.1 + 0.2; renderHousehold()`);
const numberAmountSummaryHtml = element("household-summary").innerHTML;
const numberAmountBillsHtml = element("household-bills").innerHTML;
invoke(`state.bundle = state.bundle.map((summary, index) => ({
  ...summary,
  amountDue: ["10.01", "20.02", "30.03"][index],
})); renderHousehold()`);

invoke(`state.bundle[2].currency = "CAD"; renderHousehold()`);
const mixedCurrencySummaryHtml = element("household-summary").innerHTML;
invoke(`state.bundle[2].currency = "USD";
  state.bundle[2].periodStart = null; renderHousehold()`);
const missingPeriodSummaryHtml = element("household-summary").innerHTML;
invoke(`state.bundle[2].periodStart = "2025-01-01";
  state.bundle[2].periodEnd = "2025-01-31"; renderHousehold()`);
const nonoverlapSummaryHtml = element("household-summary").innerHTML;
invoke(`state.bundle = state.bundle.map((summary, index) => ({
  ...summary,
  periodStart: ["2024-01-01", "2024-01-15", "2024-01-20"][index],
  periodEnd: ["2024-01-31", "2024-02-15", "2024-01-25"][index],
  currency: "USD",
})); state.bundle[2].amountDue = null; renderHousehold()`);
const missingAmountSummaryHtml = element("household-summary").innerHTML;
invoke(`state.bundle[2].amountDue = "30.03";
  state.bundle = state.bundle.map((summary) => ({ ...summary, currency: null }));
  renderHousehold()`);
const missingCurrencySummaryHtml = element("household-summary").innerHTML;

invoke("state.bundle = savedBundle; renderHousehold(); renderProviderReviewRequests()");
invoke("clearHousehold()");
const afterClear = invoke(`({
  bundleLength: state.bundle.length,
  currentBundleId: state.currentBundleId,
  replacementBundleId: state.replacementBundleId,
  replacementArmed: state.replacementArmed,
  extraction: state.extraction,
  audit: state.audit,
  previewUrl: state.previewUrl,
  uploadVisible: !document.getElementById("step-1").hidden,
})`);

process.stdout.write(JSON.stringify({
  summaries,
  firstSummarySnapshot,
  summarySourceIsolated: JSON.stringify(firstSummarySnapshot) === JSON.stringify(summaries[0]),
  afterRepeatedFinish,
  afterAddFollowingFinish,
  bundle,
  householdHtml,
  householdSummaryHtml,
  requestCount,
  requestsHtml,
  editedRequestBody,
  editedRequestsHtml,
  compatibleSummaryHtml,
  exactAdditionSummaryHtml,
  noEarlyRoundingSummaryHtml,
  numberAmountSummaryHtml,
  numberAmountBillsHtml,
  mixedCurrencySummaryHtml,
  missingPeriodSummaryHtml,
  nonoverlapSummaryHtml,
  missingAmountSummaryHtml,
  missingCurrencySummaryHtml,
  revokedUrls,
  uploadResetCount: element("upload-form").resetCount,
  afterClear,
  clearedMarkup: {
    household: element("household-bills").innerHTML,
    summary: element("household-summary").innerHTML,
    requests: element("provider-review-requests").innerHTML,
    review: element("service-review-sections").innerHTML,
    audit: element("audit-lines").innerHTML,
  },
}));
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
  crypto: { randomUUID: () => "renderer-bundle-id" },
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
    warningsHtml: byId("review-warnings").innerHTML,
    warningsHidden: byId("review-warnings").hidden,
    verificationHtml: byId("verification-level").innerHTML,
    verificationText: byId("verification-level").textContent,
    servicesHtml: byId("service-results").innerHTML,
    priorityHtml: byId("priority-findings").innerHTML,
    auditHtml: byId("audit-lines").innerHTML,
    verdictHtml: byId("verdict-card").innerHTML,
    comparisonHtml: byId("optional-comparison").innerHTML,
    comparisonHidden: byId("optional-comparison").hidden,
    requestsHtml: byId("provider-review-requests").innerHTML,
    summaryIssueCount: summarizeCurrentBill()?.issueCount,
    numericFormatting: {
      moneyHalfUp: money("100.005", "USD"),
      moneyNegativeHalfUp: money("-100.005", "USD"),
      moneyNegativeZero: money("-0.004", "USD"),
      moneyPositiveZero: money("+0.000", "USD"),
      measurement: decimalValue("1234567.123456789012345678"),
      scientificMeasurement: decimalValue("1.23456789e-10"),
      scientificTrailingZeros: decimalValue("1.2300e2"),
      minimumExponent: decimalValue("1e-18"),
      leadingZeroExponent: decimalValue("1e-000000000000000018"),
      maximumMagnitude: decimalValue("999999999999"),
      signedMeasurementZero: decimalValue("-0.000"),
      safeIntegerMoney: money(31, "USD"),
      safeIntegerMeasurement: decimalValue(31),
      numberMoney: money(100.005, "USD"),
      numberMeasurement: decimalValue(0.1 + 0.2),
      outOfRangeInteger: decimalValue(1000000000000),
      confidenceHtml: evidenceMarkup({
        evidence: { page: 1, text: "Exact confidence", confidence: "0.145" },
      }),
      numberConfidenceHtml: evidenceMarkup({
        evidence: { page: 1, text: "Binary confidence", confidence: 0.145 },
      }),
      oversizedMeasurement: decimalValue("1".repeat(65)),
      outOfRangeExponent: decimalValue("1e1000000"),
      exponentBelowDomain: decimalValue("1e-19"),
      magnitudeAboveDomain: decimalValue("1e12"),
      tooManyDigits: decimalValue("12345678901234567890123456789e-18"),
      surroundingWhitespace: decimalValue(" 1.2"),
    },
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


def _exercise_async_state_contract(
    scenario: str,
    *,
    extraction_a: dict[str, Any] | None = None,
    extraction_b: dict[str, Any] | None = None,
    audit_a: dict[str, Any] | None = None,
    **options: Any,
) -> dict[str, Any]:
    payload = {
        "appPath": str(APP_JAVASCRIPT),
        "scenario": scenario,
        "extractionA": extraction_a,
        "extractionB": extraction_b,
        "auditA": audit_a,
        **options,
    }
    completed = subprocess.run(
        ["node", "-e", ASYNC_STATE_HARNESS],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result: dict[str, Any] = json.loads(completed.stdout)
    return result


def _exercise_household_state_contract(
    documents: list[dict[str, Any]],
) -> dict[str, Any]:
    completed = subprocess.run(
        ["node", "-e", HOUSEHOLD_STATE_HARNESS],
        input=json.dumps(
            {
                "appPath": str(APP_JAVASCRIPT),
                "documents": documents,
            }
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result: dict[str, Any] = json.loads(completed.stdout)
    return result


def _sample_document(client: Any, kind: str) -> dict[str, Any]:
    extraction = client.get(f"/api/sample/{kind}").get_json()["extraction"]
    audit = client.post("/api/audit", json=extraction).get_json()["audit"]
    return {
        "extraction": extraction,
        "audit": audit,
        "mode": kind,
        "previewUrl": f"blob:{kind}",
    }


def _validate_staged_screenshot(path: Path, dimensions: tuple[int, int]) -> None:
    assert path.is_file() and not path.is_symlink(), (
        f"staged screenshot is not a regular file: {path.name}"
    )
    data = path.read_bytes()
    assert len(data) > 10_000, f"staged screenshot is too small: {path.name}"
    assert data.startswith(b"\x89PNG\r\n\x1a\n"), (
        f"staged screenshot is not PNG: {path.name}"
    )
    assert data[12:16] == b"IHDR", f"staged screenshot lacks IHDR: {path.name}"
    actual_dimensions = tuple(
        int.from_bytes(data[offset : offset + 4], "big") for offset in (16, 20)
    )
    assert actual_dimensions == dimensions, (
        f"staged screenshot has dimensions {actual_dimensions}, expected "
        f"{dimensions}: {path.name}"
    )


def _publish_staged_screenshots(staging: Path, target: Path) -> None:
    actual_names = {path.name for path in staging.iterdir()}
    expected_names = set(REVIEW_SCREENSHOT_SPECS)
    assert actual_names == expected_names, (
        "capture must contain the exact screenshot set; "
        f"missing={sorted(expected_names - actual_names)}, "
        f"unexpected={sorted(actual_names - expected_names)}"
    )
    for name, dimensions in REVIEW_SCREENSHOT_SPECS.items():
        _validate_staged_screenshot(staging / name, dimensions)

    assert target.is_dir() and not target.is_symlink(), (
        f"screenshot target must be an existing regular directory: {target}"
    )
    backup = staging / ".previous"
    backup.mkdir()
    previously_present: set[str] = set()
    for name in REVIEW_SCREENSHOT_SPECS:
        destination = target / name
        if destination.exists() or destination.is_symlink():
            assert destination.is_file() and not destination.is_symlink(), (
                f"refusing non-regular screenshot target: {destination}"
            )
            os.link(destination, backup / name)
            previously_present.add(name)

    published: list[str] = []
    try:
        for name in REVIEW_SCREENSHOT_SPECS:
            os.replace(staging / name, target / name)
            published.append(name)
    except BaseException:
        for name in reversed(published):
            destination = target / name
            if name in previously_present:
                os.replace(backup / name, destination)
            else:
                destination.unlink(missing_ok=True)
        raise


@contextmanager
def _screenshot_capture_transaction(target: Path) -> Iterator[Path]:
    assert target.is_dir() and not target.is_symlink(), (
        f"screenshot target must be an existing regular directory: {target}"
    )
    with tempfile.TemporaryDirectory(
        prefix=f".{target.name}-capture-",
        dir=target.parent,
    ) as temporary_directory:
        staging = Path(temporary_directory)
        yield staging
        _publish_staged_screenshots(staging, target)


def test_review_artifacts_exist() -> None:
    for name, dimensions in REVIEW_SCREENSHOT_SPECS.items():
        image = PROJECT_ROOT / "docs" / "screenshots" / name
        assert image.is_file()
        assert image.stat().st_size > 10_000
        data = image.read_bytes()
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        assert tuple(
            int.from_bytes(data[offset : offset + 4], "big")
            for offset in (16, 20)
        ) == dimensions
    assert (PROJECT_ROOT / "docs" / "screenshots" / "README.md").is_file()


def _seed_screenshot_target(target: Path) -> dict[str, bytes]:
    target.mkdir(parents=True)
    originals: dict[str, bytes] = {}
    for index, name in enumerate(REVIEW_SCREENSHOT_SPECS):
        original = f"existing screenshot {index}".encode()
        (target / name).write_bytes(original)
        originals[name] = original
    (target / "README.md").write_text("preserve this manifest\n", encoding="utf-8")
    return originals


def _stage_committed_screenshots(staging: Path, *, omit: str | None = None) -> None:
    source = PROJECT_ROOT / "docs" / "screenshots"
    for name in REVIEW_SCREENSHOT_SPECS:
        if name != omit:
            shutil.copyfile(source / name, staging / name)


def test_screenshot_capture_transaction_rejects_incomplete_set_without_changes(
    tmp_path: Path,
) -> None:
    target = tmp_path / "screenshots"
    originals = _seed_screenshot_target(target)
    missing = "water-review-mobile.png"
    staging_path: Path | None = None

    with pytest.raises(AssertionError, match="exact screenshot set"):
        with _screenshot_capture_transaction(target) as staging:
            staging_path = staging
            _stage_committed_screenshots(staging, omit=missing)

    assert staging_path is not None and not staging_path.exists()
    assert {name: (target / name).read_bytes() for name in originals} == originals
    assert (target / "README.md").read_text(encoding="utf-8") == (
        "preserve this manifest\n"
    )


def test_screenshot_capture_transaction_cleans_interrupted_capture(
    tmp_path: Path,
) -> None:
    target = tmp_path / "screenshots"
    originals = _seed_screenshot_target(target)
    staging_path: Path | None = None

    with pytest.raises(KeyboardInterrupt):
        with _screenshot_capture_transaction(target) as staging:
            staging_path = staging
            first = next(iter(REVIEW_SCREENSHOT_SPECS))
            shutil.copyfile(PROJECT_ROOT / "docs" / "screenshots" / first, staging / first)
            raise KeyboardInterrupt

    assert staging_path is not None and not staging_path.exists()
    assert {name: (target / name).read_bytes() for name in originals} == originals


def test_screenshot_capture_transaction_rolls_back_publication_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "screenshots"
    originals = _seed_screenshot_target(target)
    staging_path: Path | None = None
    real_replace = os.replace
    publication_calls = 0

    def fail_second_publication(source: str | Path, destination: str | Path) -> None:
        nonlocal publication_calls
        if staging_path is not None and Path(source).parent == staging_path:
            publication_calls += 1
            if publication_calls == 2:
                raise OSError("simulated publication interruption")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_second_publication)
    with pytest.raises(OSError, match="simulated publication interruption"):
        with _screenshot_capture_transaction(target) as staging:
            staging_path = staging
            _stage_committed_screenshots(staging)

    assert staging_path is not None and not staging_path.exists()
    assert {name: (target / name).read_bytes() for name in originals} == originals


def test_screenshot_capture_transaction_publishes_complete_valid_set(
    tmp_path: Path,
) -> None:
    target = tmp_path / "screenshots"
    _seed_screenshot_target(target)
    staging_path: Path | None = None

    with _screenshot_capture_transaction(target) as staging:
        staging_path = staging
        _stage_committed_screenshots(staging)

    assert staging_path is not None and not staging_path.exists()
    for name in REVIEW_SCREENSHOT_SPECS:
        assert (target / name).read_bytes() == (
            PROJECT_ROOT / "docs" / "screenshots" / name
        ).read_bytes()
    assert (target / "README.md").read_text(encoding="utf-8") == (
        "preserve this manifest\n"
    )


def test_public_sample_fetcher_uses_official_hash_pinned_sources() -> None:
    fetcher = PROJECT_ROOT / "scripts" / "fetch-public-samples.sh"
    source = fetcher.read_text(encoding="utf-8")

    assert "set -euo pipefail" in source
    assert 'tmp_directory="$repository_root/tmp"' in source
    assert 'destination_directory="$tmp_directory/public-samples"' in source
    assert "cd -P" in source
    assert "pwd -P" in source
    assert "stat -f '%d:%i'" in source
    assert "stat -c '%d:%i'" in source
    assert "sha256sum" in source
    assert "shasum" in source
    assert '[[ -e "$destination" || -L "$destination" ]]' in source
    assert 'ln "$temporary_file" "$destination"' in source
    expected = {
        "duke-electricity.pdf": (
            "https://www.duke-energy.com/-/media/pdfs/bill-examples/"
            "260482-bill-tutorial-handout-res-dei.pdf",
            "b131c36a215762796e72f3d20986fbea7e64e2dd611081d8936f8442102c3e9a",
        ),
        "centerpoint-gas.pdf": (
            "https://www.centerpointenergy.com/en-us/CustomerService/Documents/"
            "bill-guides/240312-20-EIP-IN%20Gas-bill-guide.pdf",
            "c0b7d9b0252226078b39d6760308506c28b388729906d3ac54db950b9f819262",
        ),
        "bloomington-water.pdf": (
            "https://bloomington.in.gov/sites/default/files/2026-02/"
            "Understanding%20Your%20Water%20Bill%202026%20Accessible.pdf",
            "a414c296e3dd71a08aa459bb1a7c38fcdeab0c90aa0bb05f7c4e39ae9d70b79c",
        ),
    }
    for filename, (url, digest) in expected.items():
        assert filename in source
        assert url in source
        assert digest in source


def test_public_sample_fetcher_refuses_to_replace_mismatched_existing_file(
    tmp_path: Path,
) -> None:
    isolated_root = tmp_path / "checkout"
    isolated_scripts = isolated_root / "scripts"
    isolated_samples = isolated_root / "tmp" / "public-samples"
    isolated_scripts.mkdir(parents=True)
    isolated_samples.mkdir(parents=True)
    fetcher = isolated_scripts / "fetch-public-samples.sh"
    shutil.copy2(PROJECT_ROOT / "scripts" / fetcher.name, fetcher)
    mismatched = isolated_samples / "duke-electricity.pdf"
    original_bytes = b"not the approved public guide"
    mismatched.write_bytes(original_bytes)

    completed = subprocess.run(
        ["bash", str(fetcher)],
        cwd=isolated_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert mismatched.read_bytes() == original_bytes
    assert "the existing file was not replaced" in completed.stderr
    assert not list(isolated_samples.glob(".download.*"))
    assert sorted(path.name for path in isolated_samples.iterdir()) == [
        "duke-electricity.pdf"
    ]


def test_public_sample_fetcher_refuses_dangling_destination_symlink(
    tmp_path: Path,
) -> None:
    isolated_root = tmp_path / "checkout"
    isolated_scripts = isolated_root / "scripts"
    isolated_samples = isolated_root / "tmp" / "public-samples"
    fake_bin = isolated_root / "fake-bin"
    isolated_scripts.mkdir(parents=True)
    isolated_samples.mkdir(parents=True)
    fake_bin.mkdir()
    fetcher = isolated_scripts / "fetch-public-samples.sh"
    shutil.copy2(PROJECT_ROOT / "scripts" / fetcher.name, fetcher)
    dangling = isolated_samples / "duke-electricity.pdf"
    dangling.symlink_to("missing-target.pdf")
    download_marker = isolated_root / "download-attempted"
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        f"#!/usr/bin/env bash\ntouch {shlex.quote(str(download_marker))}\nexit 99\n",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)

    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
    completed = subprocess.run(
        ["bash", str(fetcher)],
        cwd=isolated_root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert dangling.is_symlink()
    assert os.readlink(dangling) == "missing-target.pdf"
    assert not download_marker.exists()
    assert "refusing non-regular existing path" in completed.stderr
    assert not list(isolated_samples.glob(".download.*"))


def _write_download_guard(fake_bin: Path, marker: Path) -> None:
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        f"#!/usr/bin/env bash\ntouch {shlex.quote(str(marker))}\nexit 99\n",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)


def _run_isolated_fetcher(
    isolated_root: Path,
    fake_bin: Path,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
    return subprocess.run(
        ["bash", str(isolated_root / "scripts" / "fetch-public-samples.sh")],
        cwd=isolated_root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_public_sample_fetcher_rejects_symlinked_tmp_component(
    tmp_path: Path,
) -> None:
    isolated_root = tmp_path / "checkout"
    isolated_scripts = isolated_root / "scripts"
    outside = tmp_path / "outside"
    fake_bin = isolated_root / "fake-bin"
    isolated_scripts.mkdir(parents=True)
    outside.mkdir()
    fake_bin.mkdir()
    shutil.copy2(
        PROJECT_ROOT / "scripts" / "fetch-public-samples.sh",
        isolated_scripts / "fetch-public-samples.sh",
    )
    (isolated_root / "tmp").symlink_to(outside, target_is_directory=True)
    download_marker = isolated_root / "download-attempted"
    _write_download_guard(fake_bin, download_marker)

    completed = _run_isolated_fetcher(isolated_root, fake_bin)

    assert completed.returncode != 0
    assert not download_marker.exists()
    assert not list(outside.iterdir())
    assert "symlinked path component" in completed.stderr


def test_public_sample_fetcher_rejects_symlinked_public_samples_component(
    tmp_path: Path,
) -> None:
    isolated_root = tmp_path / "checkout"
    isolated_scripts = isolated_root / "scripts"
    isolated_tmp = isolated_root / "tmp"
    outside = tmp_path / "outside"
    fake_bin = isolated_root / "fake-bin"
    isolated_scripts.mkdir(parents=True)
    isolated_tmp.mkdir()
    outside.mkdir()
    fake_bin.mkdir()
    shutil.copy2(
        PROJECT_ROOT / "scripts" / "fetch-public-samples.sh",
        isolated_scripts / "fetch-public-samples.sh",
    )
    (isolated_tmp / "public-samples").symlink_to(
        outside,
        target_is_directory=True,
    )
    download_marker = isolated_root / "download-attempted"
    _write_download_guard(fake_bin, download_marker)

    completed = _run_isolated_fetcher(isolated_root, fake_bin)

    assert completed.returncode != 0
    assert not download_marker.exists()
    assert not list(outside.iterdir())
    assert "symlinked path component" in completed.stderr


def test_public_sample_fetcher_detects_destination_replacement_before_publish(
    tmp_path: Path,
) -> None:
    isolated_root = tmp_path / "checkout"
    isolated_scripts = isolated_root / "scripts"
    isolated_samples = isolated_root / "tmp" / "public-samples"
    moved_samples = isolated_root / "tmp" / "public-samples-before-replacement"
    fake_bin = isolated_root / "fake-bin"
    isolated_scripts.mkdir(parents=True)
    isolated_samples.mkdir(parents=True)
    fake_bin.mkdir()
    shutil.copy2(
        PROJECT_ROOT / "scripts" / "fetch-public-samples.sh",
        isolated_scripts / "fetch-public-samples.sh",
    )
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        "\n".join(
            (
                "#!/usr/bin/env bash",
                'output=""',
                'while [[ "$#" -gt 0 ]]; do',
                '  if [[ "$1" == "--output" ]]; then',
                "    shift",
                '    output="$1"',
                "  fi",
                "  shift",
                "done",
                'printf "approved bytes" > "$output"',
                f"mv {shlex.quote(str(isolated_samples))} "
                f"{shlex.quote(str(moved_samples))}",
                f"mkdir {shlex.quote(str(isolated_samples))}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    fake_sha256sum = fake_bin / "sha256sum"
    fake_sha256sum.write_text(
        "\n".join(
            (
                "#!/usr/bin/env bash",
                'last_argument="${!#}"',
                'printf "%s  %s\\n" '
                '"b131c36a215762796e72f3d20986fbea7e64e2dd611081d8936f8442102c3e9a" '
                '"$last_argument"',
            )
        )
        + "\n",
        encoding="utf-8",
    )
    fake_sha256sum.chmod(0o755)

    completed = _run_isolated_fetcher(isolated_root, fake_bin)

    assert completed.returncode != 0
    assert isolated_samples.is_dir() and not isolated_samples.is_symlink()
    assert not list(isolated_samples.iterdir())
    assert moved_samples.is_dir()
    assert not list(moved_samples.glob(".download.*"))
    assert "destination directory changed" in completed.stderr


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
        "review-warnings",
        "provider-review-requests",
        "add-another-bill",
        "finish-household",
        "discard-current-document",
        "replace-household-bill",
    ):
        assert f'id="{element_id}"' in page
    assert 'id="optional-comparison"' in page
    assert "hidden" in page[page.index('id="optional-comparison"') :][:160]
    warnings_markup = page[page.index('id="review-warnings"') :][:240]
    assert 'role="alert"' in warnings_markup
    assert 'aria-live="polite"' in warnings_markup
    assert 'aria-atomic="true"' in warnings_markup
    assert "hidden" in warnings_markup


def test_household_and_next_steps_have_required_controls() -> None:
    page = create_app().test_client().get("/").get_data(as_text=True)

    for element_id in (
        "add-another-bill",
        "finish-household",
        "household-bills",
        "household-summary",
        "clear-household",
        "provider-requests",
    ):
        assert f'id="{element_id}"' in page

    assert 'id="household-summary"' in page
    summary_markup = page[page.index('id="household-summary"') :][:220]
    assert 'aria-live="polite"' in summary_markup
    assert 'aria-atomic="true"' in summary_markup


def test_bundle_uses_page_memory_only() -> None:
    source = APP_JAVASCRIPT.read_text(encoding="utf-8")

    assert "bundle: []" in source
    assert "currentBundleId: null" in source
    for persistent_api in (
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "document.cookie",
    ):
        assert persistent_api not in source


def test_bundle_summary_has_a_strict_privacy_allowlist_and_exact_decimal_strings() -> None:
    client = create_app().test_client()
    documents = [
        _sample_document(client, kind)
        for kind in ("synthetic", "centerpoint", "bloomington")
    ]
    centerpoint = documents[1]
    centerpoint["extraction"]["customer_identity"] = {
        "name": "PRIVATE CUSTOMER",
        "account_number": "PRIVATE ACCOUNT 991",
        "service_address": "PRIVATE ADDRESS",
    }
    centerpoint["extraction"]["sections"][0]["meter"] = {
        "meter_id": "PRIVATE METER 88"
    }
    centerpoint["extraction"]["private_pdf_blob"] = "blob:private-source"
    centerpoint["audit"]["private_audit_note"] = "PRIVATE AUDIT NOTE"
    centerpoint["audit"]["review_requests"][0].update(
        {
            "evidence": ["PRIVATE REQUEST EVIDENCE"],
            "citations": ["PRIVATE REQUEST CITATION"],
            "account_number": "PRIVATE REQUEST ACCOUNT",
        }
    )

    result = _exercise_household_state_contract(documents)
    summary_keys = {
        "id",
        "providers",
        "serviceTypes",
        "periodStart",
        "periodEnd",
        "period",
        "usageSummaries",
        "amountDue",
        "currency",
        "verificationLevel",
        "discrepancyTotal",
        "issueCount",
        "reviewRequests",
    }
    request_keys = {"provider", "subject", "body"}
    usage_keys = {"serviceType", "value", "unit"}

    assert result["summarySourceIsolated"] is True
    for summary in result["summaries"]:
        assert set(summary) == summary_keys
        assert isinstance(summary["amountDue"], str)
        assert isinstance(summary["discrepancyTotal"], str)
        assert all(set(usage) == usage_keys for usage in summary["usageSummaries"])
        assert all(
            isinstance(usage["value"], str)
            for usage in summary["usageSummaries"]
        )
        assert all(set(request) == request_keys for request in summary["reviewRequests"])

    synthetic, centerpoint_summary, _bloomington = result["summaries"]
    assert synthetic["issueCount"] == 1
    assert centerpoint_summary["usageSummaries"] == [
        {"serviceType": "natural_gas", "value": "112.277", "unit": "therm"}
    ]
    serialized = json.dumps(centerpoint_summary, sort_keys=True)
    for forbidden in (
        "PRIVATE CUSTOMER",
        "PRIVATE ACCOUNT 991",
        "PRIVATE ADDRESS",
        "PRIVATE METER 88",
        "blob:private-source",
        "PRIVATE AUDIT NOTE",
        "PRIVATE REQUEST EVIDENCE",
        "PRIVATE REQUEST CITATION",
        "PRIVATE REQUEST ACCOUNT",
        "grounded_audit_line_ids",
        "requires_user_review",
        "original_value",
        "evidence",
        "citations",
    ):
        assert forbidden not in serialized


def test_household_sequence_deduplicates_combines_safely_and_clears() -> None:
    client = create_app().test_client()
    documents = [
        _sample_document(client, kind)
        for kind in ("duke", "centerpoint", "bloomington")
    ]

    result = _exercise_household_state_contract(documents)

    assert result["afterRepeatedFinish"]["bundleLength"] == 1
    assert result["afterRepeatedFinish"]["currentBundleId"] is None
    assert result["afterRepeatedFinish"]["replacementBundleId"] is not None
    assert result["afterRepeatedFinish"]["replacementArmed"] is False
    assert result["afterRepeatedFinish"]["extraction"] is None
    assert result["afterRepeatedFinish"]["audit"] is None
    assert result["afterRepeatedFinish"]["previewUrl"] is None
    assert result["afterAddFollowingFinish"] == {
        "bundleLength": 1,
        "currentBundleId": None,
        "replacementBundleId": None,
        "replacementArmed": False,
        "extraction": None,
        "audit": None,
        "uploadVisible": True,
    }
    assert len(result["bundle"]) == 3
    assert len({summary["id"] for summary in result["bundle"]}) == 3
    assert result["householdHtml"].count("household-bill-card") == 3
    for provider in (
        "Duke Energy",
        "CenterPoint Energy",
        "City of Bloomington Utilities",
    ):
        assert provider in result["householdHtml"]
    assert "112.277 therm" in result["householdHtml"]
    assert "$132.19" in result["householdHtml"]
    assert "Combined amount shown" not in result["householdSummaryHtml"]
    assert not {
        "savings",
        "overcharge",
    } & set(result["householdHtml"].lower().split())

    assert result["requestCount"] == 3
    assert result["requestsHtml"].count("provider-request-card") == 3
    for provider in (
        "Duke Energy Indiana, LLC",
        "Southern Indiana Gas and Electric Company d/b/a CenterPoint Energy Indiana South",
        "City of Bloomington Utilities",
    ):
        assert provider in result["requestsHtml"]
    assert result["editedRequestBody"] == "Page-memory edit only <draft>"
    assert "Page-memory edit only &lt;draft&gt;" in result["editedRequestsHtml"]
    assert result["editedRequestsHtml"].count("provider-request-card") == 3

    assert "Combined amount shown" in result["compatibleSummaryHtml"]
    assert "$60.06" in result["compatibleSummaryHtml"]
    assert "$0.30" in result["exactAdditionSummaryHtml"]
    assert "$0.01" in result["noEarlyRoundingSummaryHtml"]
    assert "Combined amount shown" not in result["numberAmountSummaryHtml"]
    assert "Not combined" in result["numberAmountSummaryHtml"]
    assert "—" in result["numberAmountBillsHtml"]
    for incompatible in (
        result["mixedCurrencySummaryHtml"],
        result["missingPeriodSummaryHtml"],
        result["nonoverlapSummaryHtml"],
        result["missingAmountSummaryHtml"],
        result["missingCurrencySummaryHtml"],
    ):
        assert "Combined amount shown" not in incompatible

    assert result["revokedUrls"] == [
        "blob:duke",
        "blob:centerpoint",
        "blob:bloomington",
    ]
    assert result["uploadResetCount"] == 5
    assert result["afterClear"] == {
        "bundleLength": 0,
        "currentBundleId": None,
        "replacementBundleId": None,
        "replacementArmed": False,
        "extraction": None,
        "audit": None,
        "previewUrl": None,
        "uploadVisible": True,
    }
    assert set(result["clearedMarkup"].values()) == {""}


def test_reaudit_replaces_completed_summary_with_stable_identity_and_order() -> None:
    client = create_app().test_client()
    extraction = client.get("/api/sample/duke").get_json()["extraction"]
    first_audit = client.post("/api/audit", json=extraction).get_json()["audit"]
    extraction["private_account_marker"] = "PRIVATE RAW ACCOUNT 774"
    first_audit["private_evidence_marker"] = "PRIVATE RAW EVIDENCE"
    second_audit = json.loads(json.dumps(first_audit))
    second_audit.update(
        {
            "verification_level": "evidence_extracted",
            "verdict": "possible_discrepancy",
            "headline": "Corrected facts require provider review",
            "discrepancy_total": "7.250000000000000001",
            "review_requests": [
                {
                    "provider": "Corrected Duke review desk",
                    "subject": "Corrected bill evidence",
                    "body": "Newly sanitized corrected request",
                }
            ],
        }
    )
    corrected_line = json.loads(json.dumps(first_audit["lines"][0]))
    corrected_line.update(
        {
            "id": "corrected-root-line",
            "root_cause_id": "corrected-root",
            "status": "discrepancy",
            "delta": "7.250000000000000001",
            "label": "Corrected amount review",
        }
    )
    second_audit["lines"] = [corrected_line]

    result = _exercise_async_state_contract(
        "finish_reaudit_refinish",
        extraction_a=extraction,
        extraction_b=json.loads(json.dumps(extraction)),
        audit_a=first_audit,
        auditB=second_audit,
        mode="duke",
        nextUsage="1234.500000000000000001",
        nextAmount="100.005",
        abortAware=False,
    )

    after_finish = result["afterFirstFinish"]
    assert len(result["bundle"]) == 1
    assert result["first"]["id"] == result["replaced"]["id"]
    assert after_finish["state"]["extraction"] is None
    assert after_finish["state"]["audit"] is None
    assert after_finish["state"]["previewUrl"] is None
    assert after_finish["state"]["currentBundleId"] is None
    assert after_finish["state"]["replacementBundleId"] == result["first"]["id"]
    assert after_finish["state"]["replacementArmed"] is False
    assert after_finish["revokedUrls"] == ["blob:completed-upload"]
    assert after_finish["reviewHtml"] == ""
    assert after_finish["warningsHtml"] == ""
    assert after_finish["verificationHtml"] == ""
    assert after_finish["auditHtml"] == ""
    assert after_finish["previewSrc"] == ""
    assert after_finish["uploadResetCount"] == 1
    retained_state = json.dumps(after_finish["state"], sort_keys=True)
    assert "PRIVATE RAW ACCOUNT 774" not in retained_state
    assert "PRIVATE RAW EVIDENCE" not in retained_state
    assert result["idempotent"]["reviewRequests"][0]["body"] == (
        "Page-memory draft"
    )
    assert result["armedReplacement"]["replacementBundleId"] == result["first"][
        "id"
    ]
    assert result["armedReplacement"]["replacementArmed"] is True
    assert result["armedReplacement"]["extraction"] is None
    assert result["afterExplicitReload"]["currentBundleId"] == result["first"][
        "id"
    ]
    assert result["afterExplicitReload"]["replacementArmed"] is True
    assert result["replaced"] == result["repeated"]
    assert result["replaced"]["usageSummaries"] == [
        {
            "serviceType": "electricity",
            "value": "1234.500000000000000001",
            "unit": "kWh",
        }
    ]
    assert result["replaced"]["amountDue"] == "100.005"
    assert result["replaced"]["verificationLevel"] == "evidence_extracted"
    assert result["replaced"]["discrepancyTotal"] == "7.250000000000000001"
    assert result["replaced"]["issueCount"] == 1
    assert result["replaced"]["reviewRequests"] == [
        {
            "provider": "Corrected Duke review desk",
            "subject": "Corrected bill evidence",
            "body": "Newly sanitized corrected request",
        }
    ]
    assert result["afterReplacementFinish"]["extraction"] is None
    assert result["afterReplacementFinish"]["audit"] is None
    assert result["afterReplacementFinish"]["previewUrl"] is None
    assert result["afterReplacementFinish"]["currentBundleId"] is None
    assert result["afterReplacementFinish"]["replacementBundleId"] == result[
        "first"
    ]["id"]
    assert result["afterReplacementFinish"]["replacementArmed"] is False
    assert result["afterReplacementAddAnother"]["currentBundleId"] is None
    assert result["afterReplacementAddAnother"]["replacementBundleId"] is None
    assert result["afterReplacementAddAnother"]["replacementArmed"] is False
    assert result["afterReplacementAddAnother"]["extraction"] is None
    assert result["afterReplacementAddAnother"]["audit"] is None
    assert result["revokedUrls"] == ["blob:completed-upload"]
    assert "$100.01" in result["householdHtml"]
    assert "1,234.500000000000000001 kWh" in result["householdHtml"]
    assert "Newly sanitized corrected request" in result["requestsHtml"]
    assert "Page-memory draft" not in result["requestsHtml"]


def test_household_and_request_values_are_inert_markup() -> None:
    client = create_app().test_client()
    documents = [
        _sample_document(client, kind)
        for kind in ("duke", "centerpoint", "bloomington")
    ]
    marker = '<img id="household-hostile" src=x onerror=alert(1)>'
    documents[0]["extraction"]["sections"][0]["provider"]["value"] = marker
    documents[0]["extraction"]["sections"][0]["service_type"] = marker
    documents[0]["audit"]["verification_level"] = marker
    documents[0]["audit"]["review_requests"][0].update(
        {"provider": marker, "subject": marker, "body": marker}
    )

    result = _exercise_household_state_contract(documents)
    fragments = result["householdHtml"] + result["requestsHtml"]
    probe = _MarkupProbe()
    probe.feed(fragments)

    assert "img" not in probe.tags
    assert not any(name.lower().startswith("on") for name, _value in probe.attributes)
    assert marker in "".join(probe.text) or marker in {
        value for name, value in probe.attributes if name == "value"
    }


def test_later_bill_failure_keeps_completed_household_cards() -> None:
    client = create_app().test_client()
    duke = _sample_document(client, "duke")

    result = _exercise_async_state_contract(
        "bundle_then_sample_error",
        extraction_a=duke["extraction"],
        audit_a=duke["audit"],
        mode="duke",
        abortAware=False,
    )

    assert len(result["bundle"]) == 1
    assert "Duke Energy" in result["householdHtml"]
    assert result["currentBundleId"] is None
    assert result["extraction"] is None
    assert result["audit"] is None
    assert result["message"] == "Fixture temporarily unavailable"
    assert result["activeElement"] == "global-message"
    assert result["uploadHidden"] is False


def test_later_upload_failure_revokes_preview_and_keeps_completed_bundle() -> None:
    client = create_app().test_client()
    duke = _sample_document(client, "duke")

    result = _exercise_async_state_contract(
        "bundle_then_upload_error",
        extraction_a=duke["extraction"],
        audit_a=duke["audit"],
        mode="duke",
        abortAware=False,
    )

    assert len(result["bundle"]) == 1
    assert "Duke Energy" in result["householdHtml"]
    assert result["createdUrls"] == ["blob:test-1"]
    assert result["revokedUrls"] == ["blob:test-1"]
    assert result["previewUrl"] is None
    assert result["currentBundleId"] is None
    assert result["extraction"] is None
    assert result["audit"] is None
    assert result["fileCount"] == 0
    assert result["message"] == "Later rendered page reader failed"
    assert result["activeElement"] == "bill-file"
    assert result["uploadHidden"] is False


def test_mobile_contract_removes_horizontal_audit_and_household_scroll() -> None:
    stylesheet = (PROJECT_ROOT / "wattproof" / "static" / "app.css").read_text(
        encoding="utf-8"
    )
    mobile = stylesheet[stylesheet.index("@media (max-width: 640px)") :]

    assert ".table-scroll { overflow-x: visible; }" in mobile
    assert ".household-bills" in mobile
    assert ".provider-request-card" in mobile
    assert "grid-template-columns: 1fr" in mobile


def test_global_error_alert_is_keyboard_focusable() -> None:
    page = create_app().test_client().get("/").get_data(as_text=True)
    alert_start = page.index('id="global-message"')
    alert_markup = page[alert_start : alert_start + 220]

    assert 'role="alert"' in alert_markup
    assert 'aria-live="assertive"' in alert_markup
    assert 'aria-atomic="true"' in alert_markup
    assert 'tabindex="-1"' in alert_markup


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


def test_browser_exact_decimal_formatting_never_uses_binary_numbers() -> None:
    client = create_app().test_client()
    extraction = client.get("/api/sample/duke").get_json()["extraction"]
    audit = client.post("/api/audit", json=extraction).get_json()["audit"]

    rendered = _exercise_javascript_contract(extraction, audit, mode="duke")
    numeric = rendered["numericFormatting"]

    assert numeric["moneyHalfUp"] == "$100.01"
    assert numeric["moneyNegativeHalfUp"] == "−$100.01"
    assert numeric["moneyNegativeZero"] == "$0.00"
    assert numeric["moneyPositiveZero"] == "$0.00"
    assert numeric["measurement"] == "1,234,567.123456789012345678"
    assert numeric["scientificMeasurement"] == "0.000000000123456789"
    assert numeric["scientificTrailingZeros"] == "123.00"
    assert numeric["minimumExponent"] == "0.000000000000000001"
    assert numeric["leadingZeroExponent"] == "0.000000000000000001"
    assert numeric["maximumMagnitude"] == "999,999,999,999"
    assert numeric["signedMeasurementZero"] == "0.000"
    assert numeric["safeIntegerMoney"] == "$31.00"
    assert numeric["safeIntegerMeasurement"] == "31"
    assert "<summary>Page 1 · 15% confidence</summary>" in numeric[
        "confidenceHtml"
    ]
    for unavailable in (
        "numberMoney",
        "numberMeasurement",
        "outOfRangeInteger",
        "oversizedMeasurement",
        "outOfRangeExponent",
        "exponentBelowDomain",
        "magnitudeAboveDomain",
        "tooManyDigits",
        "surroundingWhitespace",
    ):
        assert numeric[unavailable] == "—"
    assert "confidence unavailable" in numeric["numberConfidenceHtml"]


def test_high_precision_review_and_audit_values_render_exactly() -> None:
    client = create_app().test_client()
    extraction = client.get("/api/sample/duke").get_json()["extraction"]
    extraction["sections"][0]["usage"]["value"] = "1002.123456789012345678"
    extraction["sections"][0]["usage"]["evidence"]["confidence"] = "0.145"
    extraction["amount_due"]["value"] = "100.005"
    response = client.post("/api/audit", json=extraction)
    assert response.status_code == 200
    audit = response.get_json()["audit"]

    rendered = _exercise_javascript_contract(extraction, audit, mode="duke")

    assert 'value="1002.123456789012345678"' in rendered["reviewHtml"]
    assert 'inputmode="decimal" type="text"' in rendered["reviewHtml"]
    assert "15% confidence" in rendered["reviewHtml"]
    assert "1,002.123456789012345678 kWh" in rendered["servicesHtml"]
    assert "1,002.123456789012345678 kWh" in rendered["auditHtml"]
    assert "$100.01" in rendered["auditHtml"]
    assert "−$79.40" in rendered["auditHtml"]


def test_safe_integer_bill_facts_render_as_exact_editable_values() -> None:
    client = create_app().test_client()
    legacy = client.get("/api/sample/authentic").get_json()["extraction"]
    legacy_audit = client.post("/api/audit", json=legacy).get_json()["audit"]
    legacy_rendered = _exercise_javascript_contract(
        legacy,
        legacy_audit,
        mode="authentic",
    )
    legacy_marker = 'id="fact-billing_days"'
    legacy_field = legacy_rendered["reviewHtml"][
        legacy_rendered["reviewHtml"].index(legacy_marker) :
    ][:420]
    assert 'data-exact-number="true"' in legacy_field
    assert 'inputmode="decimal"' in legacy_field
    assert 'type="text"' in legacy_field
    assert 'value="31"' in legacy_field
    assert "Exact numeric spelling unavailable" not in legacy_field

    utility = client.get("/api/sample/duke").get_json()["extraction"]
    utility["sections"][0]["supplemental_facts"] = [
        {
            "id": "billing_days",
            "fact": {
                "value": 31,
                "unit": "days",
                "status": "printed",
                "evidence": {
                    "page": 1,
                    "text": "Billing period 31 days",
                    "confidence": "1",
                    "provenance": "rendered_page",
                },
            },
        }
    ]
    utility_audit = client.post(
        "/api/audit",
        json=client.get("/api/sample/duke").get_json()["extraction"],
    ).get_json()["audit"]
    utility_rendered = _exercise_javascript_contract(
        utility,
        utility_audit,
        mode="duke",
    )
    utility_marker = 'id="fact-sections-0-supplemental_facts-0-fact"'
    utility_field = utility_rendered["reviewHtml"][
        utility_rendered["reviewHtml"].index(utility_marker) :
    ][:420]
    assert 'data-exact-number="true"' in utility_field
    assert 'inputmode="decimal"' in utility_field
    assert 'type="text"' in utility_field
    assert 'value="31"' in utility_field
    assert "Exact numeric spelling unavailable" not in utility_field


def test_internal_reconciliation_copy_keeps_unverified_categories_explicit() -> None:
    client = create_app().test_client()
    extraction = client.get("/api/sample/bloomington").get_json()["extraction"]
    audit = client.post("/api/audit", json=extraction).get_json()["audit"]

    assert any(
        line["status"] == "cannot_verify" and "tax" in line["label"].lower()
        for line in audit["lines"]
    )
    rendered = _exercise_javascript_contract(
        extraction,
        audit,
        mode="bloomington",
    )

    assert (
        "Only deterministic relationships with printed operands were checked. "
        "Unsupported lines remain explicitly unverified; this does not claim "
        "tariff truth."
    ) in rendered["verdictHtml"]
    assert "Printed meter, unit, rate, tax, subtotal, and total math was checked" not in (
        rendered["verdictHtml"]
    )


def test_review_warnings_are_visible_accessible_and_inert_before_audit() -> None:
    client = create_app().test_client()
    extraction = client.get("/api/sample/centerpoint").get_json()["extraction"]
    audit = client.post("/api/audit", json=extraction).get_json()["audit"]
    hostile = '<img id="warning-hostile" src=x onerror=alert(1)>'
    extraction["warnings"] = [
        "Rendered and native text conflict; use the rendered page.",
        hostile,
    ]

    rendered = _exercise_javascript_contract(
        extraction,
        audit,
        mode="centerpoint",
    )
    probe = _MarkupProbe()
    probe.feed(rendered["warningsHtml"])

    assert rendered["warningsHidden"] is False
    assert "Review before continuing" in rendered["warningsHtml"]
    assert "Rendered and native text conflict" in rendered["warningsHtml"]
    assert "img" not in probe.tags
    assert hostile in "".join(probe.text)
    assert not any(name.startswith("on") for name, _value in probe.attributes)


def test_priority_findings_hide_dependent_symptom_when_root_is_present() -> None:
    client = create_app().test_client()
    extraction = client.get("/api/sample/duke").get_json()["extraction"]
    audit = client.post("/api/audit", json=extraction).get_json()["audit"]
    root = json.loads(json.dumps(audit["lines"][0]))
    root.update(
        {
            "id": "root-finding",
            "label": "Root printed mismatch",
            "status": "discrepancy",
            "delta": "4.25",
        }
    )
    root.pop("root_cause_id", None)
    dependent = json.loads(json.dumps(root))
    dependent.update(
        {
            "id": "dependent-symptom",
            "root_cause_id": "root-finding",
            "label": "Downstream total symptom",
        }
    )
    audit["lines"] = [root, dependent]
    audit["verdict"] = "possible_discrepancy"

    rendered = _exercise_javascript_contract(extraction, audit, mode="duke")

    assert "Root printed mismatch" in rendered["priorityHtml"]
    assert "Downstream total symptom" not in rendered["priorityHtml"]
    assert "Root printed mismatch" in rendered["auditHtml"]
    assert "Downstream total symptom" in rendered["auditHtml"]
    assert rendered["summaryIssueCount"] == 1
    for request in audit["review_requests"]:
        assert escape(request["subject"]) in rendered["requestsHtml"]


def test_dynamic_review_and_audit_values_are_inert_markup() -> None:
    client = create_app().test_client()
    extraction = client.get("/api/sample/authentic").get_json()["extraction"]
    audit = client.post("/api/audit", json=extraction).get_json()["audit"]
    hostile = {
        "provider": "<img id=hostile-provider src=x onerror=alert(1)>",
        "unit": "<svg id=hostile-unit onload=alert(2)>",
        "currency": "<iframe id=hostile-currency srcdoc=bad>",
        "label": "<script id=hostile-label>alert(3)</script>",
        "evidence": "<img id=hostile-evidence src=x onerror=alert(4)>",
        "headline": "<math id=hostile-headline href=javascript:alert(5)>",
        "citation": "<svg id=hostile-citation onload=alert(6)>",
        "request": "<textarea id=hostile-request autofocus onfocus=alert(7)>",
    }

    extraction["delivery_provider"]["value"] = hostile["provider"]
    extraction["total_usage"]["unit"] = hostile["unit"]
    extraction["delivery_subtotal"]["unit"] = hostile["currency"]
    audit["headline"] = hostile["headline"]
    audit["currency"] = hostile["currency"]
    line = audit["lines"][0]
    line["status"] = "discrepancy"
    line["label"] = hostile["label"]
    line["unit"] = hostile["unit"]
    line["formula"] = hostile["label"]
    line["limitation"] = hostile["headline"]
    line["billed_amount"] = hostile["evidence"]
    line["expected_amount"] = 0.1 + 0.2
    line["delta"] = "1e1000000"
    line["evidence"] = [
        {
            "page": hostile["unit"],
            "text": hostile["evidence"],
            "confidence": "1.0",
            "provenance": "rendered_page",
        }
    ]
    line["citations"] = [
        {
            "label": hostile["citation"],
            "source_url": "javascript:alert(8)",
        },
        {
            "label": hostile["evidence"],
            "source_url": "data:text/html,<svg onload=alert(9)>",
        },
    ]
    audit["comparison"] = {
        "status": "insufficient_data",
        "headline": hostile["headline"],
        "explanation": hostile["evidence"],
        "required_data": [hostile["unit"]],
    }
    audit["review_requests"] = [
        {
            "provider": hostile["provider"],
            "subject": hostile["request"],
            "body": hostile["evidence"],
            "grounded_audit_line_ids": [line["id"]],
            "requires_user_review": True,
        }
    ]

    rendered = _exercise_javascript_contract(extraction, audit, mode="authentic")
    fragments = "".join(
        rendered[key]
        for key in (
            "reviewHtml",
            "verificationHtml",
            "verdictHtml",
            "servicesHtml",
            "priorityHtml",
            "auditHtml",
            "comparisonHtml",
            "requestsHtml",
        )
    )
    probe = _MarkupProbe()
    probe.feed(fragments)

    assert not ({"img", "svg", "script", "iframe", "math"} & set(probe.tags))
    assert not any(name.lower().startswith("on") for name, _value in probe.attributes)
    assert not any(
        name.lower() == "href"
        and value is not None
        and value.lower().startswith(("javascript:", "data:"))
        for name, value in probe.attributes
    )
    assert rendered["auditHtml"].count("—") >= 3
    rendered_text = "".join(probe.text)
    for marker in hostile.values():
        assert marker in rendered_text or marker in {
            value for name, value in probe.attributes if name == "value"
        }


@pytest.mark.parametrize("abort_aware", [False, True])
def test_slow_sample_cannot_overwrite_later_sample(abort_aware: bool) -> None:
    client = create_app().test_client()
    authentic = client.get("/api/sample/authentic").get_json()["extraction"]
    duke = client.get("/api/sample/duke").get_json()["extraction"]

    result = _exercise_async_state_contract(
        "sample_race",
        extraction_a=authentic,
        extraction_b=duke,
        abortAware=abort_aware,
    )

    assert result["extraction"]["schema_version"] == "2.0"
    assert "Duke Energy" in result["reviewHtml"]
    assert "Pacific Gas and Electric" not in result["reviewHtml"]
    assert result["audit"] is None
    assert result["message"] == ""
    assert result["firstDisabled"] is False
    assert result["secondDisabled"] is False


def test_slow_upload_cannot_overwrite_a_later_sample() -> None:
    client = create_app().test_client()
    authentic = client.get("/api/sample/authentic").get_json()["extraction"]
    duke = client.get("/api/sample/duke").get_json()["extraction"]

    result = _exercise_async_state_contract(
        "upload_then_sample",
        extraction_a=authentic,
        extraction_b=duke,
        abortAware=False,
    )

    assert result["extraction"]["schema_version"] == "2.0"
    assert "Duke Energy" in result["reviewHtml"]
    assert "Pacific Gas and Electric" not in result["reviewHtml"]
    assert result["audit"] is None
    assert result["message"] == ""
    assert result["uploadDisabled"] is False
    assert result["sampleDisabled"] is False
    assert result["createdUrls"] == ["blob:test-1"]
    assert result["revokedUrls"] == ["blob:test-1"]


def test_failed_upload_revokes_preview_and_resets_actionable_document_state() -> None:
    result = _exercise_async_state_contract(
        "upload_failure",
        abortAware=False,
    )

    before = result["beforeSecondClear"]
    assert result["createdUrls"] == ["blob:test-1"]
    assert before["revokedUrls"] == ["blob:test-1"]
    assert result["revokedUrls"] == ["blob:test-1"]
    assert before["state"]["previewUrl"] is None
    assert before["state"]["extraction"] is None
    assert before["state"]["audit"] is None
    assert before["state"]["bundle"] == []
    assert before["state"]["currentBundleId"] is None
    assert before["fileCount"] == 0
    assert before["uploadResetCount"] == 1
    assert result["resetAfterSecondClear"] == 2
    assert before["reviewHtml"] == ""
    assert before["auditHtml"] == ""
    assert before["previewSrc"] == ""
    assert before["previewHidden"] is True
    assert before["uploadHidden"] is False
    assert before["message"] == "Rendered page reader failed"
    assert before["activeElement"] == "bill-file"
    assert before["fileInvalid"] == "true"


def test_review_start_over_discards_upload_and_revokes_preview_once() -> None:
    client = create_app().test_client()
    duke = client.get("/api/sample/duke").get_json()["extraction"]

    result = _exercise_async_state_contract(
        "uploaded_review_discard",
        extraction_a=duke,
        abortAware=False,
    )

    assert result["previewBeforeDiscard"] == "blob:test-1"
    assert result["createdUrls"] == ["blob:test-1"]
    assert result["revokedUrls"] == ["blob:test-1"]
    assert result["previewUrl"] is None
    assert result["extraction"] is None
    assert result["audit"] is None
    assert result["currentBundleId"] is None
    assert result["fileCount"] == 0
    assert result["uploadResetCount"] == 1
    assert result["reviewHtml"] == ""
    assert result["previewSrc"] == ""
    assert result["previewHidden"] is True
    assert result["uploadHidden"] is False
    assert result["activeElement"] == "upload-title"


def test_public_sample_replaces_uploaded_preview_without_retaining_blob() -> None:
    client = create_app().test_client()
    authentic = client.get("/api/sample/authentic").get_json()["extraction"]
    duke = client.get("/api/sample/duke").get_json()["extraction"]

    result = _exercise_async_state_contract(
        "uploaded_review_then_sample",
        extraction_a=authentic,
        extraction_b=duke,
        abortAware=False,
    )

    assert result["uploadedPreview"] == "blob:test-1"
    assert result["createdUrls"] == ["blob:test-1"]
    assert result["revokedUrls"] == ["blob:test-1"]
    assert result["previewUrl"] is None
    assert result["extraction"]["schema_version"] == "2.0"
    assert result["audit"] is None
    assert result["currentBundleId"] is None
    assert result["fileCount"] == 0
    assert result["uploadResetCount"] == 1
    assert "Duke Energy" in result["reviewHtml"]


def test_pending_audit_cannot_render_beside_a_new_bill() -> None:
    client = create_app().test_client()
    authentic = client.get("/api/sample/authentic").get_json()["extraction"]
    authentic_audit = client.post("/api/audit", json=authentic).get_json()["audit"]
    duke = client.get("/api/sample/duke").get_json()["extraction"]

    result = _exercise_async_state_contract(
        "audit_then_sample",
        extraction_a=authentic,
        extraction_b=duke,
        audit_a=authentic_audit,
        mode="authentic",
        abortAware=False,
    )

    assert result["extraction"]["schema_version"] == "2.0"
    assert "Duke Energy" in result["reviewHtml"]
    assert result["audit"] is None
    assert result["verifyHidden"] is True
    assert result["message"] == ""


@pytest.mark.parametrize("navigation", ["back", "restart"])
def test_navigation_invalidates_a_pending_audit(navigation: str) -> None:
    client = create_app().test_client()
    authentic = client.get("/api/sample/authentic").get_json()["extraction"]
    authentic_audit = client.post("/api/audit", json=authentic).get_json()["audit"]

    result = _exercise_async_state_contract(
        "audit_then_navigation",
        extraction_a=authentic,
        audit_a=authentic_audit,
        mode="authentic",
        navigation=navigation,
        abortAware=False,
    )

    assert result["audit"] is None
    assert result["verifyHidden"] is True
    assert result["message"] == ""
    if navigation == "back":
        assert result["uploadHidden"] is False
        assert result["reloadCount"] == 0
    else:
        assert result["reloadCount"] == 1


@pytest.mark.parametrize(
    ("kind", "mode", "fact_path", "next_value"),
    [
        ("authentic", "authentic", "total_usage", "328.119"),
        ("duke", "duke", "sections.0.usage", "1002"),
    ],
)
@pytest.mark.parametrize("outcome", ["success", "error"])
def test_correction_provenance_survives_back_and_validation_errors(
    kind: str,
    mode: str,
    fact_path: str,
    next_value: str,
    outcome: str,
) -> None:
    client = create_app().test_client()
    extraction = client.get(f"/api/sample/{kind}").get_json()["extraction"]
    audit = client.post("/api/audit", json=extraction).get_json()["audit"]
    fact = extraction
    for part in fact_path.split("."):
        fact = fact[int(part)] if part.isdigit() else fact[part]
    original_value = str(fact["value"])
    evidence_text = (fact.get("evidence") or {"text": fact["source_text"]})["text"]

    result = _exercise_async_state_contract(
        "correction",
        extraction_a=extraction,
        audit_a=audit,
        mode=mode,
        factPath=fact_path,
        nextValue=next_value,
        outcome=outcome,
        abortAware=False,
    )

    assert result["fact"] == {
        **fact,
        "value": next_value,
        "status": "user_corrected",
        "original_value": original_value,
    }
    assert "user corrected" in result["reviewHtml"]
    assert f"Originally {original_value}" in result["reviewHtml"]
    assert f'value="{next_value}"' in result["reviewHtml"]
    assert escape(evidence_text) in result["reviewHtml"]
    assert result["reviewHidden"] is False
    if outcome == "success":
        assert result["activeElement"] == "review-title"
        assert result["message"] == ""
    else:
        assert result["activeElement"] == "corrected-input"
        assert result["inputInvalid"] == "true"
        assert result["inputDescribedBy"] == "global-message"
        assert fact_path in result["message"]


def test_general_request_error_focuses_the_alert() -> None:
    result = _exercise_async_state_contract(
        "general_error",
        abortAware=False,
    )

    assert result == {
        "activeElement": "global-message",
        "message": "Reader temporarily unavailable",
        "alertHidden": False,
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

        def run_harness(capture_directory: Path | None) -> dict[str, Any]:
            completed = subprocess.run(
                [node, "-e", REAL_BROWSER_HARNESS],
                input=json.dumps(
                    {
                        "baseUrl": f"http://127.0.0.1:{server.server_port}/",
                        "browser": _find_real_browser_binary(),
                        "captureDirectory": (
                            str(capture_directory) if capture_directory else None
                        ),
                        "debugPort": _unused_local_port(),
                        "noSandbox": hasattr(os, "geteuid")
                        and os.geteuid() == 0,
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

        capture_target_value = os.environ.get("WATTPROOF_SCREENSHOT_DIR")
        if capture_target_value:
            capture_target = Path(capture_target_value)
            if not capture_target.is_absolute():
                capture_target = Path.cwd() / capture_target
            with _screenshot_capture_transaction(capture_target) as staging:
                return run_harness(staging)
        return run_harness(None)
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
        if flow["sample"] == "centerpoint":
            assert flow["review"]["warningHidden"] is False
            assert "Review before continuing" in flow["review"]["warningText"]
            assert "Rendered/native text conflict" in flow["review"]["warningText"]
            assert "<img id=warning-real" in flow["review"]["warningText"]
            assert flow["review"]["warningInjectedElements"] == 0
            assert flow["review"]["warningEventCount"] == 0
        else:
            assert flow["review"]["warningHidden"] is True
        if flow["sample"] in {"authentic", "synthetic"}:
            assert flow["review"]["billingDays"] == {
                "value": "31",
                "exactNumber": "true",
                "unavailable": False,
            }
        else:
            assert flow["review"]["billingDays"] is None

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
        if flow["sample"] == "bloomington":
            assert "Only deterministic relationships with printed operands" in result[
                "verdictText"
            ]
            assert "Unsupported lines remain explicitly unverified" in result[
                "verdictText"
            ]

        requests = flow["requests"]
        assert requests["focus"] == "next-steps-title"
        assert requests["count"] == expected["requests"]
        assert requests["visibleCount"] == expected["requests"]
        assert requests["pageErrors"] == []

    assert flows[0]["requests"]["count"] > 1
    duke_correction = next(
        flow["correction"] for flow in flows if flow["sample"] == "duke"
    )
    assert duke_correction["value"] == "1002"
    assert duke_correction["badge"] == "user corrected"
    assert duke_correction["note"] == "Originally 1001"
    assert "1,001" in duke_correction["evidenceText"]
    assert all(
        flow["result"]["verificationLabel"] != "Tariff verified"
        for flow in flows
        if flow["sample"] not in {"authentic", "synthetic"}
    )

    sequential = evidence["sequentialDesktop"]
    assert sequential["focus"] == "household-title"
    assert sequential["bundleLength"] == 3
    assert sequential["currentBundleId"] is None
    assert sequential["replacementBundleId"]
    assert sequential["replacementArmed"] is False
    assert sequential["extractionCleared"] is True
    assert sequential["auditCleared"] is True
    assert sequential["previewCleared"] is True
    assert sequential["cardCount"] == 3
    assert sequential["uniqueIds"] == 3
    assert sequential["noHorizontalOverflow"] is True
    assert sequential["pageErrors"] == []
    for visible_value in (
        "Duke Energy",
        "CenterPoint Energy",
        "City of Bloomington Utilities",
        "112.277 therm",
        "$132.19",
    ):
        assert visible_value in sequential["text"]
    assert "Combined amount shown" not in sequential["summaryText"]

    replacement = evidence["reauditReplacement"]
    exact_edit = {
        "usage": "5.750000123456789012",
        "amount": "100.005",
        "confidence": "Page 1 · 15% confidence",
    }
    assert evidence["reauditEdited"] == exact_edit
    assert evidence["reauditRerendered"] == exact_edit
    assert evidence["reauditExpected"]["discrepancyType"] == "string"
    assert evidence["reauditExpected"]["amountBilled"] == "100.005"
    assert evidence["reauditExpected"]["amountExpected"] == "51.92"
    assert evidence["reauditExpected"]["amountDelta"] == "48.085"
    assert "$100.01" in evidence["reauditExpected"]["ledgerText"]
    assert "$48.09" in evidence["reauditExpected"]["ledgerText"]
    assert "5.750000123456789012 kgal" in evidence["reauditExpected"][
        "serviceText"
    ]
    assert replacement["bundleLength"] == 3
    assert replacement["ids"] == evidence["bundleIdsBeforeReaudit"]
    assert replacement["summary"]["id"] == evidence["bundleIdsBeforeReaudit"][-1]
    assert replacement["currentBundleId"] is None
    assert replacement["replacementBundleId"] == replacement["summary"]["id"]
    assert replacement["replacementArmed"] is False
    assert replacement["extractionCleared"] is True
    assert replacement["auditCleared"] is True
    assert replacement["previewCleared"] is True
    assert replacement["summary"]["usageSummaries"] == [
        {
            "serviceType": "water",
            "value": "5.750000123456789012",
            "unit": "kgal",
        },
        {"serviceType": "wastewater", "value": "2", "unit": "kgal"},
    ]
    assert replacement["summary"]["amountDue"] == "100.005"
    assert replacement["summary"]["verificationLevel"] == replacement[
        "expectedVerification"
    ]
    assert replacement["summary"]["discrepancyTotal"] == replacement[
        "expectedDiscrepancy"
    ]
    assert replacement["summary"]["issueCount"] == replacement["expectedIssues"]
    assert replacement["summary"]["issueCount"] == 1
    assert replacement["summary"]["reviewRequests"][0]["body"] != (
        "Stale page-memory draft"
    )
    assert "$100.01" in replacement["householdText"]
    assert "5.750000123456789012 kgal" in replacement["householdText"]
    assert "Stale page-memory draft" not in replacement["requestText"]
    assert evidence["repeatedFinish"] == {
        "count": 3,
        "summary": replacement["summary"],
    }

    mobile_household = evidence["mobileHousehold"]
    assert mobile_household["width"] == 390
    assert mobile_household["height"] == 844
    assert mobile_household["columns"] == 1
    assert mobile_household["cardCount"] == 3
    assert mobile_household["maxCardWidth"] <= mobile_household["clientWidth"]
    assert mobile_household["noHorizontalOverflow"] is True

    mobile_requests = evidence["mobileRequests"]
    assert mobile_requests["focus"] == "next-steps-title"
    assert mobile_requests["count"] == 3
    assert mobile_requests["cardColumns"] == [1, 1, 1]
    assert mobile_requests["noHorizontalOverflow"] is True
    for provider in (
        "Duke Energy Indiana, LLC",
        "Southern Indiana Gas and Electric Company d/b/a CenterPoint Energy Indiana South",
        "City of Bloomington Utilities",
    ):
        assert provider.lower() in mobile_requests["text"].lower()
    assert evidence["editedDraft"] == "Edited only in this page"

    assert evidence["laterFailure"] == {
        "bundleLength": 3,
        "currentBundleId": None,
        "replacementBundleId": replacement["summary"]["id"],
        "replacementArmed": True,
        "extractionCleared": True,
        "auditCleared": True,
        "retainedCardCount": 3,
        "message": "Choose a PDF bill first.",
        "focus": "bill-file",
        "pageErrors": [],
    }
    assert evidence["refreshClears"] == {
        "bundleLength": 0,
        "currentBundleId": None,
        "cardCount": 0,
        "requestsCount": 0,
        "pageErrors": [],
    }
    preview_discard = evidence["previewDiscard"]
    assert preview_discard["uploadedPreviewUrl"].startswith("blob:")
    assert preview_discard["previewUrl"] is None
    assert preview_discard["extractionCleared"] is True
    assert preview_discard["auditCleared"] is True
    assert preview_discard["iframeHasSource"] is False
    assert preview_discard["revokedUrls"] == [
        preview_discard["uploadedPreviewUrl"]
    ]
    assert preview_discard["fileCount"] == 0
    assert preview_discard["focus"] == "upload-title"
    assert preview_discard["pageErrors"] == []
    preview_finish = evidence["previewFinish"]
    assert preview_finish["uploadedPreviewUrl"].startswith("blob:")
    assert preview_finish["bundleLength"] == 1
    assert preview_finish["summary"]["id"] == preview_finish["replacementBundleId"]
    assert preview_finish["extractionCleared"] is True
    assert preview_finish["auditCleared"] is True
    assert preview_finish["previewUrl"] is None
    assert preview_finish["currentBundleId"] is None
    assert preview_finish["replacementArmed"] is False
    assert preview_finish["reviewCleared"] is True
    assert preview_finish["auditClearedFromDom"] is True
    assert preview_finish["iframeHasSource"] is False
    assert preview_finish["revokedUrls"] == [preview_finish["uploadedPreviewUrl"]]
    assert preview_finish["fileCount"] == 0
    assert preview_finish["focus"] == "household-title"
    assert preview_finish["pageErrors"] == []
    exact_bundle = evidence["exactBundleRendering"]
    assert exact_bundle["exactAddition"]["amountTypes"] == ["string", "string"]
    assert "$0.30" in exact_bundle["exactAddition"]["summaryText"]
    assert "1,002.123456789012345678 kWh" in exact_bundle["exactAddition"][
        "billsText"
    ]
    assert "$0.01" in exact_bundle["noEarlyRounding"]
    assert "Combined amount shown" not in exact_bundle["numberFallback"][
        "summaryText"
    ]
    assert "Not combined" in exact_bundle["numberFallback"]["summaryText"]
    assert "—" in exact_bundle["numberFallback"]["billsText"]
    assert exact_bundle["pageErrors"] == []
    assert evidence["protocolErrors"] == []
    assert evidence["externalRequests"] == []
    assert evidence["hostileDom"] == {
        "injectedElements": 0,
        "eventCount": 0,
        "textRendered": True,
        "javascriptLinks": 0,
    }

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
    assert mobile_result["tableScrollOverflowX"] == "visible"
    assert mobile_result["pageErrors"] == []
