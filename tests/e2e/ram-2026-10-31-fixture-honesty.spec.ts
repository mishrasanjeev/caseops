/**
 * BUG-002 (Documents Classification empty) fixture honesty.
 *
 * Earlier document journeys loaded the taxonomy through the admin seed
 * endpoint before opening the UI, so they passed on tenants where Ram saw an
 * empty Classification select. These journeys sign in as the tester and fail
 * if the page calls that endpoint; fixtures (prepareTester and every e2e
 * helper) are kept off it by the static guard in
 * apps/web/lib/e2e-document-taxonomy-seed-guard.test.ts. The options must
 * come from product provisioning (workspace configuration locally, proven by
 * the provisioning audit event; the release backfill on test-legal).
 *
 * Production runs only read and preview (naming-preview is side-effect free),
 * so no record is retained. The upload half is [local-only]: it links to a
 * docket created through the API, because docket creation is not the path
 * under test here (it belongs to the BUG-001 create journey).
 */
import { expect, test, type Page, type Request } from "@playwright/test";

import {
  expectNoPageOverflow, expectOnScreen, json, markPositive, prepareTester, stamp, type TesterRuntime,
} from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

// Built from segments so the static seed guard covers this file as well.
const TAXONOMY_PATH = "/api/ip/document-taxonomy";
const DOCUMENT_FILE = { name: "classification-check.txt", mimeType: "text/plain" };

/**
 * Records every request the page issues to the admin seed endpoint. It does
 * not see the Playwright `request` fixture or page.request; those are kept
 * off the endpoint by the static guard.
 */
function watchSeedCalls(page: Page): Request[] {
  const calls: Request[] = [];
  page.on("request", req => {
    const { pathname } = new URL(req.url());
    if (pathname.startsWith(`${TAXONOMY_PATH}/`) && pathname.split("/").pop() === "seed") calls.push(req);
  });
  return calls;
}

/** Local only: the tenant's entries were provisioned by workspace configuration, never seeded. */
async function expectProvisioningAudit(page: Page, rt: TesterRuntime) {
  const events = async (action: string) => {
    const response = await page.request.get(`${rt.api.origin}/api/admin/audit/export`, {
      headers: rt.headers, params: { action, format: "jsonl" },
    });
    expect(response.status(), `audit export for ${action}`).toBe(200);
    return (await response.text()).split(/\r?\n/).filter(Boolean)
      .map(line => JSON.parse(line) as { metadata: { trigger?: string } | null });
  };
  const provisioned = await events("ip_document_taxonomy.defaults_provisioned");
  expect(provisioned.map(event => event.metadata?.trigger), "provisioning audit trigger").toEqual(["workspace_configuration"]);
  expect(await events("ip_document_taxonomy.seeded"), "no seed audit event on the tester tenant").toEqual([]);
}

async function expectProvisionedReadiness(page: Page, rt: TesterRuntime) {
  const readiness = await json(await page.request.get(`${rt.api.origin}/api/ip/readiness`, { headers: rt.headers }),
    "Tester IP readiness");
  const taxonomy = readiness.configuration_status?.document_taxonomy;
  expect(taxonomy, "readiness reports document taxonomy provisioning").toBeTruthy();
  expect(taxonomy.ready, "the tester's document taxonomy is provisioned").toBe(true);
  expect(taxonomy.active_entry_count).toBeGreaterThanOrEqual(1);
  // A fresh local tenant receives exactly the standard catalogue.
  if (rt.local) expect(taxonomy.active_entry_count).toBe(14);
  return taxonomy as { active_entry_count: number };
}

async function openDocuments(page: Page, rt: TesterRuntime) {
  await page.goto(`${rt.web.origin}/app/ip`);
  await page.getByRole("tab", { name: "Documents", exact: true }).click();
  const workspace = page.getByTestId("ip-document-workspace");
  await expect(workspace.getByRole("heading", { name: "Document workflow" })).toBeVisible();
  return workspace;
}

/** Classification offers the server-listed classes, starts unchosen, and gates preview/upload. */
async function proveClassification(page: Page, rt: TesterRuntime, activeCount: number) {
  const workspace = await openDocuments(page, rt);
  const classification = workspace.getByLabel("Classification", { exact: true });
  await expect(classification).toBeEnabled();
  const options = classification.locator('option:not([value=""])');
  await expect(options).toHaveCount(activeCount);
  await expect(classification.locator('option[value="assignment"]')).toHaveText("Assignment");
  await expect(classification).toHaveValue("");
  await expect(workspace.getByText("No document classifications are configured")).toHaveCount(0);

  const preview = workspace.getByRole("button", { name: "Preview controlled name", exact: true });
  const upload = workspace.getByRole("button", { name: "Upload reviewed document", exact: true });
  await expect(preview).toBeDisabled();
  await expect(upload).toBeDisabled();
  await expect(workspace.locator("#ip-document-upload-requirements")).toContainText("a classification");

  await workspace.getByLabel("Original file", { exact: true }).setInputFiles({
    ...DOCUMENT_FILE, buffer: Buffer.from(`${stamp("Classification check")}; synthetic, no legal effect.`),
  });
  await classification.selectOption("assignment");
  await expect(classification).toHaveValue("assignment");
  await expect(preview).toBeEnabled();
  const rendered = await options.evaluateAll(nodes => nodes.map(node => (node as HTMLOptionElement).value));

  const previewed = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/ip/documents/naming-preview" && response.request().method() === "POST");
  await preview.click();
  const response = await previewed;
  expect(response.status(), "naming preview").toBe(200);
  const sent = response.request().postDataJSON() as { document_type: string };
  expect(rendered, "the previewed classification is one the page rendered from the server list").toContain(sent.document_type);
  expect(sent.document_type).toBe("assignment");
  await expect(workspace.getByText("Controlled name preview", { exact: true })).toBeVisible();
  return { workspace, classification, preview, upload, rendered };
}

test("BUG-002 Ram's Documents Classification is provisioned, never seeded, and previews a classified name", async ({
  page, request, baseURL,
}, info) => {
  test.setTimeout(180_000);
  const seedCalls = watchSeedCalls(page);
  const rt = await prepareTester(page, request, baseURL);
  const taxonomy = await expectProvisionedReadiness(page, rt);
  await proveClassification(page, rt, taxonomy.active_entry_count);
  expect(seedCalls, "the page never calls the admin seed endpoint (fixtures: static guard)").toHaveLength(0);
  await markPositive(info, "bug-002-classification-provisioned", {
    local: rt.local, active_entry_count: taxonomy.active_entry_count,
  });
});

test("BUG-002 [local-only] a classified upload from the provisioned taxonomy is created as Assignment", async ({
  page, request, baseURL,
}, info) => {
  test.setTimeout(180_000);
  const seedCalls = watchSeedCalls(page);
  const rt = await prepareTester(page, request, baseURL);
  expect(rt.local, "This test creates records; production runs the preview test instead.").toBe(true);
  const taxonomy = await expectProvisionedReadiness(page, rt);
  await expectProvisioningAudit(page, rt);
  // Prerequisite only (docket creation is BUG-001's journey): a stamped docket to link to.
  const title = stamp("Fixture honesty docket");
  const docket = await json(await page.request.post(`${rt.api.origin}/api/ip/dockets`, { headers: rt.headers, data: {
    title, primary_identifier: `TM-${title.replace(/\W+/g, "-")}`,
    particulars: {
      form_key: "TM-A", form_version: "2026.1", mark_kind: "word",
      representation: { text: "FIXTURE HONESTY", evidence_reference: "attachment:fixture-honesty" },
      classes: [{ class_number: 42, specification: "Legal workflow software" }],
      use_priority: null, parties: [{ role: "applicant", name: "Test Legal LLP" }], agent: null,
      filing_manifest: [{ key: "representation", label: "Mark representation", required: true,
        evidence_reference: "attachment:fixture-honesty" }],
    },
  } }), "Local prerequisite docket", 201);

  const { workspace, upload, rendered } = await proveClassification(page, rt, taxonomy.active_entry_count);
  await workspace.getByLabel("Linked docket", { exact: true }).selectOption(docket.id);
  await expect(upload).toBeEnabled();
  const uploaded = page.waitForResponse(response =>
    new URL(response.url()).pathname === "/api/ip/documents/upload" && response.request().method() === "POST");
  await upload.click();
  const response = await uploaded;
  expect(response.status(), "document upload").toBe(200);
  // The browser does not expose a multipart body with a file; the stored record is the oracle.
  const body = await response.json();
  expect(body.outcome).toBe("created");
  expect(body.document.taxonomy_key).toBe("assignment");
  expect(rendered, "the stored classification is one the page offered").toContain(body.document.taxonomy_key);
  await expect(workspace.getByText(body.document.versions[0].display_name, { exact: true }).first()).toBeVisible();

  const listed = await json(await page.request.get(`${rt.api.origin}/api/ip/documents?docket_id=${docket.id}`,
    { headers: rt.headers }), "Docket documents");
  expect(listed.items.map((item: { id: string }) => item.id)).toContain(body.document.id);
  expect(seedCalls, "the page never calls the admin seed endpoint (fixtures: static guard)").toHaveLength(0);
  await markPositive(info, "bug-002-classified-upload", { document_id: body.document.id });
});

test("BUG-002 [mobile] Classification and its upload gate stay on screen without horizontal scroll", async ({
  page, request, baseURL,
}, info) => {
  test.setTimeout(180_000);
  const seedCalls = watchSeedCalls(page);
  const viewport = page.viewportSize() ?? { width: 393, height: 851 };
  const rt = await prepareTester(page, request, baseURL, viewport);
  const taxonomy = await expectProvisionedReadiness(page, rt);
  const { classification, preview } = await proveClassification(page, rt, taxonomy.active_entry_count);
  await classification.scrollIntoViewIfNeeded();
  await expectOnScreen(classification, "Classification is reachable on a phone");
  await preview.scrollIntoViewIfNeeded();
  await expectOnScreen(preview, "Preview controlled name is reachable on a phone");
  await expectNoPageOverflow(page);
  expect(seedCalls, "the page never calls the admin seed endpoint (fixtures: static guard)").toHaveLength(0);
  await markPositive(info, "bug-002-classification-mobile", { viewport });
});
