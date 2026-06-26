/**
 * Hari 2026-06-26 workbook regressions.
 *
 * BUG-001: Context Research must not expose unreadable OCR snippets for
 * natural-language Section 138 / Section 142 cheque-dishonour searches.
 * BUG-002: New Matter must reject matter codes with spaces or special
 * characters before submit.
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "HariJun26Bugs!";
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
): Promise<{ ownerEmail: string }> {
  const ownerEmail = `owner-${slug}@example.com`;
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Hari 2026-06-26 LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Hari Jun26 Owner",
      owner_email: ownerEmail,
      owner_password: PASSWORD,
    },
  });
  if (resp.status() !== 200) {
    throw new Error(`Bootstrap failed with HTTP ${resp.status()}: ${await resp.text()}`);
  }
  return { ownerEmail };
}

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app/);
}

test.describe("Hari 2026-06-26 bugs", () => {
  test.setTimeout(120_000);

  test("BUG-001: Context Research hides low-quality OCR previews for cheque dishonour query", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h62601");
    let ownerEmail = "";
    try {
      ({ ownerEmail } = await bootstrap(api, slug));
    } finally {
      await api.dispose();
    }
    await signIn(page, slug, ownerEmail);

    let searchPayload: Record<string, unknown> | null = null;
    await page.route("**/api/authorities/search", async (route) => {
      searchPayload = route.request().postDataJSON() as Record<string, unknown>;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          query: CHEQUE_QUERY,
          mode: "contextual",
          provider: "caseops-authority-contextual-search-v1",
          generated_at: new Date().toISOString(),
          contextual_plan: {
            key_facts: ["cheque dishonour", "dishonour for insufficient funds"],
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
                "A cheque was dishonoured for insufficient funds. The court analysed Section 138 and Section 142 of the Negotiable Instruments Act where demand notice timing was disputed.",
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
    await expect(page.getByTestId("research-result-garbled")).toBeVisible();
    await expect(page.getByText(/\$O \?J/)).toHaveCount(0);
    expect(searchPayload?.mode).toBe("contextual");
    expect(searchPayload?.query).toBe(CHEQUE_QUERY);
  });

  test("BUG-002: New Matter rejects invalid matter code before API submission", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h62602");
    let ownerEmail = "";
    try {
      ({ ownerEmail } = await bootstrap(api, slug));
    } finally {
      await api.dispose();
    }
    await signIn(page, slug, ownerEmail);

    const matterCreateRequests: string[] = [];
    page.on("request", (req) => {
      if (req.method() === "POST" && req.url().endsWith("/api/matters/")) {
        matterCreateRequests.push(req.postData() ?? "");
      }
    });

    await page.goto("/app/matters");
    await page.getByTestId("new-matter-trigger").first().click();
    await expect(page.getByTestId("new-matter-forum-state")).toHaveValue("Delhi");
    await page.getByLabel("Title").fill("Invalid matter code workflow");
    await page.getByLabel("Matter code").fill("BAD CODE/1");
    await page.getByLabel("Practice area").fill("Commercial");
    await page.getByRole("button", { name: /Create matter/i }).click();

    await expect(page.getByRole("alert")).toContainText(
      /letters, numbers, and hyphens only/i,
    );
    await expect(page.getByRole("dialog", { name: /New matter/i })).toBeVisible();
    expect(matterCreateRequests).toEqual([]);
  });
});
