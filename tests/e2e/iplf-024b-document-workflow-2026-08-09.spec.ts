import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";

const PASSWORD = "IpDocumentWorkflow2026!";

function grantIpEntitlement(companyId: string): void {
  const python =
    process.platform === "win32"
      ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
      : path.join(repoRoot, "apps", "api", ".venv", "bin", "python");
  const script = [
    "import os",
    "from caseops_api.db.models import BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "session=get_session_factory()()",
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_024b_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
    "session.commit()",
    "session.close()",
  ].join("; ");
  const result = spawnSync(python, ["-c", script], {
    cwd: repoRoot,
    encoding: "utf8",
    env: {
      ...process.env,
      ...e2eEnv,
      CASEOPS_E2E_COMPANY_ID: companyId,
      PYTHONPATH: [path.join(repoRoot, "apps", "api", "src"), process.env.PYTHONPATH]
        .filter(Boolean)
        .join(path.delimiter),
    },
  });
  expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
}

async function createDockets(
  api: APIRequestContext,
  headers: Record<string, string>,
): Promise<string[]> {
  const ids: string[] = [];
  for (const index of [1, 2]) {
    const response = await api.post(`${apiBaseUrl}/api/ip/dockets`, {
      headers,
      data: {
        title: `IPLF 024B docket ${index}`,
        primary_identifier: `TM-DOC-${Date.now()}-${index}`,
        particulars: {
          form_key: "TM-A",
          form_version: "2026.1",
          mark_kind: "word",
          representation: {
            text: `DOCUMENT FLOW ${index}`,
            evidence_reference: `attachment:document-flow-${index}`,
          },
          classes: [{ class_number: 42, specification: "Legal workflow software" }],
          use_priority: null,
          parties: [{ role: "applicant", name: `Document Flow ${index} LLP` }],
          agent: null,
          filing_manifest: [{
            key: "representation",
            label: "Mark representation",
            required: true,
            evidence_reference: `attachment:document-flow-${index}`,
          }],
        },
      },
    });
    expect(response.status(), await response.text()).toBe(201);
    ids.push((await response.json()).id as string);
  }
  return ids;
}

async function bootstrap(api: APIRequestContext) {
  const slug = `doc-workflow-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 024B Document Workflow LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Document Workflow Owner",
      owner_email: `owner-${slug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  const body = await response.json();
  grantIpEntitlement(body.company.id as string);
  const headers = { Authorization: `Bearer ${body.access_token as string}` };
  const configuration = await api.put(`${apiBaseUrl}/api/ip/workspace/configuration`, {
    headers,
    data: {
      enabled_asset_types: ["trademark"],
      jurisdictions: ["IN"],
      offices: ["IP India"],
      timezone: "Asia/Kolkata",
      holiday_calendar_key: "iplf-024b-calendar",
      working_day_policy: { working_weekdays: [0, 1, 2, 3, 4] },
      document_taxonomy_version: "ip-document-taxonomy-v1",
      event_catalog_version: "ip-events-v1",
      deadline_rule_versions: { "IN-TM": "2026.1" },
      notification_channels: ["in_app"],
      critical_event_policy: { escalation_after_minutes: 30 },
      escalation_owner_membership_id: body.membership.id,
      provider_keys: [],
      provider_terms_version: null,
      accept_provider_terms: false,
    },
  });
  expect(configuration.status(), await configuration.text()).toBe(200);
  const enabled = await api.post(`${apiBaseUrl}/api/ip/workspace/enable`, {
    headers,
    data: { expected_config_version: 1, enabled_automations: [] },
  });
  expect(enabled.status(), await enabled.text()).toBe(200);
  return { ...body, slug };
}

async function installSession(page: Page, session: Record<string, unknown>): Promise<void> {
  await page.context().addCookies([{
    name: "caseops_session",
    value: session.access_token as string,
    url: apiBaseUrl,
    httpOnly: true,
    secure: false,
    sameSite: "Lax",
  }]);
  await page.addInitScript((context) => {
    window.localStorage.setItem("caseops.session.context", JSON.stringify(context));
  }, {
    company: session.company,
    user: session.user,
    membership: session.membership,
    capabilities: session.capabilities,
  });
}

async function upload(
  api: APIRequestContext,
  headers: Record<string, string>,
  input: { filename: string; content: Buffer; docketId: string; privileged?: boolean },
) {
  return api.post(`${apiBaseUrl}/api/ip/documents/upload`, {
    headers,
    multipart: {
      metadata_json: JSON.stringify({
        taxonomy_key: "evidence",
        title: "Evidence affidavit",
        confidentiality: input.privileged ? "restricted" : "internal",
        is_privileged: input.privileged ?? false,
        client_code: "ACME",
        asset_type: "Trademark",
        mark: "ASTER",
        jurisdiction: "IN",
        document_date: "2026-08-09",
        links: [{ target_type: "docket", target_id: input.docketId }],
      }),
      upload: { name: input.filename, mimeType: "text/plain", buffer: input.content },
    },
  });
}

test("IPLF-024B completes the controlled document journey without silent legal use", async () => {
  test.setTimeout(120_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = { Authorization: `Bearer ${tenant.access_token as string}` };
  const dockets = await createDockets(api, headers);
  expect(dockets).toHaveLength(2);

  const seeded = await api.post(`${apiBaseUrl}/api/ip/document-taxonomy/seed`, { headers });
  expect(seeded.status(), await seeded.text()).toBe(200);

  const aliasPreview = await api.post(
    `${apiBaseUrl}/api/ip/document-taxonomy/import-aliases`,
    {
      headers,
      data: {
        dry_run: true,
        entries: [{ taxonomy_key: "evidence", aliases: ["Affidavit Evidence"] }],
      },
    },
  );
  expect(aliasPreview.status(), await aliasPreview.text()).toBe(200);
  expect((await aliasPreview.json()).imported_count).toBe(1);

  const bytes = Buffer.from("Evidence affidavit with searchable particulars. ".repeat(30));
  const createdResponse = await upload(api, headers, {
    filename: "=original unsafe evidence.txt",
    content: bytes,
    docketId: dockets[0],
  });
  expect(createdResponse.status(), await createdResponse.text()).toBe(200);
  const created = await createdResponse.json();
  expect(created.outcome).toBe("created");
  expect(created.document.versions[0].original_filename).toBe("=original unsafe evidence.txt");
  expect(created.document.versions[0].display_name).not.toBe("=original unsafe evidence.txt");
  const documentId = created.document.id as string;

  await expect.poll(async () => {
    const response = await api.get(`${apiBaseUrl}/api/ip/documents/${documentId}`, { headers });
    expect(response.status(), await response.text()).toBe(200);
    return (await response.json()).versions[0].processing_status as string;
  }, { timeout: 30_000 }).toBe("indexed");
  const loadedResponse = await api.get(`${apiBaseUrl}/api/ip/documents/${documentId}`, { headers });
  expect(loadedResponse.status(), await loadedResponse.text()).toBe(200);
  const loaded = await loadedResponse.json();
  expect(loaded.versions[0]).toMatchObject({
    processing_status: "indexed",
    low_ocr_quality: false,
    ai_eligible: true,
    state: "draft",
  });
  expect(loaded.versions[0].ocr_quality_score).toBeGreaterThanOrEqual(0.65);

  const downloaded = await api.get(
    `${apiBaseUrl}/api/ip/documents/${documentId}/versions/1/download`,
    { headers },
  );
  expect(downloaded.status(), await downloaded.text()).toBe(200);
  expect(Buffer.from(await downloaded.body())).toEqual(bytes);

  const duplicateResponse = await upload(api, headers, {
    filename: "different-name.txt",
    content: bytes,
    docketId: dockets[1],
  });
  expect(duplicateResponse.status(), await duplicateResponse.text()).toBe(200);
  const duplicate = await duplicateResponse.json();
  expect(duplicate.outcome).toBe("duplicate_found");
  expect(duplicate.duplicate_candidates[0]).toMatchObject({
    document_id: documentId,
    reuse_action: "link_existing_document",
  });

  const linked = await api.post(`${apiBaseUrl}/api/ip/documents/${documentId}/links`, {
    headers,
    data: {
      expected_current_version: 1,
      links: [{ target_type: "docket", target_id: dockets[1] }],
    },
  });
  expect(linked.status(), await linked.text()).toBe(200);
  expect((await linked.json()).links).toHaveLength(2);

  for (const [expectedState, targetState] of [
    ["draft", "review"],
    ["review", "approved"],
    ["approved", "filed"],
  ] as const) {
    const transition = await api.post(
      `${apiBaseUrl}/api/ip/documents/${documentId}/versions/1/transition`,
      {
        headers,
        data: {
          expected_current_version: 1,
          expected_state: expectedState,
          target_state: targetState,
        },
      },
    );
    expect(transition.status(), await transition.text()).toBe(200);
  }
  const filed = await api.get(`${apiBaseUrl}/api/ip/documents/${documentId}`, { headers });
  expect((await filed.json()).versions[0]).toMatchObject({
    state: "filed",
    locked_by_membership_id: tenant.membership.id,
  });

  const privilegedResponse = await upload(api, headers, {
    filename: "privileged.txt",
    content: Buffer.from("Privileged advice. ".repeat(30)),
    docketId: dockets[0],
    privileged: true,
  });
  const privileged = await privilegedResponse.json();
  const policy = await api.get(
    `${apiBaseUrl}/api/ip/documents/${privileged.document.id}/policy`,
    { headers },
  );
  expect(policy.status(), await policy.text()).toBe(200);
  expect(await policy.json()).toMatchObject({
    ai_retrieval_allowed: false,
    portal_share_allowed: false,
    export_allowed: false,
    notification_content_allowed: false,
  });
  const denied = await api.post(
    `${apiBaseUrl}/api/ip/documents/${privileged.document.id}/authorize-action`,
    { headers, data: { action: "portal_share" } },
  );
  expect(denied.status()).toBe(403);

  await api.dispose();
});

test("IPLF-024B keeps every document action visible and usable at 360px", async ({ page }) => {
  test.setTimeout(120_000);
  const api = await request.newContext();
  const tenant = await bootstrap(api);
  const headers = { Authorization: `Bearer ${tenant.access_token as string}` };
  const dockets = await createDockets(api, headers);
  const seeded = await api.post(`${apiBaseUrl}/api/ip/document-taxonomy/seed`, { headers });
  expect(seeded.status(), await seeded.text()).toBe(200);

  for (const [index, docketId] of dockets.entries()) {
    const created = await upload(api, headers, {
      filename: `mobile-evidence-${index + 1}.txt`,
      content: Buffer.from(`Distinct responsive document ${index + 1}. `.repeat(30)),
      docketId,
    });
    expect(created.status(), await created.text()).toBe(200);
  }

  await installSession(page, tenant as Record<string, unknown>);
  await page.setViewportSize({ width: 360, height: 900 });
  await page.goto("/app/ip");

  const workspace = page.getByTestId("ip-document-workspace");
  await expect(workspace.getByRole("heading", { name: "Document workflow" })).toBeVisible();
  await expect(workspace.getByLabel("Original file")).toBeVisible();
  await expect(workspace.getByLabel("Supplied document names")).toBeVisible();
  await expect(workspace.getByLabel(/^New version for /).first()).toBeVisible();

  const actionNames = [
    "Preview controlled name",
    "Upload reviewed document",
    "Preview alias import",
    "Import reviewed aliases",
    "Preview rename and classification",
    "Download original",
    "Move to review",
  ];
  for (const name of actionNames) {
    const control = workspace.getByRole("button", { name }).first();
    await expect(control).toBeVisible();
    const box = await control.boundingBox();
    expect(box, `${name} should have a rendered box`).not.toBeNull();
    expect(box!.x, `${name} should start inside the viewport`).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width, `${name} should fit the 360px viewport`).toBeLessThanOrEqual(360);
  }

  const widths = await workspace.evaluate((element) => ({
    workspaceClientWidth: element.clientWidth,
    workspaceScrollWidth: element.scrollWidth,
    pageClientWidth: document.documentElement.clientWidth,
    pageScrollWidth: document.documentElement.scrollWidth,
  }));
  expect(widths.workspaceScrollWidth).toBeLessThanOrEqual(widths.workspaceClientWidth);
  expect(widths.pageScrollWidth).toBeLessThanOrEqual(widths.pageClientWidth);
  await api.dispose();
});
