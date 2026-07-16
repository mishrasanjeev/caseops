/**
 * Hari 2026-06-27 workbook regressions.
 *
 * BUG-001: Context Research must suppress low-quality OCR authority cards when
 * readable authorities match the same natural-language query.
 * BUG-002: Research filter changes must not disable or auto-fire Search before
 * the user submits, in both keyword and contextual modes.
 *
 * Case-reopening audit: a disposed matter must remain disposed after reload.
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "HariJun27Bugs!";
const CHEQUE_QUERY =
  "Cheque bounced due to insufficient funds and notice was sent after 35 days";

function unique(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 8)}`;
}

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ token: string; ownerEmail: string }> {
  const ownerEmail = `owner-${slug}@example.com`;
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Hari 2026-06-27 LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Hari Jun27 Owner",
      owner_email: ownerEmail,
      owner_password: PASSWORD,
    },
  });
  expect(resp.status(), await resp.text()).toBe(200);
  const body = (await resp.json()) as { access_token: string };
  return { token: body.access_token, ownerEmail };
}

async function createMatter(
  api: APIRequestContext,
  token: string,
  code: string,
): Promise<string> {
  const resp = await api.post(`${apiBaseUrl}/api/matters/`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      title: `Hari Jun27 matter ${code}`,
      matter_code: code,
      practice_area: "commercial",
      forum_level: "high_court",
      status: "intake",
      court_name: "Delhi High Court",
    },
  });
  expect(resp.status(), await resp.text()).toBe(200);
  return ((await resp.json()) as { id: string }).id;
}

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app/);
}

async function chooseOption(page: Page, testId: string, name: string): Promise<void> {
  await page.getByTestId(testId).click();
  await page.getByRole("option", { name }).click();
}

test.describe("Hari 2026-06-27 bugs", () => {
  test.setTimeout(120_000);

  test("BUG-001: Context Research suppresses unreadable OCR authority cards", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h62701");
    const { ownerEmail } = await bootstrap(api, slug);
    await api.dispose();
    await signIn(page, slug, ownerEmail);

    const searchPayloads: Record<string, unknown>[] = [];
    await page.route("**/api/authorities/search", async (route) => {
      searchPayloads.push(route.request().postDataJSON() as Record<string, unknown>);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          query: CHEQUE_QUERY,
          mode: "contextual",
          provider: "caseops-authority-contextual-search-v1",
          generated_at: new Date().toISOString(),
          contextual_plan: {
            key_facts: ["cheque dishonour", "insufficient funds"],
            likely_issues: ["demand notice timing for cheque dishonour"],
            statutes_or_sections: [
              "Section 138 Negotiable Instruments Act",
              "Section 142 Negotiable Instruments Act",
            ],
            procedural_posture: [],
            jurisdiction_hints: [],
            timing_signals: ["after 35 days"],
            planned_query: CHEQUE_QUERY,
          },
          coverage_notice: null,
          total_after_filter: 2,
          offset: 0,
          results: [
            {
              authority_document_id: "clean-cheque-138",
              title: "Cheque dishonour demand notice limitation under Section 138",
              court_name: "High Court of Delhi",
              forum_level: "high_court",
              document_type: "judgment",
              decision_date: "2026-05-01",
              case_reference: "CRL.A. 138/2026",
              bench_name: "Justice A. Rao",
              summary:
                "Readable authority on Section 138, Section 142, insufficient funds, and notice timing.",
              source: "test",
              source_reference: "https://official.example.test/cheque-138.pdf",
              snippet:
                "A cheque was dishonoured for insufficient funds. The court analysed Section 138 and Section 142 where demand notice timing was disputed.",
              score: 245,
              matched_terms: ["cheque", "notice", "section", "138"],
              relevance_reason:
                "Source-backed match on Section 138 Negotiable Instruments Act.",
              worst_treatment: null,
              adverse_count: 0,
            },
            {
              authority_document_id: "garbled-cheque-138",
              title: "Cheque dishonour Section 138 notice delay OCR damaged record",
              court_name: "High Court of Delhi",
              forum_level: "high_court",
              document_type: "judgment",
              decision_date: "2026-06-01",
              case_reference: "CRL.A. OCR/2026",
              bench_name: "Justice OCR Damaged",
              summary: "OCR damaged record matching the same cheque dishonour query.",
              source: "test",
              source_reference: "https://official.example.test/garbled.pdf",
              snippet:
                "Section 138 cheque notice insufficient funds after 35 days $O ?J '>2> 380 :J $)2J* J!'>) /=, +> +/2J?(=2>) :J ?( $!?( ! ?2J: 488 $O 477 .*J.:J.",
              score: 240,
              matched_terms: ["cheque", "notice", "section", "138"],
              relevance_reason:
                "Source-backed match on Section 138 Negotiable Instruments Act.",
              worst_treatment: null,
              adverse_count: 0,
            },
          ],
        }),
      });
    });

    await page.goto("/app/research");
    await page.getByTestId("research-mode-contextual").click();
    await page.getByTestId("research-query-input").fill(CHEQUE_QUERY);
    await page.getByTestId("research-query-submit").click();

    await expect(page.getByTestId("research-contextual-plan")).toBeVisible();
    await expect(
      page.getByText("Cheque dishonour demand notice limitation under Section 138"),
    ).toBeVisible();
    await expect(
      page.getByText("Cheque dishonour Section 138 notice delay OCR damaged record"),
    ).toHaveCount(0);
    await expect(page.getByTestId("research-result-garbled")).toHaveCount(0);
    await expect(page.getByText(/\$O \?J/)).toHaveCount(0);
    expect(searchPayloads).toHaveLength(1);
    expect(searchPayloads[0]).toMatchObject({
      mode: "contextual",
      query: CHEQUE_QUERY,
    });
  });

  for (const mode of ["keyword", "contextual"] as const) {
    test(`BUG-002: filter changes keep Search enabled in ${mode} mode`, async ({
      page,
    }) => {
      const api = await request.newContext();
      const slug = unique(`h62702-${mode}`);
      const { ownerEmail } = await bootstrap(api, slug);
      await api.dispose();
      await signIn(page, slug, ownerEmail);

      const searchPayloads: Record<string, unknown>[] = [];
      await page.route("**/api/authorities/search", async (route) => {
        searchPayloads.push(route.request().postDataJSON() as Record<string, unknown>);
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            query: "Section 138 notice delay",
            mode,
            provider: "caseops-authority-search-v2",
            generated_at: new Date().toISOString(),
            contextual_plan: mode === "contextual" ? null : undefined,
            coverage_notice: null,
            total_after_filter: 0,
            offset: 0,
            results: [],
          }),
        });
      });

      await page.goto("/app/research");
      await page.getByTestId(`research-mode-${mode}`).click();
      await page.getByTestId("research-query-input").fill("Section 138 notice delay");
      await chooseOption(page, "research-filter-forum", "High Court");
      await page.getByTestId("research-filter-court").fill("Delhi");
      await chooseOption(page, "research-filter-doctype", "Judgment");

      await expect(page.getByTestId("research-query-submit")).toBeEnabled();
      expect(searchPayloads).toHaveLength(0);

      await page.getByTestId("research-query-submit").click();

      await expect.poll(() => searchPayloads.length).toBe(1);
      expect(searchPayloads[0]).toMatchObject({
        query: "Section 138 notice delay",
        mode,
        forum_level: "high_court",
        court_name: "Delhi",
        document_type: "judgment",
      });
    });
  }

  test("case-reopening audit: disposed matter remains disposed after reload", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h627status");
    const { token, ownerEmail } = await bootstrap(api, slug);
    const matterId = await createMatter(api, token, "H627-STATUS");
    await api.dispose();
    await signIn(page, slug, ownerEmail);

    await page.goto("/app/matters");
    // Clickable DataTable rows intentionally expose role="button" for keyboard
    // activation, so locate the semantic <tr> directly instead of asking for
    // the overridden ARIA row role.
    const matterRow = page
      .locator('tr[role="button"]')
      .filter({ hasText: "H627-STATUS" });
    await expect(matterRow).toBeVisible({ timeout: 15_000 });

    const patchResponse = page.waitForResponse(
      (response) =>
        response.url().includes(
          `/api/matters/${matterId}/lifecycle/status`,
        ) &&
        response.request().method() === "PATCH",
    );
    await matterRow.getByTestId("matter-dispose-trigger").click();
    const lifecycleDialog = page.getByRole("dialog", {
      name: "Dispose matter",
    });
    await lifecycleDialog
      .getByTestId("matter-lifecycle-reason")
      .fill("Final order closed the June 27 regression matter.");
    await lifecycleDialog.getByTestId("matter-lifecycle-confirm").click();
    const disposedResponse = await patchResponse;
    expect(disposedResponse.status()).toBe(200);
    expect(((await disposedResponse.json()) as { status: string }).status).toBe(
      "disposed",
    );
    await expect(
      matterRow.getByTestId("matter-reopen-trigger"),
    ).toBeVisible();
    await expect(matterRow.getByLabel("Status for H627-STATUS")).toHaveCount(0);

    await page.reload();
    const reloadedMatterRow = page
      .locator('tr[role="button"]')
      .filter({ hasText: "H627-STATUS" });
    await expect(
      reloadedMatterRow.getByTestId("matter-reopen-trigger"),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      reloadedMatterRow.getByLabel("Status for H627-STATUS"),
    ).toHaveCount(0);
  });
});
