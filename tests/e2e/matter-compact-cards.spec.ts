import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";

import type { BenchStrategy, OutsideCounselRecommendationsResult } from "../../apps/web/lib/api/endpoints";
import { localTransportHeaders } from "./support/cost-controls";
import { apiBaseUrl } from "./support/env";
import { expectNoPageOverflow, json, reportedDevicePress, signIn } from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off" });

const PASSWORD = "CompactCardsProof2026!";

test.describe("BUG-016 compact Matter cards", () => {
  for (const phone of [false, true]) {
    test(phone ? "[mobile] populated counsel and bench disclosures" : "populated counsel and bench disclosures",
      async ({ page, request: api, baseURL }, info) => {
        if (!baseURL) throw new Error("Compact card verification requires a local web origin");
        const web = new URL(baseURL);
        if (web.protocol !== "http:" || !["localhost", "127.0.0.1", "[::1]"].includes(web.hostname)
          || web.username || web.password || web.pathname !== "/" || web.search || web.hash) {
          throw new Error("Compact card fixture creation is loopback-only");
        }
        await page.setViewportSize(phone ? { width: 393, height: 851 } : { width: 1365, height: 900 });
        const press = await reportedDevicePress(page, info, phone);
        const slug = `compact-${randomUUID()}`;
        const transport = localTransportHeaders(apiBaseUrl);
        const mutation = { maxRetries: 0, maxRedirects: 0 };
        const { access_token: token } = await json<{ access_token: string }>(
          await api.post(`${apiBaseUrl}/api/bootstrap/company`, { ...mutation, headers: transport, data: {
            company_name: "Compact cards QA LLP", company_slug: slug, company_type: "law_firm",
            owner_full_name: "Compact Cards QA", owner_email: `owner-${slug}@example.com`, owner_password: PASSWORD,
          } }), "Local compact-card owner bootstrap",
        );
        const headers = { ...transport, Authorization: `Bearer ${token}` };
        const matter = await json<{ id: string; matter_code: string }>(await api.post(`${apiBaseUrl}/api/matters/`, {
          ...mutation, headers, data: { title: "Compact card review", matter_code: `COMPACT-${randomUUID()}`,
            practice_area: "Commercial Litigation", forum_level: "high_court", status: "intake" },
        }), "Create local compact-card matter");
        const preferredName = "ChandrasekharanInternationalCommercialLitigationAndArbitrationCounsel";
        const inactiveName = "Inactive Civil Counsel";
        const preferred = await json<{ id: string }>(await api.post(`${apiBaseUrl}/api/outside-counsel/profiles`, {
          ...mutation, headers, data: { name: preferredName, panel_status: "preferred", practice_areas: ["Commercial Litigation"] },
        }), "Create local preferred counsel");
        const inactive = await json<{ id: string }>(await api.post(`${apiBaseUrl}/api/outside-counsel/profiles`, {
          ...mutation, headers, data: { name: inactiveName, panel_status: "inactive", practice_areas: ["Civil"] },
        }), "Create local inactive counsel");
        for (const [currency, amount] of [["INR", 15], ["USD", 23]] as const) {
          const recorded = await json<{ currency: string; approved_amount_minor: number }>(
            await api.post(`${apiBaseUrl}/api/outside-counsel/spend-records`, {
              ...mutation, headers, data: { matter_id: matter.id, counsel_id: preferred.id,
                description: "Compact counsel approved spend", currency, amount_minor: amount,
                approved_amount_minor: amount, status: "approved" },
            }), "Create local approved panel spend",
          );
          expect(recorded).toMatchObject({ currency, approved_amount_minor: amount });
        }

        // Only this bench response is synthetic. Counsel rankings come from the real API.
        const benchPath = `/api/matters/${matter.id}/bench-strategy`;
        const statuteLabel = "Synthetic long statute label for testing complete text at narrow viewport widths";
        const authorityTitle = "SyntheticUnbrokenAuthorityTitleForBenchStrategyHorizontalWrapping";
        const fixture: BenchStrategy = {
          matter_id: matter.id, bench_judge_ids: ["synthetic-judge"], total_decisions_indexed: 47,
          evidence_quality: "strong",
          top_authorities: [{ authority_id: "synthetic-authority", title: authorityTitle, citation_count: 12,
            last_year: 2024, sample_judgment_id: null }],
          top_statute_sections: [{ statute_section_id: "synthetic-section", statute_id: "synthetic-act",
            section_number: "101A", section_label: statuteLabel, citation_count: 8, last_year: 2025, sample_judgment_id: null }],
          disclaimer: "Statistical analysis based on indexed decisions only. Not legal advice.",
        };
        await page.route(url => url.origin === apiBaseUrl && url.pathname === benchPath, async route => {
          const outgoing = route.request();
          if (outgoing.method() === "OPTIONS") return route.continue();
          if (outgoing.method() !== "GET" || outgoing.headers()["x-caseops-automated-test"] !== "no-paid-providers") {
            await route.abort("blockedbyclient");
            throw new Error("Unexpected or unmarked bench request");
          }
          await route.fulfill({ json: fixture, headers: {
            "Access-Control-Allow-Origin": web.origin, "Access-Control-Allow-Credentials": "true",
          } });
        });
        await signIn(page, { web }, { slug, email: `owner-${slug}@example.com`, password: PASSWORD });
        const recommendations = page.waitForResponse(response => {
          const url = new URL(response.url());
          return url.origin === apiBaseUrl && url.pathname === "/api/outside-counsel/recommendations"
            && response.request().method() === "POST" && response.request().postDataJSON()?.matter_id === matter.id;
        });
        await page.goto(`/app/matters/${matter.id}`);
        const response = await recommendations;
        expect(response.request().headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
        expect(await response.finished()).toBeNull();
        const payload = await json<OutsideCounselRecommendationsResult>(response, "Canonical counsel recommendations");
        expect(payload.matter_id).toBe(matter.id);
        expect(payload.results.map(row => [row.counsel_id, row.score])).toEqual([[preferred.id, 8], [inactive.id, -2]]);
        expect(payload.results.map(row => row.approved_spend_by_currency)).toEqual([
          [{ currency: "INR", approved_spend_minor: 15 }, { currency: "USD", approved_spend_minor: 23 }], [],
        ]);

        const counsel = page.getByTestId("counsel-recommendations-card");
        const preferredToggle = counsel.locator("summary").filter({ hasText: preferredName });
        const inactiveToggle = counsel.locator("summary").filter({ hasText: inactiveName });
        const practiceEvidence = counsel.getByText("Practice area match for Commercial Litigation.", { exact: true });
        const inactiveEvidence = counsel.getByText("Inactive panel status reduces ranking.", { exact: true });
        const spendBreakdown = counsel.locator('dl[aria-label="Approved spend by currency"]');
        await expect(preferredToggle.getByText("8 pts", { exact: true })).toBeVisible();
        await expect(inactiveToggle.getByText("-2 pts", { exact: true })).toBeVisible();
        await expect(practiceEvidence).toBeHidden();
        await expect(inactiveEvidence).toBeHidden();
        await expect(spendBreakdown).toBeHidden();

        const panel = page.getByTestId("bench-strategy-panel");
        const statuteToggle = panel.locator("summary").filter({ hasText: /^Top statute sections cited \(1\)$/ });
        const authorityToggle = panel.locator("summary").filter({ hasText: /^Top authorities cited \(1\)$/ });
        const statutes = panel.getByTestId("bench-strategy-statutes");
        const authorities = panel.getByTestId("bench-strategy-authorities");
        await expect(panel.getByTestId("bench-strategy-quality-chip")).toContainText("Strong evidence base");
        await expect(panel.getByTestId("bench-strategy-disclaimer")).toContainText("Not legal advice");
        await expect(statutes).toBeHidden();
        await expect(authorities).toBeHidden();

        for (const [toggle, details] of [[preferredToggle, practiceEvidence], [inactiveToggle, inactiveEvidence],
          [statuteToggle, statutes], [authorityToggle, authorities]] as const) {
          await expect(toggle).toBeVisible();
          if (phone) {
            const target = await toggle.boundingBox();
            expect(target?.height).toBeGreaterThanOrEqual(44);
            expect(target?.width).toBeGreaterThanOrEqual(44);
            await toggle[press]();
          } else {
            await toggle.focus();
            await toggle.press("Space");
            await expect(toggle).toBeFocused();
          }
          await expect(details).toBeVisible();
        }
        await expect(statutes.getByText(statuteLabel, { exact: true })).toBeVisible();
        await expect(authorities.getByText(authorityTitle, { exact: true })).toBeVisible();
        await expect(spendBreakdown.locator("dt")).toHaveText(["INR", "USD"]);
        await expect(spendBreakdown.locator("dd")).toHaveText(["₹0.15", "$0.23"]);
        await expectNoPageOverflow(page);
        for (const name of [preferredToggle.getByText(preferredName, { exact: true }),
          statutes.getByText(statuteLabel, { exact: true }), authorities.getByText(authorityTitle, { exact: true })]) {
          expect(await name.evaluate(element => element.scrollWidth <= element.clientWidth + 1
            && element.scrollHeight <= element.clientHeight + 1), "Complete label must fit without clipping").toBe(true);
        }
        if (phone) {
          await preferredToggle[press]();
          await statuteToggle[press]();
        } else {
          await preferredToggle.press("Space");
          await page.keyboard.press("Tab");
          await expect(inactiveToggle).toBeFocused();
          await statuteToggle.press("Space");
          await page.keyboard.press("Tab");
          await expect(authorityToggle).toBeFocused();
        }
        await expect(practiceEvidence).toBeHidden();
        await expect(statutes).toBeHidden();
        await expect(inactiveEvidence).toBeVisible();
        await expect(authorities).toBeVisible();
      },
    );
  }
});
