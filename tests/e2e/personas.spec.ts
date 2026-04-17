import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

// Per PRD §8.3 — the dashboard has to work for three personas. These
// tests run the same "sign in → dashboard → create first matter → open
// cockpit" happy path for a law-firm owner, a GC (company_type =
// corporate_legal), and a solo practitioner. They catch regressions
// that only surface on a non-default persona — for example, permission
// gates or empty-state copy that only looked right on one company type.

const PASSWORD = "PersonaPass123!";

type Persona = {
  slug: string;
  companyName: string;
  companyType: "law_firm" | "corporate_legal";
  ownerName: string;
  matterTitle: string;
  matterCode: string;
};

function makePersona(partial: Omit<Persona, "slug" | "matterCode">): Persona {
  const suffix = Math.random().toString(36).slice(2, 8);
  return {
    ...partial,
    slug: `${partial.companyName
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")}-${suffix}`,
    matterCode: `P-${suffix.toUpperCase()}`,
  };
}

async function bootstrap(api: APIRequestContext, persona: Persona): Promise<void> {
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: persona.companyName,
      company_slug: persona.slug,
      company_type: persona.companyType,
      owner_full_name: persona.ownerName,
      owner_email: `owner-${persona.slug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  if (resp.status() === 409) return;
  if (resp.status() !== 200) {
    throw new Error(
      `Bootstrap failed for ${persona.slug}: ${resp.status()} ${await resp.text()}`,
    );
  }
}

async function runPersonaFlow(page: Page, persona: Persona): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(persona.slug);
  await page.locator("#email").fill(`owner-${persona.slug}@example.com`);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();

  // Dashboard.
  await page.waitForURL("**/app");
  await expect(
    page.getByRole("heading", { name: /Good to have you back/i }),
  ).toBeVisible();
  // First-time owners see the "0 total in workspace" hint.
  await expect(page.getByText(/total in workspace/i)).toBeVisible();

  // Click through via the sidebar — the client-side transition has to
  // survive the queryKey reconciliation between dashboard (useQuery)
  // and the matters list (useInfiniteQuery).
  await page.getByRole("link", { name: "Matters", exact: true }).click();
  await page.waitForURL("**/app/matters");
  await expect(page.getByRole("heading", { name: /Matter portfolio/i })).toBeVisible();

  await page.getByTestId("new-matter-trigger").first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Title").fill(persona.matterTitle);
  await dialog.getByLabel("Matter code").fill(persona.matterCode);
  await dialog.getByLabel("Practice area").fill("Commercial");
  await dialog.getByRole("button", { name: /Create matter/i }).click();
  await expect(dialog).toBeHidden();

  // The new matter appears in the portfolio.
  await expect(page.getByText(persona.matterTitle)).toBeVisible();
}

test.describe("Personas (PRD §8.3)", () => {
  test("law-firm owner can sign in and create a first matter", async ({ page }) => {
    const persona = makePersona({
      companyName: `Law Firm ${Math.random().toString(36).slice(2, 5)}`,
      companyType: "law_firm",
      ownerName: "Asha Partner",
      matterTitle: "Rao v. State — Bail",
    });
    const api = await request.newContext();
    await bootstrap(api, persona);
    await runPersonaFlow(page, persona);
  });

  test("corporate GC can sign in and create a first matter", async ({ page }) => {
    const persona = makePersona({
      companyName: `Corp Legal ${Math.random().toString(36).slice(2, 5)}`,
      companyType: "corporate_legal",
      ownerName: "Deepa GC",
      matterTitle: "Vendor Dispute — Arbitration",
    });
    const api = await request.newContext();
    await bootstrap(api, persona);
    await runPersonaFlow(page, persona);
  });

  test("solo practitioner can sign in and create a first matter", async ({ page }) => {
    const persona = makePersona({
      companyName: `Solo ${Math.random().toString(36).slice(2, 5)}`,
      companyType: "law_firm",
      ownerName: "Ravi Solo",
      matterTitle: "Notice reply — Consumer",
    });
    const api = await request.newContext();
    await bootstrap(api, persona);
    await runPersonaFlow(page, persona);
  });
});
