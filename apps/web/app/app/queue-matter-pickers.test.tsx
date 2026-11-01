/**
 * B4-ADJ-02: the Drive, mailbox and calendar-conflict review queues asked a
 * lawyer to type a "Matter id for actions" and showed suggested Matters as
 * UUIDs. Each queue now chooses the Matter with the house MatterPicker over the
 * review validator's predicate (a Matter the reviewer can open that can still
 * take operational work) and names Matters by their caption.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/config";

const mocks = vi.hoisted(() => ({
  fetchCalendarProviderEventCandidates: vi.fn(),
  fetchDriveCandidates: vi.fn(),
  fetchGoogleDriveStatus: vi.fn(),
  fetchGmailMailboxStatus: vi.fn(),
  fetchMailboxImports: vi.fn(),
  fetchMatter: vi.fn(),
  listMatters: vi.fn(),
  reviewCalendarProviderEventCandidate: vi.fn(),
  reviewDriveCandidate: vi.fn(),
  reviewMailboxImport: vi.fn(),
}));

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("@/lib/capabilities", () => ({ useCapability: () => true }));
vi.mock("@/lib/api/endpoints", () => ({
  ...mocks,
  importRecentGmailMessages: vi.fn(),
  startGoogleDriveConnection: vi.fn(),
  startGmailMailboxConnection: vi.fn(),
  syncGoogleDriveCandidates: vi.fn(),
}));

import CalendarConflictsPage from "@/app/app/calendar/conflicts/page";
import DrivePage from "@/app/app/drive/page";
import MailboxPage from "@/app/app/mailbox/page";

const now = "2026-11-01T00:00:00Z";
const MATTERS = {
  open: { id: "matter-open", matter_code: "LIT-1", title: "Aster v Nova", client_name: "Aster", status: "active" },
  closed: { id: "matter-closed", matter_code: "LIT-2", title: "Closed dispute", client_name: "Aster", status: "closed" },
};

function renderPage(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.fetchGoogleDriveStatus.mockResolvedValue({ configured: true, connections: [{ status: "connected" }] });
  mocks.fetchGmailMailboxStatus.mockResolvedValue({ configured: true, connections: [{ status: "connected" }] });
  // Rows name their Matter through the wall-scoped list (`?id=`); a walled
  // Matter is simply absent. GET /api/matters/{id} audits a denial on every
  // render for a walled viewer and must never be used to name a row.
  mocks.listMatters.mockImplementation(async (params?: { id?: string }) => {
    if (!params?.id) return { matters: [MATTERS.open, MATTERS.closed], next_cursor: null };
    const found = params.id === "matter-suggested"
      ? { id: params.id, matter_code: "SUG-9", title: "Suggested matter", client_name: "Nova", status: "active" }
      : null;
    return { matters: found ? [found] : [], next_cursor: null };
  });
  mocks.fetchMatter.mockRejectedValue(new ApiError(404, "Matter not found.", null));
  mocks.fetchDriveCandidates.mockResolvedValue({
    pending_count: 2,
    candidates: [
      { id: "drive-suggested", provider: "google_drive", name: "Signed agreement.pdf", mime_type: "application/pdf", size_bytes: 2048, folder_path: null, suggested_matter_id: "matter-suggested", linked_matter_id: null, status: "new", last_error_redacted: null, created_at: now, updated_at: now },
      { id: "drive-unmatched", provider: "google_drive", name: "Board minutes.pdf", mime_type: "application/pdf", size_bytes: 4096, folder_path: null, suggested_matter_id: null, linked_matter_id: null, status: "new", last_error_redacted: null, created_at: now, updated_at: now },
    ],
  });
  mocks.reviewDriveCandidate.mockResolvedValue({ id: "drive-unmatched", status: "linked_metadata" });
  mocks.fetchMailboxImports.mockResolvedValue({
    summary: { imported: 0, unmatched: 1, duplicate: 0, failed: 0, attachment_candidates: 0 },
    imports: [
      { id: "mail-unlinked", provider: "gmail", provider_message_id: "gmail-1", matter_id: null, sender_name: "Client", subject: "Demand notice", snippet: "Snippet", occurred_at: now, status: "new", attachment_count: 0, last_error_redacted: null },
    ],
  });
  mocks.reviewMailboxImport.mockResolvedValue({ import_record: { id: "mail-unlinked", status: "linked_metadata" } });
  mocks.fetchCalendarProviderEventCandidates.mockResolvedValue({
    pending_count: 1,
    conflict_count: 0,
    candidates: [
      { id: "cal-unmatched", provider: "google_calendar", title: "Arguments", starts_at: now, location: null, suggested_matter_id: null, linked_matter_id: null, status: "new", conflict_reason: null },
    ],
  });
  mocks.reviewCalendarProviderEventCandidate.mockResolvedValue({ candidate: { id: "cal-unmatched", status: "accepted" } });
});

async function chooseMatter(name: string) {
  const select = await screen.findByRole<HTMLSelectElement>("combobox", { name });
  await waitFor(() => expect(select).toBeEnabled());
  // The picker states the validator's reason for a closed Matter instead of offering it.
  const closed = Array.from(select.options).find((option) => option.value === "matter-closed");
  expect(closed?.disabled).toBe(true);
  expect(closed?.textContent).toContain("closed Matters cannot take");
  expect(select).toHaveValue("");
  fireEvent.change(select, { target: { value: "matter-open" } });
  return select;
}

describe("review queues choose Matters by name (B4-ADJ-02)", () => {
  it("Drive: no Matter id field, suggestions named, actions gated until a Matter is chosen", async () => {
    renderPage(<DrivePage />);
    expect(await screen.findByText("Board minutes.pdf")).toBeVisible();
    expect(screen.queryByLabelText(/matter id/i)).toBeNull();
    expect(screen.queryByPlaceholderText(/matter id/i)).toBeNull();
    expect(await screen.findByText("SUG-9 · Suggested matter · Nova")).toBeVisible();
    expect(screen.queryByText("matter-suggested")).toBeNull();

    const unmatched = screen.getByText("Board minutes.pdf").closest("div.grid") as HTMLElement;
    expect(within(unmatched).getByRole("button", { name: "Link" })).toBeDisabled();
    expect(within(unmatched).getByText(/Choose a Matter for Link and Import above/)).toBeVisible();

    await chooseMatter("Matter for Link and Import");
    const link = within(unmatched).getByRole("button", { name: "Link" });
    await waitFor(() => expect(link).toBeEnabled());
    fireEvent.click(link);
    await waitFor(() => expect(mocks.reviewDriveCandidate).toHaveBeenCalledWith({
      candidateId: "drive-unmatched", action: "link_metadata", matterId: "matter-open",
    }));
  });

  it("Mailbox: links an unlinked message to the chosen Matter", async () => {
    renderPage(<MailboxPage />);
    expect(await screen.findByText("Demand notice")).toBeVisible();
    expect(screen.queryByLabelText(/matter id/i)).toBeNull();
    expect(screen.getByText(/Matter: unlinked/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Link" })).toBeDisabled();
    await chooseMatter("Matter for Link and Request");
    await waitFor(() => expect(screen.getByRole("button", { name: "Link" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Link" }));
    await waitFor(() => expect(mocks.reviewMailboxImport).toHaveBeenCalledWith({
      importId: "mail-unlinked", action: "link_metadata", matterId: "matter-open",
    }));
  });

  it("Calendar conflicts: accepts an unmatched event on the chosen Matter", async () => {
    renderPage(<CalendarConflictsPage />);
    expect(await screen.findByText("Arguments")).toBeVisible();
    expect(screen.queryByLabelText(/matter id/i)).toBeNull();
    expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
    expect(screen.getByText(/Choose a Matter for Accept above/)).toBeVisible();
    await chooseMatter("Matter for Accept");
    await waitFor(() => expect(screen.getByRole("button", { name: "Accept" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(mocks.reviewCalendarProviderEventCandidate).toHaveBeenCalledWith({
      candidateId: "cal-unmatched", action: "accept", matterId: "matter-open", forceOverwriteLocked: false,
    }));
  });

  it("names a suggested Matter the reviewer cannot open without leaking its id", async () => {
    mocks.fetchDriveCandidates.mockResolvedValue({
      pending_count: 1,
      candidates: [{ id: "drive-hidden", provider: "google_drive", name: "Walled.pdf", mime_type: null, size_bytes: null, folder_path: null, suggested_matter_id: "matter-walled", linked_matter_id: null, status: "new", last_error_redacted: null, created_at: now, updated_at: now }],
    });
    renderPage(<DrivePage />);
    expect(await screen.findByText("A Matter you cannot open")).toBeVisible();
    expect(screen.queryByText(/matter-walled/)).toBeNull();
    // Named through the wall-scoped list, never the audited by-id read.
    expect(mocks.listMatters).toHaveBeenCalledWith(expect.objectContaining({ id: "matter-walled" }));
    expect(mocks.fetchMatter).not.toHaveBeenCalled();
  });
});
