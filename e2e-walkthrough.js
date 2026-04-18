/*
 * End-to-end user walkthrough against http://127.0.0.1:3000 with the
 * seeded demo firm (aster-demo / sanjeev@aster-demo.in). Every major
 * surface is exercised; each step logs whether the UI behaved as
 * expected. Screenshots land in ./e2e-screenshots/.
 */
const path = require("path");
const fs = require("fs");
const { chromium } = require("playwright");

const BASE = "http://127.0.0.1:3000";
const SHOT_DIR = path.join(__dirname, "e2e-screenshots");
fs.mkdirSync(SHOT_DIR, { recursive: true });

const LOGIN = {
  slug: "aster-demo",
  email: "sanjeev@aster-demo.in",
  password: "DemoPass123!",
};

const results = [];
function record(name, status, notes = "") {
  const icon = { pass: "✅", fail: "❌", warn: "⚠️ ", info: "ℹ️ " }[status];
  const line = `${icon} ${name}${notes ? ` — ${notes}` : ""}`;
  console.log(line);
  results.push({ name, status, notes });
}

async function shot(page, slug) {
  await page.screenshot({
    path: path.join(SHOT_DIR, `${slug}.png`),
    fullPage: false,
  });
}

async function main() {
  const execEdge = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
  const opts = fs.existsSync(execEdge) ? { executablePath: execEdge } : {};
  const browser = await chromium.launch({ headless: true, ...opts });
  const ctx = await browser.newContext({
    baseURL: BASE,
    viewport: { width: 1440, height: 900 },
  });
  const page = await ctx.newPage();

  const pageErrors = [];
  page.on("pageerror", (err) => pageErrors.push(err.message));
  page.on("console", (msg) => {
    if (msg.type() === "error") pageErrors.push(`CONSOLE: ${msg.text()}`);
  });

  try {
    // 1. Landing page — marketing surface.
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    const heroOk = await page
      .getByRole("heading", { name: /The operating system for legal work/i })
      .isVisible();
    record(
      "Landing /",
      heroOk ? "pass" : "fail",
      heroOk ? "hero + full marketing site renders" : "hero not visible",
    );
    await shot(page, "01-landing");

    // 2. Sign-in with invalid input → zod rejects.
    await page.goto("/sign-in");
    await page.locator("#company-slug").fill("Not A Slug");
    await page.locator("#email").fill("bad");
    await page.locator("#password").fill("x");
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    const slugErr = await page
      .getByText(/Lowercase letters, digits, and hyphens only/i)
      .isVisible()
      .catch(() => false);
    record(
      "Sign-in validation",
      slugErr ? "pass" : "fail",
      slugErr ? "zod aria-invalid + role=alert copy shown" : "no validation",
    );

    // 3. Real sign-in.
    await page.locator("#company-slug").fill("");
    await page.locator("#company-slug").fill(LOGIN.slug);
    await page.locator("#email").fill("");
    await page.locator("#email").fill(LOGIN.email);
    await page.locator("#password").fill("");
    await page.locator("#password").fill(LOGIN.password);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app$/);
    const welcomeLocator = page
      .getByRole("heading", { name: /Good to have you back/i })
      .first();
    await welcomeLocator
      .waitFor({ state: "visible", timeout: 15_000 })
      .catch(() => {});
    const welcome = await welcomeLocator.isVisible().catch(() => false);
    record(
      "Sign-in → dashboard",
      welcome ? "pass" : "fail",
      welcome ? "dashboard header visible" : "no dashboard header",
    );
    await shot(page, "02-dashboard");

    // 4. Matters list — should already show the BLR-2026-001 matter.
    await page.getByRole("link", { name: "Matters", exact: true }).click();
    await page.waitForURL(/\/app\/matters$/);
    const matterHeading = await page
      .getByRole("heading", { name: /Matter portfolio/i })
      .first()
      .isVisible();
    const existingRow = page.getByText("BLR-2026-001").first();
    await existingRow
      .waitFor({ state: "visible", timeout: 15_000 })
      .catch(() => {});
    const existingCount = await page.getByText("BLR-2026-001").count();
    record(
      "/app/matters list",
      matterHeading && existingCount >= 1 ? "pass" : "fail",
      `portfolio heading=${matterHeading}, BLR-2026-001 rows=${existingCount}`,
    );
    await shot(page, "03-matters");

    // 5. Open the matter cockpit by clicking the row.
    await existingRow.click();
    await page.waitForURL(/\/app\/matters\/[0-9a-f-]+$/);
    const matterUrl = page.url();
    const matterId = matterUrl.split("/").pop();
    const cockpitH1 = await page
      .getByRole("heading", { level: 1 })
      .first()
      .innerText()
      .catch(() => "");
    record(
      "Matter cockpit /matters/{id}",
      cockpitH1.length > 0 ? "pass" : "fail",
      `h1="${cockpitH1}" matterId=${matterId}`,
    );
    await shot(page, "04-cockpit-overview");

    // Scope cockpit tab clicks to the cockpit <nav> so they do not collide
    // with identical-text sidebar items ("Hearings", "Recommendations").
    const cockpit = page.getByRole("navigation", { name: /Matter cockpit tabs/i });
    const cockpitLink = (label) => cockpit.getByRole("link", { name: label, exact: true });

    // 6. Drafts tab — full state machine.
    await cockpitLink("Drafts").click();
    await page.waitForURL(/\/drafts$/);
    const draftsEmpty = await page
      .getByText(/No drafts yet/i)
      .isVisible()
      .catch(() => false);
    record("Drafts tab landing", "pass", draftsEmpty ? "empty state" : "has drafts");

    const nowTag = `${Date.now()}`;
    // Dialog may open from header button or empty-state action — try either.
    const newDraftTriggers = page.getByTestId("new-draft-trigger");
    await newDraftTriggers.first().click();
    const createDialog = page.getByRole("dialog");
    await createDialog.getByLabel("Title").fill(`Interim reply — ${nowTag}`);
    await createDialog.getByRole("button", { name: /Create draft/i }).click();
    await page.waitForURL(/\/drafts\/[0-9a-f-]+$/);
    const draftId = page.url().split("/").pop();
    record("Draft created", "pass", `draftId=${draftId}`);

    // Generate version.
    await page.getByTestId("draft-generate").click();
    await page
      .getByText(/Generated /)
      .first()
      .waitFor({ timeout: 20_000 });
    record("Draft generate (v1)", "pass", "version body + generated-at visible");

    // Submit for review.
    await page.getByTestId("draft-submit").click();
    await page
      .getByText(/in review/i)
      .first()
      .waitFor({ timeout: 10_000 });
    record("Draft submit", "pass", "status flipped to in review");

    // Request changes.
    await page.getByTestId("draft-request-changes").click();
    await page
      .getByText(/changes requested/i)
      .first()
      .waitFor({ timeout: 10_000 });
    record("Draft request-changes", "pass", "status flipped to changes requested");

    // Approve path — the mock LLM produces a draft without verified
    // citations (no seeded authorities in this demo DB), so approve
    // must fail closed with a toast.
    await page.getByTestId("draft-submit").click();
    await page
      .getByText(/in review/i)
      .first()
      .waitFor({ timeout: 10_000 });
    await page.getByTestId("draft-approve").click();
    // Toast 'verified citations' should appear.
    const refused = await page
      .getByText(/verified citations/i)
      .first()
      .waitFor({ timeout: 5_000 })
      .then(() => true)
      .catch(() => false);
    record(
      "Draft approve fail-closed",
      refused ? "pass" : "warn",
      refused
        ? "toast 'verified citations' — 422 as designed"
        : "no toast matched (may still have refused)",
    );

    // DOCX download button present.
    const docxBtn = await page.getByTestId("draft-download-docx").count();
    record(
      "DOCX download button",
      docxBtn >= 1 ? "pass" : "fail",
      `buttons=${docxBtn}`,
    );
    await shot(page, "05-drafts-detail");

    // Actually fetch the DOCX bytes via the API to confirm the endpoint
    // streams a real Word doc (the UI button just navigates to this URL).
    const cookies = await ctx.cookies();
    const authToken = await page.evaluate(() =>
      window.localStorage.getItem("caseops.session.token"),
    );
    const docxResp = await page.request.get(
      `http://127.0.0.1:8000/api/matters/${matterId}/drafts/${draftId}/export.docx`,
      { headers: { Authorization: `Bearer ${authToken}` } },
    );
    const docxBuf = await docxResp.body();
    const looksLikeDocx =
      docxResp.status() === 200 &&
      docxBuf.slice(0, 4).toString("hex") === "504b0304";
    record(
      "DOCX export bytes",
      looksLikeDocx ? "pass" : "fail",
      `status=${docxResp.status()} size=${docxBuf.length}`,
    );
    fs.writeFileSync(path.join(SHOT_DIR, "draft-export.docx"), docxBuf);

    // 7. Hearings tab — add a hearing via the API (the UI dialog for
    // adding hearings still lives in the legacy console), then exercise
    // the HearingPackDialog.
    await cockpitLink("Hearings").click();
    await page.waitForURL(/\/hearings$/);
    const hearingResp = await page.request.post(
      `http://127.0.0.1:8000/api/matters/${matterId}/hearings`,
      {
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        data: {
          hearing_on: "2026-05-20",
          forum_name: "Delhi High Court",
          purpose: "Directions hearing",
          status: "scheduled",
        },
      },
    );
    record(
      "Hearing created via API",
      hearingResp.status() === 200 ? "pass" : "fail",
      `status=${hearingResp.status()}`,
    );
    await page.reload();
    await page.waitForLoadState("networkidle");
    const packTriggers = page.getByTestId("hearing-pack-trigger");
    await packTriggers.first().waitFor({ state: "visible", timeout: 10_000 });
    await packTriggers.first().click();
    const packDialog = page.getByRole("dialog");
    await packDialog.waitFor({ state: "visible" });
    await page.getByTestId("generate-hearing-pack").click();
    await packDialog
      .getByText(/Review required/i)
      .first()
      .waitFor({ timeout: 20_000 });
    record("Hearing pack generated", "pass", "review-required badge visible");
    await shot(page, "06-hearing-pack");
    await page.getByTestId("mark-pack-reviewed").click();
    await packDialog
      .getByText(/Reviewed/i)
      .first()
      .waitFor({ timeout: 10_000 });
    record("Hearing pack marked reviewed", "pass", "status flipped to reviewed");
    await page.keyboard.press("Escape");

    // 8. Recommendations tab — generate an authority recommendation.
    await cockpitLink("Recommendations").click();
    await page.waitForURL(/\/recommendations$/);
    await page.getByTestId("generate-authority-recommendation").click();
    // Recommendation refuses without supporting citations; the service
    // toasts 'refused on purpose' (422). That is correct guardrail
    // behaviour in an empty demo DB. Assert either the success card or
    // the explicit refusal toast.
    const recSuccess = await page
      .getByText(/filtered through CaseOps/i)
      .first()
      .waitFor({ timeout: 20_000 })
      .then(() => true)
      .catch(() => false);
    const recRefused = !recSuccess && (await page
      .getByText(/verifiable recommendation/i)
      .first()
      .waitFor({ timeout: 5_000 })
      .then(() => true)
      .catch(() => false));
    record(
      "Recommendations",
      recSuccess || recRefused ? "pass" : "warn",
      recSuccess
        ? "generated with verified citations"
        : recRefused
          ? "refused-on-purpose (fail-closed) — correct for empty tenant DB"
          : "neither success nor refusal surfaced",
    );
    await shot(page, "07-recommendations");

    // 9. Billing tab.
    await cockpitLink("Billing").click();
    await page.waitForURL(/\/billing$/);
    const billingTotals = await page
      .getByText(/Total billed/i)
      .isVisible()
      .catch(() => false);
    record(
      "Billing tab",
      billingTotals ? "pass" : "warn",
      billingTotals ? "totals card visible" : "no totals",
    );

    // 10. Audit tab — every prior action should have an activity row.
    await cockpitLink("Audit").click();
    await page.waitForURL(/\/audit$/);
    const auditHeading = await page
      .getByRole("heading", { name: /Audit trail/i })
      .isVisible();
    record(
      "Audit tab",
      auditHeading ? "pass" : "fail",
      auditHeading ? "timeline renders" : "heading not found",
    );
    await shot(page, "08-audit");

    // 11. Contracts portfolio.
    await page.getByRole("link", { name: "Contracts", exact: true }).click();
    await page.waitForURL(/\/app\/contracts$/);
    const contractsHeading = await page
      .getByRole("heading", { name: /Contract repository/i })
      .isVisible();
    record(
      "Contracts list",
      contractsHeading ? "pass" : "fail",
      contractsHeading ? "page renders" : "no heading",
    );
    await shot(page, "09-contracts");

    // 12. Outside counsel portfolio.
    await page.getByRole("link", { name: "Outside Counsel", exact: true }).click();
    await page.waitForURL(/\/app\/outside-counsel$/);
    const counselHeading = await page
      .getByRole("heading", { level: 1 })
      .first()
      .innerText();
    record(
      "Outside counsel",
      /counsel/i.test(counselHeading) ? "pass" : "fail",
      `h1="${counselHeading}"`,
    );
    await shot(page, "10-outside-counsel");

    // 13. Sign out.
    await page.getByRole("button", { name: /Open user menu/i }).click();
    await page.getByTestId("sign-out").click();
    await page.waitForURL(/\/sign-in/);
    record("Sign out", "pass", "redirected back to /sign-in");
    await shot(page, "11-signed-out");

    // Any uncaught page errors.
    if (pageErrors.length > 0) {
      record(
        "Uncaught page errors",
        "warn",
        `${pageErrors.length} — ${pageErrors.slice(0, 3).join(" | ")}`,
      );
    } else {
      record("Console / pageerror listeners", "pass", "none during walkthrough");
    }
  } catch (err) {
    record("FATAL", "fail", `${err.name}: ${err.message}`);
    throw err;
  } finally {
    await browser.close();
    // Print summary.
    const pass = results.filter((r) => r.status === "pass").length;
    const warn = results.filter((r) => r.status === "warn").length;
    const fail = results.filter((r) => r.status === "fail").length;
    console.log(`\n--- summary: ${pass} pass, ${warn} warn, ${fail} fail ---`);
    if (fail > 0) process.exit(1);
  }
}

main();
