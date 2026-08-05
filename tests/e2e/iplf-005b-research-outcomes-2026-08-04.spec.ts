import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "ResearchOutcomes123!";

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

async function bootstrap(api: APIRequestContext, slug: string): Promise<string> {
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Research Outcomes LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Research Owner",
      owner_email: email,
      owner_password: PASSWORD,
    },
  });
  expect(response.status()).toBe(200);
  return email;
}

test("IPLF-UJ-16-NORMAL/EXC: typed outcomes, frozen query, report, and 360px controls", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const api = await request.newContext();
  const slug = unique("iplf005b");
  const email = await bootstrap(api, slug);

  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app/);
  await page.setViewportSize({ width: 360, height: 800 });

  await page.route("**/api/authorities/stats", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        document_count: 0,
        chunk_count: 0,
        embedded_chunk_count: 0,
        forum_counts: {},
        last_ingested_at: null,
      }),
    }),
  );

  let searchCount = 0;
  await page.route("**/api/authorities/search", async (route) => {
    searchCount += 1;
    const requestBody = route.request().postDataJSON() as Record<string, unknown>;
    if (searchCount === 1) {
      expect(requestBody.query).toBe("Section 11 trademark");
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          query: requestBody.query,
          mode: "keyword",
          provider: "caseops-authority-search-v2",
          generated_at: "2026-08-04T10:00:00Z",
          results: [],
          contextual_plan: null,
          coverage_notice: "The authority corpus is unavailable.",
          total_after_filter: 0,
          offset: 0,
          outcome: "corpus_unavailable",
          diagnostics: {},
          corpus_coverage: {
            document_count: 0,
            chunk_count: 0,
            embedded_chunk_count: 0,
            forum_counts: {},
            last_ingested_at: null,
            last_indexed_at: null,
            index_state: "unavailable",
            scope_summary: "indexed authority corpus; en language scope",
          },
        }),
      });
      return;
    }
    expect(requestBody.mode).toBe("exact_citation");
    expect(requestBody.query).toBe("2026:DHC:111");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        query: requestBody.query,
        mode: "exact_citation",
        provider: "caseops-authority-search-v2",
        generated_at: "2026-08-04T10:01:00Z",
        results: [
          {
            authority_document_id: "authority-111",
            title: "Aster Labs v Registrar of Trade Marks",
            court_name: "Delhi High Court",
            forum_level: "high_court",
            document_type: "judgment",
            decision_date: "2026-07-01",
            case_reference: "CS(COMM) 11/2026",
            neutral_citation: "2026:DHC:111",
            bench_name: "Justice A. Rao",
            summary: "Relative grounds for refusal under Section 11.",
            source: "Delhi High Court",
            source_reference: "https://official.example.test/authority-111.pdf",
            source_action: {
              state: "available",
              label: "Open source",
              open_url: "/api/source-actions/open?url=https%3A%2F%2Fofficial.example.test%2Fauthority-111.pdf",
              source_reference: "https://official.example.test/authority-111.pdf",
              reason: null,
              opens_new_tab: true,
            },
            snippet: "The Court considered relative grounds under Section 11.",
            score: 210,
            matched_terms: ["2026:DHC:111"],
            relevance_reason: "Why this result: exact citation metadata match. Verify the source before relying on it.",
            worst_treatment: null,
            adverse_count: 0,
          },
        ],
        contextual_plan: null,
        coverage_notice: null,
        total_after_filter: 1,
        offset: 0,
        outcome: "results_found",
        diagnostics: { returned_count: 1 },
        corpus_coverage: {
          document_count: 1,
          chunk_count: 1,
          embedded_chunk_count: 1,
          forum_counts: { high_court: 1 },
          last_ingested_at: "2026-08-04T09:00:00Z",
          last_indexed_at: "2026-08-04T09:01:00Z",
          index_state: "current",
          scope_summary: "indexed authority corpus; en language scope",
        },
      }),
    });
  });

  let savedReportBody: Record<string, unknown> | null = null;
  await page.route("**/api/authorities/research-reports", async (route) => {
    savedReportBody = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({ id: "report-111" }),
    });
  });

  await page.goto("/app/research");
  const modeButtons = ["Keyword", "Context", "Citation", "Party", "Court", "Judge", "Act / section"];
  for (const name of modeButtons) {
    await expect(page.getByRole("button", { name, exact: true })).toBeVisible();
  }

  const query = page.getByTestId("research-query-input");
  await query.fill("Section 11 trademark");
  await page.getByTestId("research-query-submit").click();
  await expect(page.getByText("Corpus unavailable", { exact: true })).toBeVisible();

  await query.fill("draft filters stay editable");
  await expect(page.getByText("Corpus unavailable", { exact: true })).toBeVisible();
  await page.getByTestId("research-mode-exact-citation").click();
  await query.fill("2026:DHC:111");
  await page.getByTestId("research-query-submit").click();
  await expect(page.getByText("Aster Labs v Registrar of Trade Marks")).toBeVisible();
  await expect(page.getByText(/Publisher: Delhi High Court/)).toBeVisible();
  await expect(page.getByText(/2026:DHC:111/).first()).toBeVisible();
  await expect(page.getByTestId("research-result-relevance")).toContainText("exact citation");

  await page.getByTestId("research-save-report").click();
  await expect.poll(() => savedReportBody).not.toBeNull();
  expect(savedReportBody?.result_ids).toEqual(["authority-111"]);
  expect(savedReportBody?.mode).toBe("exact_citation");

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
});
