import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "StatuteTrust123!";

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

async function bootstrap(api: APIRequestContext, slug: string): Promise<string> {
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Statute Trust LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Source Curator",
      owner_email: email,
      owner_password: PASSWORD,
    },
  });
  expect(response.status()).toBe(200);
  return email;
}

test("IPLF-UJ-15/UJ-48: verified text, separated material, fail-closed exceptions, and 360px curator controls", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const api = await request.newContext();
  const slug = unique("iplf006c");
  const email = await bootstrap(api, slug);

  const login = await page.request.post(`${apiBaseUrl}/api/auth/login`, {
    data: {
      company_slug: slug,
      email,
      password: PASSWORD,
    },
  });
  expect(login.status()).toBe(200);
  const session = (await login.json()) as {
    access_token: string;
    company: unknown;
    user: unknown;
    membership: unknown;
    capabilities?: unknown;
  };
  await page.context().addCookies([
    {
      name: "caseops_session",
      value: session.access_token,
      url: apiBaseUrl,
      httpOnly: true,
      secure: false,
      sameSite: "Lax",
    },
  ]);
  await page.addInitScript((context) => {
    window.localStorage.setItem("caseops.session.context", JSON.stringify(context));
  }, {
    company: session.company,
    user: session.user,
    membership: session.membership,
    capabilities: session.capabilities,
  });
  await page.setViewportSize({ width: 360, height: 800 });

  let failClosed = false;
  await page.route("**/api/statutes/trust-act-2026/sections/12", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: {
        "Access-Control-Allow-Origin": "http://127.0.0.1:3100",
        "Access-Control-Allow-Credentials": "true",
      },
      body: JSON.stringify({
        statute: {
          id: "trust-act-2026",
          short_name: "Trust Act",
          long_name: "Source Trust Act, 2026",
          enacted_year: 2026,
          jurisdiction: "india",
          source_url: "https://www.indiacode.nic.in/handle/123456789/2026",
          issuing_body: "Legislative Department",
          source_category: "consolidated_statute",
          source_status: "official",
          legal_status: "enacted",
          verification_status: "verified_official",
          history_status: "current_text_only",
          is_active: true,
        },
        section: {
          id: "section-12",
          statute_id: "trust-act-2026",
          section_number: "12",
          section_label: "Independent source review",
          section_text: failClosed
            ? null
            : "Section 12. Independently reviewed statutory text.",
          section_text_source: failClosed ? "seed_catalog" : "official_source",
          editorial_notes: "Editorial commentary is not binding statutory text.",
          case_annotations: "A research annotation, not statutory text.",
          ai_explanation: "An AI explanation, not statutory text.",
          is_provisional: failClosed,
          verification_status: failClosed ? "quarantined" : "verified_official",
          source_sha256: failClosed ? null : "a".repeat(64),
          source_publisher: "India Code",
          issuing_body: "Legislative Department",
          source_category: "consolidated_statute",
          source_status: "official",
          legal_status: "enacted",
          publication_date: "2026-01-01",
          effective_from: "2026-02-01",
          effective_to: null,
          amendment_metadata_json: {},
          history_status: "current_text_only",
          exact_source_version: "consolidated-2026-08-04",
          source_locator_type: "section_deep_link",
          link_health_status: failClosed ? "missing" : "available",
          link_last_checked_at: "2026-08-04T10:00:00Z",
          link_last_error: failClosed ? "http_404" : null,
          source_retrieved_at: "2026-08-04T09:00:00Z",
          source_version: 2,
          verified_at: failClosed ? null : "2026-08-04T10:01:00Z",
          quarantine_reason: failClosed ? "Credible source conflict." : null,
          section_url: "https://www.indiacode.nic.in/show-data?actid=trust&orderno=12",
          parent_section_id: null,
          ordinal: 12,
          source_action: failClosed
            ? {
                state: "quarantined",
                open_url: null,
                source_reference: null,
                reason: "Credible source conflict.",
                target_type: "statute_section",
                target_id: "section-12",
              }
            : {
                state: "available",
                open_url: "/api/source-actions/targets/statute_section/section-12/open",
                source_reference: null,
                reason: null,
                target_type: "statute_section",
                target_id: "section-12",
              },
        },
        parent_section: null,
        child_sections: [],
      }),
    }),
  );
  await page.route("**/api/statutes/verification/sections/section-12/source-versions", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: {
        "Access-Control-Allow-Origin": "http://127.0.0.1:3100",
        "Access-Control-Allow-Credentials": "true",
      },
      body: JSON.stringify({
        versions: [
          {
            id: "proposal-2",
            section_id: "section-12",
            proposed_source_version: 2,
            candidate_text: "Section 12. Independently reviewed statutory text.",
            candidate_sha256: "a".repeat(64),
            source_url: "https://www.indiacode.nic.in/show-data?actid=trust&orderno=12",
            source_publisher: "India Code",
            issuing_body: "Legislative Department",
            source_category: "consolidated_statute",
            source_status: "official",
            legal_status: "enacted",
            source_locator_type: "section_deep_link",
            exact_source_version: "consolidated-2026-08-04",
            retrieved_at: "2026-08-04T09:00:00Z",
            publication_date: "2026-01-01",
            effective_from: "2026-02-01",
            effective_to: null,
            amendment_metadata_json: {},
            diff_unified: "+Independently reviewed statutory text.",
            status: "pending",
            proposed_by_membership_id: "membership-proposer",
            proposed_at: "2026-08-04T09:30:00Z",
            reviewed_by_membership_id: null,
            reviewed_at: null,
            review_reason: null,
          },
        ],
      }),
    }),
  );

  await page.goto("/app/statutes/trust-act-2026/sections/12");
  await expect(page.getByTestId("statute-section-text")).toContainText(
    "Independently reviewed statutory text",
  );
  await expect(page.getByRole("heading", { name: "Editorial notes" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Case annotations" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "AI explanation" })).toBeVisible();
  await expect(page.getByText("consolidated-2026-08-04")).toBeVisible();
  await expect(page.getByTestId("statute-act-landing-page")).toContainText(
    "not a section deep link",
  );
  await expect(page.getByTestId("statute-source-candidate")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Reject" })).toBeVisible();

  let overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);

  failClosed = true;
  await page.reload();
  await expect(page.getByText("Verified statutory text unavailable")).toBeVisible();
  await expect(page.getByText(/credible source conflict is under legal review/i)).toBeVisible();
  await expect(page.getByTestId("statute-section-text")).toHaveCount(0);
  await expect(page.getByText(/Not activated:/)).toBeVisible();
  overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
});
