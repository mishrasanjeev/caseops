import { expect, test } from "@playwright/test";

import { deadSelects } from "./support/ram-bugs4";

test("control audit follows fieldset, first-legend and option-group disabled states", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", request => requests.push(request.url()));
  await page.setContent(`
    <main>
      <label for="enabled">Enabled placeholder</label><select id="enabled"><option value="">Choose</option></select>
      <label for="own-disabled">Own disabled</label><select id="own-disabled" disabled><option value="">Choose</option></select>
      <fieldset disabled>
        <legend>Read-only fields</legend>
        <label for="inherited">Inherited disabled</label><select id="inherited"><option value="">Choose</option></select>
        <input name="matter_id" aria-label="Disabled internal field">
      </fieldset>
      <fieldset disabled>
        <legend><label for="first-legend">First legend placeholder</label><select id="first-legend"><option value="">Choose</option></select></legend>
        <label for="after-legend">After first legend</label><select id="after-legend"><option value="">Choose</option></select>
      </fieldset>
      <label for="group">Disabled group</label><select id="group"><option value="">Choose</option><optgroup disabled label="Retired"><option id="group-option" value="retired">Retired</option></optgroup></select>
      <label for="mixed">Mixed group</label><select id="mixed"><optgroup disabled label="Retired"><option value="retired">Retired</option></optgroup><option value="active">Active</option></select>
      <label for="option">Disabled option</label><select id="option"><option value="">Choose</option><option disabled value="retired">Retired</option></select>
      <select hidden aria-label="Hidden placeholder"><option value="">Choose</option></select>
    </main>
    <label for="outside">Outside scope</label><select id="outside"><option value="">Choose</option></select>
  `);

  await expect(page.getByLabel("Inherited disabled")).toBeDisabled();
  await expect(page.locator("#first-legend")).toBeEnabled();
  expect(await page.locator("#group-option").evaluate(option => (option as HTMLOptionElement).disabled)).toBe(false);
  expect(await page.locator("#group-option").evaluate(option => option.matches(":disabled"))).toBe(true);
  expect(await deadSelects(page, page.locator("main"))).toEqual([
    "Enabled placeholder", "First legend placeholder", "Disabled group", "Disabled option",
  ]);
  expect(await deadSelects(page)).toEqual([
    "Enabled placeholder", "First legend placeholder", "Disabled group", "Disabled option", "Outside scope",
  ]);
  expect(requests).toEqual([]);
});
