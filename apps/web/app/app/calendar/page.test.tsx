// Phase B / J08 / M08 — calendar page rendering contract.
//
// Covers the invariants that, if broken, would re-open BUG-029 or
// silently drop events from the lawyer's grid:
//
// - Page mounts and shows the current month label.
// - Events for the current month render as chips with the
//   matter title in the chip's tooltip.
// - Each event chip deep-links to the right matter route per kind.
// - "+N more" overflow appears when a single day has >3 events.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchCalendarEventsMock,
  fetchCalendarSummaryMock,
  fetchCalendarSyncStatusMock,
  extractEmailInvitationCandidatesMock,
  fetchGmailMailboxStatusMock,
  listCalendarConnectionsMock,
  listEmailInvitationCandidatesMock,
  importRecentGmailMessagesMock,
  reviewEmailInvitationCandidateMock,
  revokeCalendarConnectionMock,
  revokeGmailMailboxConnectionMock,
  startGmailMailboxConnectionMock,
  startGmailWatchMock,
  startGoogleCalendarConnectionMock,
  startOutlookCalendarConnectionMock,
  syncGoogleCalendarVisibleRangeMock,
  syncOutlookVisibleRangeMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  fetchCalendarEventsMock: vi.fn(),
  fetchCalendarSummaryMock: vi.fn(),
  fetchCalendarSyncStatusMock: vi.fn(),
  extractEmailInvitationCandidatesMock: vi.fn(),
  fetchGmailMailboxStatusMock: vi.fn(),
  listCalendarConnectionsMock: vi.fn(),
  listEmailInvitationCandidatesMock: vi.fn(),
  importRecentGmailMessagesMock: vi.fn(),
  reviewEmailInvitationCandidateMock: vi.fn(),
  revokeCalendarConnectionMock: vi.fn(),
  revokeGmailMailboxConnectionMock: vi.fn(),
  startGmailMailboxConnectionMock: vi.fn(),
  startGmailWatchMock: vi.fn(),
  startGoogleCalendarConnectionMock: vi.fn(),
  startOutlookCalendarConnectionMock: vi.fn(),
  syncGoogleCalendarVisibleRangeMock: vi.fn(),
  syncOutlookVisibleRangeMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  extractEmailInvitationCandidates: extractEmailInvitationCandidatesMock,
  fetchCalendarEvents: fetchCalendarEventsMock,
  fetchCalendarSummary: fetchCalendarSummaryMock,
  fetchCalendarSyncStatus: fetchCalendarSyncStatusMock,
  fetchGmailMailboxStatus: fetchGmailMailboxStatusMock,
  importRecentGmailMessages: importRecentGmailMessagesMock,
  listCalendarConnections: listCalendarConnectionsMock,
  listEmailInvitationCandidates: listEmailInvitationCandidatesMock,
  reviewEmailInvitationCandidate: reviewEmailInvitationCandidateMock,
  revokeCalendarConnection: revokeCalendarConnectionMock,
  revokeGmailMailboxConnection: revokeGmailMailboxConnectionMock,
  startGmailMailboxConnection: startGmailMailboxConnectionMock,
  startGmailWatch: startGmailWatchMock,
  startGoogleCalendarConnection: startGoogleCalendarConnectionMock,
  startOutlookCalendarConnection: startOutlookCalendarConnectionMock,
  syncGoogleCalendarVisibleRange: syncGoogleCalendarVisibleRangeMock,
  syncOutlookVisibleRange: syncOutlookVisibleRangeMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: useCapabilityMock,
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import CalendarPage from "./page";
import { calendarEventListResponse, calendarSyncStatusResponse } from "@/lib/api/schemas";
import { calendarStatusFixture } from "@/test/calendar-status-fixtures";

function withClient(node: ReactNode): ReactNode {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

function isoToday(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

describe("CalendarPage", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/app/calendar");
    fetchCalendarEventsMock.mockReset();
    fetchCalendarSummaryMock.mockReset();
    fetchCalendarSyncStatusMock.mockReset();
    extractEmailInvitationCandidatesMock.mockReset();
    fetchGmailMailboxStatusMock.mockReset();
    listCalendarConnectionsMock.mockReset();
    listEmailInvitationCandidatesMock.mockReset();
    importRecentGmailMessagesMock.mockReset();
    reviewEmailInvitationCandidateMock.mockReset();
    revokeCalendarConnectionMock.mockReset();
    revokeGmailMailboxConnectionMock.mockReset();
    startGmailMailboxConnectionMock.mockReset();
    startGmailWatchMock.mockReset();
    startGoogleCalendarConnectionMock.mockReset();
    startOutlookCalendarConnectionMock.mockReset();
    syncGoogleCalendarVisibleRangeMock.mockReset();
    syncOutlookVisibleRangeMock.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockReturnValue(true);
    listCalendarConnectionsMock.mockResolvedValue({
      provider: "outlook",
      provider_available: true,
      unavailable_reason: null,
      durable_automation: "blocked_pending_provider_approval",
      connections: [],
    });
    fetchCalendarSyncStatusMock.mockResolvedValue({
      provider_available: true,
      durable_automation: "blocked_pending_provider_approval",
      notification_delivery: "wtd_5_3_foundation_available",
      capabilities: {
        sync_mode: "manual_bounded",
        manual_sync_available: true,
        durable_automation: "blocked_pending_provider_approval",
        notification_delivery: "wtd_5_3_foundation_available",
        email_invitation_candidates: "review_queue_available",
      },
      provider_config: [
        {
          provider: "outlook",
          configured: true,
          missing_config_names: [],
        },
        {
          provider: "google_calendar",
          configured: false,
          missing_config_names: ["GOOGLE_CALENDAR_CLIENT_ID", "GOOGLE_CALENDAR_CLIENT_SECRET", "GOOGLE_CALENDAR_REDIRECT_URI"],
        },
      ],
      conflict_summary: {
        has_conflicts: false,
        candidate_count: 0,
        duplicate_provider_event_count: 0,
        changed_event_candidate_count: 0,
        changed_event_detection: "unsupported_no_provider_snapshot",
      },
      conflict_candidates: [],
      connections: [],
      syncs: [],
    });
    listEmailInvitationCandidatesMock.mockResolvedValue({
      candidates: [],
      pending_count: 0,
      duplicate_count: 0,
    });
    fetchGmailMailboxStatusMock.mockResolvedValue({
      provider: "gmail",
      configured: false,
      webhook_configured: false,
      missing_config_names: [
        "GMAIL_CLIENT_ID",
        "GMAIL_CLIENT_SECRET",
        "GMAIL_REDIRECT_URI",
      ],
      missing_webhook_config_names: [
        "GMAIL_PUBSUB_TOPIC",
        "GMAIL_WEBHOOK_VERIFICATION_TOKEN",
      ],
      connections: [],
    });
    importRecentGmailMessagesMock.mockResolvedValue({
      summary: {
        imported: 0,
        unmatched: 0,
        duplicate: 0,
        failed: 0,
        attachment_candidates: 0,
      },
      imports: [],
    });
    startGmailWatchMock.mockResolvedValue({
      provider: "gmail",
      watch_started: true,
      webhook_configured: true,
      history_id: "history-id",
      watch_expires_at: new Date().toISOString(),
      missing_config_names: [],
    });
    extractEmailInvitationCandidatesMock.mockResolvedValue({
      examined_count: 0,
      created_count: 0,
      duplicate_count: 0,
      candidates: [],
    });
    reviewEmailInvitationCandidateMock.mockResolvedValue({});
  });

  it("keeps configured Google readiness with actual pending-deletion sync rows", async () => {
    fetchCalendarEventsMock.mockResolvedValue({ range_from: isoToday(), range_to: isoToday(), events: [] });
    fetchCalendarSyncStatusMock.mockImplementation(async () => calendarSyncStatusResponse.parse(calendarStatusFixture()));
    render(withClient(<CalendarPage />));
    await waitFor(() => expect(screen.getByTestId("calendar-google-connect")).toBeEnabled());
    const panel = screen.getByTestId("calendar-google-panel");
    expect(within(panel).queryByText(/OAuth is not configured/)).not.toBeInTheDocument();
    expect(within(panel).queryByText(/Missing Google config/)).not.toBeInTheDocument();
    expect(startGoogleCalendarConnectionMock).not.toHaveBeenCalled();
    expect(syncGoogleCalendarVisibleRangeMock).not.toHaveBeenCalled();
  });

  it("shows a readiness load failure without inventing missing credentials and can retry", async () => {
    fetchCalendarEventsMock.mockResolvedValue({ range_from: isoToday(), range_to: isoToday(), events: [] });
    fetchCalendarSyncStatusMock.mockRejectedValueOnce(new Error("Synthetic readiness transport failure"))
      .mockImplementation(async () => calendarSyncStatusResponse.parse(calendarStatusFixture()));
    render(withClient(<CalendarPage />));
    const error = await screen.findByTestId("calendar-readiness-error");
    expect(error).toHaveTextContent("Could not load Calendar connection status");
    expect(screen.queryByText(/Google Calendar OAuth is not configured/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Missing Google config/)).not.toBeInTheDocument();
    expect(screen.getByTestId("calendar-google-connect")).toBeDisabled();
    await userEvent.click(within(error).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByTestId("calendar-google-connect")).toBeEnabled());
    expect(screen.queryByTestId("calendar-readiness-error")).not.toBeInTheDocument();
    expect(fetchCalendarSyncStatusMock).toHaveBeenCalledTimes(2);
    expect(startGoogleCalendarConnectionMock).not.toHaveBeenCalled();
  });

  it("does not label loading readiness as missing Google configuration", async () => {
    fetchCalendarEventsMock.mockResolvedValue({ range_from: isoToday(), range_to: isoToday(), events: [] });
    fetchCalendarSyncStatusMock.mockImplementation(() => new Promise(() => {}));
    render(withClient(<CalendarPage />));
    expect(await screen.findByText("Checking Google Calendar readiness...")).toBeVisible();
    expect(screen.queryByText(/Missing Google config/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Google Calendar OAuth is not configured/)).not.toBeInTheDocument();
    expect(screen.getByTestId("calendar-google-connect")).toBeDisabled();
  });

  it("keeps a missing provider-status entry unknown rather than inventing configuration facts", async () => {
    fetchCalendarEventsMock.mockResolvedValue({ range_from: isoToday(), range_to: isoToday(), events: [] });
    const payload = calendarStatusFixture();
    payload.provider_config = payload.provider_config?.filter(row => row.provider === "outlook");
    fetchCalendarSyncStatusMock.mockResolvedValue(calendarSyncStatusResponse.parse(payload));
    render(withClient(<CalendarPage />));
    expect(await screen.findByText("Google Calendar readiness is unavailable.")).toBeVisible();
    expect(screen.queryByText(/Missing Google config/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Google Calendar OAuth is not configured/)).not.toBeInTheDocument();
    expect(screen.getByTestId("calendar-google-connect")).toBeDisabled();
  });

  it("keeps Outlook connection errors distinct from disconnected or missing configuration", async () => {
    fetchCalendarEventsMock.mockResolvedValue({ range_from: isoToday(), range_to: isoToday(), events: [] });
    listCalendarConnectionsMock.mockRejectedValueOnce(new Error("Synthetic Outlook status failure"));
    render(withClient(<CalendarPage />));
    const error = await screen.findByTestId("calendar-outlook-readiness-error");
    expect(error).toHaveTextContent("Could not load Outlook connection status");
    expect(screen.getByTestId("calendar-outlook-connect")).toBeDisabled();
    expect(startOutlookCalendarConnectionMock).not.toHaveBeenCalled();
    await userEvent.click(within(error).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByTestId("calendar-outlook-connect")).toBeEnabled());
  });

  it("does not enable Outlook connection while its status is still loading", async () => {
    fetchCalendarEventsMock.mockResolvedValue({ range_from: isoToday(), range_to: isoToday(), events: [] });
    listCalendarConnectionsMock.mockImplementation(() => new Promise(() => {}));
    render(withClient(<CalendarPage />));
    expect(await screen.findByText("Checking connection...")).toBeVisible();
    expect(screen.getByTestId("calendar-outlook-connect")).toBeDisabled();
  });

  it("does not invent Gmail credential or webhook failures after a status error", async () => {
    fetchCalendarEventsMock.mockResolvedValue({ range_from: isoToday(), range_to: isoToday(), events: [] });
    fetchGmailMailboxStatusMock.mockRejectedValueOnce(new Error("Synthetic Gmail status failure"));
    render(withClient(<CalendarPage />));
    const error = await screen.findByTestId("calendar-gmail-readiness-error");
    expect(error).toHaveTextContent("Could not load Gmail connection status");
    const panel = screen.getByTestId("calendar-gmail-panel");
    expect(within(panel).queryByText(/Gmail OAuth is not configured/)).not.toBeInTheDocument();
    expect(within(panel).queryAllByText(/Missing Gmail config|Gmail webhook blocked/)).toHaveLength(0);
    expect(screen.getByTestId("calendar-gmail-connect")).toBeDisabled();
    await userEvent.click(within(error).getByRole("button", { name: "Try again" }));
    expect(await within(panel).findByText(/Gmail OAuth is not configured/)).toBeVisible();
    expect(fetchGmailMailboxStatusMock).toHaveBeenCalledTimes(2);
    expect(startGmailMailboxConnectionMock).not.toHaveBeenCalled();
  });

  it("does not invent Gmail configuration failures while status is loading", async () => {
    fetchCalendarEventsMock.mockResolvedValue({ range_from: isoToday(), range_to: isoToday(), events: [] });
    fetchGmailMailboxStatusMock.mockImplementation(() => new Promise(() => {}));
    render(withClient(<CalendarPage />));
    expect(await screen.findByText("Checking Gmail readiness...")).toBeVisible();
    const panel = screen.getByTestId("calendar-gmail-panel");
    expect(within(panel).queryAllByText(/Missing Gmail config|Gmail webhook blocked/)).toHaveLength(0);
    expect(screen.getByTestId("calendar-gmail-connect")).toBeDisabled();
  });

  it("renders the current month label and a Today affordance", async () => {
    fetchCalendarEventsMock.mockResolvedValueOnce({
      range_from: "2026-04-01",
      range_to: "2026-05-31",
      events: [],
    });
    render(withClient(<CalendarPage />));
    const label = await screen.findByTestId("calendar-month-label");
    expect(label.textContent).toMatch(
      /(January|February|March|April|May|June|July|August|September|October|November|December) \d{4}/,
    );
    expect(screen.getByTestId("calendar-today")).toBeTruthy();
    expect(screen.getByTestId("calendar-prev-month")).toBeTruthy();
    expect(screen.getByTestId("calendar-next-month")).toBeTruthy();
    expect(await screen.findByTestId("calendar-outlook-panel")).toBeTruthy();
    expect(await screen.findByTestId("calendar-google-panel")).toHaveTextContent(
      "Google Calendar",
    );
    expect(screen.getByTestId("calendar-google-connect")).toBeDisabled();
    expect(
      screen.getByTestId("calendar-google-provider-config-status"),
    ).toHaveTextContent(/GOOGLE_CALENDAR_CLIENT_ID/);
    expect(screen.getByTestId("calendar-google-ics-download")).toBeInTheDocument();
    expect(screen.getByTestId("calendar-google-integrations-link")).toHaveAttribute(
      "href",
      "/app/admin/integrations",
    );
    expect(await screen.findByTestId("calendar-gmail-panel")).toHaveTextContent(
      "Gmail mailbox",
    );
    expect(screen.getByTestId("calendar-gmail-connect")).toBeDisabled();
    expect(
      screen.getByTestId("calendar-gmail-provider-config-status"),
    ).toHaveTextContent(/GMAIL_CLIENT_ID/);
    expect(
      screen.getByTestId("calendar-gmail-webhook-config-status"),
    ).toHaveTextContent(/GMAIL_WEBHOOK_VERIFICATION_TOKEN/);
    expect(screen.getByTestId("calendar-ics-download")).toBeTruthy();
  });

  it("enables Google Calendar connect when OAuth configuration is present", async () => {
    fetchCalendarEventsMock.mockResolvedValueOnce({
      range_from: "2026-04-01",
      range_to: "2026-05-31",
      events: [],
    });
    fetchCalendarSyncStatusMock.mockResolvedValue({
      provider_available: true,
      durable_automation: "blocked_pending_provider_approval",
      notification_delivery: "wtd_5_3_foundation_available",
      capabilities: {
        sync_mode: "manual_bounded",
        manual_sync_available: true,
        durable_automation: "blocked_pending_provider_approval",
        notification_delivery: "wtd_5_3_foundation_available",
        email_invitation_candidates: "review_queue_available",
      },
      provider_config: [
        {
          provider: "outlook",
          configured: true,
          missing_config_names: [],
        },
        {
          provider: "google_calendar",
          configured: true,
          missing_config_names: [],
        },
      ],
      conflict_summary: {
        has_conflicts: false,
        candidate_count: 0,
        duplicate_provider_event_count: 0,
        changed_event_candidate_count: 0,
        changed_event_detection: "unsupported_no_provider_snapshot",
      },
      conflict_candidates: [],
      connections: [],
      syncs: [],
    });

    render(withClient(<CalendarPage />));

    await waitFor(() =>
      expect(screen.getByTestId("calendar-google-panel")).toHaveTextContent(
        "Manual hearing, task, and deadline sync is available after a Google Calendar connection is added.",
      ),
    );
    expect(screen.getByTestId("calendar-google-connect")).toBeEnabled();
    expect(
      screen.queryByTestId("calendar-google-provider-config-status"),
    ).toBeNull();
    expect(startGoogleCalendarConnectionMock).not.toHaveBeenCalled();
  });

  it("syncs and revokes a connected Google Calendar account", async () => {
    const now = new Date().toISOString();
    const googleConnection = {
      id: "google-conn-1",
      company_id: "co-1",
      membership_id: "mem-1",
      provider: "google_calendar",
      provider_account_id: "google-account-1",
      display_email: "owner@gmail.example",
      status: "connected",
      scopes: ["https://www.googleapis.com/auth/calendar.events"],
      connected_at: now,
      last_sync_at: null,
      created_at: now,
      updated_at: now,
    };
    fetchCalendarEventsMock.mockResolvedValueOnce({
      range_from: "2026-04-01",
      range_to: "2026-05-31",
      events: [],
    });
    listCalendarConnectionsMock.mockResolvedValueOnce({
      provider: "outlook",
      provider_available: true,
      unavailable_reason: null,
      durable_automation: "blocked_pending_provider_approval",
      connections: [googleConnection],
    });
    fetchCalendarSyncStatusMock.mockResolvedValue({
      provider_available: true,
      durable_automation: "blocked_pending_provider_approval",
      notification_delivery: "wtd_5_3_foundation_available",
      capabilities: {
        sync_mode: "manual_bounded",
        manual_sync_available: true,
        durable_automation: "blocked_pending_provider_approval",
        notification_delivery: "wtd_5_3_foundation_available",
        email_invitation_candidates: "review_queue_available",
      },
      provider_config: [
        {
          provider: "outlook",
          configured: true,
          missing_config_names: [],
        },
        {
          provider: "google_calendar",
          configured: true,
          missing_config_names: [],
        },
      ],
      conflict_summary: {
        has_conflicts: false,
        candidate_count: 0,
        duplicate_provider_event_count: 0,
        changed_event_candidate_count: 0,
        changed_event_detection: "unsupported_no_provider_snapshot",
      },
      conflict_candidates: [],
      connections: [googleConnection],
      syncs: [],
    });
    syncGoogleCalendarVisibleRangeMock.mockResolvedValueOnce({
      examined: 2,
      created: 1,
      updated: 1,
      failed: 0,
      skipped: 0,
      items: [],
      durable_automation: "blocked_pending_provider_approval",
    });
    revokeCalendarConnectionMock.mockResolvedValueOnce({
      ...googleConnection,
      status: "revoked",
    });

    const user = userEvent.setup();
    render(withClient(<CalendarPage />));

    await waitFor(() =>
      expect(screen.getByTestId("calendar-google-panel")).toHaveTextContent(
        "Connected as owner@gmail.example",
      ),
    );
    await user.click(screen.getByTestId("calendar-google-sync-range"));
    await waitFor(() =>
      expect(syncGoogleCalendarVisibleRangeMock).toHaveBeenCalledWith(
        expect.objectContaining({
          from: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
          to: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
        }),
      ),
    );
    expect(
      await screen.findByText(
        /Synced 1 new, 1 updated, 0 failed, 0 skipped \(2 examined\)\./,
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByTestId("calendar-google-revoke"));
    await waitFor(() =>
      expect(revokeCalendarConnectionMock).toHaveBeenCalledWith(
        "google-conn-1",
        expect.anything(),
      ),
    );
  });

  it("imports, watches, and revokes a connected Gmail mailbox without internal fields", async () => {
    const now = new Date().toISOString();
    const gmailConnection = {
      id: "gmail-conn-1",
      company_id: "co-1",
      membership_id: "mem-1",
      provider: "gmail",
      provider_account_id: "owner@gmail.example",
      display_email: "owner@gmail.example",
      status: "connected",
      scopes: ["https://www.googleapis.com/auth/gmail.readonly"],
      last_history_id: "history-1",
      watch_expires_at: now,
      last_import_at: now,
      connected_at: now,
      created_at: now,
      updated_at: now,
    };
    fetchCalendarEventsMock.mockResolvedValueOnce({
      range_from: "2026-04-01",
      range_to: "2026-05-31",
      events: [],
    });
    fetchGmailMailboxStatusMock.mockResolvedValue({
      provider: "gmail",
      configured: true,
      webhook_configured: true,
      missing_config_names: [],
      missing_webhook_config_names: [],
      connections: [gmailConnection],
    });
    importRecentGmailMessagesMock.mockResolvedValueOnce({
      summary: {
        imported: 2,
        unmatched: 1,
        duplicate: 0,
        failed: 0,
        attachment_candidates: 1,
      },
      imports: [],
    });
    revokeGmailMailboxConnectionMock.mockResolvedValueOnce({
      ...gmailConnection,
      status: "revoked",
    });

    const user = userEvent.setup();
    render(withClient(<CalendarPage />));

    const panel = await screen.findByTestId("calendar-gmail-panel");
    await waitFor(() =>
      expect(panel).toHaveTextContent("Connected as owner@gmail.example"),
    );
    expect(panel.textContent).not.toMatch(
      /token|secret|gross profit|gross margin|provider fee|internal cost/i,
    );

    await user.click(screen.getByTestId("calendar-gmail-import"));
    await waitFor(() =>
      expect(importRecentGmailMessagesMock).toHaveBeenCalledWith({ limit: 25 }),
    );
    expect(
      await screen.findByText(
        "Imported 2, unmatched 1, duplicates 0, attachment candidates 1.",
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByTestId("calendar-gmail-watch"));
    await waitFor(() => expect(startGmailWatchMock).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Gmail webhook watch started.")).toBeInTheDocument();

    await user.click(screen.getByTestId("calendar-gmail-revoke"));
    await waitFor(() =>
      expect(revokeGmailMailboxConnectionMock).toHaveBeenCalledWith(
        "gmail-conn-1",
        expect.anything(),
      ),
    );
  });

  it("shows Outlook unavailable state without hiding ICS export", async () => {
    fetchCalendarEventsMock.mockResolvedValueOnce({
      range_from: "2026-04-01",
      range_to: "2026-05-31",
      events: [],
    });
    listCalendarConnectionsMock.mockResolvedValueOnce({
      provider: "outlook",
      provider_available: false,
      unavailable_reason: "Microsoft Graph OAuth is not configured.",
      durable_automation: "blocked_pending_provider_approval",
      connections: [],
    });
    render(withClient(<CalendarPage />));
    expect(
      await screen.findByText(/Microsoft Graph OAuth is not configured/i),
    ).toBeInTheDocument();
    expect(screen.getByTestId("calendar-ics-download")).toBeInTheDocument();
  });

  it("renders bounded sync status without claiming durable automation", async () => {
    fetchCalendarEventsMock.mockResolvedValue({
      range_from: "2026-04-01",
      range_to: "2026-05-31",
      events: [],
    });
    render(withClient(<CalendarPage />));
    const panel = await screen.findByTestId("calendar-sync-status-panel");
    expect(within(panel).getByText("Manual visible-range sync")).toBeInTheDocument();
    expect(within(panel).getByText("Pending provider approval")).toBeInTheDocument();
    expect(within(panel).getByText("Durable foundation available")).toBeInTheDocument();
    expect(within(panel).getByText("Review queue available")).toBeInTheDocument();
  });

  it("renders durable hearing sync as one-way when tenant readiness is passed", async () => {
    fetchCalendarEventsMock.mockResolvedValue({
      range_from: "2026-04-01",
      range_to: "2026-05-31",
      events: [],
    });
    fetchCalendarSyncStatusMock.mockResolvedValueOnce({
      provider_available: true,
      durable_automation: "caseops_to_outlook_hearings_ready",
      notification_delivery: "wtd_5_3_foundation_available",
      capabilities: {
        sync_mode: "manual_bounded",
        manual_sync_available: true,
        durable_automation: "caseops_to_outlook_hearings_ready",
        notification_delivery: "wtd_5_3_foundation_available",
        email_invitation_candidates: "review_queue_available",
      },
      provider_config: [
        {
          provider: "outlook",
          configured: true,
          missing_config_names: [],
        },
        {
          provider: "google_calendar",
          configured: false,
          missing_config_names: [
            "GOOGLE_CALENDAR_CLIENT_ID",
            "GOOGLE_CALENDAR_CLIENT_SECRET",
            "GOOGLE_CALENDAR_REDIRECT_URI",
          ],
        },
      ],
      conflict_summary: {
        has_conflicts: false,
        candidate_count: 0,
        duplicate_provider_event_count: 0,
        changed_event_candidate_count: 0,
        changed_event_detection: "unsupported_no_provider_snapshot",
      },
      conflict_candidates: [],
      connections: [],
      syncs: [],
    });
    render(withClient(<CalendarPage />));
    const panel = await screen.findByTestId("calendar-sync-status-panel");
    expect(
      within(panel).getByText("CaseOps-to-Outlook hearing sync ready"),
    ).toBeInTheDocument();
    expect(panel.textContent).not.toMatch(/two-way|mailbox|Google Drive/i);
  });

  it("shows email invitation candidates and review actions without provider sync claims", async () => {
    fetchCalendarEventsMock.mockResolvedValueOnce({
      range_from: "2026-04-01",
      range_to: "2026-05-31",
      events: [],
    });
    listEmailInvitationCandidatesMock.mockResolvedValueOnce({
      pending_count: 1,
      duplicate_count: 0,
      candidates: [
        {
          id: "candidate-1",
          company_id: "company-1",
          matter_id: "matter-1",
          matter_title: "State v Accused",
          matter_code: "CR-001",
          communication_id: "comm-1",
          thread_key: null,
          status: "needs_review",
          detected_title: "Strategy conference",
          detected_start_at: "2026-06-15T10:30:00Z",
          detected_end_at: "2026-06-15T11:30:00Z",
          detected_location: "Courtroom 4",
          source_preview: "Calendar invitation for 2026-06-15 at 10:30 AM.",
          confidence_band: "high",
          duplicate_of_candidate_id: null,
          created_deadline_id: null,
          reviewed_by_membership_id: null,
          reviewed_at: null,
          created_at: "2026-05-24T00:00:00Z",
          updated_at: "2026-05-24T00:00:00Z",
        },
      ],
    });
    render(withClient(<CalendarPage />));

    expect(await screen.findByText("Strategy conference")).toBeInTheDocument();
    const panel = screen.getByTestId("calendar-email-candidates-panel");
    expect(within(panel).getByText(/CR-001/)).toBeInTheDocument();
    expect(within(panel).getByText(/1 needs review/)).toBeInTheDocument();
    expect(within(panel).getByText(/External provider sync is not used/)).toBeInTheDocument();
    expect(panel.textContent).not.toMatch(/storage_key|access_token|raw invite/i);

    const user = userEvent.setup();
    await user.click(
      within(panel).getByTestId("calendar-email-candidate-approve-candidate-1"),
    );
    await waitFor(() =>
      expect(reviewEmailInvitationCandidateMock).toHaveBeenCalledWith(
        {
          candidateId: "candidate-1",
          action: "approve",
        },
        expect.anything(),
      ),
    );
  });

  it("shows sync conflict candidates from safe metadata only", async () => {
    fetchCalendarEventsMock.mockResolvedValueOnce({
      range_from: "2026-04-01",
      range_to: "2026-05-31",
      events: [],
    });
    fetchCalendarSyncStatusMock.mockResolvedValueOnce({
      provider_available: true,
      durable_automation: "blocked_pending_provider_approval",
      notification_delivery: "wtd_5_3_foundation_available",
      capabilities: {
        sync_mode: "manual_bounded",
        manual_sync_available: true,
        durable_automation: "blocked_pending_provider_approval",
        notification_delivery: "wtd_5_3_foundation_available",
        email_invitation_candidates: "review_queue_available",
      },
      provider_config: [
        {
          provider: "outlook",
          configured: true,
          missing_config_names: [],
        },
      ],
      conflict_summary: {
        has_conflicts: true,
        candidate_count: 1,
        duplicate_provider_event_count: 1,
        changed_event_candidate_count: 0,
        changed_event_detection: "unsupported_no_provider_snapshot",
      },
      conflict_candidates: [
        {
          id: "dup-provider-event:abc",
          conflict_type: "duplicate_provider_event_id",
          severity: "review",
          provider: "outlook",
          calendar_connection_id: "conn-1",
          provider_event_id: "remote-event-1",
          duplicate_count: 2,
          source_ids: ["hearing-1", "hearing-2"],
          source_types: ["matter_hearing"],
          sync_ids: ["sync-1", "sync-2"],
          message:
            "Multiple CaseOps calendar sync records point to the same Outlook event.",
        },
      ],
      connections: [],
      syncs: [],
    });
    render(withClient(<CalendarPage />));
    const status = await screen.findByTestId("calendar-conflict-status");
    expect(within(status).getByText(/1 candidate/)).toBeInTheDocument();
    expect(within(status).getByText(/remote-event-1/)).toBeInTheDocument();
    expect(status.textContent).not.toMatch(/storage_key|access_token|raw email/i);
  });

  it("renders an event chip for each event returned by the API", async () => {
    const today = isoToday();
    fetchCalendarEventsMock.mockResolvedValueOnce({
      range_from: today,
      range_to: today,
      events: [
        {
          id: "hearing:h1",
          kind: "hearing", display_type: "hearing",
          occurs_on: today,
          title: "Bail hearing",
          matter_id: "m1",
          matter_code: "BAIL-001",
          matter_title: "State v Accused",
          status: "scheduled",
          detail: "Bombay HC",
        },
        {
          id: "task:t1",
          kind: "task", display_type: "task_date",
          occurs_on: today,
          title: "Draft reply",
          matter_id: "m2",
          matter_code: "CIV-002",
          matter_title: "Civil dispute",
          status: "todo",
          detail: "high",
        },
      ],
    });
    render(withClient(<CalendarPage />));

    // Wait for the data — the chips have stable testids tied to the
    // event id.
    expect(await screen.findByTestId("calendar-event-hearing:h1")).toBeTruthy();
    expect(await screen.findByTestId("calendar-event-task:t1")).toBeTruthy();
  });

  it("names a month day's counts on its day button, which phones show instead of clipped chips", async () => {
    const today = isoToday();
    const base = { matter_id: "m1", matter_code: "BAIL-001", matter_title: "State v Accused", detail: null };
    fetchCalendarEventsMock.mockResolvedValue({
      range_from: today,
      range_to: today,
      events: [
        { ...base, id: "hearing:h1", kind: "hearing", occurs_on: today, title: "Bail hearing", status: "scheduled", display_type: "hearing" },
        { ...base, id: "hearing:h2", kind: "hearing", occurs_on: today, title: "Mention", status: "scheduled", display_type: "hearing" },
        { ...base, id: "task:t1", kind: "task", occurs_on: today, title: "Draft reply", status: "todo", display_type: "task_date" },
      ],
    });
    render(withClient(<CalendarPage />));
    const badge = await screen.findByTestId(`calendar-month-count-${today}`);
    expect(badge).toHaveAttribute("data-total", "3");
    expect(Array.from(badge.querySelectorAll("[data-display-type]")).map((dot) => dot.getAttribute("data-display-type")))
      .toEqual(["hearing", "task_date"]);
    const trigger = screen.getByRole("button", { name: `View all events on ${today}` });
    expect(trigger).toContainElement(badge);
    expect(trigger.getAttribute("aria-describedby")).toBe(badge.id);
    expect(badge).toHaveTextContent(/: 3 events — 2 hearings, 1 task date/);
  });

  it("does not report an empty calendar while its events request is delayed", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 9, 17, 12));
    const events = [15, 16].flatMap(day => Array.from({ length: 8 }, (_, index) => ({
      id: `hearing:delayed-${day}-${index}`, kind: "hearing", display_type: "hearing", occurs_on: `2026-10-${day}`,
      title: "Delayed hearing", matter_id: `delayed-matter-${Math.floor(index / 2)}`,
      matter_code: `CAL-DELAY-${Math.floor(index / 2)}`, matter_title: "Delayed matter",
      status: "scheduled", court_label: `Configured court ${Math.floor(index / 2)}`,
      court_identity: `Configured court ${Math.floor(index / 2)}`, forum_display_order: Math.floor(index / 2),
      time_status: "exact", hearing_time: index % 2 === 0 ? "09:30:00" : "10:30:00",
      session_label: null, timezone: "Asia/Kolkata",
    })));
    const response = calendarEventListResponse.parse({
      range_from: "2026-09-28", range_to: "2026-11-08",
      events: [...events, { ...events[0], id: "hearing:delayed-session", occurs_on: "2026-10-17",
        time_status: "session", hearing_time: null, session_label: "Afternoon session" }],
    });
    let resolveEvents!: (value: typeof response) => void;
    fetchCalendarEventsMock.mockReturnValueOnce(new Promise<typeof response>(resolve => {
      resolveEvents = resolve;
    }));
    try {
      render(withClient(<CalendarPage />));
      await waitFor(() => expect(fetchCalendarEventsMock).toHaveBeenCalledExactlyOnceWith({
        from: "2026-09-28", to: "2026-11-08",
      }));
      expect(screen.getByTestId("calendar-month-label")).toHaveTextContent("October 2026");
      expect(screen.getAllByTestId(/^calendar-month-day-/)).toHaveLength(42);
      expect(screen.queryByTestId("calendar-empty-state")).not.toBeInTheDocument();
      expect(screen.queryByText("Could not load calendar")).not.toBeInTheDocument();
      expect(screen.queryAllByTestId(/^calendar-event-/)).toHaveLength(0);
      await act(async () => resolveEvents(response));
      for (const day of [15, 16]) {
        const cell = within(screen.getByTestId(`calendar-month-day-2026-10-${day}`));
        const chips = await cell.findAllByTestId(/^calendar-event-/);
        expect(chips.map(chip => chip.getAttribute("data-testid")))
          .toEqual([0, 1, 2].map(index => `calendar-event-hearing:delayed-${day}-${index}`));
        expect(cell.getByRole("button", { name: `Show 5 more events on 2026-10-${day}` })).toBeEnabled();
      }
      expect(screen.getByTestId("calendar-event-hearing:delayed-session"))
        .toHaveAttribute("title", expect.stringContaining("Afternoon session"));
      await userEvent.setup().click(screen.getByRole("button", { name: "View all events on 2026-10-17" }));
      const dialog = await screen.findByRole("dialog", { name: "Events on 2026-10-17" });
      expect(within(dialog).getByTestId("calendar-event-hearing:delayed-session"))
        .toHaveTextContent("Afternoon session");
      expect(screen.queryByTestId("calendar-empty-state")).not.toBeInTheDocument();
      expect(fetchCalendarEventsMock).toHaveBeenCalledTimes(1);
    } finally { vi.useRealTimers(); }
  });

  it("shows schema-rejected event responses as errors, never as empty success", async () => {
    fetchCalendarEventsMock.mockImplementationOnce(async () => calendarEventListResponse.parse({
      range_from: isoToday(), range_to: isoToday(),
      events: [{ id: "hearing:invalid", kind: "hearing", display_type: "hearing", occurs_on: isoToday(),
        title: "Invalid fixture", matter_id: "invalid-matter", matter_code: "CAL-INVALID",
        matter_title: "Invalid matter", time_status: "invalid_precision" }],
    }));
    render(withClient(<CalendarPage />));
    expect(await screen.findByText("Could not load calendar")).toBeVisible();
    expect(screen.queryByTestId("calendar-empty-state")).not.toBeInTheDocument();
    expect(screen.queryAllByTestId(/^calendar-event-/)).toHaveLength(0);
    expect(fetchCalendarEventsMock).toHaveBeenCalledTimes(1);
  });

  it("shows a failed events request distinctly and recovers only after explicit retry", async () => {
    const today = isoToday();
    fetchCalendarEventsMock.mockRejectedValueOnce(new Error("Calendar request unavailable"));
    render(withClient(<CalendarPage />));
    expect(await screen.findByText("Could not load calendar")).toBeVisible();
    expect(screen.getByText("Calendar request unavailable")).toBeVisible();
    expect(screen.queryByTestId("calendar-empty-state")).not.toBeInTheDocument();
    expect(screen.queryByTestId("calendar-event-hearing:recovered")).not.toBeInTheDocument();
    expect(fetchCalendarEventsMock).toHaveBeenCalledTimes(1);
    fetchCalendarEventsMock.mockResolvedValueOnce({
      range_from: today, range_to: today,
      events: [{ id: "hearing:recovered", kind: "hearing", display_type: "hearing", occurs_on: today,
        title: "Recovered hearing", matter_id: "recovered-matter", matter_code: "CAL-RETRY",
        matter_title: "Recovered matter" }],
    });
    await userEvent.setup().click(screen.getByRole("button", { name: /^Try again$/ }));
    expect(await screen.findByTestId("calendar-event-hearing:recovered"))
      .toHaveAttribute("href", "/app/matters/recovered-matter/hearings");
    expect(screen.queryByText("Could not load calendar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("calendar-empty-state")).not.toBeInTheDocument();
    expect(fetchCalendarEventsMock).toHaveBeenCalledTimes(2);
  });

  it("deep-links each event chip to the source matter's right tab", async () => {
    const today = isoToday();
    fetchCalendarEventsMock.mockResolvedValueOnce({
      range_from: today,
      range_to: today,
      events: [
        {
          id: "hearing:h1",
          kind: "hearing", display_type: "hearing",
          occurs_on: today,
          title: "Bail hearing",
          matter_id: "m1",
          matter_code: "BAIL-001",
          matter_title: "State v Accused",
        },
        {
          id: "task:t1",
          kind: "task", display_type: "task_date",
          occurs_on: today,
          title: "Draft reply",
          matter_id: "m2",
          matter_code: "CIV-002",
          matter_title: "Civil dispute",
        },
        {
          id: "deadline:d1",
          kind: "deadline", display_type: "deadline",
          occurs_on: today,
          title: "Filing deadline",
          matter_id: "m3",
          matter_code: "DRAFT-003",
          matter_title: "Filing matter",
        },
      ],
    });
    render(withClient(<CalendarPage />));

    const hearingLink = await screen.findByTestId("calendar-event-hearing:h1");
    const taskLink = await screen.findByTestId("calendar-event-task:t1");
    const deadlineLink = await screen.findByTestId("calendar-event-deadline:d1");

    expect(hearingLink.getAttribute("href")).toBe("/app/matters/m1/hearings");
    expect(taskLink.getAttribute("href")).toBe("/app/matters/m2/tasks");
    expect(deadlineLink.getAttribute("href")).toBe("/app/matters/m3/tasks");
  });

  it("distinguishes legal filing dates, internal targets, renewals, hearings, and task dates", async () => {
    const user = userEvent.setup();
    const today = isoToday();
    fetchCalendarEventsMock.mockResolvedValue({
      range_from: today,
      range_to: today,
      events: [
        { id: "deadline:legal", kind: "deadline", display_type: "filing_deadline", occurs_on: today, title: "File response", matter_id: "m1", matter_code: "IP-1", matter_title: "Mark", ip_docket_id: "docket-1" },
        { id: "deadline:target", kind: "deadline", display_type: "internal_target", occurs_on: today, title: "Prepare response", matter_id: "m1", matter_code: "IP-1", matter_title: "Mark", ip_docket_id: "docket-1" },
        { id: "deadline:renewal", kind: "deadline", display_type: "renewal", occurs_on: today, title: "Renew registration", matter_id: "m1", matter_code: "IP-1", matter_title: "Mark" },
        { id: "hearing:h1", kind: "hearing", display_type: "hearing", occurs_on: today, title: "Opposition hearing", matter_id: "m1", matter_code: "IP-1", matter_title: "Mark" },
        { id: "task:t1", kind: "task", display_type: "task_date", occurs_on: today, title: "Draft affidavit", matter_id: "m1", matter_code: "IP-1", matter_title: "Mark" },
      ],
    });
    render(withClient(<CalendarPage />));

    const legal = await screen.findByTestId("calendar-event-deadline:legal");
    expect(legal).toHaveTextContent("Filing: File response");
    expect(screen.getByTestId("calendar-event-deadline:target")).toHaveTextContent("Target: Prepare response");
    expect(screen.getByTestId("calendar-event-deadline:renewal")).toHaveTextContent("Renewal: Renew registration");
    expect(legal).toHaveAttribute(
      "href",
      "/app/ip?docket=docket-1",
    );
    await user.click(screen.getByTestId("calendar-view-day"));
    expect(screen.getByTestId("calendar-event-hearing:h1")).toHaveTextContent("Hearing or listing · IP-1");
    expect(screen.getByTestId("calendar-event-task:t1")).toHaveTextContent("Task date · IP-1");
  });

  it("shows '+N more' when a single day has more than 3 events", async () => {
    const today = isoToday();
    const events = Array.from({ length: 5 }).map((_, i) => ({
      id: `hearing:overflow-${i}`,
      kind: "hearing" as const, display_type: "hearing" as const,
      occurs_on: today,
      title: `Hearing ${i + 1}`,
      matter_id: `m${i}`,
      matter_code: `OV-${i}`,
      matter_title: `Overflow matter ${i}`,
    }));
    fetchCalendarEventsMock.mockResolvedValueOnce({
      range_from: today,
      range_to: today,
      events,
    });
    render(withClient(<CalendarPage />));

    // Wait for the first chip to land before asserting overflow.
    await screen.findByTestId("calendar-event-hearing:overflow-0");
    // The overflow badge reads "+2 more" because we cap at 3 chips.
    const overflow = await screen.findAllByText(/\+2 more/);
    expect(overflow.length).toBeGreaterThan(0);
    // And the overflow chips should NOT have rendered as their own
    // links — the cap is enforced at render time.
    expect(screen.queryByTestId("calendar-event-hearing:overflow-3")).toBeNull();
    expect(screen.queryByTestId("calendar-event-hearing:overflow-4")).toBeNull();
    const user = userEvent.setup();
    const trigger = screen.getByRole("button", { name: `Show 2 more events on ${today}` });
    await user.click(trigger);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getAllByRole("link")).toHaveLength(2);
    for (const index of [3, 4]) {
      expect(within(dialog).getByTestId(`calendar-event-hearing:overflow-${index}`))
        .toHaveAttribute("href", `/app/matters/m${index}/hearings`);
      expect(dialog).toHaveTextContent(`Overflow matter ${index}`);
    }
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(trigger).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    const reopenedDialog = screen.getByRole("dialog");
    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(reopenedDialog).not.toBeInTheDocument();
      expect(trigger).toHaveFocus();
    });
    await user.click(screen.getByRole("button", { name: `View all events on ${today}` }));
    expect(within(screen.getByRole("dialog")).getAllByRole("link")).toHaveLength(5);
  });

  it("waits for all-events close focus restoration before overflow keyboard activation", async () => {
    const today = isoToday();
    const events = Array.from({ length: 8 }, (_, index) => ({
      id: `hearing:lifecycle-${index}`, kind: "hearing" as const, display_type: "hearing" as const, occurs_on: today,
      title: `Lifecycle hearing ${index}`, matter_id: `lifecycle-${index}`,
      matter_code: `LIFE-${index}`, matter_title: `Lifecycle matter ${index}`,
    }));
    fetchCalendarEventsMock.mockResolvedValue({ range_from: today, range_to: today, events });
    render(withClient(<CalendarPage />));
    await screen.findByTestId("calendar-event-hearing:lifecycle-0");
    const user = userEvent.setup();
    const dayTrigger = screen.getByRole("button", { name: `View all events on ${today}` });
    const overflowTrigger = screen.getByRole("button", { name: `Show 5 more events on ${today}` });
    await user.click(dayTrigger);
    const allDialog = screen.getByRole("dialog", { name: `Events on ${today}` });
    expect(within(allDialog).getAllByRole("link")).toHaveLength(8);
    expect(within(allDialog).getAllByRole("link").map(link => link.getAttribute("data-testid")))
      .toEqual(events.map(event => `calendar-event-${event.id}`));
    await user.click(within(allDialog).getByRole("button", { name: "Close" }));
    await waitFor(() => {
      expect(allDialog).not.toBeInTheDocument();
      expect(dayTrigger).toHaveFocus();
    });
    act(() => overflowTrigger.focus());
    expect(overflowTrigger).toHaveFocus();
    await user.keyboard("{Enter}");
    const overflowDialog = screen.getByRole("dialog", { name: `More events on ${today}` });
    expect(within(overflowDialog).getAllByRole("link")).toHaveLength(5);
    expect(within(overflowDialog).getAllByRole("link").map(link => link.getAttribute("data-testid")))
      .toEqual(events.slice(3).map(event => `calendar-event-${event.id}`));
    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(overflowDialog).not.toBeInTheDocument();
      expect(overflowTrigger).toHaveFocus();
    });
    await user.keyboard("{Enter}");
    const reopened = screen.getByRole("dialog", { name: `More events on ${today}` });
    expect(within(reopened).getAllByRole("link").map(link => link.getAttribute("data-testid")))
      .toEqual(events.slice(3).map(event => `calendar-event-${event.id}`));
    await user.click(within(reopened).getByRole("button", { name: "Close" }));
    await waitFor(() => {
      expect(reopened).not.toBeInTheDocument();
      expect(overflowTrigger).toHaveFocus();
    });
    await user.click(dayTrigger);
    const allReopened = screen.getByRole("dialog", { name: `Events on ${today}` });
    expect(within(allReopened).getAllByRole("link").map(link => link.getAttribute("data-testid")))
      .toEqual(events.map(event => `calendar-event-${event.id}`));
    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(allReopened).not.toBeInTheDocument();
      expect(dayTrigger).toHaveFocus();
    });
  });

  it("shows canonical court identity in month, week and day without inventing missing data", async () => {
    const today = isoToday();
    fetchCalendarEventsMock.mockResolvedValue({
      range_from: today, range_to: today,
      events: [{
        id: "hearing:court", kind: "hearing", display_type: "hearing",
        occurs_on: today, title: "Next hearing", matter_id: "court-matter",
        matter_code: "COURT-1", matter_title: "Court identity matter",
        court_label: "HC - Allahabad High Court, Lucknow Bench",
        court_identity: "Allahabad High Court, Lucknow Bench, Court 7",
        hearing_time: "10:30:00", timezone: "Asia/Kolkata",
      }],
    });
    const user = userEvent.setup();
    render(withClient(<CalendarPage />));
    const chip = await screen.findByTestId("calendar-event-hearing:court");
    expect(chip).toHaveTextContent("HC - Allahabad High Court, Lucknow Bench");
    expect(chip).toHaveAttribute("title", expect.stringContaining("Court 7"));
    for (const view of ["week", "day"]) {
      await user.click(screen.getByTestId(`calendar-view-${view}`));
      expect(screen.getByTestId("calendar-event-hearing:court"))
        .toHaveTextContent("HC - Allahabad High Court, Lucknow Bench");
    }
    expect(screen.getByTestId("calendar-event-hearing:court"))
      .toHaveTextContent("10:30 Asia/Kolkata");
  });

  it("retains a stored hearing session without inventing an exact time", async () => {
    const today = isoToday();
    fetchCalendarEventsMock.mockResolvedValue({range_from: today, range_to: today, events: [{
      id: "hearing:session", kind: "hearing", display_type: "hearing", occurs_on: today, title: "Session hearing",
      matter_id: "m1", matter_code: "SESSION-1", matter_title: "Session matter",
      hearing_time: null, time_status: "session", session_label: "Afternoon",
      timezone: "Asia/Kolkata",
    }]});
    const user = userEvent.setup();
    render(withClient(<CalendarPage />));
    const chip = await screen.findByTestId("calendar-event-hearing:session");
    expect(chip).toHaveAttribute("title", expect.stringContaining("Afternoon"));
    await user.click(screen.getByTestId("calendar-view-day"));
    expect(screen.getByTestId("calendar-event-hearing:session")).toHaveTextContent("Afternoon");
    expect(screen.getByTestId("calendar-event-hearing:session")).not.toHaveTextContent("00:00");
  });

  // BUG-039 (Hari 2026-05-09): the bulk sync button only renders
  // when the caller has the `calendar:sync` capability AND a
  // connected Outlook account. Click triggers
  // POST /api/calendar/sync/outlook with the same `from`/`to` the
  // events query is using. Result counts surface to the user via the
  // existing outlook-message panel.
  it("renders Sync visible range to Outlook button when connected and posts the visible range", async () => {
    const now = new Date().toISOString();
    const outlookConnection = {
      id: "conn-1",
      company_id: "co-1",
      membership_id: "mem-1",
      provider: "outlook",
      provider_account_id: "acct-1",
      display_email: "qa-bot@caseops.ai",
      status: "connected",
      scopes: ["Calendars.ReadWrite"],
      connected_at: now,
      last_sync_at: null,
      created_at: now,
      updated_at: now,
    };
    fetchCalendarEventsMock.mockResolvedValueOnce({
      range_from: "2026-04-01",
      range_to: "2026-05-31",
      events: [],
    });
    listCalendarConnectionsMock.mockResolvedValueOnce({
      provider: "outlook",
      provider_available: true,
      unavailable_reason: null,
      durable_automation: "blocked_pending_provider_approval",
      connections: [outlookConnection],
    });
    fetchCalendarSyncStatusMock.mockResolvedValueOnce({
      provider_available: true,
      durable_automation: "blocked_pending_provider_approval",
      notification_delivery: "wtd_5_3_foundation_available",
      capabilities: {
        sync_mode: "manual_bounded",
        manual_sync_available: true,
        durable_automation: "blocked_pending_provider_approval",
        notification_delivery: "wtd_5_3_foundation_available",
        email_invitation_candidates: "review_queue_available",
      },
      provider_config: [
        {
          provider: "outlook",
          configured: true,
          missing_config_names: [],
        },
        {
          provider: "google_calendar",
          configured: false,
          missing_config_names: [
            "GOOGLE_CALENDAR_CLIENT_ID",
            "GOOGLE_CALENDAR_CLIENT_SECRET",
            "GOOGLE_CALENDAR_REDIRECT_URI",
          ],
        },
      ],
      conflict_summary: {
        has_conflicts: false,
        candidate_count: 0,
        duplicate_provider_event_count: 0,
        changed_event_candidate_count: 0,
        changed_event_detection: "unsupported_no_provider_snapshot",
      },
      conflict_candidates: [],
      connections: [outlookConnection],
      syncs: [],
    });
    syncOutlookVisibleRangeMock.mockResolvedValueOnce({
      examined: 3,
      created: 2,
      updated: 1,
      failed: 0,
      skipped: 0,
      items: [],
      durable_automation: "blocked_pending_provider_approval",
    });

    const user = userEvent.setup();
    render(withClient(<CalendarPage />));

    const syncButton = await screen.findByTestId("calendar-outlook-sync-range");
    expect(syncButton).toBeEnabled();
    await user.click(syncButton);

    await waitFor(() => expect(syncOutlookVisibleRangeMock).toHaveBeenCalled());
    const args = syncOutlookVisibleRangeMock.mock.calls[0][0];
    expect(args.from).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(args.to).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    // Summary message includes the per-bucket counts.
    expect(
      await screen.findByText(
        /Synced 2 new, 1 updated, 0 failed, 0 skipped \(3 examined\)\./,
      ),
    ).toBeInTheDocument();
  });

  it("hides the Sync visible range to Outlook button when no Outlook account is connected", async () => {
    fetchCalendarEventsMock.mockResolvedValueOnce({
      range_from: "2026-04-01",
      range_to: "2026-05-31",
      events: [],
    });
    // The default beforeEach mock returns connections: []. Wait for
    // the connect-button to appear (proving the connections query
    // resolved) before asserting the sync button is absent.
    render(withClient(<CalendarPage />));
    await screen.findByTestId("calendar-outlook-connect");
    expect(screen.queryByTestId("calendar-outlook-sync-range")).toBeNull();
    expect(syncOutlookVisibleRangeMock).not.toHaveBeenCalled();
  });

  describe("Month navigation clamps the day (ENH-017)", () => {
    it.each([
      ["2026-01-31", "calendar-next-month", "February 2026", "2026-02-28"],
      ["2026-10-31", "calendar-next-month", "November 2026", "2026-11-30"],
      ["2026-03-31", "calendar-prev-month", "February 2026", "2026-02-28"],
    ])("from %s, %s shows %s with date %s", async (start, button, label, date) => {
      fetchCalendarEventsMock.mockImplementation(async ({ from, to }: { from: string; to: string }) => ({
        range_from: from, range_to: to, events: [],
      }));
      window.history.replaceState(null, "", `/app/calendar?view=month&date=${start}`);
      const user = userEvent.setup();
      render(withClient(<CalendarPage />));
      await user.click(await screen.findByTestId(button));
      await waitFor(() => expect(screen.getByTestId("calendar-month-label")).toHaveTextContent(label));
      await waitFor(() => expect(new URLSearchParams(window.location.search).get("date")).toBe(date));
    });
  });

  describe("Year view (ENH-017)", () => {
    const DAY_MS = 86_400_000;
    // Honest mock: the event list refuses more than 92 days, exactly like the API.
    const honestEvents = () =>
      fetchCalendarEventsMock.mockImplementation(async ({ from, to }: { from: string; to: string }) => {
        if ((Date.parse(to) - Date.parse(from)) / DAY_MS > 92) {
          throw new Error("Calendar range is capped at 92 days. Request a narrower window.");
        }
        return { range_from: from, range_to: to, events: [] };
      });
    const summary2026 = {
      range_from: "2026-01-01",
      range_to: "2026-12-31",
      total: 7,
      days: [
        { occurs_on: "2026-09-26", total: 6, by_display_type: { hearing: 5, task_date: 1 } },
        { occurs_on: "2026-03-04", total: 1, by_display_type: { task_date: 1 } },
      ],
    };

    it("opens the Year tab with one bounded summary call and twelve month grids", async () => {
      honestEvents();
      fetchCalendarSummaryMock.mockResolvedValue(summary2026);
      window.history.replaceState(null, "", "/app/calendar?date=2026-05-10");
      const user = userEvent.setup();
      render(withClient(<CalendarPage />));
      await user.click(await screen.findByTestId("calendar-view-year"));

      expect(await screen.findByTestId("calendar-month-label")).toHaveTextContent("2026");
      await waitFor(() => expect(screen.getAllByTestId(/^calendar-year-month-\d{4}-\d{2}$/)).toHaveLength(12));
      expect(fetchCalendarSummaryMock).toHaveBeenCalledTimes(1);
      expect(fetchCalendarSummaryMock).toHaveBeenCalledWith({ from: "2026-01-01", to: "2026-12-31" });
      for (const [args] of fetchCalendarEventsMock.mock.calls) {
        expect((Date.parse(args.to) - Date.parse(args.from)) / DAY_MS).toBeLessThanOrEqual(92);
      }
      expect(new URLSearchParams(window.location.search).get("view")).toBe("year");
      expect(screen.queryByTestId("calendar-load-error")).toBeNull();
    });

    it("restores ?view=year&date= on mount and moves one year with Previous and Next", async () => {
      honestEvents();
      fetchCalendarSummaryMock.mockImplementation(async ({ from, to }: { from: string; to: string }) => ({
        range_from: from, range_to: to, total: 0, days: [],
      }));
      window.history.replaceState(null, "", "/app/calendar?view=year&date=2026-01-15");
      const user = userEvent.setup();
      render(withClient(<CalendarPage />));

      expect(await screen.findByTestId("calendar-month-label")).toHaveTextContent("2026");
      expect(screen.getByTestId("calendar-view-year")).toHaveAttribute("aria-selected", "true");
      expect(await screen.findByTestId("calendar-empty-state")).toHaveTextContent(
        "No open hearings, tasks or deadlines in 2026",
      );
      await user.click(screen.getByTestId("calendar-prev-month"));
      expect(await screen.findByTestId("calendar-month-label")).toHaveTextContent("2025");
      await waitFor(() =>
        expect(fetchCalendarSummaryMock).toHaveBeenLastCalledWith({ from: "2025-01-01", to: "2025-12-31" }),
      );
      expect(new URLSearchParams(window.location.search).get("date")).toBe("2025-01-15");
      await user.click(screen.getByTestId("calendar-next-month"));
      await user.click(screen.getByTestId("calendar-next-month"));
      expect(await screen.findByTestId("calendar-month-label")).toHaveTextContent("2027");
      expect(fetchCalendarEventsMock).not.toHaveBeenCalled();
    });

    it("names each day's counts by type and opens the day in Day view", async () => {
      honestEvents();
      fetchCalendarSummaryMock.mockResolvedValue(summary2026);
      window.history.replaceState(null, "", "/app/calendar?view=year&date=2026-06-01");
      const user = userEvent.setup();
      render(withClient(<CalendarPage />));

      const busy = await screen.findByTestId("calendar-year-day-2026-09-26");
      expect(busy).toHaveAccessibleName(
        "26 Sep 2026: 6 events — 5 hearings, 1 task date. Open in Day view",
      );
      expect(busy).toHaveAttribute("data-total", "6");
      expect(busy).toHaveTextContent("6");
      expect(
        Array.from(busy.querySelectorAll("[data-display-type]")).map((dot) => dot.getAttribute("data-display-type")),
      ).toEqual(["hearing", "task_date"]);
      expect(screen.getByTestId("calendar-year-grid").querySelectorAll('[data-testid^="calendar-year-day-"][tabindex="0"]'))
        .toHaveLength(1);

      await user.click(busy);
      expect(await screen.findByTestId("calendar-month-label")).toHaveTextContent("26 September 2026");
      await waitFor(() => expect(screen.getByTestId("calendar-view-region")).toHaveFocus());
      expect(screen.getByTestId("calendar-view-day")).toHaveAttribute("aria-selected", "true");
      expect(new URLSearchParams(window.location.search).get("view")).toBe("day");
      expect(new URLSearchParams(window.location.search).get("date")).toBe("2026-09-26");
      await waitFor(() =>
        expect(fetchCalendarEventsMock).toHaveBeenCalledWith({ from: "2026-09-26", to: "2026-09-26" }),
      );
    });

    it("opens a month heading in Month view", async () => {
      honestEvents();
      fetchCalendarSummaryMock.mockResolvedValue(summary2026);
      window.history.replaceState(null, "", "/app/calendar?view=year&date=2026-06-01");
      const user = userEvent.setup();
      render(withClient(<CalendarPage />));
      await user.click(await screen.findByRole("button", { name: "Open March 2026 in Month view" }));
      expect(await screen.findByTestId("calendar-month-label")).toHaveTextContent("March 2026");
      expect(screen.getByTestId("calendar-view-month")).toHaveAttribute("aria-selected", "true");
    });

    it("shows a summary failure with Retry and never empty months", async () => {
      honestEvents();
      fetchCalendarSummaryMock.mockRejectedValueOnce(new Error("summary unavailable"));
      fetchCalendarSummaryMock.mockResolvedValueOnce(summary2026);
      window.history.replaceState(null, "", "/app/calendar?view=year&date=2026-06-01");
      const user = userEvent.setup();
      render(withClient(<CalendarPage />));
      const error = await screen.findByTestId("calendar-load-error");
      expect(error).toHaveTextContent("Could not load the 2026 summary");
      expect(screen.queryByTestId("calendar-year-grid")).toBeNull();
      expect(screen.queryByTestId("calendar-empty-state")).toBeNull();
      await user.click(within(error).getByRole("button", { name: /try again/i }));
      expect(await screen.findByTestId("calendar-year-day-2026-09-26")).toHaveAttribute("data-total", "6");
    });

    it("exports per quarter within the 92-day cap and disables range sync with the reason", async () => {
      honestEvents();
      fetchCalendarSummaryMock.mockResolvedValue(summary2026);
      const now = new Date().toISOString();
      const outlook = {
        id: "conn-1", company_id: "co-1", membership_id: "mem-1", provider: "outlook",
        provider_account_id: "acct-1", display_email: "qa-bot@caseops.ai", status: "connected",
        scopes: ["Calendars.ReadWrite"], connected_at: now, last_sync_at: null, created_at: now, updated_at: now,
      };
      listCalendarConnectionsMock.mockResolvedValue({
        provider: "outlook", provider_available: true, unavailable_reason: null,
        durable_automation: "blocked_pending_provider_approval", connections: [outlook],
      });
      const status = await fetchCalendarSyncStatusMock();
      fetchCalendarSyncStatusMock.mockResolvedValue({ ...status, connections: [outlook] });
      window.history.replaceState(null, "", "/app/calendar?view=year&date=2026-06-01");
      render(withClient(<CalendarPage />));

      const quarters = await screen.findByTestId("calendar-ics-quarters");
      const links = within(quarters).getAllByRole("link");
      expect(links.map((link) => link.textContent)).toEqual(["Q1", "Q2", "Q3", "Q4"]);
      for (const link of links) {
        const url = new URL(link.getAttribute("href") ?? "", "http://localhost");
        const days = (Date.parse(url.searchParams.get("to") ?? "") - Date.parse(url.searchParams.get("from") ?? "")) / DAY_MS;
        expect(days).toBeLessThanOrEqual(92);
      }
      expect(links[3]).toHaveAttribute("href", expect.stringContaining("from=2026-10-01&to=2026-12-31"));
      expect(screen.getByTestId("calendar-year-export-note")).toHaveTextContent("limited to 92 days");
      expect(screen.queryByTestId("calendar-ics-download")).toBeNull();
      expect(screen.queryByTestId("calendar-google-ics-download")).toBeNull();
      const sync = await screen.findByTestId("calendar-outlook-sync-range");
      expect(sync).toBeDisabled();
      expect(sync).toHaveAccessibleDescription(
        "Sync covers up to 92 days. Switch to Month, Week or Day to sync that range.",
      );
      expect(syncOutlookVisibleRangeMock).not.toHaveBeenCalled();
    });

    it("reaches any day from one tab stop with the arrow keys and opens it with Enter", async () => {
      honestEvents();
      fetchCalendarSummaryMock.mockResolvedValue({
        range_from: "2030-01-01", range_to: "2030-12-31", total: 1,
        days: [{ occurs_on: "2030-03-04", total: 1, by_display_type: { task_date: 1 } }],
      });
      window.history.replaceState(null, "", "/app/calendar?view=year&date=2030-06-01");
      const user = userEvent.setup();
      render(withClient(<CalendarPage />));
      const busy = await screen.findByTestId("calendar-year-day-2030-03-04");
      // Today is outside 2030, so the single tab stop is the first busy day.
      expect(screen.getByTestId("calendar-year-grid").querySelectorAll('[tabindex="0"][data-testid^="calendar-year-day-"]'))
        .toHaveLength(1);
      screen.getByRole("button", { name: "Open March 2030 in Month view" }).focus();
      await user.tab();
      expect(busy).toHaveFocus();
      await user.keyboard("{ArrowRight}");
      expect(screen.getByTestId("calendar-year-day-2030-03-05")).toHaveFocus();
      await user.keyboard("{ArrowDown}");
      const empty = screen.getByTestId("calendar-year-day-2030-03-12");
      expect(empty).toHaveFocus();
      expect(empty).toHaveAttribute("tabindex", "0");
      expect(busy).toHaveAttribute("tabindex", "-1");
      await user.keyboard("{Enter}");
      await waitFor(() => expect(screen.getByTestId("calendar-month-label")).toHaveTextContent("Tue, 12 March 2030"));
      expect(new URLSearchParams(window.location.search).get("date")).toBe("2030-03-12");
      // An empty day names itself instead of claiming the calendar is empty.
      expect(await screen.findByTestId("calendar-empty-state")).toHaveTextContent(
        "No open hearings, tasks or deadlines on Tue, 12 March 2030",
      );
      expect(screen.getByTestId("calendar-empty-state")).not.toHaveTextContent("calendar yet");
    });

    it("disables Google range sync in Year view with the reason", async () => {
      honestEvents();
      fetchCalendarSummaryMock.mockResolvedValue(summary2026);
      const now = new Date().toISOString();
      const google = {
        id: "google-conn-1", company_id: "co-1", membership_id: "mem-1", provider: "google_calendar",
        provider_account_id: "google-account-1", display_email: "owner@gmail.example", status: "connected",
        scopes: ["https://www.googleapis.com/auth/calendar.events"], connected_at: now, last_sync_at: null,
        created_at: now, updated_at: now,
      };
      const status = await fetchCalendarSyncStatusMock();
      fetchCalendarSyncStatusMock.mockResolvedValue({
        ...status,
        provider_config: status.provider_config.map((config: { provider: string }) =>
          config.provider === "google_calendar" ? { ...config, configured: true, missing_config_names: [] } : config),
        connections: [google],
      });
      window.history.replaceState(null, "", "/app/calendar?view=year&date=2026-06-01");
      render(withClient(<CalendarPage />));
      const sync = await screen.findByTestId("calendar-google-sync-range");
      expect(sync).toBeDisabled();
      expect(sync).toHaveAccessibleDescription(
        "Sync covers up to 92 days. Switch to Month, Week or Day to sync that range.",
      );
      expect(screen.getByTestId("calendar-google-ics-year-note")).toBeInTheDocument();
      expect(syncGoogleCalendarVisibleRangeMock).not.toHaveBeenCalled();
    });

    it("follows a same-page navigation back to the bare calendar URL", async () => {
      honestEvents();
      fetchCalendarSummaryMock.mockResolvedValue(summary2026);
      window.history.replaceState(null, "", "/app/calendar?view=year&date=2026-06-01");
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      const page = () => <QueryClientProvider client={client}><CalendarPage /></QueryClientProvider>;
      const { rerender } = render(page());
      expect(await screen.findByTestId("calendar-year-grid")).toBeInTheDocument();
      // The sidebar's Calendar link: same mounted page, new URL.
      act(() => window.history.replaceState(null, "", "/app/calendar"));
      rerender(page());
      await waitFor(() => expect(screen.getByTestId("calendar-view-month")).toHaveAttribute("aria-selected", "true"));
      const now = new Date();
      expect(screen.getByTestId("calendar-month-label")).toHaveTextContent(
        `${now.toLocaleString("en-US", { month: "long" })} ${now.getFullYear()}`,
      );
    });

    it("lists every display type in the legend", async () => {
      honestEvents();
      render(withClient(<CalendarPage />));
      const legend = await screen.findByTestId("calendar-legend");
      expect(within(legend).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
        "Legal filing deadline", "Hearing or listing", "Internal target", "Renewal date",
        "Task date", "Client-instruction date", "Reminder time", "Other deadline",
      ]);
    });
  });
});
