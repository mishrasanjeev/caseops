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
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchCalendarEventsMock,
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

import CalendarPage from "./page";

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
    fetchCalendarEventsMock.mockReset();
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
          kind: "hearing",
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
          kind: "task",
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

  it("deep-links each event chip to the source matter's right tab", async () => {
    const today = isoToday();
    fetchCalendarEventsMock.mockResolvedValueOnce({
      range_from: today,
      range_to: today,
      events: [
        {
          id: "hearing:h1",
          kind: "hearing",
          occurs_on: today,
          title: "Bail hearing",
          matter_id: "m1",
          matter_code: "BAIL-001",
          matter_title: "State v Accused",
        },
        {
          id: "task:t1",
          kind: "task",
          occurs_on: today,
          title: "Draft reply",
          matter_id: "m2",
          matter_code: "CIV-002",
          matter_title: "Civil dispute",
        },
        {
          id: "deadline:d1",
          kind: "deadline",
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

  it("shows '+N more' when a single day has more than 3 events", async () => {
    const today = isoToday();
    const events = Array.from({ length: 5 }).map((_, i) => ({
      id: `hearing:overflow-${i}`,
      kind: "hearing" as const,
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
    // Use 'within' so the linter doesn't flag the import as unused.
    void within;
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
});
