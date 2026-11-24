/**
 * J14/M13, US-040, FT-007/FT-008, SEC-004, NFT-013: the Admin ethical-walls
 * screen. An owner walls a colleague off one litigation Matter with an
 * explicit confirmation, the walled colleague can no longer find or open that
 * Matter (while an unwalled Matter stays visible), and lifting the wall
 * restores access. Runs at 1280px and at 393px (`[mobile]`, Pixel 5 project).
 */
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { createNoPaidApiContext } from "./support/cost-controls";
import { apiBaseUrl } from "./support/env";

const PASSWORD = "EthicalWalls2026!";

function nonce(): string {
  return Math.random().toString(36).slice(2, 8);
}

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^sign in$/i }).click();
  await page.waitForURL(/\/app(\/|$|\?)/, { timeout: 30_000 });
}

async function expectNoHorizontalScroll(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, "page must not scroll horizontally").toBeLessThanOrEqual(0);
}

for (const mobile of [false, true]) {
  const width = mobile ? 393 : 1280;
  test(`${mobile ? "[mobile] " : ""}admin walls a colleague off a Matter and lifts the wall at ${width}px`, async ({ page }) => {
    test.setTimeout(180_000);
    await page.setViewportSize(mobile ? { width: 393, height: 851 } : { width: 1280, height: 900 });
    const api = await createNoPaidApiContext(apiBaseUrl);
    try {
      const id = nonce();
      const slug = `walls-${id}`;
      const ownerEmail = `owner-${slug}@example.com`;
      const memberEmail = `member-${slug}@example.com`;
      const memberName = `Walled Colleague ${id}`;

      const boot = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
        data: {
          company_name: "Ethical Walls E2E LLP",
          company_slug: slug,
          company_type: "law_firm",
          owner_full_name: "Walls Owner",
          owner_email: ownerEmail,
          owner_password: PASSWORD,
        },
      });
      expect(boot.status(), await boot.text()).toBe(200);
      const owner = { Authorization: `Bearer ${(await boot.json()).access_token as string}` };

      const createMatter = async (code: string, title: string): Promise<string> => {
        const resp = await api.post(`${apiBaseUrl}/api/matters/`, {
          headers: owner,
          data: {
            title,
            matter_code: code,
            client_name: "Walls Client",
            practice_area: "Commercial",
            forum_level: "high_court",
            status: "active",
          },
        });
        expect(resp.status(), await resp.text()).toBe(200);
        return (await resp.json()).id as string;
      };
      const walledCode = `EW-${id.toUpperCase()}-W`;
      const openCode = `EW-${id.toUpperCase()}-O`;
      const walledMatter = await createMatter(walledCode, "Conflicted brief");
      await createMatter(openCode, "Unconflicted brief");

      const member = await api.post(`${apiBaseUrl}/api/companies/current/users`, {
        headers: owner,
        data: { full_name: memberName, email: memberEmail, role: "member", password: PASSWORD },
      });
      expect(member.status(), await member.text()).toBe(200);
      const memberId = (await member.json()).membership_id as string;

      // Owner sets the wall up from Admin, through the confirmation step.
      await signIn(page, slug, ownerEmail);
      await page.goto("/app/admin");
      const card = page.getByTestId("matter-ethical-walls");
      await expect(card).toBeVisible();
      await expect(card.getByTestId("matter-walls-empty")).toBeVisible();
      const matterSelect = card.locator("#matter-wall-matter");
      await expect(matterSelect.locator(`option[value="${walledMatter}"]`)).toHaveCount(1);
      await matterSelect.selectOption(walledMatter);
      const people = card.getByTestId("matter-wall-people");
      await expect(people.getByRole("checkbox", { name: /Walls Owner/ })).toBeDisabled();
      await people.getByRole("checkbox", { name: new RegExp(memberName) }).check();
      await card.getByLabel("Reason (optional)").fill("Acted for the respondent before joining.");
      await card.getByTestId("matter-wall-review").click();
      const confirm = card.getByTestId("matter-wall-confirm");
      await expect(confirm).toContainText(`Wall off ${memberName} from ${walledCode}`);
      await expectNoHorizontalScroll(page);
      await confirm.getByRole("button", { name: "Confirm wall" }).click();
      await expect(card.getByTestId("matter-wall-result")).toHaveText(
        `Wall set up: ${memberName} can no longer open ${walledCode}.`,
      );
      const group = card.getByTestId(`matter-walls-${walledCode}`);
      await expect(group).toContainText(memberName);
      await expect(group).toContainText("Acted for the respondent before joining.");
      await expect(group).toContainText("Walls Owner");
      await expectNoHorizontalScroll(page);

      const directory = await api.get(`${apiBaseUrl}/api/matters/ethical-walls`, { headers: owner });
      expect(directory.status()).toBe(200);
      const walls = (await directory.json()).walls as Array<{ matter_id: string; excluded_membership_id: string }>;
      expect(walls.map((row) => [row.matter_id, row.excluded_membership_id])).toEqual([[walledMatter, memberId]]);

      // What the walled colleague sees: the Matter is gone from the list and
      // its URL answers "not found"; the unwalled Matter is still there.
      await page.context().clearCookies();
      await signIn(page, slug, memberEmail);
      await page.goto("/app/matters");
      await expect(page.getByText(openCode).first()).toBeVisible();
      await expect(page.getByText(walledCode)).toHaveCount(0);
      await page.goto(`/app/matters/${walledMatter}`);
      await expect(page.getByText("Matter not found")).toBeVisible();

      // Owner lifts the wall, again only after confirmation.
      await page.context().clearCookies();
      await signIn(page, slug, ownerEmail);
      await page.goto("/app/admin");
      const liftGroup = page.getByTestId(`matter-walls-${walledCode}`);
      await liftGroup.getByRole("button", { name: `Lift wall for ${memberName} on ${walledCode}` }).click();
      await expect(liftGroup).toContainText(`${memberName} regains normal access to ${walledCode}.`);
      await liftGroup.getByRole("button", { name: "Confirm lift" }).click();
      await expect(page.getByTestId(`matter-walls-${walledCode}`)).toHaveCount(0);
      await expect(page.getByTestId("matter-walls-empty")).toBeVisible();

      // Access is back for the colleague.
      await page.context().clearCookies();
      await signIn(page, slug, memberEmail);
      await page.goto(`/app/matters/${walledMatter}`);
      await expect(page.getByText("Matter not found")).toHaveCount(0);
      await expect(page.getByText(walledCode).first()).toBeVisible();
    } finally {
      await api.dispose();
    }
  });
}
