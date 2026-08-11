import { expect, test, type Page } from "@playwright/test";

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
});
