/**
 * Ram's 26 Nov 2026 Research Answer rows, as the reporting tester (test-legal
 * in production, a fresh "Test Legal LLP" tenant on loopback):
 *
 * - BUG-002: a cheque-dishonour question that does not name its Act is
 *   researched as Section 138 NI Act; no statutory source from another Act
 *   (Section 482 CrPC) is listed, and the identified focus is shown.
 * - BUG-003: the pending state shows elapsed time, the submit button cannot
 *   send a duplicate, a second identical request returns the same answer, and
 *   the run finishes inside the bound the page promises.
 * - BUG-004: "Explain about this matter/case." with no matter asks for detail
 *   instead of the old dead end, and the same words asked from a matter whose
 *   record describes a dishonoured cheque are answered on Section 138.
 *
 * The no-paid header routes the model to the deterministic offline provider,
 * so production proves retrieval, focus, verification, timing and UI without
 * paid spend. It never proves the paid model's prose: that stays a recorded
 * human check.
 */
import { randomUUID } from "node:crypto";

import { expect, test, type Page } from "@playwright/test";

import { json, prepareTester, stamp, type TesterRuntime } from "./support/ram-bugs4";
import { OFF_ISSUE_JUDGMENT_TITLE, seedLocalResearchSources } from "./support/research-local-sources";
import { disposeMatter } from "./support/retire-records";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });

const FOCUS_138 = "Section 138, Negotiable Instruments Act, 1881";
const UNNAMED_ACT_QUESTION =
  "My client's cheque given to a supplier bounced for insufficient funds. What are the essential "
  + "ingredients, notice period, limitation and jurisdiction for the complaint?";
const VAGUE_QUESTION = "Explain about this matter/case.";
// The page promises "one to two minutes"; a run must finish inside that.
const ANSWER_BOUND_MS = 120_000;

type Source = { number: number; kind: "statute_section" | "judgment"; title: string; court: string | null };
type Record_ = {
  id: string; status: string; error_code: string | null; message: string | null;
  answer: { question_focus: string[] } | null; sources: Source[]; suggestions: string[];
};

async function readRecord(rt: TesterRuntime, page: Page, id: string): Promise<Record_> {
  return json<Record_>(await page.request.get(`${rt.api.origin}/api/research/answers/${id}`,
    { headers: rt.headers }), "Read the research answer record");
}

for (const phone of [false, true]) {
  test(`${phone ? "[mobile] " : ""}BUG-002/003 an unnamed-Act cheque question is researched on Section 138 only, once, inside the promised time`, async ({ page, request, baseURL }) => {
    test.setTimeout(420_000);
    const rt = await prepareTester(page, request, baseURL, { width: phone ? 390 : 1440, height: 900 });
    if (rt.local) await seedLocalResearchSources();
    await page.goto(`${rt.web.origin}/app/research?tab=answer`);
    const question = `${UNNAMED_ACT_QUESTION} (${stamp("B6")})`;

    await page.getByLabel("Legal question").fill(question);
    const created = page.waitForResponse((r) => r.request().method() === "POST"
      && new URL(r.url()).pathname === "/api/research/answers");
    const started = Date.now();
    await page.getByRole("button", { name: "Get research answer" }).click();
    const first = await json<{ id: string }>(await created, "Queue the research answer", 202);

    // BUG-003: a visible, honest pending state; no second submission possible.
    const pending = page.getByTestId("research-answer-pending");
    await expect(pending).toBeVisible();
    await expect(page.getByTestId("research-answer-elapsed")).toHaveText(/^\d{2}:\d{2}$/);
    await expect(page.getByTestId("research-answer-expectation")).toContainText("one to two minutes");
    await expect(page.getByRole("button", { name: /Researching/ })).toBeDisabled();
    const repeat = await json<{ id: string }>(await request.post(`${rt.api.origin}/api/research/answers`, {
      headers: rt.headers, data: { query: question },
    }), "Repeat the identical request while it runs", 202);
    expect(repeat.id, "an identical request while one runs returns the same answer").toBe(first.id);

    const answer = page.getByTestId("research-answer");
    const unavailable = page.getByTestId("research-answer-unavailable");
    await expect(answer.or(unavailable)).toBeVisible({ timeout: ANSWER_BOUND_MS });
    const elapsedMs = Date.now() - started;
    test.info().annotations.push({ type: "research-answer-elapsed-ms", description: String(elapsedMs) });
    expect(elapsedMs, "the run finishes inside the promised bound").toBeLessThan(ANSWER_BOUND_MS);
    await expect(unavailable, "the Section 138 corpus must answer this question").toHaveCount(0);

    // BUG-002: the identified focus is shown and every statutory source is NI Act.
    await expect(page.getByTestId("research-question-focus")).toContainText(FOCUS_138);
    const record = await readRecord(rt, page, first.id);
    expect(record.answer?.question_focus).toContain(FOCUS_138);
    const statutes = record.sources.filter((source) => source.kind === "statute_section");
    expect(statutes.length).toBeGreaterThan(0);
    for (const source of statutes) {
      expect(source.title, "statutory sources stay in the Act the question is about")
        .toContain("Negotiable Instruments Act");
    }
    const cardTitles = await answer.getByTestId("research-authority-card").locator("h4").allTextContents();
    for (const title of cardTitles) {
      expect(title).not.toMatch(/Code of Criminal Procedure|Nagarik Suraksha Sanhita/);
    }
    // Loopback seeds the off-issue Section 482 / 420 judgment beside the
    // Section 138 authority; it matches the question's words but must never be listed.
    if (rt.local) expect(record.sources.map((source) => source.title)).not.toContain(OFF_ISSUE_JUDGMENT_TITLE);
    await expect(page.getByTestId("research-short-answer")).not.toContainText(/Section\s+482|Section\s+528/);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, "no horizontal page scroll").toBeLessThanOrEqual(1);
  });
}

test("BUG-004 a vague question asks for detail without a matter and is researched from the matter record", async ({ page, request, baseURL }) => {
  test.setTimeout(480_000);
  const rt = await prepareTester(page, request, baseURL, { width: 1440, height: 900 });
  if (rt.local) await seedLocalResearchSources();
  const nonce = randomUUID().slice(0, 8).toUpperCase();

  // Without a matter: guidance, not "no indexed statute section or judgment".
  await page.goto(`${rt.web.origin}/app/research?tab=answer`);
  await page.getByLabel("Legal question").fill(`${VAGUE_QUESTION} ${nonce}`);
  const vague = page.waitForResponse((r) => r.request().method() === "POST"
    && new URL(r.url()).pathname === "/api/research/answers");
  await page.getByRole("button", { name: "Get research answer" }).click();
  const vagueId = (await json<{ id: string }>(await vague, "Queue the vague question", 202)).id;
  const guidance = page.getByTestId("research-answer-unavailable");
  await expect(guidance).toBeVisible({ timeout: ANSWER_BOUND_MS });
  await expect(guidance).toContainText("Name the Act and section");
  await expect(guidance).toContainText("start the research from a matter");
  await expect(guidance).not.toContainText("no indexed statute section or judgment");
  expect((await readRecord(rt, page, vagueId)).error_code).toBe("needs_detail");

  // From a matter whose record describes a dishonoured cheque.
  let matterId: string | undefined;
  try {
    await page.goto(`${rt.web.origin}/app/matters`);
    await page.getByTestId("new-matter-trigger").first().click();
    const dialog = page.getByRole("dialog", { name: "New matter" });
    await dialog.getByLabel("Title", { exact: true }).fill(stamp(`Bugs6 cheque matter ${nonce}`));
    await dialog.getByLabel("Matter code", { exact: true }).fill(`BUGS6-${nonce}`);
    await dialog.getByLabel("Practice area", { exact: true }).fill("Criminal");
    await dialog.getByLabel("Description", { exact: true })
      .fill("The client's cheque was dishonoured for insufficient funds and a demand notice was served.");
    const created = page.waitForResponse((r) => r.request().method() === "POST"
      && new URL(r.url()).pathname === "/api/matters/");
    await dialog.getByRole("button", { name: "Create matter", exact: true }).click();
    matterId = (await json<{ id: string }>(await created, "Create the journey's Matter through the UI")).id;

    await page.goto(`${rt.web.origin}/app/matters/${matterId}`);
    // The matter's own Research tab, not the sidebar's workspace-wide Research.
    await page.locator(`a[href*="/app/research?tab=answer&matter=${encodeURIComponent(matterId)}"]`).first().click();
    await expect(page).toHaveURL(new RegExp(`matter=${matterId}`));
    await expect(page.getByTestId("research-context-matter")).toBeVisible();
    await page.getByLabel("Legal question").fill(VAGUE_QUESTION);
    const fromMatter = page.waitForResponse((r) => r.request().method() === "POST"
      && new URL(r.url()).pathname === "/api/research/answers");
    await page.getByRole("button", { name: "Get research answer" }).click();
    const id = (await json<{ id: string }>(await fromMatter, "Queue the matter question", 202)).id;
    await expect(page.getByTestId("research-answer")).toBeVisible({ timeout: ANSWER_BOUND_MS });
    await expect(page.getByTestId("research-question-focus")).toContainText(FOCUS_138);
    await expect(page.getByTestId("research-matter-facts")).toContainText("dishonoured");
    const record = await readRecord(rt, page, id);
    expect(record.status).toBe("answered");
    expect(record.answer?.question_focus).toContain(FOCUS_138);
  } finally {
    if (matterId) {
      await disposeMatter(request, rt.api.origin, rt.headers, matterId, "Bugs6 research journey record retired");
    }
  }
});
