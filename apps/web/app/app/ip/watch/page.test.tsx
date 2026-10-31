import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/config";

const {
  capabilityMock,
  coreMock,
  createHandoffMock,
  createProfileMock,
  decideHitMock,
  docketMock,
  docketsMock,
  ingestMock,
  readinessMock,
  toastError,
  toastSuccess,
  usersMock,
  workspaceMock,
} = vi.hoisted(() => ({
  capabilityMock: vi.fn(),
  coreMock: vi.fn(),
  createHandoffMock: vi.fn(),
  createProfileMock: vi.fn(),
  decideHitMock: vi.fn(),
  docketMock: vi.fn(),
  docketsMock: vi.fn(),
  ingestMock: vi.fn(),
  readinessMock: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
  usersMock: vi.fn(),
  workspaceMock: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => capabilityMock(capability),
}));

vi.mock("@/lib/use-session", () => ({
  useSession: () => ({
    status: "authenticated",
    token: null,
    context: { membership: { id: "member-1" } },
    signOut: vi.fn(),
  }),
}));

vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));

vi.mock("@/lib/api/endpoints", () => ({
  createIpWatchHandoff: createHandoffMock,
  createIpWatchProfile: createProfileMock,
  decideIpWatchHit: decideHitMock,
  fetchIpCoreRecords: coreMock,
  fetchIpDocket: docketMock,
  fetchIpDockets: docketsMock,
  fetchIpWatchWorkspace: workspaceMock,
  fetchIpWorkspaceReadiness: readinessMock,
  ingestIpJournal: ingestMock,
  listCompanyUsers: usersMock,
  updateIpWatchProfileStatus: vi.fn(),
}));

import IpJournalWatchPage from "@/app/app/ip/watch/page";

const PROFILE = {
  id: "profile-1",
  docket_id: "docket-1",
  name: "ASTER publication watch",
  provider_key: "manual-journal",
  word_terms_json: ["ASTER"],
  phonetic_terms_json: ["ASTER"],
  device_references_json: [],
  class_numbers_json: [9, 42],
  proprietor_terms_json: [],
  jurisdictions_json: ["IN"],
  frequency: "publication",
  recipient_membership_ids_json: ["member-1"],
  max_cost_minor_per_period: 500,
  spent_cost_minor_in_period: 20,
  cost_currency: "INR",
  poll_status: "active",
  pause_reason: null,
  last_polled_at: "2026-08-24T08:00:00Z",
  next_poll_at: "2026-08-25T08:00:00Z",
  version: 1,
};

const PUBLICATION = {
  id: "publication-1",
  application_id: "application-1",
  provider_key: "ipindia-journal-manual",
  journal_number: "TMJ-2248",
  journal_date: "2026-08-21",
  publication_kind: "readvertisement",
  application_number: "TM-9876543",
  mark_text: "ASTER PRIME",
  proprietor_name: "Aster Legal Technologies",
  class_numbers_json: [9, 42],
  goods_services_json: { "9": ["downloadable software"], "42": ["SaaS"] },
  publication_scope_json: { scope_kind: "partial", published_classes: [9] },
  source_url: "https://ipindia.gov.in/journal/2248/page/412",
  source_page: "412",
  source_status: "unavailable",
  source_retrieved_at: "2026-08-24T08:00:00Z",
  attribution_json: { publisher: "IP India" },
  raw_evidence_json: { extract_text: "ASTER PRIME, class 9 and 42, advertised before acceptance.", capture_method: "manual" },
};

// A capture that matched no profile: listed for correction, never in the hit queue.
const ZERO_HIT_PUBLICATION = {
  ...PUBLICATION,
  id: "publication-zero",
  publication_kind: "advertisement",
  journal_number: "2187",
  journal_date: "2026-10-27",
  application_number: "BUG014-TRIAGE-20261031",
  mark_text: "ZQXV TRIAGE PROBE",
  class_numbers_json: [45],
  goods_services_json: { "45": ["Legal services"] },
  publication_scope_json: { scope_kind: "full" },
  source_status: "available",
  raw_evidence_json: { page_text: "Journal 2187 page 45", captured_by: "BUG-014 triage" },
};

const HIT = {
  id: "hit-1",
  profile_id: PROFILE.id,
  publication_id: PUBLICATION.id,
  duplicate_of_hit_id: "hit-original",
  candidate_mark_json: { mark_text: "ASTER PRIME" },
  classes_goods_json: { scope: { scope_kind: "partial" } },
  similarity_evidence_json: { word: [{ compared: "ASTER", score: 0.87 }], class_overlap: [9, 42] },
  ai_advisory: true,
  advisory_notice: "Similarity scoring is advisory. Verify the official source.",
  source_url: PUBLICATION.source_url,
  source_status: "unavailable",
  hit_date: "2026-08-21",
  stale_source_alert: true,
  deadline_confirmation_state: "pending",
  disposition: "reviewing",
  disposition_reason: "Awaiting source",
  version: 2,
};

const WORKSPACE = {
  profiles: [PROFILE],
  publications: [PUBLICATION, ZERO_HIT_PUBLICATION],
  hits: [HIT],
  ingestion_runs: [],
  handoffs: [],
  intake_profile_count: 1,
};

const DOCKET = { id: "docket-1", title: "ASTER mark", primary_identifier: "TM-9876543", record_type: "trademark" };

const USERS = {
  company_id: "company-1",
  company_slug: "aster",
  users: [
    { membership_id: "member-1", role: "owner", membership_active: true, user_id: "u-1", email: "ram@aster.example", full_name: "Ram Gupta", user_active: true, created_at: "2026-01-01" },
    { membership_id: "member-2", role: "member", membership_active: true, user_id: "u-2", email: "hari@aster.example", full_name: "Hari Rao", user_active: true, created_at: "2026-01-01" },
  ],
};

function readiness(blocked: string[]) {
  return {
    timezone: "Asia/Kolkata",
    workspace_available: true,
    manual_docketing_available: true,
    features: [{
      feature_id: "watch_operations",
      available: blocked.length === 0,
      reason: blocked[0] ?? "available",
      blocked_reasons: blocked,
      owner: "product-ip",
      required_capabilities: ["ip:watch_manage"],
      missing_capabilities: [],
      entitlement_key: "ip_watch",
      entitled: !blocked.includes("missing_entitlement"),
      rollout_flag: "ip_watch_enabled",
      rollout_enabled: !blocked.includes("rollout_disabled"),
      rollout_expires_at: null,
      manual_fallback_feature_id: "manual_docketing",
      blocked_by_incident_id: null,
    }],
  };
}

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

// Mutation tests query only inside their own render container. If a test ever
// overruns its deadline, cleanup() empties that container and the abandoned
// user flow fails on its next query instead of driving the next test's page.
function renderWatchPage() {
  const view = render(<IpJournalWatchPage />, { wrapper: wrapper() });
  return within(view.container);
}

// One paste per field: the field still receives focus and a real input event,
// but the page re-renders once per field instead of once per character.
async function enterText(user: UserEvent, field: HTMLElement, value: string) {
  await user.click(field);
  await user.paste(value);
  expect(field).toHaveDisplayValue(value);
}

async function chooseScopeDocket(user: UserEvent, page: ReturnType<typeof renderWatchPage>) {
  const scope = await page.findByRole<HTMLSelectElement>("combobox", { name: "Docket scope" });
  await waitFor(() => expect(scope).toBeEnabled());
  await user.selectOptions(scope, "docket-1");
  return scope;
}

async function fillLawyerCapture(user: UserEvent, page: ReturnType<typeof renderWatchPage>, classes: string) {
  await enterText(user, page.getByLabelText("Journal number"), "2187");
  await user.type(page.getByLabelText("Journal date"), "2026-10-27");
  await enterText(user, page.getByLabelText("Registry application number"), "BUG014-CAPTURE-1");
  await enterText(user, page.getByLabelText("Published word mark"), "ZQXV CAPTURE");
  await enterText(user, page.getByLabelText("Published Nice classes"), classes);
  await enterText(user, page.getByLabelText("Official source URL"), "https://search.ipindia.gov.in/IPOJournal/Journal/ViewJournal");
  await enterText(user, page.getByLabelText("Source page"), "45");
}

describe("IP journal watch page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capabilityMock.mockReturnValue(true);
    docketsMock.mockResolvedValue({ dockets: [DOCKET], count: 1, has_more: false, next_cursor: null, total_count: 1 });
    docketMock.mockResolvedValue(DOCKET);
    coreMock.mockResolvedValue({
      assets: [{ id: "asset-1", title: "ASTER" }],
      applications: [{ id: "application-1", asset_id: "asset-1", office: "IP India", jurisdiction: "IN", filing_phase: "filed" }],
      proceedings: [],
      identifiers: [{ application_id: "application-1", identifier_kind: "application", raw_value: "TM-9876543", effective_until: null }],
    });
    workspaceMock.mockResolvedValue(WORKSPACE);
    readinessMock.mockResolvedValue(readiness(["rollout_disabled"]));
    usersMock.mockResolvedValue(USERS);
  });

  it("fails closed without IP read access", () => {
    capabilityMock.mockReturnValue(false);
    render(<IpJournalWatchPage />, { wrapper: wrapper() });
    expect(screen.getByText("IP access required")).toBeVisible();
    expect(workspaceMock).not.toHaveBeenCalled();
  });

  it("shows correction lineage, source failure blocking, captured evidence and advisory evidence", async () => {
    render(<IpJournalWatchPage />, { wrapper: wrapper() });
    expect(await screen.findByRole("heading", { name: "ASTER PRIME" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Open source" })).toHaveAttribute("href", PUBLICATION.source_url);
    expect(screen.getByText(/Final source-dependent dispositions are blocked/)).toBeVisible();
    expect(screen.getByText(/Prior hit hit-original/)).toBeVisible();
    expect(screen.getByText("AI assistance is advisory.")).toBeVisible();
    expect(screen.getByText(/class_overlap/)).toBeVisible();
    // IP-WATCH-02: the evidence the lawyer captured is shown with the hit, not hidden.
    expect(screen.getByText(PUBLICATION.raw_evidence_json.extract_text)).toBeVisible();
    expect(screen.getByText("Only classes 9")).toBeVisible();
  });

  it("BUG-014 keeps All accessible dockets selected and never picks a docket by itself", async () => {
    const user = userEvent.setup();
    const page = renderWatchPage();
    const scope = await chooseScopeDocket(user, page);
    await waitFor(() => expect(workspaceMock).toHaveBeenLastCalledWith("docket-1"));
    await user.selectOptions(scope, "");
    await waitFor(() => expect(workspaceMock).toHaveBeenLastCalledWith(null));
    expect(scope).toHaveValue("");
    expect(scope.selectedOptions[0]).toHaveTextContent("All accessible dockets");
  });

  it("names each automation gate instead of one generic sentence", async () => {
    readinessMock.mockResolvedValue(readiness(["missing_entitlement", "rollout_disabled"]));
    const page = renderWatchPage();
    const automated = await page.findByTestId("watch-readiness-automated");
    expect(await within(automated).findByText("Not in your plan")).toBeVisible();
    expect(within(automated).getByText("Paused by CaseOps")).toBeVisible();
    expect(within(automated).getByText("CaseOps has not switched automated journal polling on yet.")).toBeVisible();
    const manual = page.getByTestId("watch-readiness-manual");
    expect(within(manual).getByText("Available")).toBeVisible();
    expect(within(manual).getByText(/This is the manual path/)).toBeVisible();
  });

  it("labels a linked journal application by mark and number and really selects the no-link option", async () => {
    const user = userEvent.setup();
    const page = renderWatchPage();
    await chooseScopeDocket(user, page);
    await user.click(page.getByRole("button", { name: "Journal intake" }));
    const application = await page.findByRole<HTMLSelectElement>("combobox", { name: "Linked trademark application" });
    await user.selectOptions(application, "application-1");
    expect(application).toHaveAccessibleDescription("ASTER · Application TM-9876543 · IP India · filed");
    expect(document.getElementById(application.getAttribute("aria-describedby")!))
      .toHaveAttribute("data-selected-option-value", "application-1");
    await user.selectOptions(application, "");
    expect(application.value).toBe("");
    expect(application).not.toHaveAttribute("aria-describedby");
  });

  it("BUG-014 records the reported lawyer inputs ('Class 45', a goods row, an extract) with the exact API shape", async () => {
    const user = userEvent.setup();
    ingestMock.mockImplementation(async ({ publication }) => ({
      run: { id: "run-1", status: "succeeded", duplicate_hits: 0 },
      publications: [{ ...ZERO_HIT_PUBLICATION, id: "publication-new", ...publication, class_numbers_json: [45], raw_evidence_json: publication.raw_evidence }],
      hits: [],
      idempotent_replay: false,
    }));
    const page = renderWatchPage();
    await user.click(await page.findByRole("button", { name: "Journal intake" }));
    await fillLawyerCapture(user, page, "Class 45");
    await enterText(user, await page.findByLabelText("Class 45 goods/services as published"), "Legal services");
    await enterText(user, page.getByLabelText("Journal entry as published"), "Journal 2187 page 45: ZQXV CAPTURE, class 45.");
    await user.click(page.getByRole("button", { name: "Record and compare" }));
    await waitFor(() => expect(ingestMock).toHaveBeenCalledTimes(1));
    const call = ingestMock.mock.calls[0][0];
    expect(call.providerKey).toBe("ipindia-journal-manual");
    expect(call.costMinor).toBe(0);
    expect(call.publication).toEqual({
      application_id: null,
      journal_number: "2187",
      journal_date: "2026-10-27",
      publication_kind: "advertisement",
      application_number: "BUG014-CAPTURE-1",
      mark_text: "ZQXV CAPTURE",
      device_reference: null,
      proprietor_name: null,
      office: "IP India",
      jurisdiction: "IN",
      class_numbers: [45],
      goods_services: { "45": ["Legal services"] },
      publication_scope: { scope_kind: "full" },
      source_url: "https://search.ipindia.gov.in/IPOJournal/Journal/ViewJournal",
      source_page: "45",
      source_status: "available",
      source_retrieved_at: null,
      parser_version: "manual-journal-v1",
      attribution: { publisher: "IP India", capture_method: "manual" },
      raw_evidence: { capture_method: "manual", extract_text: "Journal 2187 page 45: ZQXV CAPTURE, class 45." },
      supersedes_publication_id: null,
      correction_reason: null,
    });
    const result = await page.findByTestId("journal-intake-result");
    expect(result).toHaveTextContent("Recorded: Journal 2187 · Application BUG014-CAPTURE-1 · ZQXV CAPTURE");
    expect(result).toHaveTextContent("journal extract captured · 0 new watch hits");
    expect(toastError).not.toHaveBeenCalled();
  });

  it("BUG-014 blocks a bad class token and empty evidence next to their fields without calling the API", async () => {
    const user = userEvent.setup();
    const page = renderWatchPage();
    await user.click(await page.findByRole("button", { name: "Journal intake" }));
    await fillLawyerCapture(user, page, "Class 30 - Biscuits");
    await user.click(page.getByRole("button", { name: "Record and compare" }));
    const classes = page.getByLabelText("Published Nice classes");
    await waitFor(() => expect(classes).toHaveAttribute("aria-invalid", "true"));
    expect(classes).toHaveAccessibleDescription(expect.stringContaining("\"Biscuits\" is not a Nice class number"));
    expect(classes).toHaveFocus();
    const extract = page.getByLabelText("Journal entry as published");
    expect(extract).toHaveAttribute("aria-invalid", "true");
    expect(extract).toHaveAccessibleDescription(expect.stringContaining("Capture the source evidence"));
    expect(page.getByTestId("journal-intake-error")).toHaveTextContent("Published Nice classes, Captured source evidence");
    expect(ingestMock).not.toHaveBeenCalled();
  });

  it("BUG-014 anchors the API's 422 errors under the fields that caused them", async () => {
    const user = userEvent.setup();
    ingestMock.mockRejectedValue(new ApiError(422, "Publications › Class numbers: List should have at least 1 item", {
      detail: "Publications › Class numbers: ...",
      errors: [
        { loc: ["body", "publications", 0, "goods_services", "45"], msg: "Input should be a valid list", type: "list_type" },
        { loc: ["body", "publications", 0, "raw_evidence"], msg: "Value error, Capture the source evidence: the journal entry as published.", type: "value_error" },
      ],
    }));
    const page = renderWatchPage();
    await user.click(await page.findByRole("button", { name: "Journal intake" }));
    await fillLawyerCapture(user, page, "45");
    await enterText(user, await page.findByLabelText("Class 45 goods/services as published"), "Legal services");
    await enterText(user, page.getByLabelText("Saved page reference"), "DMS 4410 / Journal 2187.pdf");
    await user.click(page.getByRole("button", { name: "Record and compare" }));
    const goods = page.getByLabelText("Class 45 goods/services as published");
    await waitFor(() => expect(goods).toHaveAttribute("aria-invalid", "true"));
    expect(goods).toHaveAccessibleDescription(expect.stringContaining("Input should be a valid list"));
    const extract = page.getByLabelText("Journal entry as published");
    expect(extract).toHaveAccessibleDescription(expect.stringContaining("Capture the source evidence: the journal entry as published."));
    expect(extract).not.toHaveAccessibleDescription(expect.stringContaining("Value error"));
    expect(toastError).not.toHaveBeenCalled();
  });

  it("BUG-014 offers the profile form instead of an intake that can only fail without an active profile", async () => {
    const user = userEvent.setup();
    workspaceMock.mockResolvedValue({ ...WORKSPACE, profiles: [], hits: [], intake_profile_count: 0 });
    const page = renderWatchPage();
    await user.click(await page.findByRole("button", { name: "Journal intake" }));
    expect(await page.findByText("No active watch profile to compare with")).toBeVisible();
    expect(page.queryByRole("button", { name: "Record and compare" })).toBeNull();
    await user.click(page.getByRole("button", { name: "Create a watch profile" }));
    expect(await page.findByRole("button", { name: "Create profile" })).toBeVisible();
  });

  it("BUG-014 lists a zero-hit capture as a correctable entry", async () => {
    const user = userEvent.setup();
    const page = renderWatchPage();
    await user.click(await page.findByRole("button", { name: "Journal intake" }));
    expect(await page.findByTestId("journal-entry-publication-zero")).toHaveTextContent("ZQXV TRIAGE PROBE");
    await user.selectOptions(page.getByLabelText("Publication kind"), "correction");
    const predecessor = page.getByRole<HTMLSelectElement>("combobox", { name: "Journal entry being corrected" });
    expect(Array.from(predecessor.options, (option) => option.value)).toEqual(["", "publication-1", "publication-zero"]);
    await user.selectOptions(predecessor, "publication-zero");
    expect(predecessor).toHaveValue("publication-zero");
  });

  it("creates criteria, frequency, recipients chosen by name, and cost policy", async () => {
    const user = userEvent.setup();
    createProfileMock.mockResolvedValue(PROFILE);
    const page = renderWatchPage();
    await user.click(await page.findByRole("button", { name: "Profiles" }));
    const docket = await page.findByRole<HTMLSelectElement>("combobox", { name: "Docket" });
    await waitFor(() => expect(docket).toBeEnabled());
    await user.selectOptions(docket, "docket-1");
    await enterText(user, page.getByLabelText("Profile name"), "ACME class and word watch");
    await enterText(user, page.getByLabelText("Word terms"), "ACME, ACME PRIME");
    await enterText(user, page.getByLabelText("Nice classes"), "Class 9, 42");
    expect(page.queryByLabelText(/membership/i)).toBeNull();
    const chosen = page.getByRole("list", { name: "Chosen recipients" });
    expect(await within(chosen).findByText("Ram Gupta — ram@aster.example")).toBeVisible();
    const picker = page.getByRole<HTMLSelectElement>("combobox", { name: "Add a recipient" });
    await waitFor(() => expect(picker).toBeEnabled());
    expect(Array.from(picker.options, (option) => option.value)).toEqual(["", "member-2"]);
    await user.selectOptions(picker, "member-2");
    await user.click(page.getByRole("button", { name: "Add recipient" }));
    expect(await within(chosen).findByText("Hari Rao — hari@aster.example")).toBeVisible();
    await user.selectOptions(page.getByLabelText("Frequency"), "daily");
    await user.clear(page.getByLabelText("Max cost per period (paise)"));
    await enterText(user, page.getByLabelText("Max cost per period (paise)"), "250");
    await user.click(page.getByRole("button", { name: "Create profile" }));
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Watch profile created."));
    expect(createProfileMock).toHaveBeenCalledTimes(1);
    expect(createProfileMock.mock.calls[0][0]).toEqual({
      docketId: "docket-1",
      name: "ACME class and word watch",
      providerKey: "manual-journal",
      wordTerms: ["ACME", "ACME PRIME"],
      phoneticTerms: [],
      deviceReferences: [],
      classNumbers: [9, 42],
      proprietorTerms: [],
      jurisdictions: ["IN"],
      frequency: "daily",
      recipientMembershipIds: ["member-1", "member-2"],
      maxCostMinorPerPeriod: 250,
      costCurrency: "INR",
    });
    expect(toastError).not.toHaveBeenCalled();
    await waitFor(() => expect(page.getByRole("button", { name: "Create profile" })).toBeEnabled());
  });

  it("disables adding a recipient when every active colleague already is one", async () => {
    const user = userEvent.setup();
    usersMock.mockResolvedValue({ ...USERS, users: [USERS.users[0]] });
    const page = renderWatchPage();
    await user.click(await page.findByRole("button", { name: "Profiles" }));
    expect(await within(page.getByRole("list", { name: "Chosen recipients" })).findByText("Ram Gupta — ram@aster.example")).toBeVisible();
    await waitFor(() => expect(page.getByRole("combobox", { name: "Add a recipient" })).toBeDisabled());
    expect(page.getByRole("button", { name: "Add recipient" })).toBeDisabled();
    expect(page.getByText("No other colleague is available to choose.")).toBeVisible();
  });

  it("BUG-014 never drops a profile class token silently", async () => {
    const user = userEvent.setup();
    const page = renderWatchPage();
    await user.click(await page.findByRole("button", { name: "Profiles" }));
    const docket = await page.findByRole<HTMLSelectElement>("combobox", { name: "Docket" });
    await waitFor(() => expect(docket).toBeEnabled());
    await user.selectOptions(docket, "docket-1");
    await enterText(user, page.getByLabelText("Profile name"), "Biscuit watch");
    await enterText(user, page.getByLabelText("Nice classes"), "Class 30, 4x");
    await user.click(page.getByRole("button", { name: "Create profile" }));
    const classes = page.getByLabelText("Nice classes");
    await waitFor(() => expect(classes).toHaveAttribute("aria-invalid", "true"));
    expect(classes).toHaveAccessibleDescription(expect.stringContaining("\"4x\" is not a Nice class number"));
    expect(createProfileMock).not.toHaveBeenCalled();
  });

  it("records source-confirmed review and creates a canonical opposition handoff", async () => {
    const user = userEvent.setup();
    const relevant = { ...HIT, source_status: "available", disposition: "relevant", version: 3 };
    workspaceMock.mockResolvedValue({ ...WORKSPACE, hits: [relevant], publications: [{ ...PUBLICATION, source_status: "available" }] });
    decideHitMock.mockResolvedValue(relevant);
    createHandoffMock.mockResolvedValue({ id: "handoff-1", hit_id: HIT.id, handoff_kind: "opposition", status: "completed", target_type: "ip_proceeding" });
    const page = renderWatchPage();
    await chooseScopeDocket(user, page);
    await user.selectOptions(await page.findByLabelText("Disposition"), "relevant");
    await user.clear(page.getByLabelText("Reason"));
    await enterText(user, page.getByLabelText("Reason"), "Official journal confirms overlapping classes.");
    await user.click(page.getByLabelText(/I opened and confirmed/));
    await user.click(page.getByRole("button", { name: "Record review" }));
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Attorney review recorded."));
    expect(decideHitMock).toHaveBeenCalledTimes(1);
    expect(decideHitMock.mock.calls[0][0]).toEqual({
      hitId: HIT.id,
      expectedVersion: 3,
      disposition: "relevant",
      reason: "Official journal confirms overlapping classes.",
      sourceConfirmed: true,
    });
    await waitFor(() => expect(page.getByRole("button", { name: "Record review" })).toBeEnabled());
    const application = await page.findByRole<HTMLSelectElement>("combobox", { name: "Application" });
    await waitFor(() => expect(application).toHaveValue("application-1"));
    expect(application).toHaveAccessibleDescription("ASTER · Application TM-9876543 · IP India · filed");
    await user.click(page.getByRole("button", { name: "Create opposition" }));
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("opposition created without re-entry."));
    expect(createHandoffMock).toHaveBeenCalledTimes(1);
    expect(createHandoffMock.mock.calls[0][0]).toEqual({
      hitId: HIT.id,
      handoffKind: "opposition",
      applicationId: "application-1",
      title: "Review ASTER PRIME",
      matterCode: null,
      dueOn: null,
      assigneeMembershipId: "member-1",
      notes: null,
    });
    expect(toastError).not.toHaveBeenCalled();
    await waitFor(() => expect(page.getByRole("button", { name: "Create opposition" })).toBeEnabled());
  });
});
