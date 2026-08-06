#!/usr/bin/env node
/**
 * AgenticFabWorks 사이트 자가진단.
 *
 * 배포된 사이트를 실제 브라우저로 열어 디자인 기준 위반과 콘솔 오류를 센다.
 * 개선 전후 비교가 목적이므로 판정 대신 수치를 그대로 출력한다.
 *
 * 사용법:
 *   node audit_sites.mjs                       기본 5개 사이트
 *   node audit_sites.mjs https://a https://b   지정 URL만
 *   AFW_AUDIT_WIDTH=390 node audit_sites.mjs   모바일 폭 점검
 *
 * Playwright 가 설치된 디렉터리에서 실행한다.
 */

import { createRequire } from "node:module";
import path from "node:path";

const requireFromProject = createRequire(path.join(process.cwd(), "package.json"));
const { chromium } = requireFromProject("playwright");

const DEFAULT_TARGETS = [
  "https://agenticfabworks.com/",
  "https://tools.agenticfabworks.com/",
  "https://skct.agenticfabworks.com/",
  "https://calendar.agenticfabworks.com/",
  "https://interview.agenticfabworks.com/",
];

const targets = process.argv.slice(2).length ? process.argv.slice(2) : DEFAULT_TARGETS;
const width = Number(process.env.AFW_AUDIT_WIDTH ?? 1440);
const height = Number(process.env.AFW_AUDIT_HEIGHT ?? 900);

/** Runs inside the page. Counts violations of the design-system minimums. */
function collect() {
  const undersized = [...document.querySelectorAll("p,span,small,li,label,button,a,h1,h2,h3,td,th")]
    .map((node) => ({
      px: parseFloat(getComputedStyle(node).fontSize),
      text: (node.textContent || "").trim().slice(0, 28),
    }))
    .filter((item) => Number.isFinite(item.px) && item.px > 0 && item.px < 13 && item.text);

  const smallTargets = [...document.querySelectorAll("button,a,input,select,textarea,[role=button],[role=tab]")]
    .map((node) => {
      const rect = node.getBoundingClientRect();
      return {
        h: Math.round(rect.height),
        label: (node.textContent || node.getAttribute("aria-label") || "").trim().slice(0, 24),
      };
    })
    .filter((item) => item.h > 0 && item.h < 32);

  let css = "";
  for (const sheet of document.styleSheets) {
    try {
      for (const rule of sheet.cssRules) css += rule.cssText || "";
    } catch {
      // Cross-origin stylesheet, not readable.
    }
  }

  return {
    title: document.title.slice(0, 70),
    bodyFontSize: getComputedStyle(document.body).fontSize,
    h1: document.querySelector("h1")?.textContent?.trim().slice(0, 50) ?? null,
    undersizedTextCount: undersized.length,
    undersizedSamples: undersized.slice(0, 5),
    smallTargetCount: smallTargets.length,
    smallTargetSamples: smallTargets.slice(0, 5),
    hasReducedMotion: css.includes("prefers-reduced-motion"),
    hasContainerQuery: css.includes("@container"),
    hasFocusVisible: css.includes(":focus-visible"),
    horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
    missingImageAlt: document.querySelectorAll("img:not([alt])").length,
    inlineStyled: document.querySelectorAll("[style]").length,
  };
}

const browser = await chromium.launch({ headless: true, channel: "chrome" });
const report = {};

for (const url of targets) {
  const page = await browser.newPage({ viewport: { width, height } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error.message).slice(0, 160)));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text().slice(0, 160));
  });
  try {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45_000 });
    await page.waitForTimeout(2500);
    report[url] = await page.evaluate(collect);
    // Ad and analytics vendors emit CSP noise the site cannot fix. Separate it
    // so real defects stay visible in the summary line.
    const vendor = /googlesyndication|doubleclick|adtrafficquality|cloudflareinsights|googletagmanager/;
    report[url].consoleErrors = errors.filter((entry) => !vendor.test(entry)).slice(0, 5);
    report[url].vendorNoiseCount = errors.filter((entry) => vendor.test(entry)).length;
  } catch (error) {
    report[url] = { failed: String(error).slice(0, 160) };
  }
  await page.close();
}

await browser.close();

const lines = Object.entries(report).map(([url, data]) => {
  const host = new URL(url).hostname
    .replace(".agenticfabworks.com", "")
    .replace("agenticfabworks.com", "hub");
  if (data.failed) return `${host.padEnd(11)} FAILED ${data.failed}`;
  return [
    host.padEnd(11),
    `<13px:${String(data.undersizedTextCount).padStart(4)}`,
    `<32px:${String(data.smallTargetCount).padStart(3)}`,
    `overflow:${data.horizontalOverflow ? "YES" : "no "}`,
    `err:${String(data.consoleErrors.length).padStart(2)}`,
    `noAlt:${String(data.missingImageAlt).padStart(2)}`,
    `container:${data.hasContainerQuery ? "y" : "n"}`,
    `reduced:${data.hasReducedMotion ? "y" : "n"}`,
  ].join("  ");
});

console.log(`viewport ${width}x${height}`);
console.log(lines.join("\n"));
console.log("\n--- detail ---");
console.log(JSON.stringify(report, null, 1));
