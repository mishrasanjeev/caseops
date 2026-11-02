/**
 * Document retirement through the IP workspace Documents tab (B4-ADJ-07).
 *
 * Production specs that upload an IP document retire it here, through the UI,
 * after the records that cited it are withdrawn or retired: the server refuses
 * a retirement while a live record still relies on the document, and keeps the
 * retired document readable in history.
 */
import { expect, test, type APIRequestContext, type Page, type Response } from "@playwright/test";

import { expectNoPageOverflow, expectOnScreen, json, type TesterRuntime } from "./ram-bugs4";

/**
 * Runs failure-path cleanup steps without masking the journey's own error: a
 * step that fails is reported as a `cleanup-failure` annotation and on stderr
 * (the residue it leaves is named there), and the remaining steps still run.
 * A passing journey retires everything through the UI, so its steps are no-ops.
 */
export async function runCleanup(steps: Array<[string, (() => Promise<unknown>) | null]>) {
  for (const [label, step] of steps) {
    // A null step names something the journey never created.
    if (step === null) continue;
    try {
      await step();
    } catch (error) {
      const firstLine = error instanceof Error ? error.message.split(/\r?\n/)[0] : String(error);
      const message = `${label} failed: ${firstLine}`;
      test.info().annotations.push({ type: "cleanup-failure", description: message });
      console.error(message);
    }
  }
}

/** Failure-path cleanup: retires the document unless it is already retired. */
export async function retireDocumentByApi(request: APIRequestContext, rt: TesterRuntime, documentId: string) {
  const document = await json(await request.get(`${rt.api.origin}/api/ip/documents/${documentId}`, { headers: rt.headers }),
    "Read document for cleanup");
  if (document.retirement) return;
  await json(await request.post(`${rt.api.origin}/api/ip/documents/${documentId}/retire`, { headers: rt.headers, data: {
    expected_current_version: document.current_version, reason: `Ram batch-4 acceptance cleanup ${rt.run}`,
  } }), "Retire acceptance document");
}

/** Failure-path cleanup: retires the docket unless it is already closed. */
export async function retireDocketByApi(request: APIRequestContext, rt: TesterRuntime, docketId: string) {
  const docket = await json(await request.get(`${rt.api.origin}/api/ip/dockets/${docketId}`, { headers: rt.headers }),
    "Read docket for cleanup");
  if (docket.is_active === false) return;
  const body = {
    expected_lifecycle_version: docket.lifecycle_version, to_status: "retired", effective_at: new Date().toISOString(),
    reason: `Ram batch-4 acceptance record ${rt.run}`, outcome: "test record retired", source: "manual_review",
    evidence_ref: `e2e:${rt.run}`, successor_docket_id: null, acknowledged_exception_codes: [] as string[],
    second_approver_membership_id: null, client_report_handling: "retain", linked_matter_handling: "not_linked",
  };
  const preview = await json(await request.post(`${rt.api.origin}/api/ip/dockets/${docketId}/lifecycle/preview`,
    { headers: rt.headers, data: body }), "Preview docket retirement");
  body.acknowledged_exception_codes = preview.blocker_codes ?? [];
  await json(await request.post(`${rt.api.origin}/api/ip/dockets/${docketId}/lifecycle`, { headers: rt.headers, data: body }),
    "Retire acceptance docket");
}

/** Failure-path cleanup: withdraws the recordal unless it is already withdrawn or rejected. */
export async function withdrawRecordalByApi(request: APIRequestContext, rt: TesterRuntime, recordalId: string) {
  const recordal = await json(await request.get(`${rt.api.origin}/api/ip/recordals/${recordalId}`, { headers: rt.headers }),
    "Read recordal for cleanup");
  if (["withdrawn", "rejected"].includes(recordal.status)) return;
  const docket = await json(await request.get(`${rt.api.origin}/api/ip/dockets/${recordal.docket_id}`, { headers: rt.headers }),
    "Read the recordal's docket for cleanup");
  await json(await request.post(`${rt.api.origin}/api/ip/recordals/${recordalId}/transactions`, { headers: rt.headers, data: {
    expected_version: recordal.version, expected_lifecycle_version: docket.lifecycle_version,
    transaction_kind: "withdrawn", responsible_membership_id: rt.actor.membership.id,
    reason: `Ram batch-4 acceptance cleanup ${rt.run}`,
  } }), "Withdraw acceptance recordal", 201);
}

/** `json` for a browser `Response` (the shared helper takes an `APIResponse`). */
export async function responseJson<T = any>(response: Response, operation: string, expected = 200): Promise<T> {
  expect(response.status(), `${operation} returned ${response.status()}; body intentionally not logged.`).toBe(expected);
  return response.json() as Promise<T>;
}

const HISTORY_TOGGLE = "Show retired documents and documents of closed records";

/**
 * A disposable trademark docket created through the IP workspace's own
 * "New trademark" panel: one Nice class chosen from the catalogue by heading.
 */
export async function createDocketThroughUi(page: Page, rt: TesterRuntime, title: string, wordMark: string) {
  await page.goto(`${rt.web.origin}/app/ip`);
  await page.getByRole("button", { name: "New trademark", exact: true }).click();
  const form = page.getByRole("region", { name: "New trademark application" });
  await expect(form).toBeVisible();
  await form.getByLabel("Docket title", { exact: true }).fill(title);
  await form.getByLabel("Word mark", { exact: true }).fill(wordMark);
  const nice = form.getByRole("combobox", { name: "Nice class, row 1" });
  await nice.click();
  await nice.fill("9");
  await page.getByRole("listbox").getByRole("option", { name: /^Class 9, goods:/ }).click();
  await form.getByLabel("Goods and services, row 1").fill("Downloadable legal practice software");
  await form.getByLabel("Applicant", { exact: true }).fill("Aster Labs Private Limited");
  await form.getByLabel("Representation evidence reference").fill(`e2e:${title}`);
  const created = page.waitForResponse(apiCall(rt, "POST", "/api/ip/trademark-applications/manual"));
  await form.getByRole("button", { name: "Create application" }).click();
  const body = await responseJson<{ docket: { id: string; title: string } }>(await created, "Create the disposable docket", 201);
  expect(body.docket.title).toBe(title);
  return body.docket;
}

function apiCall(rt: TesterRuntime, method: string, path: string) {
  return (response: Response) => {
    const url = new URL(response.url());
    return url.origin === rt.api.origin && response.request().method() === method && url.pathname === path;
  };
}

/** Opens the Documents tab with history shown and returns the document's card, found by server identity. */
export async function openDocumentCard(page: Page, rt: TesterRuntime, documentId: string, history: boolean) {
  await page.goto(`${rt.web.origin}/app/ip?tab=documents`);
  await expect(page.getByRole("tab", { name: "Documents", exact: true })).toHaveAttribute("aria-selected", "true");
  const toggle = page.getByLabel(HISTORY_TOGGLE);
  await expect(toggle).toBeVisible();
  if (history) {
    const listed = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.origin === rt.api.origin && url.pathname === "/api/ip/documents"
        && url.searchParams.get("include_history") === "true";
    });
    await toggle.check();
    await responseJson(await listed, "List documents with history");
  }
  const card = page.getByTestId(`ip-document-${documentId}`);
  await expect(card).toBeVisible();
  return card;
}

/**
 * A document listed only because its record is closed is read-only: the API
 * says so, and the card offers Download and Retire but no state change, no new
 * version and no bulk selection (each of those is refused by the API).
 */
async function expectClosedRecordCard(page: Page, rt: TesterRuntime, card: ReturnType<Page["getByTestId"]>, documentId: string) {
  const detail = await json<{ read_only_reason: string | null; retirement: unknown }>(
    await page.request.get(`${rt.api.origin}/api/ip/documents/${documentId}`, { headers: rt.headers }),
    "Closed record's document detail");
  expect(detail).toEqual(expect.objectContaining({ read_only_reason: "closed_record", retirement: null }));
  await expect(card).toHaveAttribute("data-read-only", "true");
  await expect(card.getByText("Closed record", { exact: true })).toBeVisible();
  await expect(card.getByText(/Its record is closed/)).toBeVisible();
  await expect(card.getByRole("button", { name: /Download original/ })).toBeEnabled();
  await expect(card.getByRole("button", { name: /^Move to / })).toHaveCount(0);
  await expect(card.getByLabel(/^New version for /)).toHaveCount(0);
  await expect(card.getByRole("checkbox")).toHaveCount(0);
}

/**
 * Retires an uploaded document through the Documents tab: the reliance check,
 * the reason and the confirm, then asserts the server state and the history card.
 */
export async function retireDocumentThroughUi(
  page: Page,
  rt: TesterRuntime,
  documentId: string,
  reason: string,
  options: { history: boolean; mobile: boolean; closedRecord?: boolean },
) {
  const card = await openDocumentCard(page, rt, documentId, options.history);
  await expect(card).toHaveAttribute("data-retired", "false");
  if (options.closedRecord) await expectClosedRecordCard(page, rt, card, documentId);
  const previewed = page.waitForResponse(apiCall(rt, "GET", `/api/ip/documents/${documentId}/retirement`));
  await card.getByRole("button", { name: "Retire", exact: true }).click();
  const preview = await responseJson<{ retirable: boolean; blockers: unknown[] }>(await previewed, "Check what relies on the document");
  expect(preview).toEqual(expect.objectContaining({ retirable: true, blockers: [] }));
  const panel = card.getByRole("region", { name: /^Retire / });
  const field = panel.getByLabel("Reason for retiring");
  await expect(field).toBeVisible();
  await field.fill(reason);
  const confirm = panel.getByRole("button", { name: "Retire document" });
  await expect(confirm).toBeEnabled();
  await confirm.scrollIntoViewIfNeeded();
  await expectOnScreen(confirm, "Retire document is on screen");
  await expectNoPageOverflow(page);
  const retired = page.waitForResponse(apiCall(rt, "POST", `/api/ip/documents/${documentId}/retire`));
  await confirm.click();
  const response = await retired;
  expect(response.request().postDataJSON()).toEqual(expect.objectContaining({ reason: reason.trim() }));
  const body = await responseJson<{ id: string; retirement: { reason: string; retired_by_name: string } | null }>(
    response, "Retire the document");
  expect(body.id).toBe(documentId);
  expect(body.retirement?.reason).toBe(reason.trim());

  // Server state: readable in history, gone from the current list.
  const detail = await json<{ retirement: { reason: string } | null }>(
    await page.request.get(`${rt.api.origin}/api/ip/documents/${documentId}`, { headers: rt.headers }),
    "Retired document detail");
  expect(detail.retirement?.reason).toBe(reason.trim());
  const current = await json<{ items: Array<{ id: string }> }>(
    await page.request.get(`${rt.api.origin}/api/ip/documents`, { headers: rt.headers }), "Current documents");
  expect(current.items.map((row) => row.id)).not.toContain(documentId);
  return body;
}

/** Asserts the retire panel names the live record and keeps its confirm disabled. */
export async function expectRetirementBlockedThroughUi(
  page: Page,
  rt: TesterRuntime,
  documentId: string,
  blocker: { label: string; status: string; recordId: string },
  options: { mobile: boolean },
) {
  const card = await openDocumentCard(page, rt, documentId, false);
  const previewed = page.waitForResponse(apiCall(rt, "GET", `/api/ip/documents/${documentId}/retirement`));
  await card.getByRole("button", { name: "Retire", exact: true }).click();
  const preview = await responseJson<{ retirable: boolean; blockers: Array<{ record_id: string; kind: string }> }>(
    await previewed, "Check what relies on the document");
  expect(preview.retirable).toBe(false);
  expect(preview.blockers.map((row) => row.record_id)).toEqual([blocker.recordId]);
  const panel = card.getByRole("region", { name: /^Retire / });
  const list = panel.getByTestId("ip-document-retirement-blockers");
  await expect(list).toContainText(`${blocker.label} · ${blocker.status}`);
  await expect(list.getByRole("link", { name: "Open" })).toBeVisible();
  await expect(panel.getByLabel("Reason for retiring")).toHaveCount(0);
  const confirm = panel.getByRole("button", { name: "Retire document" });
  await expect(confirm).toBeDisabled();
  await expect(confirm).toHaveAccessibleDescription(/still relies on this document/);
  await expectNoPageOverflow(page);
  await panel.getByRole("button", { name: "Cancel" }).click();
  await expect(panel).toHaveCount(0);
}
