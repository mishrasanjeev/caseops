import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  capabilityMock,
  coreMock,
  createHandoffMock,
  createProfileMock,
  decideHitMock,
  docketsMock,
  ingestMock,
  workspaceMock,
} = vi.hoisted(() => ({
  capabilityMock: vi.fn(),
  coreMock: vi.fn(),
  createHandoffMock: vi.fn(),
  createProfileMock: vi.fn(),
  decideHitMock: vi.fn(),
  docketsMock: vi.fn(),
  ingestMock: vi.fn(),
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

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("@/lib/api/endpoints", () => ({
  createIpWatchHandoff: createHandoffMock,
  createIpWatchProfile: createProfileMock,
  decideIpWatchHit: decideHitMock,
  fetchIpCoreRecords: coreMock,
  fetchIpDockets: docketsMock,
  fetchIpWatchWorkspace: workspaceMock,
  ingestIpJournal: ingestMock,
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
  publication_scope_json: { scope_kind: "partial" },
  source_url: "https://ipindia.gov.in/journal/2248/page/412",
  source_page: "412",
  source_status: "unavailable",
  source_retrieved_at: "2026-08-24T08:00:00Z",
  attribution_json: { publisher: "IP India" },
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
  publications: [PUBLICATION],
  hits: [HIT],
  ingestion_runs: [],
  handoffs: [],
};

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("IP journal watch page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capabilityMock.mockReturnValue(true);
    docketsMock.mockResolvedValue({ dockets: [{ id: "docket-1", title: "ASTER mark" }], count: 1 });
    coreMock.mockResolvedValue({ assets: [], applications: [{ id: "application-1" }], proceedings: [], identifiers: [] });
    workspaceMock.mockResolvedValue(WORKSPACE);
  });

  it("fails closed without IP read access", () => {
    capabilityMock.mockReturnValue(false);
    render(<IpJournalWatchPage />, { wrapper: wrapper() });
    expect(screen.getByText("IP access required")).toBeVisible();
    expect(workspaceMock).not.toHaveBeenCalled();
  });

  it("shows correction lineage, source failure blocking, provenance, and advisory evidence", async () => {
    render(<IpJournalWatchPage />, { wrapper: wrapper() });
    expect(await screen.findByRole("heading", { name: "ASTER PRIME" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Open source" })).toHaveAttribute("href", PUBLICATION.source_url);
    expect(screen.getByText(/Final source-dependent dispositions are blocked/)).toBeVisible();
    expect(screen.getByText(/Prior hit hit-original/)).toBeVisible();
    expect(screen.getByText("AI assistance is advisory.")).toBeVisible();
    expect(screen.getByText(/class_overlap/)).toBeVisible();
  });

  it("creates explicit criteria, frequency, recipients, and cost policy", async () => {
    const user = userEvent.setup();
    createProfileMock.mockResolvedValue(PROFILE);
    render(<IpJournalWatchPage />, { wrapper: wrapper() });
    await user.click(await screen.findByRole("button", { name: "Profiles" }));
    await user.type(screen.getByLabelText("Profile name"), "ACME class and word watch");
    await user.type(screen.getByLabelText("Word terms"), "ACME, ACME PRIME");
    await user.type(screen.getByLabelText("Nice classes"), "9, 42");
    await user.clear(screen.getByLabelText("Recipient membership IDs"));
    await user.type(screen.getByLabelText("Recipient membership IDs"), "member-1, member-2");
    await user.selectOptions(screen.getByLabelText("Frequency"), "daily");
    await user.clear(screen.getByLabelText("Max cost (minor units)"));
    await user.type(screen.getByLabelText("Max cost (minor units)"), "250");
    await user.click(screen.getByRole("button", { name: "Create profile" }));
    await waitFor(() => expect(createProfileMock).toHaveBeenCalledTimes(1));
    expect(createProfileMock.mock.calls[0][0]).toEqual(expect.objectContaining({
      docketId: "docket-1",
      wordTerms: ["ACME", "ACME PRIME"],
      classNumbers: [9, 42],
      frequency: "daily",
      recipientMembershipIds: ["member-1", "member-2"],
      maxCostMinorPerPeriod: 250,
    }));
  });

  it("records source-confirmed review and creates a canonical opposition handoff", async () => {
    const user = userEvent.setup();
    const relevant = { ...HIT, source_status: "available", disposition: "relevant", version: 3 };
    workspaceMock.mockResolvedValue({ ...WORKSPACE, hits: [relevant], publications: [{ ...PUBLICATION, source_status: "available" }] });
    decideHitMock.mockResolvedValue(relevant);
    createHandoffMock.mockResolvedValue({ id: "handoff-1", hit_id: HIT.id, handoff_kind: "opposition", status: "completed", target_type: "ip_proceeding" });
    render(<IpJournalWatchPage />, { wrapper: wrapper() });
    await user.selectOptions(await screen.findByLabelText("Disposition"), "relevant");
    await user.clear(screen.getByLabelText("Reason"));
    await user.type(screen.getByLabelText("Reason"), "Official journal confirms overlapping classes.");
    await user.click(screen.getByLabelText(/I opened and confirmed/));
    await user.click(screen.getByRole("button", { name: "Record review" }));
    await waitFor(() => expect(decideHitMock).toHaveBeenCalledTimes(1));
    expect(decideHitMock.mock.calls[0][0]).toEqual(expect.objectContaining({ sourceConfirmed: true, disposition: "relevant" }));
    await user.click(screen.getByRole("button", { name: "Create opposition" }));
    await waitFor(() => expect(createHandoffMock).toHaveBeenCalledTimes(1));
    expect(createHandoffMock.mock.calls[0][0]).toEqual(expect.objectContaining({ hitId: HIT.id, handoffKind: "opposition", applicationId: "application-1" }));
  });
});
