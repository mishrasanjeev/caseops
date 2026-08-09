import { expect, test, type Page } from "@playwright/test";

const PROD_BASE_URL = process.env.PROD_BASE_URL ?? "https://caseops.ai";
const PROD_API_BASE_URL =
  process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai";
const COMPANY_SLUG = process.env.CASEOPS_RAM_PROD_SLUG ?? "legal";
const TESTER_EMAIL = process.env.CASEOPS_RAM_PROD_EMAIL ?? "hari.gupta@gmail.com";

function requiredPassword(): string {
  const password = process.env.CASEOPS_RAM_PROD_PASSWORD?.trim() ?? "";
  if (!password) throw new Error("CASEOPS_RAM_PROD_PASSWORD is required for production proof.");
  return password;
}

async function signIn(page: Page): Promise<void> {
  await page.goto(`${PROD_BASE_URL}/sign-in`);
  await page.locator("#company-slug").fill(COMPANY_SLUG);
  await page.locator("#email").fill(TESTER_EMAIL);
  await page.locator("#password").fill(requiredPassword());
  const login = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/auth/login" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  expect((await login).status()).toBe(200);
  await page.waitForURL(new RegExp(`${PROD_BASE_URL}/app(?:[/?]|$)`));
}

async function csrfHeaders(page: Page): Promise<Record<string, string>> {
  const cookies = await page.context().cookies();
  const csrf = cookies.find((cookie) => cookie.name === "caseops_csrf")?.value;
  expect(csrf, "caseops_csrf cookie must exist after sign-in").toBeTruthy();
  return { "X-CSRF-Token": csrf! };
}

test("IPLF-023B production keeps unentitled legal automation and records fail-closed at 360px", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await signIn(page);
  const protectedRequests: string[] = [];
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (
      pathname.includes("/deadline-workspace") ||
      pathname.includes("/deadline-rules") ||
      pathname.includes("/working-calendars")
    ) {
      protectedRequests.push(pathname);
    }
  });
  const readinessResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/ip/readiness" &&
      response.request().method() === "GET",
  );
  await page.setViewportSize({ width: 360, height: 900 });
  await page.goto(`${PROD_BASE_URL}/app/ip`);
  const readiness = await readinessResponse;
  expect(readiness.status()).toBe(200);
  const body = (await readiness.json()) as { workspace_available: boolean };
  expect(body.workspace_available).toBe(false);
  await expect(page.getByRole("heading", { name: "IP workspace setup" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Legal deadline control" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Rule and calendar governance" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Calculate deadline proposal" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Confirm legal deadline" })).toHaveCount(0);
  expect(protectedRequests).toEqual([]);

  const setup = page.getByRole("heading", { name: "IP workspace setup" });
  const box = await setup.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(360);
});

test("IPLF-024A production serves the exact document contract to the entitled QA tenant", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const unauthenticated = await fetch(
    `${PROD_API_BASE_URL}/api/ip/documents/foundation-contract`,
  );
  expect(unauthenticated.status).toBe(401);

  await signIn(page);
  const foundation = await page.request.get(
    `${PROD_API_BASE_URL}/api/ip/documents/foundation-contract`,
  );
  expect(foundation.status(), await foundation.text()).toBe(200);
  expect(await foundation.json()).toEqual({
    identity_owner: "ip_documents",
    version_owner: "ip_document_versions",
    link_owner: "ip_document_links",
    binary_storage_owner: "shared_document_storage",
    processing_queue_owner: "document_processing_jobs",
    processing_target_type: "ip_document_version",
    taxonomy_version: "ip-document-taxonomy-v1",
    naming_pattern:
      "[ClientCode]_[AssetType]_[Mark]_[Jurisdiction]_[ApplicationNo]_[ProceedingType]_[ProceedingNo]_[DocumentType]_[YYYY-MM-DD]_[Version]",
    supported_link_targets: ["docket", "application", "proceeding", "event", "deadline"],
  });

  const taxonomy = await page.request.get(`${PROD_API_BASE_URL}/api/ip/document-taxonomy`);
  expect(taxonomy.status(), await taxonomy.text()).toBe(200);
  const taxonomyBody = (await taxonomy.json()) as {
    taxonomy_version: string;
    entries: unknown[];
  };
  expect(taxonomyBody.taxonomy_version).toBe("ip-document-taxonomy-v1");
  expect(Array.isArray(taxonomyBody.entries)).toBe(true);
});

test("IPLF-024B production runs the reusable, locked, fail-closed document journey", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await signIn(page);
  const headers = await csrfHeaders(page);

  const seeded = await page.request.post(
    `${PROD_API_BASE_URL}/api/ip/document-taxonomy/seed`,
    { headers },
  );
  expect(seeded.status(), await seeded.text()).toBe(200);

  const aliasPreview = await page.request.post(
    `${PROD_API_BASE_URL}/api/ip/document-taxonomy/import-aliases`,
    {
      headers,
      data: {
        dry_run: true,
        entries: [{
          taxonomy_key: "evidence",
          aliases: ["Production QA Evidence Affidavit"],
        }],
      },
    },
  );
  expect(aliasPreview.status(), await aliasPreview.text()).toBe(200);
  const aliasPreviewBody = await aliasPreview.json();
  expect(aliasPreviewBody.conflicts).toEqual([]);
  if (aliasPreviewBody.imported_count === 1) {
    const imported = await page.request.post(
      `${PROD_API_BASE_URL}/api/ip/document-taxonomy/import-aliases`,
      {
        headers,
        data: {
          dry_run: false,
          entries: [{
            taxonomy_key: "evidence",
            aliases: ["Production QA Evidence Affidavit"],
          }],
        },
      },
    );
    expect(imported.status(), await imported.text()).toBe(200);
  } else {
    expect(aliasPreviewBody.unchanged_count).toBe(1);
  }

  const listedDockets = await page.request.get(`${PROD_API_BASE_URL}/api/ip/dockets`);
  expect(listedDockets.status(), await listedDockets.text()).toBe(200);
  const docketItems = ((await listedDockets.json()) as { items: Array<{ id: string }> }).items;
  let docketId = docketItems[0]?.id;
  if (!docketId) {
    const createdDocket = await page.request.post(`${PROD_API_BASE_URL}/api/ip/dockets`, {
      headers,
      data: {
        title: "IPLF-024B production document canary",
        primary_identifier: "TM-IPLF-024B-PROD",
        particulars: {
          form_key: "TM-A",
          form_version: "2026.1",
          mark_kind: "word",
          representation: {
            text: "DOCUMENT CANARY",
            evidence_reference: "attachment:iplf-024b-production-canary",
          },
          classes: [{ class_number: 42, specification: "Legal workflow software" }],
          use_priority: null,
          parties: [{ role: "applicant", name: "CaseOps QA Bot LLP" }],
          agent: null,
          filing_manifest: [{
            key: "representation",
            label: "Mark representation",
            required: true,
            evidence_reference: "attachment:iplf-024b-production-canary",
          }],
        },
      },
    });
    expect(createdDocket.status(), await createdDocket.text()).toBe(201);
    docketId = (await createdDocket.json()).id as string;
  }

  const bytes = Buffer.from("IPLF-024B stable production QA evidence. ".repeat(30));
  const uploadDocument = (filename: string, privileged = false) =>
    page.request.post(`${PROD_API_BASE_URL}/api/ip/documents/upload`, {
      headers,
      multipart: {
        metadata_json: JSON.stringify({
          taxonomy_key: "evidence",
          title: privileged
            ? "IPLF-024B privileged production canary"
            : "IPLF-024B production document canary",
          confidentiality: privileged ? "restricted" : "internal",
          is_privileged: privileged,
          client_code: "CASEOPS-QA",
          asset_type: "Trademark",
          mark: privileged ? "PRIVILEGED CANARY" : "DOCUMENT CANARY",
          jurisdiction: "IN",
          document_date: "2026-08-09",
          links: [{ target_type: "docket", target_id: docketId }],
        }),
        upload: {
          name: filename,
          mimeType: "text/plain",
          buffer: privileged
            ? Buffer.from("Privileged IPLF-024B production QA advice. ".repeat(30))
            : bytes,
        },
      },
    });

  const uploaded = await uploadDocument("=iplf-024b-production-canary.txt");
  expect(uploaded.status(), await uploaded.text()).toBe(200);
  const uploadedBody = await uploaded.json();
  const documentId = (uploadedBody.outcome === "created"
    ? uploadedBody.document.id
    : uploadedBody.duplicate_candidates[0].document_id) as string;

  await expect.poll(async () => {
    const response = await page.request.get(`${PROD_API_BASE_URL}/api/ip/documents/${documentId}`);
    expect(response.status(), await response.text()).toBe(200);
    return (await response.json()).versions[0].processing_status as string;
  }, { timeout: 45_000 }).toBe("indexed");
  let documentResponse = await page.request.get(
    `${PROD_API_BASE_URL}/api/ip/documents/${documentId}`,
  );
  let documentBody = await documentResponse.json();
  expect(documentBody.versions[0].original_filename).toBe(
    "=iplf-024b-production-canary.txt",
  );
  expect(documentBody.versions[0].display_name).not.toBe(
    documentBody.versions[0].original_filename,
  );
  expect(documentBody.versions[0].ai_eligible).toBe(true);

  const duplicate = await uploadDocument("different-production-name.txt");
  expect(duplicate.status(), await duplicate.text()).toBe(200);
  const duplicateBody = await duplicate.json();
  expect(duplicateBody.outcome).toBe("duplicate_found");
  expect(duplicateBody.duplicate_candidates[0].document_id).toBe(documentId);

  const transitionTargets: Record<string, string> = {
    draft: "review",
    review: "approved",
    approved: "filed",
    filed: "served",
    served: "accepted",
    rejected: "draft",
  };
  while (documentBody.versions[0].state !== "accepted") {
    const version = documentBody.versions[0];
    const targetState = transitionTargets[version.state];
    expect(targetState, `Unexpected production document state ${version.state}`).toBeTruthy();
    const transition = await page.request.post(
      `${PROD_API_BASE_URL}/api/ip/documents/${documentId}/versions/${version.version}/transition`,
      {
        headers,
        data: {
          expected_current_version: documentBody.current_version,
          expected_state: version.state,
          target_state: targetState,
        },
      },
    );
    expect(transition.status(), await transition.text()).toBe(200);
    documentBody = await transition.json();
  }
  expect(documentBody.versions[0].locked_by_membership_id).toBeTruthy();
  expect(documentBody.versions[0].locked_at).toBeTruthy();

  const downloaded = await page.request.get(
    `${PROD_API_BASE_URL}/api/ip/documents/${documentId}/versions/${documentBody.current_version}/download`,
  );
  expect(downloaded.status(), await downloaded.text()).toBe(200);
  expect(Buffer.from(await downloaded.body())).toEqual(bytes);

  const privilegedUpload = await uploadDocument("iplf-024b-privileged-canary.txt", true);
  expect(privilegedUpload.status(), await privilegedUpload.text()).toBe(200);
  const privilegedBody = await privilegedUpload.json();
  const privilegedDocumentId = (privilegedBody.outcome === "created"
    ? privilegedBody.document.id
    : privilegedBody.duplicate_candidates[0].document_id) as string;
  const policy = await page.request.get(
    `${PROD_API_BASE_URL}/api/ip/documents/${privilegedDocumentId}/policy`,
  );
  expect(policy.status(), await policy.text()).toBe(200);
  expect(await policy.json()).toMatchObject({
    ai_retrieval_allowed: false,
    portal_share_allowed: false,
    export_allowed: false,
    notification_content_allowed: false,
  });
  const denied = await page.request.post(
    `${PROD_API_BASE_URL}/api/ip/documents/${privilegedDocumentId}/authorize-action`,
    { headers, data: { action: "portal_share" } },
  );
  expect(denied.status()).toBe(403);
});
