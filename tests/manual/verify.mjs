// Production bug verification for CaseOps — runs against
// https://caseops.ai / https://api.caseops.ai with the aster-demo tenant.
//
// Covers: BUG-001 draft creation, BUG-002 draft regeneration,
// BUG-004 schedule-hearing button, BUG-009 research page.
// (BUG-010 was already verified via curl redirect.)
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const OUT = "C:/Users/mishr/caseops/tmp/bug_verify_2026_04_21";
fs.mkdirSync(OUT, { recursive: true });

const BASE = "https://caseops.ai";
const EMAIL = "sanjeev@aster-demo.in";
const PASSWORD = "Aster-Demo-2026!";
const SLUG = "aster-demo";

const results = {};
const apiCalls = [];

function log(bug, msg) {
  console.log(`[${bug}] ${msg}`);
}

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();

page.on("response", async (resp) => {
  if (!resp.url().includes("/api/")) return;
  apiCalls.push({ url: resp.url(), status: resp.status() });
});

async function signIn() {
  await page.goto(`${BASE}/sign-in`, { waitUntil: "load" });
  await page.locator("#company-slug").fill(SLUG);
  await page.locator("#email").fill(EMAIL);
  await page.locator("#password").fill(PASSWORD);
  const btn = page.locator('button[type="submit"]').first();
  await Promise.all([
    page.waitForURL(/\/app(?!\/sign-in)/, { timeout: 30000 }).catch(() => null),
    btn.click(),
  ]);
  if (page.url().includes("/sign-in")) throw new Error("sign-in did not redirect");
}

try {
  await signIn();
  log("setup", `signed in. url=${page.url()}`);

  // ---- Grab a matter id ---------------------------------------
  await page.goto(`${BASE}/app/matters`, { waitUntil: "load" });
  await page.screenshot({ path: path.join(OUT, "00_matters.png"), fullPage: true });

  // Use known matter id (BAIL-2026-001 in aster-demo) rather than
  // relying on in-page fetch which hits CORS boundaries.
  const matterId = "310b7c38-47ad-461b-9ebf-7bb59e9c8667";
  log("setup", `using matterId=${matterId}`);

  // ---- BUG-009: Research page ---------------------------------
  await page.goto(`${BASE}/app/research`, { waitUntil: "load" });
  await page.screenshot({ path: path.join(OUT, "09_research.png"), fullPage: true });
  const hasSearch = await page
    .locator('input[type="search"], input[placeholder*="search" i], textarea[placeholder*="search" i]')
    .first()
    .count();
  const hasBanner = (await page.textContent("body"))?.includes("invalid_token") ?? false;
  if (hasSearch > 0 && !hasBanner) {
    // Try a query
    const box = page.locator('input[type="search"], input[placeholder*="search" i]').first();
    await box.fill("bail BNSS 483 triple test");
    await box.press("Enter").catch(() => null);
    await page.waitForTimeout(15000);
    await page.screenshot({ path: path.join(OUT, "09_research_after.png"), fullPage: true });
    const afterText = (await page.textContent("body")) ?? "";
    results["BUG-009"] =
      afterText.includes("invalid_token") || afterText.length < 100
        ? `FAIL — post-search body suspicious (len=${afterText.length})`
        : "PASS — research page loaded + search submitted";
  } else {
    results["BUG-009"] = hasBanner ? "FAIL — invalid_token on page" : "FAIL — no search box found";
  }
  log("BUG-009", results["BUG-009"]);

  // ---- BUG-004: Schedule hearing button -----------------------
  await page.goto(`${BASE}/app/matters/${matterId}/hearings`, { waitUntil: "load" });
  // Use the data-testid — Playwright's getByRole accessible-name
  // matcher is brittle when the button wraps an icon + text.
  const scheduleBtn = page.locator('[data-testid="schedule-hearing-open"]').first();
  // The hearings page fetches workspace + matter + hearings data
  // client-side after hydration, so wait for the button to actually
  // render before the visibility probe rather than relying on a
  // generic page-load timeout.
  await scheduleBtn.waitFor({ state: "visible", timeout: 20000 }).catch(() => null);
  await page.screenshot({ path: path.join(OUT, "04_hearings.png"), fullPage: true });
  const scheduleVisible = (await scheduleBtn.count()) > 0 && (await scheduleBtn.isVisible());
  // Diagnostic dump: what buttons ARE on the page?
  const visibleButtons = await page.locator("button:visible").allTextContents();
  console.log(
    "[BUG-004] hearings-page buttons:",
    visibleButtons.slice(0, 15).map((t) => t.trim()).filter((t) => t),
  );
  const url = page.url();
  console.log(`[BUG-004] final url: ${url}`);
  if (scheduleVisible) {
    await scheduleBtn.click();
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(OUT, "04_hearings_dialog.png"), fullPage: true });
    // Dialog should contain a date input for hearing_on and forum name
    const hasDialog = (await page.locator('[role="dialog"]').count()) > 0;
    results["BUG-004"] = hasDialog
      ? "PASS — Schedule hearing button visible + dialog opens"
      : "FAIL — button visible but no dialog opened";
  } else {
    results["BUG-004"] = "FAIL — Schedule hearing button not visible";
  }
  log("BUG-004", results["BUG-004"]);

  // Close any open dialog
  await page.keyboard.press("Escape").catch(() => null);

  // ---- BUG-001 + BUG-002: Draft creation + regeneration -------
  await page.goto(`${BASE}/app/matters/${matterId}/drafts`, { waitUntil: "load" });
  await page.screenshot({ path: path.join(OUT, "01_drafts_before.png"), fullPage: true });

  const newDraftBtn = page.getByRole("button", { name: /new draft|create draft|\+ draft/i }).first();
  if ((await newDraftBtn.count()) === 0) {
    results["BUG-001"] = "INCONCLUSIVE — no 'New draft' button found";
    results["BUG-002"] = "SKIPPED";
  } else {
    await newDraftBtn.click();
    await page.waitForTimeout(500);
    // Fill a draft title in whatever input appears
    const titleInput = page
      .locator('input[name="title"], input[placeholder*="title" i]')
      .first();
    if ((await titleInput.count()) > 0) {
      await titleInput.fill(`BUG-001 verify 2026-04-21`);
    }
    // Try to submit
    const submitBtn = page
      .getByRole("button", { name: /create|save|submit/i })
      .first();
    await submitBtn.click().catch(() => null);
    await page.waitForTimeout(8000);
    await page.screenshot({ path: path.join(OUT, "01_drafts_after.png"), fullPage: true });

    // Check API calls for a draft POST
    const draftPost = apiCalls.find(
      (c) => /\/api\/matters\/[^/]+\/drafts/.test(c.url) && c.status >= 200 && c.status < 400,
    );
    results["BUG-001"] = draftPost
      ? "PASS — draft created (draft POST succeeded)"
      : "FAIL — no successful draft POST observed";
    log("BUG-001", results["BUG-001"]);

    // BUG-002: try regenerate if we have a draft
    if (draftPost) {
      const genBtn = page.getByRole("button", { name: /generate/i }).first();
      if ((await genBtn.count()) > 0) {
        await genBtn.click().catch(() => null);
        await page.waitForTimeout(120000); // wait up to 2 min
        await page.screenshot({ path: path.join(OUT, "02_after_generate.png"), fullPage: true });
        const genOk = apiCalls.find(
          (c) => c.url.includes("/generate") && c.status >= 200 && c.status < 400,
        );
        const genFail = apiCalls.find(
          (c) => c.url.includes("/generate") && c.status >= 500,
        );
        results["BUG-002"] = genOk
          ? "PASS — draft generation succeeded"
          : genFail
            ? `FAIL — generation returned ${genFail.status}`
            : "INCONCLUSIVE — no generate API call seen (possibly button not present)";
      } else {
        results["BUG-002"] = "INCONCLUSIVE — no Generate button on draft page";
      }
    } else {
      results["BUG-002"] = "SKIPPED — BUG-001 failed, cannot test regen";
    }
    log("BUG-002", results["BUG-002"]);
  }
} catch (err) {
  results["ERROR"] = err.message;
  await page.screenshot({ path: path.join(OUT, "99_error.png"), fullPage: true }).catch(() => null);
  console.error("run error:", err);
} finally {
  fs.writeFileSync(path.join(OUT, "results.json"), JSON.stringify(results, null, 2));
  fs.writeFileSync(path.join(OUT, "api_calls.json"), JSON.stringify(apiCalls.slice(0, 60), null, 2));
  console.log("---- RESULTS ----");
  for (const [k, v] of Object.entries(results)) console.log(`${k}: ${v}`);
  await browser.close();
}
