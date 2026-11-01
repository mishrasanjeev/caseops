/**
 * B4-ADJ-07 (Ram batch 4 adjacent defect, 2026-11-01): an IP document could
 * not be retired, so every tester upload stayed in the tenant for good.
 *
 * Signed in as the tester through the real sign-in form (production: Ram on
 * test-legal; local: a fresh tenant shaped like it), each run:
 *   1. creates a disposable, clock-stamped trademark docket through the
 *      "New trademark" panel;
 *   2. uploads a document to it from the Documents tab;
 *   3. opens Retire on that document, is told (on the field) that the reason
 *      is too short without any request leaving the browser, then retires it
 *      with a reason;
 *   4. sees it leave the current list and every picker the API serves, and
 *      finds it, read-only with its reason, under "Show retired documents";
 *   5. retires the docket (API oracle cleanup, as the ip-create journey does).
 *
 * The refusal while a live record relies on the document is proven through
 * the UI by ram-2026-10-31-recordals.spec.ts (a draft recordal blocks it, the
 * withdrawn recordal releases it). B4-ADJ-06 (event- and deadline-linked
 * documents in the docket list) has no UI path that creates such a link, so it
 * is proven by apps/api/tests/test_ip_document_retirement_20261101.py.
 * Traces, screenshots and video stay off because the runtime holds the
 * tester's credentials.
 */
import { expect, test, type APIRequestContext, type Page, type Request, type TestInfo } from "@playwright/test";

import { createDocketThroughUi, openDocumentCard, responseJson } from "./support/ip-documents";
import {
  expectNoPageOverflow,
  expectOnScreen,
  json,
  markPositive,
  prepareTester,
  stamp,
  type TesterRuntime,
} from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

const DESKTOP = { width: 1440, height: 900 };
const PIXEL_5 = { width: 393, height: 851 };

async function retireDocketByApi(request: APIRequestContext, rt: TesterRuntime, docketId: string) {
  const docket = await json(await request.get(`${rt.api.origin}/api/ip/dockets/${docketId}`, { headers: rt.headers }),
    "Read docket for cleanup");
  const body = {
    expected_lifecycle_version: docket.lifecycle_version, to_status: "retired", effective_at: new Date().toISOString(),
    reason: `Ram batch-4 adjacent acceptance record ${rt.run}`, outcome: "test record retired", source: "manual_review",
    evidence_ref: `e2e:${rt.run}`, successor_docket_id: null, acknowledged_exception_codes: [] as string[],
    second_approver_membership_id: null, client_report_handling: "retain", linked_matter_handling: "not_linked",
  };
  const preview = await json(await request.post(`${rt.api.origin}/api/ip/dockets/${docketId}/lifecycle/preview`,
    { headers: rt.headers, data: body }), "Preview docket retirement");
  body.acknowledged_exception_codes = preview.blocker_codes ?? [];
  await json(await request.post(`${rt.api.origin}/api/ip/dockets/${docketId}/lifecycle`, { headers: rt.headers, data: body }),
    "Retire acceptance docket");
}

async function uploadFromDocumentsTab(page: Page, rt: TesterRuntime, docketId: string, title: string): Promise<string> {
  await page.goto(`${rt.web.origin}/app/ip?docket=${docketId}&tab=documents`);
  const workspace = page.getByTestId("ip-document-workspace");
  await expect(workspace.locator("#ip-document-docket")).toHaveValue(docketId);
  await workspace.getByLabel("Original file", { exact: true }).setInputFiles({
    name: `${title.replaceAll(" ", "-")}.txt`, mimeType: "text/plain",
    buffer: Buffer.from(`Mistaken upload for ${title}; no legal effect.\n`.repeat(20)),
  });
  await workspace.getByLabel("Title", { exact: true }).fill(title);
  const classification = workspace.getByLabel("Classification", { exact: true });
  await expect(classification).toBeEnabled();
  const key = await classification.locator('option:not([value=""]):not([disabled])').first().getAttribute("value");
  expect(key, "An enabled IP workspace offers at least one classification").toBeTruthy();
  await classification.selectOption(key as string);
  await workspace.getByRole("button", { name: "Preview controlled name" }).click();
  await expect(workspace.getByText("Controlled name preview", { exact: true })).toBeVisible();
  const uploaded = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/ip/documents/upload"
    && response.request().method() === "POST");
  await workspace.getByRole("button", { name: "Upload reviewed document" }).click();
  const result = await responseJson<{ outcome: string; document: { id: string; title: string } }>(await uploaded, "Upload the document");
  expect(result.outcome).toBe("created");
  expect(result.document.title).toBe(title);
  return result.document.id;
}

async function retirementJourney(page: Page, request: APIRequestContext, rt: TesterRuntime, info: TestInfo, mobile: boolean) {
  const docket = await createDocketThroughUi(page, rt, stamp(`ADJ-07 docket ${mobile ? "mobile" : "desktop"}`),
    mobile ? "ADJ07M" : "ADJ07D");
  try {
    const title = stamp(`ADJ-07 mistaken upload ${mobile ? "mobile" : "desktop"}`);
    const documentId = await uploadFromDocumentsTab(page, rt, docket.id, title);

    // Retire from the current list: the reliance check runs first.
    const card = await openDocumentCard(page, rt, documentId, false);
    await expectNoPageOverflow(page);
    const retire = card.getByRole("button", { name: "Retire", exact: true });
    await expect(retire).toHaveAttribute("aria-expanded", "false");
    const previewed = page.waitForResponse((response) =>
      new URL(response.url()).pathname === `/api/ip/documents/${documentId}/retirement`);
    await retire.click();
    const preview = await responseJson<{ retirable: boolean; may_retire: boolean; blockers: unknown[]; title: string }>(
      await previewed, "Check what relies on the document");
    expect(preview).toEqual(expect.objectContaining({ retirable: true, may_retire: true, blockers: [], title }));
    await expect(retire).toHaveAttribute("aria-expanded", "true");
    const panel = card.getByRole("region", { name: `Retire ${title}` });
    const reason = panel.getByLabel("Reason for retiring");
    await expectOnScreen(reason, "The reason field is on screen");
    await expectNoPageOverflow(page);

    // A too-short reason is anchored on the field and nothing is sent.
    const retireRequests: Request[] = [];
    const track = (req: Request) => {
      if (new URL(req.url()).pathname === `/api/ip/documents/${documentId}/retire`) retireRequests.push(req);
    };
    page.on("request", track);
    await reason.fill("mistake");
    const confirm = panel.getByRole("button", { name: "Retire document" });
    await confirm.click();
    const error = panel.getByRole("alert");
    await expect(error).toHaveText("Give a reason of at least 10 characters.");
    await expect(reason).toHaveAttribute("aria-invalid", "true");
    await expect(reason).toHaveAttribute("aria-describedby", new RegExp(await error.getAttribute("id") ?? "missing-id"));
    expect(retireRequests).toEqual([]);

    // A real reason retires it.
    const why = `Uploaded to the wrong record during acceptance run ${rt.run}.`;
    await reason.fill(why);
    await expect(error).toHaveCount(0);
    const retired = page.waitForResponse((response) => new URL(response.url()).pathname === `/api/ip/documents/${documentId}/retire`
      && response.request().method() === "POST");
    await confirm.click();
    const body = await responseJson<{ id: string; retirement: { reason: string; retired_by_name: string } }>(await retired, "Retire the document");
    page.off("request", track);
    expect(retireRequests).toHaveLength(1);
    expect(body.retirement.reason).toBe(why);
    await expect(card).toHaveCount(0);

    // Server truth: readable in history, gone from the lists and pickers.
    const ids = async (path: string) => (await json<{ items: Array<{ id: string }> }>(
      await request.get(`${rt.api.origin}${path}`, { headers: rt.headers }), `GET ${path}`)).items.map((row) => row.id);
    expect(await ids("/api/ip/documents")).not.toContain(documentId);
    expect(await ids(`/api/ip/documents?docket_id=${docket.id}`)).not.toContain(documentId);
    expect(await ids(`/api/ip/recordals/instruments?docket_id=${docket.id}`)).not.toContain(documentId);
    expect(await ids(`/api/ip/documents?docket_id=${docket.id}&include_history=true`)).toContain(documentId);

    // History shows it read-only, with who retired it and why.
    const history = await openDocumentCard(page, rt, documentId, true);
    await expect(history).toHaveAttribute("data-retired", "true");
    await expect(history.getByText("Retired", { exact: true })).toBeVisible();
    await expect(history).toContainText(`by ${body.retirement.retired_by_name}: ${why}`);
    await expect(history.getByRole("button", { name: /Download original/ })).toBeEnabled();
    await expect(history.getByRole("button", { name: "Retire", exact: true })).toHaveCount(0);
    await expect(history.getByRole("button", { name: /Move to/ })).toHaveCount(0);
    await expect(history.getByLabel(/New version for/)).toHaveCount(0);
    // No lawyer-facing internal id in the card.
    await expect(history).not.toContainText(documentId);
    await expectNoPageOverflow(page);
    await markPositive(info, `adj07-document-retired-${mobile ? "mobile" : "desktop"}`, {
      local: rt.local, docket_id: docket.id, document_id: documentId,
    });
  } finally {
    await retireDocketByApi(request, rt, docket.id);
  }
}

test("B4-ADJ-07 Ram retires a mistaken upload from the Documents tab and finds it under history", async ({ page, request, baseURL }, info) => {
  test.setTimeout(6 * 60_000);
  const rt = await prepareTester(page, request, baseURL, DESKTOP);
  await retirementJourney(page, request, rt, info, false);
});

test("B4-ADJ-07 [mobile] the retire panel, its field error and the history card fit 393px", async ({ page, request, baseURL }, info) => {
  test.setTimeout(6 * 60_000);
  const rt = await prepareTester(page, request, baseURL, PIXEL_5);
  expect(page.viewportSize()).toEqual(PIXEL_5);
  await retirementJourney(page, request, rt, info, true);
});
