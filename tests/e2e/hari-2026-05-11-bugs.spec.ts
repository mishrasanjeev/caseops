/**
 * Hari 2026-05-11 — BUG-042..BUG-048 regression suite (local app).
 *
 * Bug-by-bug coverage:
 *   - BUG-042 (P2): order list on /app/matters/{id}/hearings exposes
 *     a View affordance once the order has order_attachment_id set.
 *   - BUG-043 (P2): document search input on /app/matters/{id}/documents
 *     filters the rendered list and shows the empty state when no rows
 *     match.
 *   - BUG-044 (P1): /app/matters/{id}/hearings — when the user has no
 *     Outlook connection, the per-hearing strip renders a "Connect
 *     Outlook" link (NOT a Sync button that we know will 409). The
 *     onError handler also catches 409 → actionable toast (this is a
 *     code-level fallback for users who arrived with an old cached
 *     status; here we assert the pre-emptive UX).
 *   - BUG-045 (P2): matter_attachments.hearing_id schema, API param,
 *     workspace exposure + UI hearing chip.
 *   - BUG-046 (P2): stale report — /app/matters/{id} renders the
 *     BenchStrategyPanel. Asserts the loading skeleton mounts to prove
 *     the panel is present (data may be insufficient on a fresh tenant
 *     and that's OK for this assertion).
 *   - BUG-047 (P1): stale report — /app/admin/employees New / Edit
 *     dialogs both expose a Role <select>. Asserts the create-form
 *     selector is present.
 *   - BUG-048 (P1): admin matter-access fan-out endpoint returns
 *     entries for every matter in the company; UI panel inside the
 *     EditEmployeeDialog renders rows + Grant action.
 *
 * Anchored to bug-fixing skill ("Playwright-on-Prod Verification
 * Rule"): this spec is the *local* probe. Prod re-run is separately
 * required after the user runs scripts/deploy-prod.sh.
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "Bug2026May11!";

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ slug: string; token: string; ownerEmail: string }> {
  const ownerEmail = `owner-${slug}@example.com`;
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Hari 2026-05-11 LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Hari 2026-05-11 Owner",
      owner_email: ownerEmail,
      owner_password: PASSWORD,
    },
  });
  if (resp.status() !== 200) {
    throw new Error(`Bootstrap failed: ${resp.status()} ${await resp.text()}`);
  }
  return { slug, token: (await resp.json()).access_token as string, ownerEmail };
}

async function createMatter(
  api: APIRequestContext,
  token: string,
  code: string,
  extra: Record<string, unknown> = {},
): Promise<string> {
  const resp = await api.post(`${apiBaseUrl}/api/matters/`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      title: `Hari 2026-05-11 ${code}`,
      matter_code: code,
      practice_area: "criminal",
      forum_level: "high_court",
      status: "active",
      court_name: "Delhi High Court",
      ...extra,
    },
  });
  if (resp.status() !== 200) {
    throw new Error(`Matter create failed: ${resp.status()} ${await resp.text()}`);
  }
  return (await resp.json()).id as string;
}

async function uploadAttachment(
  api: APIRequestContext,
  token: string,
  matterId: string,
  filename: string,
  body: string,
  fields: Record<string, string> = {},
): Promise<string> {
  const resp = await api.post(
    `${apiBaseUrl}/api/matters/${matterId}/attachments`,
    {
      headers: { Authorization: `Bearer ${token}` },
      multipart: {
        file: { name: filename, mimeType: "text/plain", buffer: Buffer.from(body) },
        ...fields,
      },
    },
  );
  if (resp.status() !== 200) {
    throw new Error(`Upload failed: ${resp.status()} ${await resp.text()}`);
  }
  return (await resp.json()).id as string;
}

async function createHearing(
  api: APIRequestContext,
  token: string,
  matterId: string,
  hearingOn: string,
): Promise<string> {
  const resp = await api.post(
    `${apiBaseUrl}/api/matters/${matterId}/hearings`,
    {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        hearing_on: hearingOn,
        hearing_type: "Bail arguments",
        purpose: "Arguments on bail",
        forum_name: "Delhi High Court",
      },
    },
  );
  if (resp.status() !== 200) {
    throw new Error(`Hearing create failed: ${resp.status()} ${await resp.text()}`);
  }
  return (await resp.json()).id as string;
}

async function createOrderWithAttachment(
  api: APIRequestContext,
  token: string,
  matterId: string,
  attachmentId: string,
): Promise<string> {
  const resp = await api.post(
    `${apiBaseUrl}/api/matters/${matterId}/court-orders`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      data: {
        order_date: "2026-05-10",
        title: "Order with attachment — BUG-042 probe",
        summary: "Bench continued the interim relief.",
        source: "manual_upload",
        order_kind: "interim_order",
        is_interim_order: true,
        order_attachment_id: attachmentId,
      },
    },
  );
  if (resp.status() !== 200) {
    throw new Error(`Order create failed: ${resp.status()} ${await resp.text()}`);
  }
  return (await resp.json()).id as string;
}

async function signIn(
  page: import("@playwright/test").Page,
  slug: string,
  email: string,
): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app/);
}

test.describe("Hari 2026-05-11 — BUG-042..048", () => {
  test.setTimeout(180_000);

  // BUG-042 — order has attachment, hearings page renders the View
  // button linking to the attachment view route.
  test("BUG-042 (UI): hearings order list shows View order document when order_attachment_id is set", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("b42");
    const { token, ownerEmail } = await bootstrap(api, slug);
    const matterId = await createMatter(api, token, "B42-001");
    const attachmentId = await uploadAttachment(
      api,
      token,
      matterId,
      "stay-order.txt",
      "Stay order body for BUG-042.",
      { document_type: "order_judgment" },
    );
    const orderId = await createOrderWithAttachment(api, token, matterId, attachmentId);

    await signIn(page, slug, ownerEmail);
    await page.goto(`/app/matters/${matterId}/hearings`);

    const viewBtn = page.getByTestId(`matter-court-order-view-${orderId}`);
    await expect(viewBtn).toBeVisible();
    const expectedHrefSuffix = `/app/matters/${matterId}/documents/${attachmentId}/view`;
    const href = await viewBtn.getAttribute("href");
    expect(href).toContain(expectedHrefSuffix);
  });

  // BUG-043 — search filter on documents page.
  test("BUG-043 (UI): document search filters the list and renders empty state for no matches", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("b43");
    const { token, ownerEmail } = await bootstrap(api, slug);
    const matterId = await createMatter(api, token, "B43-001");
    await uploadAttachment(api, token, matterId, "vakalatnama.txt", "Body A");
    await uploadAttachment(api, token, matterId, "evidence-roll.txt", "Body B");

    await signIn(page, slug, ownerEmail);
    await page.goto(`/app/matters/${matterId}/documents`);

    const search = page.getByTestId("matter-document-search");
    await expect(search).toBeVisible();
    await search.fill("vakal");

    // Showing 1 of 2 hint visible.
    const count = page.getByTestId("matter-document-search-count");
    await expect(count).toContainText("1 of 2");

    // Empty state for a guaranteed non-match.
    await search.fill("zzz-no-such-doc");
    await expect(page.getByText(/No documents match this search/i)).toBeVisible();

    // Clear restores both queries.
    await page.getByTestId("matter-document-search-clear").click();
    await expect(count).toHaveCount(0);
  });

  // BUG-044 — Outlook connect-first UX (no connection → no Sync button,
  // Connect link instead). Also exercises the API 409 path.
  test("BUG-044 (API): /api/calendar/sync/hearings/{id} returns 409 when no Outlook connection", async () => {
    const api = await request.newContext();
    const slug = unique("b44a");
    const { token } = await bootstrap(api, slug);
    const matterId = await createMatter(api, token, "B44-001");
    const hearingId = await createHearing(api, token, matterId, "2026-06-01");

    const resp = await api.post(
      `${apiBaseUrl}/api/calendar/sync/hearings/${hearingId}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(resp.status()).toBe(409);
    const detail = (await resp.json()).detail as string;
    expect(detail.toLowerCase()).toMatch(/connect|outlook/);
  });

  test("BUG-044 (UI): hearings page renders Connect Outlook link, NOT Sync, when no connection", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("b44b");
    const { token, ownerEmail } = await bootstrap(api, slug);
    const matterId = await createMatter(api, token, "B44-002");
    const hearingId = await createHearing(api, token, matterId, "2026-06-02");

    await signIn(page, slug, ownerEmail);
    await page.goto(`/app/matters/${matterId}/hearings`);

    // Pre-emptive: the connect link is shown; the broken sync button
    // is suppressed entirely so the user can't 409 themselves.
    await expect(
      page.getByTestId(`hearing-outlook-connect-${hearingId}`),
    ).toBeVisible();
    await expect(
      page.getByTestId(`hearing-outlook-sync-${hearingId}`),
    ).toHaveCount(0);
    const link = page.getByTestId(`hearing-outlook-connect-${hearingId}`);
    expect(await link.getAttribute("href")).toContain("/app/calendar");
  });

  // BUG-045 — link evidence to a hearing.
  test("BUG-045 (API+UI): hearing_id round-trips on upload and surfaces in workspace + UI chip", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("b45");
    const { token, ownerEmail } = await bootstrap(api, slug);
    const matterId = await createMatter(api, token, "B45-001");
    const hearingId = await createHearing(api, token, matterId, "2026-06-15");

    // Upload tagged with hearing_id.
    const attId = await uploadAttachment(
      api,
      token,
      matterId,
      "exhibit-A.txt",
      "Exhibit A",
      { hearing_id: hearingId },
    );

    // Workspace exposes hearing_id.
    const workspace = await api.get(
      `${apiBaseUrl}/api/matters/${matterId}/workspace`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(workspace.status()).toBe(200);
    const wsAttachments = (await workspace.json()).attachments as Array<{
      id: string;
      hearing_id: string | null;
    }>;
    const tagged = wsAttachments.find((a) => a.id === attId);
    expect(tagged?.hearing_id).toBe(hearingId);

    // Cross-tenant defence: passing an out-of-matter hearing_id is rejected.
    const otherMatterId = await createMatter(api, token, "B45-X");
    const otherHearingId = await createHearing(api, token, otherMatterId, "2026-06-15");
    const cross = await api.post(
      `${apiBaseUrl}/api/matters/${matterId}/attachments`,
      {
        headers: { Authorization: `Bearer ${token}` },
        multipart: {
          file: { name: "x.txt", mimeType: "text/plain", buffer: Buffer.from("x") },
          hearing_id: otherHearingId,
        },
      },
    );
    expect(cross.status()).toBe(400);

    // UI chip rendered on the documents page.
    await signIn(page, slug, ownerEmail);
    await page.goto(`/app/matters/${matterId}/documents`);
    await expect(
      page.getByTestId(`matter-attachment-hearing-${attId}`),
    ).toContainText(/Hearing/);

    // Hearing filter narrows results.
    const filter = page.getByTestId("matter-document-hearing-filter");
    await expect(filter).toBeVisible();
    await filter.selectOption(hearingId);
    await expect(
      page.getByTestId(`matter-attachment-hearing-${attId}`),
    ).toBeVisible();
  });

  // BUG-046 — stale report. Overview already mounts the
  // BenchStrategyPanel; assert it loads.
  test("BUG-046 (UI, stale report): matter overview mounts the BenchStrategyPanel", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("b46");
    const { token, ownerEmail } = await bootstrap(api, slug);
    const matterId = await createMatter(api, token, "B46-001");

    await signIn(page, slug, ownerEmail);
    await page.goto(`/app/matters/${matterId}`);

    // Either the loading skeleton or the rendered panel must be
    // present — both prove the panel is mounted on the overview.
    const panel = page
      .getByTestId("bench-strategy-panel-loading")
      .or(page.getByRole("heading", { name: /Bench strategy/i }));
    await expect(panel.first()).toBeVisible({ timeout: 20_000 });
  });

  // BUG-047 — stale report. Role selector exists in both create + edit.
  test("BUG-047 (UI, stale report): admin/employees New dialog exposes a role selector", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("b47");
    const { ownerEmail } = await bootstrap(api, slug);

    await signIn(page, slug, ownerEmail);
    await page.goto("/app/admin/employees");
    await page.getByRole("button", { name: /Add employee/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByTestId("employee-role")).toBeVisible();
  });

  // BUG-048 — admin matter-access fan-out endpoint + Edit dialog row.
  test("BUG-048 (API): /api/companies/current/employees/{id}/matter-access lists every matter in the company", async () => {
    const api = await request.newContext();
    const slug = unique("b48a");
    const { token } = await bootstrap(api, slug);
    const matterAId = await createMatter(api, token, "B48-A");
    const matterBId = await createMatter(api, token, "B48-B");

    // Invite a second member so we have someone to manage access for.
    const memberEmail = `member-${slug}@example.com`;
    const create = await api.post(
      `${apiBaseUrl}/api/companies/current/employees`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          full_name: "BUG-048 Member",
          email: memberEmail,
          role: "member",
        },
      },
    );
    expect(create.status()).toBe(200);
    const membershipId = (await create.json()).employee.membership_id as string;

    // Restrict matter A so the fan-out has both restricted + open rows.
    const restrict = await api.post(
      `${apiBaseUrl}/api/matters/${matterAId}/access/restricted`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: { restricted: true },
      },
    );
    expect(restrict.status()).toBe(200);

    const list = await api.get(
      `${apiBaseUrl}/api/companies/current/employees/${membershipId}/matter-access`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(list.status()).toBe(200);
    const matters = (await list.json()).matters as Array<{
      matter_id: string;
      restricted_access: boolean;
      has_grant: boolean;
    }>;
    const a = matters.find((m) => m.matter_id === matterAId);
    const b = matters.find((m) => m.matter_id === matterBId);
    expect(a?.restricted_access).toBe(true);
    expect(a?.has_grant).toBe(false);
    expect(b?.restricted_access).toBe(false);

    // Grant access to A → has_grant flips true on next fetch.
    const grant = await api.post(
      `${apiBaseUrl}/api/matters/${matterAId}/access/grants`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: { membership_id: membershipId, access_level: "member" },
      },
    );
    expect(grant.status()).toBe(200);
    const list2 = await api.get(
      `${apiBaseUrl}/api/companies/current/employees/${membershipId}/matter-access`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    const a2 = ((await list2.json()).matters as typeof matters).find(
      (m) => m.matter_id === matterAId,
    );
    expect(a2?.has_grant).toBe(true);
  });

  test("BUG-048 (UI): EditEmployeeDialog renders the Matter access panel with rows", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("b48b");
    const { token, ownerEmail } = await bootstrap(api, slug);
    await createMatter(api, token, "B48B-001");
    const memberEmail = `member-${slug}@example.com`;
    const create = await api.post(
      `${apiBaseUrl}/api/companies/current/employees`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          full_name: "BUG-048b Member",
          email: memberEmail,
          role: "member",
        },
      },
    );
    expect(create.status()).toBe(200);

    await signIn(page, slug, ownerEmail);
    await page.goto("/app/admin/employees");
    // Open the edit dialog for the non-owner row by clicking its
    // "Edit" button. The employees table renders rows keyed by
    // membership id; the Edit affordance is the first per-row button
    // in the row containing the member email.
    const memberRow = page.locator("tr", { hasText: memberEmail });
    await memberRow.getByRole("button", { name: /Edit/i }).first().click();

    // The matter-access panel must mount with at least one row.
    await expect(page.getByTestId("employee-matter-access-list")).toBeVisible({
      timeout: 15_000,
    });
    const rows = page.locator(
      '[data-testid^="employee-matter-access-row-"]',
    );
    await expect(rows.first()).toBeVisible();
  });
});
