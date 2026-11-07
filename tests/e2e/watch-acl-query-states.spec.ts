import { expect, test, type APIRequestContext } from "@playwright/test";
import { addLocalColleague, json, prepareTester, signIn, type TesterRuntime } from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });

const SOURCE = "https://search.ipindia.gov.in/IPOJournal/Journal/ViewJournal";
const NO_PAID = { "X-CaseOps-Automated-Test": "no-paid-providers" };

async function docket(request: APIRequestContext, rt: TesterRuntime, title: string, restricted: boolean) {
  return json(await request.post(`${rt.api.origin}/api/ip/trademark-applications/manual`, {
    headers: rt.headers,
    data: {
      title, restricted, asset_title: title, jurisdiction: "IN", office: "IP India",
      filing_phase: "draft", source_pending_identifier_allocation: false,
      application_number: { raw_value: title.replaceAll(" ", "-"), source: "Watch ACL fixture", effective_from: "2026-10-31", is_primary: true },
      particulars: {
        form_key: "TM-A", form_version: "2026.1", mark_kind: "word",
        representation: { text: title, evidence_reference: "fixture:watch-acl" },
        classes: [{ class_number: 45, specification: "Legal services" }],
        use_priority: null, parties: [{ role: "applicant", name: "Watch ACL LLP" }], agent: null,
        filing_manifest: [{ key: "representation", label: "Mark representation", required: true, evidence_reference: "fixture:watch-acl" }],
      },
    },
  }), "Create Watch ACL prerequisite", 201);
}

test("Watch removes revoked source evidence from the workspace and report after reload", async ({ page, request, baseURL }) => {
  // This two-account fixture creates an isolated tenant and access changes.
  expect(new URL(baseURL!).hostname).toMatch(/^(?:localhost|127\.0\.0\.1)$/);
  test.setTimeout(240_000);
  const rt = await prepareTester(page, request, baseURL, { width: 393, height: 851 });
  const api = `${rt.api.origin}/api`;
  const owner = { headers: rt.headers };
  try {
    const reviewer = await addLocalColleague(rt, request, "admin", "Watch reviewer");
    const open = await docket(request, rt, "Open Watch Docket", false);
    const source = await docket(request, rt, "Restricted Source Docket", true);
    const privateMark = "ZQX PRIVATE MARK";
    const publicMark = "QXY PUBLIC MARK";
    const evidence = "Synthetic restricted journal extract for Watch access regression.";
    const profile = await json(await request.post(`${api}/ip/watch/profiles`, {
      ...owner, data: {
        name: "Open Watch profile", docket_id: open.docket.id, word_terms: [privateMark, publicMark],
        class_numbers: [45], frequency: "publication", recipient_membership_ids: [rt.actor.membership.id],
      },
    }), "Create open Watch profile", 201);
    const capture = async (mark: string, applicationId: string | null, note: string, key: string) => {
      const date = new Date().toISOString().slice(0, 10);
      return json(await request.post(`${api}/ip/watch/journal-ingestions`, {
        ...owner, data: {
          idempotency_key: key, provider_key: "ipindia-journal-manual", external_call: false,
          publications: [{
            application_id: applicationId, application_number: key, journal_number: key, journal_date: date,
            publication_kind: "advertisement", mark_text: mark, office: "IP India", jurisdiction: "IN",
            class_numbers: [45], goods_services: { "45": ["Legal services"] },
            publication_scope: { scope_kind: "full", published_classes: [45] },
            source_url: SOURCE, source_status: "available", source_retrieved_at: new Date().toISOString(),
            parser_version: "manual-journal-v1", attribution: { publisher: "IP India", capture_method: "manual" },
            raw_evidence: { extract_text: note },
          }],
        },
      }), "Record synthetic Watch evidence", 201);
    };
    const restricted = await capture(privateMark, source.application.id, evidence, "watch-acl-private");
    const permitted = await capture(publicMark, null, "Synthetic public journal extract.", "watch-acl-public");
    const hit = restricted.hits[0];
    const publicHit = permitted.hits[0];
    expect(hit.profile_id).toBe(profile.id);
    expect(publicHit.profile_id).toBe(profile.id);

    const access = async (data: Record<string, unknown>) => {
      const url = `${api}/ip/dockets/${source.docket.id}/access`;
      const preview = await json(await request.post(`${url}/preview`, { ...owner, data }), "Preview source ACL");
      return json(await request.post(`${url}/apply`, {
        ...owner, data: { ...data, preview_token: preview.preview_token },
      }), "Apply source ACL");
    };
    const sourcePanel = await json<{ access_policy_version: number }>(await request.get(
      `${api}/ip/dockets/${source.docket.id}/access`, owner,
    ), "Read source access policy before granting");
    const granted = await access({
      action: "grant", expected_access_policy_version: sourcePanel.access_policy_version, subject_type: "membership",
      subject_id: reviewer.membershipId, reason: "Allow the reviewer to inspect the synthetic source.",
    });
    await page.context().clearCookies();
    await signIn(page, rt, reviewer.credentials);
    await page.goto(`${rt.web.origin}/app/ip/watch`);
    await page.getByRole("button", { name: "Hits", exact: true }).click();
    await page.getByTestId(`watch-hit-${hit.id}`).click();
    await expect(page.getByRole("heading", { name: privateMark })).toBeVisible();
    await expect(page.getByText(evidence, { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Open source" })).toHaveAttribute("href", SOURCE);
    await expect(page.getByRole("button", { name: "Record review" })).toBeVisible();

    const grant = granted.panel.grants.find((row: { subject_id: string }) => row.subject_id === reviewer.membershipId);
    expect(grant, "The positive fixture must have an actual persisted source grant").toBeDefined();
    await access({
      action: "revoke_grant", grant_id: grant.id,
      expected_access_policy_version: granted.panel.access_policy_version,
      reason: "Remove the reviewer's source permission without changing the open Watch profile.",
    });
    await page.reload();
    await page.getByRole("button", { name: "Hits", exact: true }).click();
    await page.getByTestId(`watch-hit-${publicHit.id}`).click();
    await expect(page.getByRole("heading", { name: publicMark })).toBeVisible();
    await expect(page.getByTestId(`watch-hit-${hit.id}`)).toHaveCount(0);
    await expect(page.getByText(evidence, { exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Journal intake", exact: true }).click();
    await expect(page.getByTestId(`journal-entry-${permitted.publications[0].id}`)).toBeVisible();
    await expect(page.getByTestId(`journal-entry-${restricted.publications[0].id}`)).toHaveCount(0);

    const dismissal = await page.request.post(`${api}/ip/watch/hits/${hit.id}/disposition`, {
      headers: NO_PAID, data: {
        expected_version: hit.version, disposition: "not_relevant",
        reason: "This stale review must be refused.", source_confirmed: true,
      },
    });
    expect(dismissal.status()).toBe(404);
    await page.goto(`${rt.web.origin}/app/ip/reports`);
    await page.getByRole("combobox", { name: "Report", exact: true }).selectOption("watch");
    const preview = page.waitForResponse(response =>
      new URL(response.url()).pathname === "/api/ip/reports/preview" && response.request().method() === "POST");
    await page.getByRole("button", { name: "Generate", exact: true }).click();
    const response = await preview;
    expect(response.request().headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
    const report = await json(response, "Render Watch report without revoked source");
    expect(report.summary).toMatchObject({ hit_total: 1, total: 1, automated_coverage_available: false });
    await expect(page.getByRole("row").filter({ hasText: publicMark })).toBeVisible();
    await expect(page.getByRole("row").filter({ hasText: privateMark })).toHaveCount(0);
  } finally {
    await rt.release();
  }
});
