/** IPLF-060B / UJ-20 canonical judge workflow acceptance. */

import { expect, request, test } from "@playwright/test";

import {
  bootstrapJudgeTenant,
  createJudgeWorkflowFixture,
  signInJudgeTenant,
} from "./support/iplf060b";

test("IPLF-060B completes UJ-20 normal and exception paths", async ({ page }) => {
  test.setTimeout(360_000);
  page.setDefaultTimeout(25_000);
  const api = await request.newContext();
  const tenant = await bootstrapJudgeTenant(api);
  const fixture = createJudgeWorkflowFixture();
  await signInJudgeTenant(page, tenant);

  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto(`/app/courts/judges/${fixture.judgeId}`);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Justice IPLF 060B");
  await expect(page.getByText("Canonical identity")).toBeVisible();
  await expect(page.getByText("Mapped authorities")).toBeVisible();
  await expect(page.getByText("Excluded from analytics")).toBeVisible();
  const mappedAuthorities = page
    .getByRole("heading", { name: "Mapped authorities" })
    .locator("../..");
  await expect(mappedAuthorities.getByRole("link", { name: "Source" }).first()).toHaveAttribute(
    "href",
    /source-actions/,
  );
  await expect(page.getByRole("link", { name: /research this judge/i })).toHaveAttribute(
    "href",
    /\/app\/research\?q=/,
  );
  for (const name of ["From year", "To year", "Mapping confidence"]) {
    await expect(page.getByLabel(name)).toBeVisible();
  }
  for (const name of ["Filter", "Load more"]) {
    const control = page.getByRole("button", { name: new RegExp(name, "i") });
    await expect(control).toBeVisible();
    const box = await control.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(360);
  }
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    ),
  ).toBe(false);

  await page.getByRole("button", { name: /load more/i }).click();
  await expect(page.getByText(/12 shown of 12 mapped/i)).toBeVisible();
  await page.getByLabel("From year").fill("2025");
  await page.getByLabel("To year").fill("2025");
  await page.getByRole("button", { name: /^filter$/i }).click();
  await expect(page.getByText("No authorities match these filters")).toBeVisible();
  await page.getByRole("button", { name: /reset/i }).click();
  await expect(page.getByText(/10 shown of 12 mapped/i)).toBeVisible();

  await page.goto(`/app/courts/judges/${fixture.emptyJudgeId}`);
  await expect(page.getByText("No mapped judgments for this judge")).toBeVisible();
  await page.goto(`/app/courts/judges/${fixture.noCorpusJudgeId}`);
  await expect(page.getByText("No mapped court corpus")).toBeVisible();

  await page.goto("/app/admin/judge-aliases");
  for (const name of ["Review queue", "Aliases", "Merge duplicates", "Reprocess"]) {
    await expect(page.getByRole("tab", { name })).toBeVisible();
  }
  await expect(page.getByText(/collision authority/i)).toBeVisible();
  await page.getByLabel("Canonical judge", { exact: true }).selectOption(fixture.judgeId);
  await page.getByLabel("Resolution note").fill("Official court roster confirms this evidence slot.");
  await page.getByRole("button", { name: /resolve evidence/i }).click();
  await expect(page.getByText("No open mapping reviews")).toBeVisible();

  await page.getByRole("tab", { name: "Aliases" }).click();
  const judgeForm = page.getByRole("heading", { name: "Judge alias" }).locator("..");
  await judgeForm
    .getByLabel("Canonical judge", { exact: true })
    .selectOption(fixture.judgeId);
  await judgeForm.getByLabel("Alias").fill(`Curator Alias ${Date.now()}`);
  await judgeForm
    .getByLabel("Official source URL")
    .fill("https://delhihighcourt.nic.in/web/Judges");
  await judgeForm.getByRole("button", { name: /add judge alias/i }).click();
  await expect(page.getByText(/Curator Alias/).last()).toBeVisible();

  await page.getByRole("tab", { name: "Merge duplicates" }).click();
  await page.getByLabel("Duplicate identity").selectOption(fixture.duplicateJudgeId);
  await page.getByLabel("Canonical destination").selectOption(fixture.judgeId);
  await page.getByLabel("Merge reason").fill("Official roster confirms a duplicate canonical identity.");
  await page.getByRole("button", { name: /merge identities/i }).click();
  await expect(page.getByText("Duplicate judge identities merged.")).toBeVisible();

  await page.getByRole("tab", { name: "Reprocess" }).click();
  await page.getByLabel("Authority document ID").fill(fixture.reviewAuthorityId);
  await page.getByRole("button", { name: /reprocess mapping/i }).click();
  await expect(page.getByText(/Remapped \d+; \d+ collisions; \d+ unresolved\./)).toBeVisible();

  await page.goto("/guide");
  await expect(page.getByRole("heading", { name: "Judge mapping and authority review" })).toBeVisible();
  await page.goto("/law-firms");
  await expect(page.getByRole("heading", { name: "Source-backed judge research" })).toBeVisible();
  await api.dispose();
});
