import { defaultScheduler, notifyManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { ApiError } from "@/lib/api/config";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const {
  bookmarksMock,
  capabilityMock,
  coreMock,
  createLinkMock,
  createReferenceMock,
  decideMatchMock,
  diffsMock,
  resolveDiffMock,
  docketMock,
  docketsMock,
  readinessMock,
  recordSnapshotMock,
  recordFailureMock,
  referencesMock,
  workspacesMock,
} = vi.hoisted(() => ({
  bookmarksMock: vi.fn(),
  capabilityMock: vi.fn(),
  coreMock: vi.fn(),
  createLinkMock: vi.fn(),
  createReferenceMock: vi.fn(),
  decideMatchMock: vi.fn(),
  diffsMock: vi.fn(),
  resolveDiffMock: vi.fn(),
  docketMock: vi.fn(),
  docketsMock: vi.fn(),
  readinessMock: vi.fn(),
  recordSnapshotMock: vi.fn(),
  recordFailureMock: vi.fn(),
  referencesMock: vi.fn(),
  workspacesMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
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

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("@/lib/api/endpoints", () => ({
  createIpRegistryLink: createLinkMock,
  createIpTrackedCaseReference: createReferenceMock,
  decideIpRegistryMatch: decideMatchMock,
  decideIpTrackedCaseReference: vi.fn(),
  fetchIpCoreRecords: coreMock,
  fetchIpDocket: docketMock,
  fetchIpDockets: docketsMock,
  fetchIpRegistryDiffs: diffsMock,
  fetchIpRegistryWorkspaces: workspacesMock,
  fetchIpTrackedCaseReferences: referencesMock,
  fetchIpWorkspaceReadiness: readinessMock,
  listCaseTrackingBookmarks: bookmarksMock,
  recordIpRegistryFailure: recordFailureMock,
  recordIpRegistryManualSnapshot: recordSnapshotMock,
  resolveIpRegistryDiff: resolveDiffMock,
}));

import IpRegistryPage from "@/app/app/ip/registry/page";

const DOCKET = {
  id: "docket-1",
  matter_id: "matter-1",
  title: "ASTER mark",
  primary_identifier: "TM-1234567",
  record_type: "trademark",
};
const OTHER = {
  id: "docket-2",
  matter_id: null,
  title: "IP18 due",
  primary_identifier: "5550001",
  record_type: "trademark",
};
const MADRID = {
  id: "madrid-1",
  matter_id: null,
  title: "TASTYBITE International Portfolio",
  primary_identifier: null,
  record_type: "international_registration",
};

const LINK = {
  id: "registry-link-1",
  company_id: "company-1",
  docket_id: "docket-1",
  application_id: "application-1",
  proceeding_id: null,
  provider_key: "ipindia-registry",
  office: "IP India",
  jurisdiction: "IN",
  identifier_kind: "application",
  raw_identifier: "TM-1234567",
  normalized_identifier: "TM1234567",
  source_url: "https://ipindia.gov.in/registry/TM-1234567",
  match_status: "candidate" as const,
  match_confidence: "0.9500",
  match_evidence_json: { identifier: "TM-1234567" },
  accepted_state_json: { office: "IP India", jurisdiction: "IN", status: "draft" },
  terms_version: null,
  capability_version: "manual-evidence-v1",
  freshness_status: "never_succeeded" as const,
  last_attempted_at: null,
  last_successful_at: null,
  last_snapshot_id: null,
  last_normalized_hash: null,
  last_error_redacted: null,
  version: 1,
  created_by_membership_id: "member-1",
  created_at: "2026-08-24T08:00:00Z",
  updated_at: "2026-08-24T08:00:00Z",
};

const APPLICATION = {
  id: "application-1",
  docket_id: "docket-1",
  office: "IP India",
  jurisdiction: "IN",
  filing_phase: "draft",
  created_at: "2026-08-01T12:00:00Z",
};
const PROCEEDING = {
  id: "proceeding-1",
  docket_id: "docket-1",
  application_id: "application-1",
  proceeding_kind: "opposition",
  side: "applicant",
  office: "IP India",
  jurisdiction: "IN",
  stage: "draft",
  created_at: "2026-08-02T12:00:00Z",
};
const ID = (overrides: Record<string, unknown>) => ({
  application_id: null,
  proceeding_id: null,
  effective_until: null,
  is_primary: true,
  ...overrides,
});
const CORE = {
  assets: [],
  applications: [APPLICATION],
  proceedings: [PROCEEDING],
  identifiers: [
    ID({ application_id: "application-1", identifier_kind: "application", raw_value: "TM-1234567" }),
    ID({ application_id: "application-1", proceeding_id: "proceeding-1", identifier_kind: "opposition", raw_value: "OPP-77" }),
  ],
};
const OTHER_CORE = {
  assets: [],
  applications: [{ ...APPLICATION, id: "application-2", docket_id: "docket-2" }],
  proceedings: [],
  identifiers: [ID({ application_id: "application-2", identifier_kind: "application", raw_value: "5550001" })],
};
const EMPTY_CORE = { assets: [], applications: [], proceedings: [], identifiers: [] };

const DOCKETS: Record<string, unknown> = { [DOCKET.id]: DOCKET, [OTHER.id]: OTHER, [MADRID.id]: MADRID };

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}


const ownedRegistrySettlements = new Set<() => Promise<void>>();
const ownedRegistryNotifications = new Set<() => Promise<void>>();
afterEach(async () => {
  const errors: unknown[] = [];
  for (const cleanup of [...ownedRegistryNotifications, ...ownedRegistrySettlements]) {
    try { await cleanup(); } catch (error) { errors.push(error); }
  }
  if (errors.length === 1) throw errors[0];
  if (errors.length > 1) throw new AggregateError(errors, "Independent registry cleanup failures");
});


function holdRegistryNotifications() {
  const pending: Array<() => void> = [];
  const flush = async () => {
    let rounds = 0;
    while (pending.length) {
      expect(rounds++).toBeLessThan(16);
      await act(async () => { pending.splice(0).forEach((callback) => callback()); });
    }
  };
  let completion: Promise<void> | undefined;
  const restore = (): Promise<void> => completion ??= (async () => {
    try { await flush(); }
    finally { notifyManager.setScheduler(defaultScheduler); ownedRegistryNotifications.delete(restore); }
  })();
  ownedRegistryNotifications.add(restore);
  notifyManager.setScheduler((callback) => { expect(pending.length).toBeLessThan(32); pending.push(callback); });
  return { pending, flush, restore };
}

function deferredRegistry<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((accept, refuse) => { resolve = accept; reject = refuse; });
  return { promise, resolve, reject };
}

async function withRegistrySettlement(release: () => void,
  body: (owned: { client: QueryClient; page: ReturnType<typeof within>; user: ReturnType<typeof userEvent.setup>; view: ReturnType<typeof render> }) => Promise<void>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } } });
  const view = render(<QueryClientProvider client={client}><IpRegistryPage /></QueryClientProvider>);
  let completion: Promise<void> | undefined;
  const cleanup = (): Promise<void> => completion ??= (async () => {
    try {
      await act(async () => { release(); });
      await waitFor(() => expect(client.isMutating()).toBe(0));
    } finally { view.unmount(); client.clear(); ownedRegistrySettlements.delete(cleanup); }
  })();
  ownedRegistrySettlements.add(cleanup);
  const errors: unknown[] = [];
  try { await body({ client, page: within(view.container), user: userEvent.setup(), view }); }
  catch (error) { errors.push(error); }
  try { await cleanup(); } catch (error) { errors.push(error); }
  if (errors.length === 1) throw errors[0];
  if (errors.length > 1) throw new AggregateError(errors, "Registry workflow and cleanup failures retained separately");
}


type RegistryCaseLink = Omit<typeof LINK, "match_status"> & { match_status: "candidate" | "confirmed" | "retired" };
function registrySettlementFixture() {
  const current: RegistryCaseLink = { ...LINK, match_status: "confirmed", version: 3 };
  const newer = { ...current, version: 4 };
  const retired: RegistryCaseLink = { ...newer, match_status: "retired", version: 5 };
  const workspace = (link: RegistryCaseLink) => ({ items: [{ link, attempts: [], snapshots: [] }], total: 1, limit: 25, offset: 0 });
  const held = deferredRegistry<ReturnType<typeof workspace>>();
  const diff = { id: "settlement-diff", version: 1, field_path: "/mark_name", mapped_field_path: null,
    change_kind: "added", before_value_json: null, after_value_json: "ASTER", risk_level: "low",
    resolution_status: "pending", deadline_recalculation_state: "not_required" };
  return { current, newer, retired, workspace, held, diff, key: ["ip", "registry", "workspaces", "", 0] };
}
async function registryText(user: ReturnType<typeof userEvent.setup>, view: ReturnType<typeof render>, id: string, value: string) {
  expect(view.container.isConnected).toBe(true);
  const field = view.container.querySelector<HTMLInputElement>(`#${id}`)!;
  expect(field).toBeInTheDocument();
  await user.clear(field); expect(field).toHaveFocus(); await user.paste(value);
}

function docketPicker() {
  return screen.getByRole<HTMLSelectElement>("combobox", { name: "IP docket" });
}

async function legalRecord() {
  return screen.findByRole<HTMLSelectElement>("combobox", { name: "Legal record" });
}

describe("IP registry reconciliation page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState(null, "", "/app/ip/registry");
    capabilityMock.mockReturnValue(true);
    docketsMock.mockResolvedValue({
      dockets: [DOCKET, OTHER], count: 2, has_more: false, next_cursor: null, total_count: 2,
    });
    docketMock.mockImplementation(async (id: string) => DOCKETS[id]);
    coreMock.mockImplementation(async (id: string) => (id === OTHER.id ? OTHER_CORE : CORE));
    workspacesMock.mockImplementation(async (docketId: string) => ({
      items: docketId === "" || docketId === DOCKET.id ? [{ link: LINK, attempts: [], snapshots: [] }] : [],
      total: docketId === "" || docketId === DOCKET.id ? 1 : 0,
      limit: 25,
      offset: 0,
    }));
    diffsMock.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    referencesMock.mockResolvedValue([]);
    readinessMock.mockResolvedValue({
      workspace_available: true,
      manual_docketing_available: true,
      timezone: "Asia/Kolkata",
      features: [{ feature_id: "registry_sync", available: false, reason: "rollout_disabled" }],
    });
    bookmarksMock.mockResolvedValue({
      bookmarks: [
        {
          id: "bookmark-1",
          tracked_case_id: "tracked-1",
          matter_id: "matter-1",
          tracked_case: { id: "tracked-1", case_title: "Aster LLP v Registrar of Trade Marks" },
        },
      ],
    });
  });

  it("fails closed without IP read access", () => {
    capabilityMock.mockReturnValue(false);

    render(<IpRegistryPage />, { wrapper: wrapper() });

    expect(screen.getByText("IP access required")).toBeVisible();
    expect(workspacesMock).not.toHaveBeenCalled();
  });

  it("BUG-012 never picks a docket itself and lists national dockets only", async () => {
    render(<IpRegistryPage />, { wrapper: wrapper() });

    await waitFor(() => expect(docketPicker()).toBeEnabled());
    expect(docketPicker()).toHaveValue("");
    expect(docketsMock).toHaveBeenCalledWith(expect.objectContaining({ recordTypes: ["trademark"], limit: 50 }));
    expect(screen.getByText(/Select a docket to begin/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Madrid portfolio" })).toHaveAttribute("href", "/app/ip/madrid");
    expect(screen.queryByRole("heading", { name: "Add registry identity" })).toBeNull();
    expect(coreMock).not.toHaveBeenCalled();
    // Identities across the workspace stay reachable without choosing a docket.
    expect(await screen.findByRole("heading", { name: "TM-1234567" })).toBeVisible();
  });

  it("BUG-012 honours a ?docket= deep link and labels each legal record by its number", async () => {
    window.history.replaceState(null, "", `/app/ip/registry?docket=${DOCKET.id}`);
    render(<IpRegistryPage />, { wrapper: wrapper() });

    const select = await legalRecord();
    await waitFor(() => expect(select).toBeEnabled());
    expect(docketPicker()).toHaveValue(DOCKET.id);
    expect(Array.from(select.options, (option) => option.textContent)).toEqual([
      "Choose the application or proceeding",
      "Application TM-1234567 · IP India · IN · Draft",
      "Opposition OPP-77 · applicant side · IP India · Draft",
    ]);
    // Two records: nothing is chosen for the lawyer, and nothing can be sent.
    expect(select).toHaveValue("");
    expect(screen.getByRole("button", { name: "Add identity" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Identifier type" })).toBeDisabled();
    expect(await screen.findByText(/paused by CaseOps/)).toBeVisible();
  });

  it("BUG-012 prefills from the chosen record and sends only that record of this docket", async () => {
    const user = userEvent.setup();
    createLinkMock.mockResolvedValue({ ...LINK, id: "registry-link-2" });
    window.history.replaceState(null, "", `/app/ip/registry?docket=${DOCKET.id}`);
    render(<IpRegistryPage />, { wrapper: wrapper() });

    const select = await legalRecord();
    await waitFor(() => expect(select).toBeEnabled());
    await user.selectOptions(select, "proceeding:proceeding-1");
    expect(select).toHaveAccessibleDescription(/Opposition OPP-77 · applicant side/);
    const kind = screen.getByRole<HTMLSelectElement>("combobox", { name: "Identifier type" });
    expect(Array.from(kind.options, (option) => option.value)).toEqual(["opposition"]);
    expect(screen.getByLabelText("Identifier")).toHaveValue("OPP-77");
    expect(screen.getByLabelText("Office")).toHaveValue("IP India");
    expect(screen.getByLabelText("Jurisdiction")).toHaveValue("IN");

    await user.click(screen.getByRole("button", { name: "Add identity" }));
    const url = screen.getByLabelText("Official source URL");
    expect(url).toHaveAttribute("aria-invalid", "true");
    expect(url).toHaveAccessibleDescription(/starting with https/);
    expect(createLinkMock).not.toHaveBeenCalled();

    await user.type(url, "https://tmrsearch.ipindia.gov.in/eregister/OPP-77");
    await user.click(screen.getByRole("button", { name: "Add identity" }));
    await waitFor(() => expect(createLinkMock).toHaveBeenCalledTimes(1));
    expect(createLinkMock.mock.calls[0][0]).toMatchObject({
      docketId: DOCKET.id,
      applicationId: null,
      proceedingId: "proceeding-1",
      identifierKind: "opposition",
      rawIdentifier: "OPP-77",
      office: "IP India",
      jurisdiction: "IN",
      sourceUrl: "https://tmrsearch.ipindia.gov.in/eregister/OPP-77",
    });
  });

  it("BUG-012 never carries a record from the previous docket after switching back", async () => {
    const user = userEvent.setup();
    createLinkMock.mockResolvedValue({ ...LINK, id: "registry-link-3" });
    render(<IpRegistryPage />, { wrapper: wrapper() });
    await waitFor(() => expect(docketPicker()).toBeEnabled());

    await user.selectOptions(docketPicker(), DOCKET.id);
    const first = await legalRecord();
    await waitFor(() => expect(first).toBeEnabled());
    await user.selectOptions(first, "application:application-1");
    await user.selectOptions(docketPicker(), OTHER.id);
    // One record on this docket: it is the only choice, so it is preselected.
    await waitFor(async () => expect(await legalRecord()).toHaveValue("application:application-2"));
    expect(window.location.search).toBe(`?docket=${OTHER.id}`);
    await user.selectOptions(docketPicker(), DOCKET.id);

    const select = await legalRecord();
    await waitFor(() => expect(select).toBeEnabled());
    expect(select).toHaveValue("");
    expect(select.selectedIndex).toBe(0);
    await user.selectOptions(select, "application:application-1");
    await user.type(screen.getByLabelText("Official source URL"), "https://tmrsearch.ipindia.gov.in/eregister/1");
    await user.click(screen.getByRole("button", { name: "Add identity" }));
    await waitFor(() => expect(createLinkMock).toHaveBeenCalledTimes(1));
    expect(createLinkMock.mock.calls[0][0]).toMatchObject({
      docketId: DOCKET.id, applicationId: "application-1", proceedingId: null,
    });
  });

  it("BUG-012 follows a later ?docket= navigation while the page is open", async () => {
    window.history.replaceState(null, "", `/app/ip/registry?docket=${DOCKET.id}`);
    const view = render(<IpRegistryPage />, { wrapper: wrapper() });
    await waitFor(() => expect(docketPicker()).toHaveValue(DOCKET.id));

    act(() => window.history.pushState(null, "", `/app/ip/registry?docket=${OTHER.id}`));
    view.rerender(<IpRegistryPage />);
    await waitFor(() => expect(docketPicker()).toHaveValue(OTHER.id));
    await waitFor(async () => expect(await legalRecord()).toHaveValue("application:application-2"));
  });

  it("BUG-012 / B4-ADJ-12 anchors a duplicate identity, a record outside the docket and a mismatched kind to their fields", async () => {
    const user = userEvent.setup();
    const { ApiError } = await import("@/lib/api/config");
    createLinkMock
      .mockRejectedValueOnce(new ApiError(409, "This registry identity is already linked.", null))
      // B4-ADJ-12: a target outside the docket is a field-anchored 422, not a 404.
      .mockRejectedValueOnce(new ApiError(422, "Application id: This application is not a record of this docket.", {
        errors: [{
          loc: ["body", "application_id"],
          msg: "This application is not a record of this docket. Choose an application or proceeding listed for this docket.",
          type: "registry_target_not_in_docket",
        }],
      }))
      .mockRejectedValueOnce(new ApiError(422, "Identifier kind: Application and registration numbers belong to an application.", {
        errors: [{
          loc: ["body", "identifier_kind"],
          msg: "Application and registration numbers belong to an application; opposition, rectification, cancellation, non-use, appeal and court numbers belong to a proceeding.",
          type: "registry_identifier_kind_mismatch",
        }],
      }));
    window.history.replaceState(null, "", `/app/ip/registry?docket=${OTHER.id}`);
    render(<IpRegistryPage />, { wrapper: wrapper() });

    await waitFor(async () => expect(await legalRecord()).toHaveValue("application:application-2"));
    await user.type(screen.getByLabelText("Official source URL"), "https://tmrsearch.ipindia.gov.in/eregister/5550001");
    await user.click(screen.getByRole("button", { name: "Add identity" }));
    const identifier = screen.getByLabelText("Identifier");
    await waitFor(() => expect(identifier).toHaveAttribute("aria-invalid", "true"));
    expect(identifier).toHaveAccessibleDescription("This registry identity is already linked.");

    await user.click(screen.getByRole("button", { name: "Add identity" }));
    const record = await legalRecord();
    await waitFor(() => expect(record).toHaveAttribute("aria-invalid", "true"));
    expect(record).toHaveAccessibleDescription(/This application is not a record of this docket/);

    await user.click(screen.getByRole("button", { name: "Add identity" }));
    const kind = screen.getByLabelText("Identifier type");
    await waitFor(() => expect(kind).toHaveAttribute("aria-invalid", "true"));
    expect(kind).toHaveAccessibleDescription(/belong to an application/);
  });

  it("BUG-012 shows a register change by its field name and plain values, keeping the path as technical detail", async () => {
    diffsMock.mockResolvedValue({
      items: [{
        id: "diff-1", version: 1, field_path: "/mark_name", mapped_field_path: null, change_kind: "added",
        before_value_json: null, after_value_json: "ASTER", risk_level: "low", resolution_status: "pending",
        deadline_recalculation_state: "not_required",
      }],
      total: 1, limit: 50, offset: 0,
    });
    render(<IpRegistryPage />, { wrapper: wrapper() });

    const decisions = await screen.findByTestId("registry-diff-decisions");
    const [item] = await within(decisions).findAllByRole("listitem");
    expect(item).toHaveTextContent("Mark as shown on the register");
    expect(item).toHaveTextContent("BeforeNot shown");
    expect(item).toHaveTextContent("AfterASTER");
    expect(item).not.toHaveTextContent('"ASTER"');
    expect(item).not.toHaveTextContent("null");
    const path = within(item).getByText("/mark_name");
    expect(path.closest("details")).not.toBeNull();
    // On a phone the decisions sit in the change's own entry.
    expect(within(item).getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });

  it("BUG-012 [mobile] keeps court reference decisions inside each reference entry", async () => {
    referencesMock.mockResolvedValue([{
      id: "reference-1", version: 1, case_title: "Aster LLP v Registrar of Trade Marks", cnr_number: "DLHC010012342026",
      case_number: null, court_name: "Delhi High Court", link_status: "active", update_count: 3,
    }]);
    window.history.replaceState(null, "", `/app/ip/registry?docket=${DOCKET.id}`);
    render(<IpRegistryPage />, { wrapper: wrapper() });

    const title = await screen.findAllByText("Aster LLP v Registrar of Trade Marks", { selector: "strong" });
    const entry = title.map((node) => node.closest("li")).find(Boolean) as HTMLElement;
    // The entry list serves any container narrower than the table needs (a phone,
    // or a laptop beside the sidebar), so Mismatch and Retire are never off-screen.
    expect(entry.closest("ul")).toHaveClass("@min-[760px]:hidden");
    expect(entry).toHaveTextContent("Delhi High Court");
    expect(within(entry).getByRole("button", { name: "Mismatch" })).toBeInTheDocument();
    expect(within(entry).getByRole("button", { name: "Retire" })).toBeInTheDocument();
    // The wide table only where its 760px fit.
    expect(screen.getByRole("table").parentElement).toHaveClass("hidden", "@min-[760px]:block");
    expect(entry.closest("ul")?.parentElement).toHaveClass("@container");
  });

  it("BUG-012 explains a Madrid docket and offers no legal record", async () => {
    window.history.replaceState(null, "", `/app/ip/registry?docket=${MADRID.id}`);
    render(<IpRegistryPage />, { wrapper: wrapper() });

    expect(await screen.findByText(/is a Madrid international record/)).toBeVisible();
    expect(screen.getByRole("link", { name: /Open the Madrid portfolio/ })).toHaveAttribute("href", "/app/ip/madrid");
    expect(screen.queryByRole("combobox", { name: "Legal record" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add identity" })).toBeNull();
    expect(coreMock).not.toHaveBeenCalled();
  });

  it("BUG-012 says an application-less docket cannot be fixed here and links only to paths that create one", async () => {
    coreMock.mockResolvedValue(EMPTY_CORE);
    window.history.replaceState(null, "", `/app/ip/registry?docket=${DOCKET.id}`);
    render(<IpRegistryPage />, { wrapper: wrapper() });

    const status = await screen.findByText(/has no trademark application, so it cannot take a registry identity/);
    expect(status).toBeVisible();
    expect(status).toHaveTextContent(/cannot add an application to an existing docket/);
    expect(status).toHaveTextContent(/each creates its own docket/);
    expect(screen.getByRole("link", { name: "IP workspace (New trademark)" })).toHaveAttribute("href", "/app/ip");
    expect(screen.getByRole("link", { name: "Portfolio import" })).toHaveAttribute("href", "/app/ip/portfolio/imports");
    // No link back to the same docket: nothing there can add the missing application.
    expect(screen.queryByRole("link", { name: "Open this docket" })).toBeNull();
    expect(await legalRecord()).toBeDisabled();
    const add = screen.getByRole("button", { name: "Add identity" });
    expect(add).toBeDisabled();
    expect(add).toHaveAccessibleDescription(/no application or proceeding/);
    expect(createLinkMock).not.toHaveBeenCalled();
  });

  it("BUG-012 shows a failed legal-record read as an error with retry, not an empty list", async () => {
    const user = userEvent.setup();
    coreMock.mockRejectedValueOnce(new Error("Gateway timeout")).mockResolvedValue(CORE);
    window.history.replaceState(null, "", `/app/ip/registry?docket=${DOCKET.id}`);
    render(<IpRegistryPage />, { wrapper: wrapper() });

    const alert = await screen.findByText(/Legal records could not be loaded: Gateway timeout/);
    expect(await legalRecord()).toBeDisabled();
    await user.click(within(alert.parentElement as HTMLElement).getByRole("button", { name: "Retry" }));
    await waitFor(async () => expect(await legalRecord()).toBeEnabled());
  });

  it("BUG-012 keeps the legal record disabled while it loads", async () => {
    coreMock.mockReturnValue(new Promise(() => undefined));
    window.history.replaceState(null, "", `/app/ip/registry?docket=${DOCKET.id}`);
    render(<IpRegistryPage />, { wrapper: wrapper() });

    const select = await legalRecord();
    expect(select).toBeDisabled();
    expect(select.options[0].textContent).toBe("Loading legal records…");
  });

  it("shows official provenance and records an explicit match decision", async () => {
    const user = userEvent.setup();
    decideMatchMock.mockResolvedValue({ ...LINK, match_status: "confirmed", version: 2 });

    render(<IpRegistryPage />, { wrapper: wrapper() });

    expect(await screen.findByRole("heading", { name: "TM-1234567" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Open source" })).toHaveAttribute("href", LINK.source_url);

    await user.type(screen.getByLabelText("Reason"), "Identifier and office match the source.");
    await user.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() =>
      expect(decideMatchMock).toHaveBeenCalledWith({
        linkId: LINK.id,
        expectedVersion: 1,
        decision: "confirm",
        reason: "Identifier and office match the source.",
      }),
    );
  });

  it("BUG-012 records register evidence through structured fields, never raw JSON", async () => {
    const user = userEvent.setup();
    const confirmed = { ...LINK, match_status: "confirmed" as const, version: 2 };
    workspacesMock.mockResolvedValue({ items: [{ link: confirmed, attempts: [], snapshots: [] }], total: 1, limit: 25, offset: 0 });
    recordSnapshotMock.mockResolvedValue({
      link: { ...confirmed, version: 3 },
      attempt: { id: "attempt-1", status: "succeeded" },
      snapshot: { id: "snapshot-1" },
      diffs: [{ id: "diff-1" }],
      no_change: false,
      idempotent_replay: false,
    });

    render(<IpRegistryPage />, { wrapper: wrapper() });

    const status = await screen.findByLabelText("Status on the register");
    expect(status).toHaveValue("draft");
    for (const field of Array.from(document.querySelectorAll("input, textarea"))) {
      const label = (field as HTMLInputElement).labels?.[0]?.textContent ?? "";
      expect(label).not.toMatch(/json|sha|uuid|parser/i);
    }
    // Nothing earlier to correct: an explanation, not an empty dropdown.
    expect(screen.queryByRole("combobox", { name: "Corrects an earlier entry" })).toBeNull();
    expect(screen.getByText(/Nothing to correct yet/)).toBeVisible();

    await user.clear(status);
    await user.type(status, "Registered");
    await user.type(screen.getByLabelText("Registration date"), "2027-01-15");
    await user.type(screen.getByLabelText("Text shown on the register page (optional)"), "Status: Registered");
    await user.click(screen.getByRole("button", { name: "Record register evidence" }));

    await waitFor(() => expect(recordSnapshotMock).toHaveBeenCalledTimes(1));
    const sent = recordSnapshotMock.mock.calls[0][0];
    const record = { office: "IP India", jurisdiction: "IN", status: "Registered", registration_date: "2027-01-15" };
    expect(sent).toMatchObject({
      linkId: LINK.id,
      expectedLinkVersion: 2,
      sourceUrl: LINK.source_url,
      parserVersion: "manual-register-form-v1",
      normalizedSnapshot: record,
      rawSnapshot: { capture_method: "manual_register_form", register_record: record, source_text: "Status: Registered" },
      supersedesSnapshotId: null,
      correctionReason: null,
    });
    expect(Number.isNaN(Date.parse(sent.sourceRetrievedAt))).toBe(false);
  });

  it("BUG-012 offers only snapshots that can still be corrected", async () => {
    const confirmed = { ...LINK, match_status: "confirmed" as const, version: 2 };
    const snapshot = (id: string, supersedes: string | null) => ({
      id, source_url: "https://tmrsearch.ipindia.gov.in/eregister/1", source_retrieved_at: "2026-10-30T10:00:00Z",
      supersedes_snapshot_id: supersedes, correction_reason: supersedes ? "Typo" : null, normalized_sha256: "a".repeat(64),
    });
    workspacesMock.mockResolvedValue({
      items: [{ link: confirmed, attempts: [], snapshots: [snapshot("s-3", "s-1"), snapshot("s-2", null), snapshot("s-1", null)] }],
      total: 1, limit: 25, offset: 0,
    });

    render(<IpRegistryPage />, { wrapper: wrapper() });

    const select = await screen.findByRole<HTMLSelectElement>("combobox", { name: "Corrects an earlier entry" });
    expect(Array.from(select.options, (option) => option.value)).toEqual(["", "s-3", "s-2"]);
    expect(Array.from(select.options, (option) => option.textContent).join(" ")).not.toMatch(/aaaa/);
  });

  it("adds a reference to the existing Matter tracked case", async () => {
    const user = userEvent.setup();
    createReferenceMock.mockResolvedValue({ id: "reference-1" });
    window.history.replaceState(null, "", `/app/ip/registry?docket=${DOCKET.id}`);

    render(<IpRegistryPage />, { wrapper: wrapper() });

    expect(await screen.findByText(/court updates are never copied/i)).toBeVisible();
    // B4-ADJ-21: neither the proceeding nor the tracked case is chosen for the user.
    const proceeding = await screen.findByRole<HTMLSelectElement>("combobox", { name: "IP proceeding" });
    const trackedCase = screen.getByRole<HTMLSelectElement>("combobox", { name: "Matter tracked case" });
    expect(proceeding).toHaveValue("");
    expect(trackedCase).toHaveValue("");
    expect(trackedCase).toBeDisabled();
    expect(screen.getByText("Choose the IP proceeding first.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Add reference" })).toBeDisabled();
    await user.selectOptions(proceeding, "proceeding-1");
    expect(trackedCase).toBeEnabled();
    expect(trackedCase).toHaveValue("");
    await user.selectOptions(trackedCase, "tracked-1");
    await user.type(screen.getByLabelText("Evidence reference"), "matter-bookmark:bookmark-1");
    await user.click(screen.getByRole("button", { name: "Add reference" }));

    await waitFor(() =>
      expect(createReferenceMock).toHaveBeenCalledWith({
        docketId: "docket-1",
        proceedingId: "proceeding-1",
        trackedCaseId: "tracked-1",
        purpose: "Opposition or appeal tracking",
        evidenceReference: "matter-bookmark:bookmark-1",
      }),
    );
  });

  it("B4-ADJ-21 lists an already-referenced tracked case as unavailable for that proceeding", async () => {
    const user = userEvent.setup();
    referencesMock.mockResolvedValue([{
      id: "reference-1", version: 1, proceeding_id: "proceeding-1", tracked_case_id: "tracked-1",
      case_title: "Aster LLP v Registrar of Trade Marks", cnr_number: null, case_number: null,
      court_name: null, link_status: "active", update_count: 0,
    }]);
    window.history.replaceState(null, "", `/app/ip/registry?docket=${DOCKET.id}`);
    render(<IpRegistryPage />, { wrapper: wrapper() });

    await user.selectOptions(await screen.findByRole("combobox", { name: "IP proceeding" }), "proceeding-1");
    const trackedCase = screen.getByRole<HTMLSelectElement>("combobox", { name: "Matter tracked case" });
    expect(trackedCase).toBeDisabled();
    expect(Array.from(trackedCase.options).find((option) => option.value === "tracked-1")?.disabled).toBe(true);
    expect(screen.getByText(/already referenced for this proceeding/i, { selector: "p" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Add reference" })).toBeDisabled();
  });

  it("BUG-012 blocks a sibling link decision until the rejected diff's new workspace version is delivered", async () => {
    const current = { ...LINK, match_status: "confirmed" as const, version: 3 };
    const newer = { ...current, version: 4 };
    const retired = { ...newer, match_status: "retired" as const, version: 5 };
    const workspace = (link: typeof current | typeof retired) => ({ items: [{ link, attempts: [], snapshots: [] }], total: 1, limit: 25, offset: 0 });
    const held = deferredRegistry<ReturnType<typeof workspace>>();
    const diff = { id: "settlement-diff", version: 1, field_path: "/mark_name", mapped_field_path: null,
      change_kind: "added", before_value_json: null, after_value_json: "ASTER", risk_level: "low",
      resolution_status: "pending", deadline_recalculation_state: "not_required" };
    workspacesMock.mockReset().mockResolvedValueOnce(workspace(current)).mockReturnValueOnce(held.promise).mockResolvedValue(workspace(retired));
    diffsMock.mockReset().mockResolvedValueOnce({ items: [diff], total: 1, limit: 50, offset: 0 }).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    resolveDiffMock.mockReset().mockResolvedValue({ ...diff, version: 2, resolution_status: "rejected" });
    decideMatchMock.mockReset().mockResolvedValue(retired);
    await withRegistrySettlement(() => held.resolve(workspace(newer)), async ({ client, page, user, view }) => {
      const decisions = await page.findByTestId("registry-diff-decisions");
      const review = view.container.querySelector<HTMLInputElement>("#review-reason")!;
      await user.click(review); expect(review).toHaveFocus(); await user.paste("Reviewed source; reject this proposed change.");
      expect(view.container.isConnected).toBe(true);
      const reason = view.container.querySelector<HTMLInputElement>("#match-reason")!;
      await user.click(reason); expect(reason).toHaveFocus(); await user.paste("Retiring this verified synthetic identity.");
      expect(page.getByRole("button", { name: /^Retire$/ })).toBeEnabled();
      const [change] = await within(decisions).findAllByRole("listitem");
      await user.click(within(change).getByRole("button", { name: /^Reject$/ }));
      await page.findByText("No field changes are awaiting a decision.");
      expect(resolveDiffMock).toHaveBeenCalledTimes(1);
      expect(client.isMutating()).toBe(1);
      const key = ["ip", "registry", "workspaces", "", 0];
      expect(client.getQueryState(key)?.fetchStatus).toBe("fetching");
      const retire = page.getByRole("button", { name: /^Retire$/ });
      expect(retire).toBeDisabled();
      expect(page.getByRole("button", { name: /^Confirm$/ })).toBeDisabled();
      expect(page.getByRole("button", { name: /^Mismatch$/ })).toBeDisabled();
      expect(decideMatchMock).not.toHaveBeenCalled();
      expect(vi.isFakeTimers()).toBe(false);
      const notifications = holdRegistryNotifications();
      try {
        const query = client.getQueryCache().find({ queryKey: key, exact: true });
        expect(query?.promise).toBeDefined();
        await act(async () => { held.resolve(workspace(newer)); await query!.promise; });
        expect(client.getQueryState(key)?.status).toBe("success");
        expect(client.getQueryData(key)).toMatchObject({ items: [{ link: { version: 4 } }] });
        expect(notifications.pending.length).toBeGreaterThan(0);
        await notifications.flush();
      } finally { await notifications.restore(); }
      await waitFor(() => expect(retire).toBeEnabled());
      await user.click(retire);
      await waitFor(() => expect(decideMatchMock).toHaveBeenCalledExactlyOnceWith({ linkId: LINK.id,
        expectedVersion: 4, decision: "retire", reason: "Retiring this verified synthetic identity." }));
      await waitFor(() => expect(client.isMutating()).toBe(0));
    });
  });

  it.each(["manual snapshot", "failure evidence"] as const)("BUG-012 serializes %s with every sibling writer through current-version refresh", async (writer) => {
    const f = registrySettlementFixture();
    const write = deferredRegistry<{ link: RegistryCaseLink; no_change: boolean; diffs: unknown[] }>();
    workspacesMock.mockReset().mockResolvedValueOnce(f.workspace(f.current)).mockReturnValueOnce(f.held.promise).mockResolvedValue(f.workspace(f.retired));
    diffsMock.mockReset().mockResolvedValue({ items: [f.diff], total: 1, limit: 50, offset: 0 });
    recordSnapshotMock.mockReset().mockReturnValue(write.promise);
    recordFailureMock.mockReset().mockReturnValue(write.promise);
    resolveDiffMock.mockReset(); decideMatchMock.mockReset().mockResolvedValue(f.retired);
    await withRegistrySettlement(() => { write.resolve({ link: f.newer, no_change: false, diffs: [] }); f.held.resolve(f.workspace(f.newer)); }, async ({ client, page, user, view }) => {
      await page.findByTestId("registry-diff-decisions");
      await registryText(user, view, "match-reason", "Retiring the verified synthetic identity.");
      await registryText(user, view, "review-reason", "Reviewed register source and change.");
      await registryText(user, view, "failure-message", "Synthetic unavailable register observation.");
      const snapshot = page.getByRole("button", { name: /^Record register evidence$/ });
      const failure = page.getByRole("button", { name: /^Record failure$/ });
      expect(snapshot).toBeEnabled(); expect(failure).toBeEnabled();
      if (writer === "manual snapshot") {
        const status = page.getByLabelText("Status on the register");
        await user.clear(status); expect(status).toHaveFocus(); await user.paste("Registered");
        await user.click(snapshot);
        await waitFor(() => expect(recordSnapshotMock).toHaveBeenCalledTimes(1));
        expect(recordSnapshotMock.mock.calls[0][0].expectedLinkVersion).toBe(3);
      } else {
        await user.click(failure);
        await waitFor(() => expect(recordFailureMock).toHaveBeenCalledTimes(1));
        expect(recordFailureMock.mock.calls[0][0].expectedLinkVersion).toBe(3);
      }
      const blocked = () => {
        for (const name of ["Confirm", "Mismatch", "Retire", "Record failure", "Record register evidence"]) {
          expect(page.getByRole("button", { name: new RegExp(`^${name}$`) })).toBeDisabled();
        }
        for (const reject of page.getAllByRole("button", { name: /^Reject$/ })) expect(reject).toBeDisabled();
      };
      blocked(); expect(client.isMutating()).toBe(1);
      const form = view.container.querySelector("#snapshot-source")!.closest("form")!;
      fireEvent.submit(form);
      expect(recordSnapshotMock).toHaveBeenCalledTimes(writer === "manual snapshot" ? 1 : 0);
      expect(recordFailureMock).toHaveBeenCalledTimes(writer === "failure evidence" ? 1 : 0);
      expect(decideMatchMock).not.toHaveBeenCalled(); expect(resolveDiffMock).not.toHaveBeenCalled();
      await act(async () => { write.resolve({ link: f.newer, no_change: false, diffs: [] }); });
      await waitFor(() => expect(workspacesMock).toHaveBeenCalledTimes(2));
      expect(client.getQueryState(f.key)?.fetchStatus).toBe("fetching"); blocked();
      await act(async () => { f.held.resolve(f.workspace(f.newer)); });
      const retire = page.getByRole("button", { name: /^Retire$/ });
      await waitFor(() => expect(retire).toBeEnabled());
      await user.click(retire);
      await waitFor(() => expect(decideMatchMock).toHaveBeenCalledExactlyOnceWith({ linkId: LINK.id,
        expectedVersion: 4, decision: "retire", reason: "Retiring the verified synthetic identity." }));
    });
  });

  it("BUG-012 keeps a confirmed write unavailable after failed workspace refresh and retries only its read", async () => {
    const f = registrySettlementFixture();
    workspacesMock.mockReset().mockResolvedValueOnce(f.workspace(f.current)).mockReturnValueOnce(f.held.promise).mockResolvedValueOnce(f.workspace(f.newer)).mockResolvedValue(f.workspace(f.retired));
    diffsMock.mockReset().mockResolvedValueOnce({ items: [f.diff], total: 1, limit: 50, offset: 0 }).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    resolveDiffMock.mockReset().mockResolvedValue({ ...f.diff, version: 2, resolution_status: "rejected" });
    decideMatchMock.mockReset().mockResolvedValue(f.retired);
    await withRegistrySettlement(() => f.held.resolve(f.workspace(f.newer)), async ({ client, page, user, view }) => {
      const decisions = await page.findByTestId("registry-diff-decisions");
      await registryText(user, view, "review-reason", "Reviewed source; reject the proposed change.");
      const [change] = await within(decisions).findAllByRole("listitem");
      await user.click(within(change).getByRole("button", { name: /^Reject$/ }));
      await waitFor(() => expect(workspacesMock).toHaveBeenCalledTimes(2));
      await act(async () => { f.held.reject(new Error("Synthetic workspace read unavailable")); });
      await page.findByText("Could not load registry identities");
      expect(page.queryByRole("button", { name: /^Retire$/ })).not.toBeInTheDocument();
      expect(client.getQueryState(f.key)?.status).toBe("error");
      expect(resolveDiffMock).toHaveBeenCalledTimes(1); expect(decideMatchMock).not.toHaveBeenCalled();
      expect(vi.mocked(toast.success)).toHaveBeenCalledWith("Registry field decision recorded.");
      expect(vi.mocked(toast.error)).not.toHaveBeenCalled();
      await user.click(page.getByRole("button", { name: /^Try again$/ }));
      await page.findByRole("heading", { name: /^TM-1234567$/ });
      expect(workspacesMock).toHaveBeenCalledTimes(3); expect(resolveDiffMock).toHaveBeenCalledTimes(1);
      await registryText(user, view, "match-reason", "Retire after fresh authorized read.");
      await user.click(page.getByRole("button", { name: /^Retire$/ }));
      await waitFor(() => expect(decideMatchMock).toHaveBeenCalledExactlyOnceWith({ linkId: LINK.id,
        expectedVersion: 4, decision: "retire", reason: "Retire after fresh authorized read." }));
    });
  });

  it("BUG-012 retains a genuine 409, refreshes current state, and requires an explicit new decision", async () => {
    const f = registrySettlementFixture();
    workspacesMock.mockReset().mockResolvedValueOnce(f.workspace(f.current)).mockReturnValueOnce(f.held.promise).mockResolvedValue(f.workspace(f.retired));
    diffsMock.mockReset().mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    const conflict = new ApiError(409, "Registry link changed; reload.", { detail: "Registry link changed; reload." });
    decideMatchMock.mockReset().mockRejectedValueOnce(conflict).mockResolvedValue(f.retired);
    resolveDiffMock.mockReset(); recordSnapshotMock.mockReset(); recordFailureMock.mockReset();
    await withRegistrySettlement(() => f.held.resolve(f.workspace(f.newer)), async ({ client, page, user, view }) => {
      await page.findByRole("heading", { name: /^TM-1234567$/ });
      await registryText(user, view, "match-reason", "Retire the reviewed synthetic identity.");
      await user.click(page.getByRole("button", { name: /^Retire$/ }));
      await waitFor(() => expect(workspacesMock).toHaveBeenCalledTimes(2));
      expect(decideMatchMock).toHaveBeenCalledTimes(1);
      expect(decideMatchMock.mock.calls[0][0].expectedVersion).toBe(3);
      expect(page.getByRole("button", { name: /^Retire$/ })).toBeDisabled();
      expect(vi.mocked(toast.error)).toHaveBeenCalledExactlyOnceWith("Registry link changed; reload.");
      expect(vi.mocked(toast.success)).not.toHaveBeenCalled();
      await act(async () => { f.held.resolve(f.workspace(f.newer)); });
      await waitFor(() => expect(client.isMutating()).toBe(0));
      expect(decideMatchMock).toHaveBeenCalledTimes(1);
      expect(client.getMutationCache().getAll()[0].state.status).toBe("error");
      expect(client.getQueryData(f.key)).toMatchObject({ items: [{ link: { version: 4 } }] });
      const retire = page.getByRole("button", { name: /^Retire$/ }); await waitFor(() => expect(retire).toBeEnabled());
      expect(recordSnapshotMock).not.toHaveBeenCalled(); expect(recordFailureMock).not.toHaveBeenCalled(); expect(resolveDiffMock).not.toHaveBeenCalled();
      await user.click(retire);
      await waitFor(() => expect(decideMatchMock).toHaveBeenCalledTimes(2));
      expect(decideMatchMock.mock.calls[1][0]).toEqual({ linkId: LINK.id, expectedVersion: 4,
        decision: "retire", reason: "Retire the reviewed synthetic identity." });
    });
  });

  it("BUG-012 creates an identity before the first workspace read ends without reusing its older empty snapshot", async () => {
    window.history.replaceState(null, "", `/app/ip/registry?docket=${DOCKET.id}`);
    const initial = deferredRegistry<{ items: unknown[]; total: number; limit: number; offset: number }>();
    const empty = { items: [], total: 0, limit: 25, offset: 0 };
    const fresh = { items: [{ link: LINK, attempts: [], snapshots: [] }], total: 1, limit: 25, offset: 0 };
    workspacesMock.mockReset().mockReturnValueOnce(initial.promise).mockResolvedValue(fresh);
    createLinkMock.mockReset().mockResolvedValue(LINK);
    diffsMock.mockReset().mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    await withRegistrySettlement(() => initial.resolve(empty), async ({ client, page, user, view }) => {
      const record = await page.findByRole("combobox", { name: /^Legal record$/ });
      await waitFor(() => expect(record).toBeEnabled());
      await user.selectOptions(record, "application:application-1");
      const source = page.getByLabelText("Official source URL");
      await user.click(source); expect(source).toHaveFocus(); await user.paste("https://tmrsearch.ipindia.gov.in/eregister/1");
      expect(view.container.isConnected).toBe(true);
      await user.click(page.getByRole("button", { name: /^Add identity$/ }));
      await page.findByRole("heading", { name: /^TM-1234567$/ });
      expect(createLinkMock).toHaveBeenCalledTimes(1); expect(workspacesMock).toHaveBeenCalledTimes(2);
      await act(async () => { initial.resolve(empty); });
      expect(page.getByRole("heading", { name: /^TM-1234567$/ })).toBeVisible();
      expect(client.getQueryData(["ip", "registry", "workspaces", DOCKET.id, 0])).toMatchObject({ items: [{ link: { id: LINK.id } }] });
      expect(createLinkMock).toHaveBeenCalledTimes(1);
    });
  });
});
