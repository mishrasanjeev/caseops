import {
  expect,
  request,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

const PROD_BASE_URL = process.env.PROD_BASE_URL ?? "https://caseops.ai";
const PROD_API_BASE_URL =
  process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai";

async function signInIpQa(page: Page): Promise<void> {
  const password = process.env.CASEOPS_IP_QA_PASSWORD?.trim() ?? "";
  if (!password) throw new Error("CASEOPS_IP_QA_PASSWORD is required.");
  await page.goto(`${PROD_BASE_URL}/sign-in`);
  await page
    .locator("#company-slug")
    .fill(process.env.CASEOPS_IP_QA_SLUG ?? "caseops-ip-qa");
  await page
    .locator("#email")
    .fill(process.env.CASEOPS_IP_QA_EMAIL ?? "ip-qa-bot@caseops.ai");
  await page.locator("#password").fill(password);
  const login = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/auth/login" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  const response = await login;
  expect(response.status(), await response.text()).toBe(200);
  await page.waitForURL(new RegExp(`${PROD_BASE_URL}/app(?:[/?]|$)`));
}

async function csrfHeaders(page: Page): Promise<Record<string, string>> {
  const cookies = await page.context().cookies();
  const csrf = cookies.find((cookie) => cookie.name === "caseops_csrf")?.value;
  expect(csrf, "caseops_csrf cookie must exist after sign-in").toBeTruthy();
  return { "X-CSRF-Token": csrf! };
}

async function signInIpQaMember(
  api: APIRequestContext,
  email: string,
  password: string,
): Promise<Record<string, string>> {
  const response = await api.post(`${PROD_API_BASE_URL}/api/auth/login`, {
    data: {
      company_slug: process.env.CASEOPS_IP_QA_SLUG ?? "caseops-ip-qa",
      email,
      password,
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  const body = (await response.json()) as { access_token: string };
  return { Authorization: `Bearer ${body.access_token}` };
}

test("IPLF-026A production enforces the record-access foundation across docket, document, source, and audit", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const unauthenticated = await fetch(
    `${PROD_API_BASE_URL}/api/ip/access/foundation-contract`,
  );
  expect(unauthenticated.status).toBe(401);

  await signInIpQa(page);
  const headers = await csrfHeaders(page);
  const memberPassword = "FoundationDenial2026!";
  const memberEmail = `ip-foundation-denial-${Date.now()}@example.com`;
  const member = await page.request.post(
    `${PROD_API_BASE_URL}/api/companies/current/users`,
    {
      headers,
      data: {
        full_name: "IP Foundation Denial Reviewer",
        email: memberEmail,
        role: "admin",
        password: memberPassword,
      },
    },
  );
  expect(member.status(), await member.text()).toBe(200);
  const memberMembershipId = (
    (await member.json()) as { membership_id: string }
  ).membership_id;
  const memberApi = await request.newContext();
  const memberLogin = await memberApi.post(
    `${PROD_API_BASE_URL}/api/auth/login`,
    {
      data: {
        company_slug: process.env.CASEOPS_IP_QA_SLUG ?? "caseops-ip-qa",
        email: memberEmail,
        password: memberPassword,
      },
    },
  );
  expect(memberLogin.status(), await memberLogin.text()).toBe(200);
  const memberHeaders = {
    Authorization: `Bearer ${
      ((await memberLogin.json()) as { access_token: string }).access_token
    }`,
  };

  const contract = await page.request.get(
    `${PROD_API_BASE_URL}/api/ip/access/foundation-contract`,
  );
  expect(contract.status(), await contract.text()).toBe(200);
  expect(await contract.json()).toMatchObject({
    contract_version: "record-access-v1",
    canonical_writer:
      "MatterAccessGrant/EthicalWall via services/matter_access.py",
    supported_targets: ["matter", "ip_docket"],
    supported_subjects: ["membership", "team"],
    owner_bypass: { matter: true, ip_docket: false },
    forbidden_parallel_owners: [
      "parallel_ip_grant_store",
      "parallel_ip_wall_store",
    ],
    excluded_persistence: [
      "portal_grants",
      "access_review_campaigns",
      "emergency_access_sessions",
    ],
  });

  const before = await page.request.get(
    `${PROD_API_BASE_URL}/api/ip/access/reconciliation`,
  );
  expect(before.status(), await before.text()).toBe(200);
  expect(await before.json()).toMatchObject({ healthy: true });

  const canary = Date.now();
  const created = await page.request.post(
    `${PROD_API_BASE_URL}/api/ip/dockets`,
    {
      headers,
      data: {
        title: `IPLF-026A restricted production canary ${canary}`,
        primary_identifier: `TM-IPLF-026A-PROD-${canary}`,
        restricted: true,
        particulars: {
          form_key: "TM-A",
          form_version: "2026.1",
          mark_kind: "word",
          representation: { text: "ACCESS CANARY" },
          classes: [
            { class_number: 42, specification: "Legal workflow software" },
          ],
          parties: [{ role: "applicant", name: "CaseOps IP QA LLP" }],
          filing_manifest: [
            {
              key: "representation",
              label: "Mark representation",
              required: true,
              evidence_reference: "qa:iplf-026a-production-access-canary",
            },
          ],
        },
      },
    },
  );
  expect(created.status(), await created.text()).toBe(201);
  const docket = (await created.json()) as {
    id: string;
    restricted: boolean;
    access_policy_version: number;
  };
  expect(docket).toMatchObject({ restricted: true, access_policy_version: 1 });

  const listing = await page.request.get(`${PROD_API_BASE_URL}/api/ip/dockets`);
  expect(listing.status(), await listing.text()).toBe(200);
  const listed = (await listing.json()) as {
    count: number;
    dockets: Array<{ id: string }>;
  };
  expect(listed.count).toBe(listed.dockets.length);
  expect(listed.dockets.some((row) => row.id === docket.id)).toBe(true);

  const direct = await page.request.get(
    `${PROD_API_BASE_URL}/api/ip/dockets/${docket.id}`,
  );
  expect(direct.status(), await direct.text()).toBe(200);

  const taxonomy = await page.request.post(
    `${PROD_API_BASE_URL}/api/ip/document-taxonomy/seed`,
    { headers },
  );
  expect(taxonomy.status(), await taxonomy.text()).toBe(200);
  const uploaded = await page.request.post(
    `${PROD_API_BASE_URL}/api/ip/documents/upload`,
    {
      headers,
      multipart: {
        metadata_json: JSON.stringify({
          taxonomy_key: "evidence",
          title: "IPLF-026A protected production source",
          confidentiality: "restricted",
          is_privileged: true,
          client_code: "CASEOPS-QA",
          asset_type: "Trademark",
          mark: "ACCESS CANARY",
          jurisdiction: "IN",
          application_no: `IPLF-026A-${canary}`,
          document_date: "2026-08-11",
          links: [{ target_type: "docket", target_id: docket.id }],
        }),
        upload: {
          name: `iplf-026a-${canary}.txt`,
          mimeType: "text/plain",
          buffer: Buffer.from(
            `Synthetic IPLF-026A access canary ${canary}.`,
          ),
        },
      },
    },
  );
  expect(uploaded.status(), await uploaded.text()).toBe(200);
  const document = (await uploaded.json()) as {
    outcome: "created" | "duplicate_found";
    document: { id: string; versions: Array<{ id: string }> };
  };
  expect(document.outcome).toBe("created");
  const versionId = document.document.versions[0]?.id;
  expect(versionId).toBeTruthy();

  const source = await page.request.get(
    `${PROD_API_BASE_URL}/api/source-actions/targets/ip_document_version/${versionId}/open?origin=ip_document`,
    { maxRedirects: 0 },
  );
  expect(source.status(), await source.text()).toBe(307);
  expect(source.headers().location).toContain(
    `/api/ip/documents/${document.document.id}/versions/1/download`,
  );

  const audit = await page.request.get(
    `${PROD_API_BASE_URL}/api/ip/dockets/${docket.id}/audit`,
  );
  expect(audit.status(), await audit.text()).toBe(200);
  const auditBody = (await audit.json()) as {
    total: number;
    events: Array<{ action: string; ip_docket_id: string }>;
  };
  expect(auditBody.total).toBeGreaterThanOrEqual(2);
  expect(
    auditBody.events.every((row) => row.ip_docket_id === docket.id),
  ).toBe(true);
  expect(auditBody.events.map((row) => row.action)).toEqual(
    expect.arrayContaining(["ip_docket.created", "source_access.opened"]),
  );

  const hiddenDockets = await memberApi.get(
    `${PROD_API_BASE_URL}/api/ip/dockets`,
    { headers: memberHeaders },
  );
  expect(hiddenDockets.status(), await hiddenDockets.text()).toBe(200);
  const hiddenDocketBody = (await hiddenDockets.json()) as {
    dockets: Array<{ id: string }>;
  };
  expect(
    hiddenDocketBody.dockets.some((row) => row.id === docket.id),
  ).toBe(false);
  expect(
    (
      await memberApi.get(
        `${PROD_API_BASE_URL}/api/ip/dockets/${docket.id}`,
        { headers: memberHeaders },
      )
    ).status(),
  ).toBe(404);
  expect(
    (
      await memberApi.get(
        `${PROD_API_BASE_URL}/api/ip/dockets/${docket.id}/audit`,
        { headers: memberHeaders },
      )
    ).status(),
  ).toBe(404);

  const hiddenDocuments = await memberApi.get(
    `${PROD_API_BASE_URL}/api/ip/documents`,
    { headers: memberHeaders },
  );
  expect(hiddenDocuments.status(), await hiddenDocuments.text()).toBe(200);
  const hiddenDocumentBody = (await hiddenDocuments.json()) as {
    items: Array<{ id: string }>;
  };
  expect(
    hiddenDocumentBody.items.some((row) => row.id === document.document.id),
  ).toBe(false);
  expect(
    (
      await memberApi.get(
        `${PROD_API_BASE_URL}/api/ip/documents/${document.document.id}`,
        { headers: memberHeaders },
      )
    ).status(),
  ).toBe(404);
  expect(
    (
      await memberApi.get(
        `${PROD_API_BASE_URL}/api/source-actions/targets/ip_document_version/${versionId}/open?origin=ip_document`,
        { headers: memberHeaders, maxRedirects: 0 },
      )
    ).status(),
  ).toBe(404);

  const after = await page.request.get(
    `${PROD_API_BASE_URL}/api/ip/access/reconciliation`,
  );
  expect(after.status(), await after.text()).toBe(200);
  expect(await after.json()).toMatchObject({
    healthy: true,
    legacy_tail_count: 0,
    invalid_target_count: 0,
    invalid_subject_count: 0,
    target_company_mismatch_count: 0,
    subject_company_mismatch_count: 0,
    uncorrelated_ip_audit_count: 0,
  });
  await memberApi.dispose();
  const deactivated = await page.request.patch(
    `${PROD_API_BASE_URL}/api/companies/current/users/${memberMembershipId}`,
    { headers, data: { is_active: false } },
  );
  expect(deactivated.status(), await deactivated.text()).toBe(200);
  expect(await deactivated.json()).toMatchObject({
    membership_active: false,
    user_active: false,
  });
});

test("IPLF-026B production previews, grants, and revokes independent IP access at 360px", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const canary = Date.now();
  const memberPassword = "AccessCanary2026!";
  const memberEmail = `ip-access-prod-${canary}@example.com`;
  const memberApi = await request.newContext();
  let ownerHeaders: Record<string, string> | null = null;
  let cleanupMembershipId: string | null = null;
  let memberDeactivated = false;

  try {
    await page.setViewportSize({ width: 360, height: 820 });
    await signInIpQa(page);
    const headers = await csrfHeaders(page);
    ownerHeaders = headers;

    const member = await page.request.post(
      `${PROD_API_BASE_URL}/api/companies/current/users`,
      {
        headers,
        data: {
          full_name: `IP Access Production Reviewer ${canary}`,
          email: memberEmail,
          role: "admin",
          password: memberPassword,
        },
      },
    );
    expect(member.status(), await member.text()).toBe(200);
    const membershipId = ((await member.json()) as { membership_id: string })
      .membership_id;
    cleanupMembershipId = membershipId;
    const memberHeaders = await signInIpQaMember(
      memberApi,
      memberEmail,
      memberPassword,
    );

    const matter = await page.request.post(
      `${PROD_API_BASE_URL}/api/matters/`,
      {
        headers,
        data: {
          title: `Independent production Matter ${canary}`,
          matter_code: `IPLF-026B-PROD-${canary}`,
          practice_area: "Intellectual Property",
          forum_level: "high_court",
          status: "active",
        },
      },
    );
    expect(matter.status(), await matter.text()).toBe(200);
    const matterId = ((await matter.json()) as { id: string }).id;

    const created = await page.request.post(
      `${PROD_API_BASE_URL}/api/ip/dockets`,
      {
        headers,
        data: {
          title: `Restricted IP access production canary ${canary}`,
          primary_identifier: `TM-IPLF-026B-PROD-${canary}`,
          matter_id: matterId,
          restricted: true,
          particulars: {
            form_key: "TM-A",
            form_version: "2026.1",
            mark_kind: "word",
            representation: { text: "ACCESS WORKFLOW" },
            classes: [
              {
                class_number: 42,
                specification: "Legal workflow software",
              },
            ],
            parties: [
              { role: "applicant", name: "CaseOps IP QA LLP" },
            ],
            filing_manifest: [
              {
                key: "representation",
                label: "Mark representation",
                required: true,
                evidence_reference: "qa:iplf-026b-production-access-canary",
              },
            ],
          },
        },
      },
    );
    expect(created.status(), await created.text()).toBe(201);
    const docket = (await created.json()) as {
      id: string;
      access_policy_version: number;
    };
    expect(docket.access_policy_version).toBe(1);

    const restrictedMatter = await page.request.post(
      `${PROD_API_BASE_URL}/api/matters/${matterId}/access/restricted`,
      { headers, data: { restricted: true } },
    );
    expect(restrictedMatter.status(), await restrictedMatter.text()).toBe(200);
    expect(
      (
        await memberApi.get(
          `${PROD_API_BASE_URL}/api/ip/dockets/${docket.id}`,
          { headers: memberHeaders },
        )
      ).status(),
    ).toBe(404);

    await page.goto(`/app/ip?docket=${encodeURIComponent(docket.id)}`);
    const workspace = page.getByTestId("ip-access-workspace");
    await expect(workspace).toBeVisible({ timeout: 45_000 });
    await expect(
      workspace.getByRole("heading", {
        name: "Internal access and ethical walls",
      }),
    ).toBeVisible();
    await expect(
      workspace.getByText(/Linked Matter permissions are never copied/i),
    ).toBeVisible();
    await expect(
      workspace.getByRole("button", { name: "Preview grant" }),
    ).toBeVisible({ timeout: 45_000 });
    await expect(
      workspace.getByRole("button", { name: "Preview default access" }),
    ).toBeVisible();

    await workspace
      .getByLabel("Reason for change")
      .fill("Assigned for the dated production IP access review.");
    await workspace.getByLabel("Person or team").selectOption(membershipId);
    const previewResponsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/api/ip/dockets/${docket.id}/access/preview`) &&
        response.request().method() === "POST",
      { timeout: 20_000 },
    );
    await workspace.getByRole("button", { name: "Preview grant" }).click();
    await expect(workspace.getByRole("status")).toContainText(
      "Calculating the affected people, documents, and queued deliveries",
    );
    const previewResponse = await previewResponsePromise;
    expect(previewResponse.status(), await previewResponse.text()).toBe(200);
    const preview = workspace.getByTestId("ip-access-preview");
    await expect(preview).toContainText("Gains: 1");
    await expect(preview).toContainText("this change never copies permissions");
    await expect(
      preview.getByRole("button", { name: "Apply access change" }),
    ).toBeVisible();
    await preview.getByRole("button", { name: "Apply access change" }).click();
    await expect(workspace.getByText("v2", { exact: true })).toBeVisible();

    expect(
      (
        await memberApi.get(
          `${PROD_API_BASE_URL}/api/ip/dockets/${docket.id}`,
          { headers: memberHeaders },
        )
      ).status(),
    ).toBe(200);
    expect(
      (
        await memberApi.get(`${PROD_API_BASE_URL}/api/matters/${matterId}`, {
          headers: memberHeaders,
        })
      ).status(),
    ).toBe(404);

    await workspace
      .getByLabel("Reason for change")
      .fill("The dated production review assignment has ended.");
    await workspace
      .getByRole("button", {
        name: new RegExp(
          `Preview revoke access for IP Access Production Reviewer ${canary}`,
        ),
      })
      .click();
    await expect(preview).toContainText("Losses: 1");
    await preview.getByRole("button", { name: "Apply access change" }).click();
    await expect(workspace.getByText("v3", { exact: true })).toBeVisible();
    await expect(workspace.getByText("Revoked")).toBeVisible();
    expect(
      (
        await memberApi.get(
          `${PROD_API_BASE_URL}/api/ip/dockets/${docket.id}`,
          { headers: memberHeaders },
        )
      ).status(),
    ).toBe(404);
    const hiddenList = await memberApi.get(
      `${PROD_API_BASE_URL}/api/ip/dockets`,
      { headers: memberHeaders },
    );
    expect(hiddenList.status(), await hiddenList.text()).toBe(200);
    const hiddenListBody = (await hiddenList.json()) as {
      dockets: Array<{ id: string }>;
    };
    expect(hiddenListBody.dockets.some((row) => row.id === docket.id)).toBe(
      false,
    );

    const panel = await page.request.get(
      `${PROD_API_BASE_URL}/api/ip/dockets/${docket.id}/access`,
    );
    expect(panel.status(), await panel.text()).toBe(200);
    const panelBody = (await panel.json()) as {
      excluded_persistence: string[];
      grants: Array<{
        id: string;
        subject_id: string;
        revoked_at: string | null;
      }>;
    };
    expect(panelBody.excluded_persistence).toEqual([
      "portal_grants",
      "access_review_campaigns",
      "emergency_access_sessions",
    ]);

    const currentMembership = await page.request.get(
      `${PROD_API_BASE_URL}/api/auth/me`,
    );
    expect(currentMembership.status(), await currentMembership.text()).toBe(
      200,
    );
    const currentMembershipId = (
      (await currentMembership.json()) as { membership: { id: string } }
    ).membership.id;
    const creatorGrant = panelBody.grants.find(
      (row) =>
        row.subject_id === currentMembershipId && row.revoked_at === null,
    );
    expect(
      creatorGrant,
      "restricted docket must retain its creator grant",
    ).toBeTruthy();
    const selfLockout = await page.request.post(
      `${PROD_API_BASE_URL}/api/ip/dockets/${docket.id}/access/preview`,
      {
        headers,
        data: {
          action: "revoke_grant",
          expected_access_policy_version: 3,
          reason: "Attempt to remove final production owner access.",
          grant_id: creatorGrant!.id,
        },
      },
    );
    expect(selfLockout.status()).toBe(409);

    const deactivated = await page.request.patch(
      `${PROD_API_BASE_URL}/api/companies/current/users/${membershipId}`,
      { headers, data: { is_active: false } },
    );
    expect(deactivated.status(), await deactivated.text()).toBe(200);
    memberDeactivated = true;
    expect(await deactivated.json()).toMatchObject({
      membership_active: false,
      user_active: false,
    });
  } finally {
    const cleanupFailures: string[] = [];
    if (ownerHeaders && cleanupMembershipId && !memberDeactivated) {
      try {
        const cleanup = await page.request.patch(
          `${PROD_API_BASE_URL}/api/companies/current/users/${cleanupMembershipId}`,
          { headers: ownerHeaders, data: { is_active: false } },
        );
        if (cleanup.status() !== 200) {
          cleanupFailures.push(
            `temporary admin deactivation returned ${cleanup.status()}: ${await cleanup.text()}`,
          );
        }
      } catch (error) {
        cleanupFailures.push(
          `temporary admin deactivation threw: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
    }
    await memberApi.dispose();
    expect(
      cleanupFailures,
      "IPLF-026B production teardown must deactivate its temporary admin",
    ).toEqual([]);
  }
});
