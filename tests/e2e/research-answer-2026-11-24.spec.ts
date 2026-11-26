/** J05/M04 US-067..069: three-part research answer, desktop and phone. */
import { expect, test } from "@playwright/test";

import { prepareTester } from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });

const QUESTION =
  "A cheque of Rs 5 lakh was dishonoured due to insufficient funds. What are the legal requirements, "
  + "notice period and procedure for filing a case under Section 138 of the Negotiable Instruments Act, 1881?";

for (const phone of [false, true]) {
  test(`${phone ? "[mobile] " : ""}Research answer: Short Answer, Detailed Research, then Authorities ${phone ? "phone" : "desktop"}`, async ({ page, request, baseURL }) => {
    const runtime = await prepareTester(page, request, baseURL, { width: phone ? 390 : 1440, height: 900 });
    await page.goto(`${runtime.web.origin}/app/research?tab=answer`);
    await expect(page.getByTestId("research-tool-answer")).toHaveAttribute("aria-pressed", "true");
    await page.getByLabel("Legal question").fill(QUESTION);
    const created = page.waitForResponse((r) => r.request().method() === "POST"
      && new URL(r.url()).pathname === "/api/research/answers");
    await page.getByRole("button", { name: "Get research answer" }).click();
    const answerId = ((await (await created).json()) as { id: string }).id;

    const answer = page.getByTestId("research-answer");
    const unavailable = page.getByTestId("research-answer-unavailable");
    await expect(answer.or(unavailable)).toBeVisible({ timeout: 180_000 });
    await expect(unavailable, "the benchmark must be answered from indexed sources").toHaveCount(0);

    // Relevance, not only structure (Nov 26): this run passed while citing NI Act
    // Section 5 ("Rs 5" read as a section) and judgments titled "AT HYDERABAD".
    const record = (await (await request.get(`${runtime.api.origin}/api/research/answers/${answerId}`,
      { headers: runtime.headers })).json()) as { sources: { kind: string; title: string }[] };
    expect(record.sources[0]?.title, "Section 138 is the first source")
      .toMatch(/^Section 138, Negotiable Instruments Act/);
    for (const source of record.sources.filter((item) => item.kind === "statute_section")) {
      expect(source.title).toContain("Negotiable Instruments Act");
    }
    for (const source of record.sources.filter((item) => item.kind === "judgment")) {
      expect(source.title, "an authority a lawyer can identify")
        .not.toMatch(/^AT [A-Z]+$|\.docx?$|^https?:|^Court No\.?\s*-|^HON.?BLE/i);
    }

    // Part order is fixed.
    const headings = await answer.getByRole("heading", { level: 3 }).allTextContents();
    expect(headings).toEqual(["Short answer", "Detailed research", "Relevant judicial authorities & sources"]);
    await expect(page.getByTestId("research-law-checked")).toContainText("Law checked as of");
    await expect(page.getByTestId("research-missing-facts")).toBeVisible();

    // Every inline marker opens an authority card that is listed in Part C.
    const markers = answer.getByTestId("research-citation-marker");
    expect(await markers.count()).toBeGreaterThan(0);
    const cards = answer.getByTestId("research-authority-card");
    const cardIds = new Set(await cards.evaluateAll((nodes) => nodes.map((node) => `#${node.id}`)));
    for (const href of await markers.evaluateAll((nodes) => nodes.map((node) => node.getAttribute("href")))) {
      expect(cardIds.has(href ?? "")).toBe(true);
    }
    const first = answer.getByTestId("research-short-answer").getByTestId("research-citation-marker").first();
    const target = (await first.getAttribute("href"))!.slice(1);
    await first.click();
    await expect(page.locator(`[id="${target}"]`)).toBeFocused();
    await page.locator(`[id="${target}"]`).getByRole("button", { name: "Back to the answer" }).click();
    await expect(first).toBeFocused();

    await expect(page.getByRole("button", { name: "Copy" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Download" })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, "no horizontal page scroll").toBeLessThanOrEqual(1);
  });
}
