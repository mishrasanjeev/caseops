import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  createInboundEmailAliasMock,
  fetchCalendarProviderEventCandidatesMock,
  fetchDriveCandidatesMock,
  fetchInboundEmailAliasesMock,
  fetchInboundEmailEventsMock,
  fetchMailboxImportsMock,
  fetchMicrosoft365TenantConfigurationMock,
  fetchNotificationPreferencesMock,
  importRecentGmailMessagesMock,
  reviewCalendarProviderEventCandidateMock,
  reviewDriveCandidateMock,
  reviewMailboxImportMock,
  syncGoogleDriveCandidatesMock,
  testMicrosoft365TenantConfigurationMock,
  updateInboundEmailAliasMock,
  updateMicrosoft365TenantConfigurationMock,
  updateUserNotificationPreferencesMock,
} = vi.hoisted(() => ({
  createInboundEmailAliasMock: vi.fn(),
  fetchCalendarProviderEventCandidatesMock: vi.fn(),
  fetchDriveCandidatesMock: vi.fn(),
  fetchInboundEmailAliasesMock: vi.fn(),
  fetchInboundEmailEventsMock: vi.fn(),
  fetchMailboxImportsMock: vi.fn(),
  fetchMicrosoft365TenantConfigurationMock: vi.fn(),
  fetchNotificationPreferencesMock: vi.fn(),
  importRecentGmailMessagesMock: vi.fn(),
  reviewCalendarProviderEventCandidateMock: vi.fn(),
  reviewDriveCandidateMock: vi.fn(),
  reviewMailboxImportMock: vi.fn(),
  syncGoogleDriveCandidatesMock: vi.fn(),
  testMicrosoft365TenantConfigurationMock: vi.fn(),
  updateInboundEmailAliasMock: vi.fn(),
  updateMicrosoft365TenantConfigurationMock: vi.fn(),
  updateUserNotificationPreferencesMock: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

vi.mock("@/lib/api/endpoints", () => ({
  createInboundEmailAlias: createInboundEmailAliasMock,
  fetchCalendarProviderEventCandidates: fetchCalendarProviderEventCandidatesMock,
  fetchDriveCandidates: fetchDriveCandidatesMock,
  fetchInboundEmailAliases: fetchInboundEmailAliasesMock,
  fetchInboundEmailEvents: fetchInboundEmailEventsMock,
  fetchMailboxImports: fetchMailboxImportsMock,
  fetchMicrosoft365TenantConfiguration: fetchMicrosoft365TenantConfigurationMock,
  fetchNotificationPreferences: fetchNotificationPreferencesMock,
  importRecentGmailMessages: importRecentGmailMessagesMock,
  reviewCalendarProviderEventCandidate: reviewCalendarProviderEventCandidateMock,
  reviewDriveCandidate: reviewDriveCandidateMock,
  reviewMailboxImport: reviewMailboxImportMock,
  syncGoogleDriveCandidates: syncGoogleDriveCandidatesMock,
  testMicrosoft365TenantConfiguration: testMicrosoft365TenantConfigurationMock,
  updateInboundEmailAlias: updateInboundEmailAliasMock,
  updateMicrosoft365TenantConfiguration: updateMicrosoft365TenantConfigurationMock,
  updateUserNotificationPreferences: updateUserNotificationPreferencesMock,
}));

import CalendarConflictsPage from "@/app/app/calendar/conflicts/page";
import DrivePage from "@/app/app/drive/page";
import MailboxPage from "@/app/app/mailbox/page";
import InboundEmailAdminPage from "@/app/app/admin/inbound-email/page";
import Microsoft365AdminPage from "@/app/app/admin/microsoft365/page";
import NotificationPreferencesPage from "@/app/app/notification-preferences/page";

function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const now = "2026-06-10T00:00:00Z";

describe("connector readiness pages", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchMailboxImportsMock.mockResolvedValue({
      summary: { imported: 0, unmatched: 1, duplicate: 0, failed: 0, attachment_candidates: 1 },
      imports: [
        {
          id: "mail-1",
          company_id: "company-1",
          connection_id: "conn-1",
          provider: "gmail",
          provider_message_id: "gmail-1",
          provider_thread_id: "thread-1",
          history_id: null,
          matter_id: "matter-1",
          sender_email: "client@example.com",
          sender_name: "Client",
          recipient_emails: ["lawyer@example.com"],
          subject: "Demand notice",
          snippet: "Metadata snippet only",
          occurred_at: now,
          labels: ["INBOX"],
          matched_by: "matter_code",
          confidence: 0.9,
          status: "new",
          attachment_count: 1,
          imported_communication_id: null,
          last_error_redacted: null,
          created_at: now,
          updated_at: now,
        },
      ],
    });
    reviewMailboxImportMock.mockResolvedValue({
      import_record: { id: "mail-1", status: "content_import_requested" },
      content_import_queued: true,
    });
    importRecentGmailMessagesMock.mockResolvedValue({
      summary: { imported: 0, unmatched: 0, duplicate: 0, failed: 0, attachment_candidates: 0 },
      imports: [],
    });
    fetchDriveCandidatesMock.mockResolvedValue({
      pending_count: 1,
      candidates: [
        {
          id: "drive-1",
          company_id: "company-1",
          provider: "google_drive",
          provider_file_id: "file-1",
          provider_version: "2026-06-10T00:00:00Z",
          name: "Signed agreement.pdf",
          mime_type: "application/pdf",
          size_bytes: 2048,
          owner_display: "Owner",
          modified_time: now,
          folder_path: "Legal Intake",
          web_url: null,
          suggested_matter_id: "matter-1",
          linked_matter_id: null,
          confidence: 0.8,
          status: "new",
          imported_attachment_id: null,
          provenance: { provider: "google_drive" },
          last_error_redacted: null,
          created_at: now,
          updated_at: now,
        },
      ],
    });
    reviewDriveCandidateMock.mockResolvedValue({
      candidate: { id: "drive-1", status: "linked_metadata" },
      imported_attachment_id: null,
    });
    syncGoogleDriveCandidatesMock.mockResolvedValue({
      provider: "google_drive",
      examined_count: 1,
      created_count: 0,
      duplicate_count: 1,
      candidates: [],
    });
    fetchCalendarProviderEventCandidatesMock.mockResolvedValue({
      pending_count: 1,
      conflict_count: 1,
      candidates: [
        {
          id: "cal-1",
          company_id: "company-1",
          provider: "google_calendar",
          provider_event_id: "event-1",
          i_cal_uid: null,
          title: "Arguments",
          starts_at: now,
          ends_at: null,
          location: "Delhi High Court",
          organizer_display: "Court",
          provider_status: "confirmed",
          suggested_matter_id: "matter-1",
          linked_matter_id: null,
          linked_hearing_id: null,
          confidence: 0.9,
          status: "conflict",
          conflict_reason: "manual_locked_next_hearing_requires_explicit_override",
          provenance: { provider: "google_calendar" },
          sync_history: [],
          reviewed_by_membership_id: null,
          reviewed_at: null,
          last_error_redacted: null,
          created_at: now,
          updated_at: now,
        },
      ],
    });
    reviewCalendarProviderEventCandidateMock.mockResolvedValue({
      candidate: { id: "cal-1", status: "accepted" },
      hearing_id: "hearing-1",
    });
    fetchMicrosoft365TenantConfigurationMock.mockResolvedValue({
      provider: "microsoft_365",
      configured: false,
      enabled: false,
      required_config: [],
      required_approvals: [],
      approved_scopes: [],
      missing_config_names: ["MICROSOFT_365_CLIENT_SECRET"],
      missing_approval_keys: ["admin_consent_approved"],
      mail_enabled: false,
      calendar_enabled: false,
      drive_enabled: false,
      connection_count: 0,
      connected_account_count: 0,
      last_test_status: "not_run",
      last_tested_at: null,
      last_error_redacted: null,
      readiness: "blocked_pending_admin_configuration",
    });
    updateMicrosoft365TenantConfigurationMock.mockResolvedValue({});
    testMicrosoft365TenantConfigurationMock.mockResolvedValue({
      provider: "microsoft_365",
      status: "blocked",
      checks: [],
      readiness: "blocked_pending_admin_configuration",
      tested_at: now,
    });
    fetchInboundEmailAliasesMock.mockResolvedValue({
      aliases: [
        {
          id: "alias-1",
          company_id: "company-1",
          matter_id: null,
          alias_type: "tenant",
          alias_address: "tenant@example.caseops.test",
          status: "disabled",
          allowed_senders: [],
          allowed_domains: [],
          retention_days: 30,
          spam_security_status: "provider_disabled",
          created_at: now,
          updated_at: now,
        },
      ],
    });
    fetchInboundEmailEventsMock.mockResolvedValue({
      pending_count: 1,
      events: [
        {
          id: "event-1",
          company_id: "company-1",
          alias_id: "alias-1",
          matched_matter_id: null,
          linked_matter_id: null,
          communication_id: null,
          provider: "local_safe",
          provider_message_id: "inbound-1",
          from_display: "Client",
          to_addresses: ["tenant@example.caseops.test"],
          cc_addresses: [],
          subject: "Inbound matter email",
          received_at: now,
          snippet: "Metadata only",
          attachment_metadata: [],
          status: "new",
          redacted_failure_reason: null,
          provenance: {},
          created_at: now,
          updated_at: now,
        },
      ],
    });
    createInboundEmailAliasMock.mockResolvedValue({});
    updateInboundEmailAliasMock.mockResolvedValue({});
    fetchNotificationPreferencesMock.mockResolvedValue({
      external_delivery_enabled: false,
      provider_configured: { in_app: true, email: false, sms: false, whatsapp: false },
      tenant: preferenceRecord("tenant", null),
      user: preferenceRecord("user", "membership-1"),
    });
    updateUserNotificationPreferencesMock.mockResolvedValue({});
  });

  it("renders and acts on the mailbox review queue", async () => {
    renderWithQuery(<MailboxPage />);

    expect(await screen.findByText("Demand notice")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Request" }));

    await waitFor(() => {
      expect(reviewMailboxImportMock).toHaveBeenCalledWith({
        importId: "mail-1",
        action: "request_content_import",
        matterId: null,
      });
    });
  });

  it("renders and acts on the Drive review queue", async () => {
    renderWithQuery(<DrivePage />);

    expect(await screen.findByText("Signed agreement.pdf")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Import" }));

    await waitFor(() => {
      expect(reviewDriveCandidateMock).toHaveBeenCalledWith({
        candidateId: "drive-1",
        action: "import_file",
        matterId: null,
      });
    });
  });

  it("renders and reviews calendar conflicts", async () => {
    renderWithQuery(<CalendarConflictsPage />);

    expect(await screen.findByText("Arguments")).toBeInTheDocument();
    expect(
      screen.getByText("manual_locked_next_hearing_requires_explicit_override"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Accept" }));

    await waitFor(() => {
      expect(reviewCalendarProviderEventCandidateMock).toHaveBeenCalledWith({
        candidateId: "cal-1",
        action: "accept",
        matterId: null,
        forceOverwriteLocked: false,
      });
    });
  });

  it("saves Microsoft 365 setup without rendering the secret", async () => {
    renderWithQuery(<Microsoft365AdminPage />);

    expect(await screen.findByText("setup needed")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Client id"), {
      target: { value: "graph-client" },
    });
    fireEvent.change(screen.getByLabelText("Client secret"), {
      target: { value: "graph-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(updateMicrosoft365TenantConfigurationMock).toHaveBeenCalledWith(
        expect.objectContaining({
          clientId: "graph-client",
          clientSecret: "graph-secret",
        }),
      );
    });
    expect(screen.queryByText("graph-secret")).not.toBeInTheDocument();
  });

  it("renders inbound aliases and toggles disabled aliases explicitly", async () => {
    renderWithQuery(<InboundEmailAdminPage />);

    expect(await screen.findByText("tenant@example.caseops.test")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Enable" }));

    await waitFor(() => {
      expect(updateInboundEmailAliasMock).toHaveBeenCalledWith({
        aliasId: "alias-1",
        status: "enabled",
      });
    });
  });

  it("renders notification preferences with external delivery blocked", async () => {
    renderWithQuery(<NotificationPreferencesPage />);

    expect(await screen.findByText("Channels")).toBeInTheDocument();
    expect(screen.getAllByText("external blocked")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(updateUserNotificationPreferencesMock).toHaveBeenCalledWith({
        channels: {},
      });
    });
  });
});

function preferenceRecord(scope: "tenant" | "user", membershipId: string | null) {
  return {
    id: `${scope}-pref-1`,
    company_id: "company-1",
    membership_id: membershipId,
    scope,
    channels: {
      in_app: {
        enabled: true,
        provider_configured: true,
        external_delivery_enabled: true,
      },
      email: {
        enabled: true,
        provider_configured: false,
        external_delivery_enabled: false,
      },
      sms: {
        enabled: false,
        provider_configured: false,
        external_delivery_enabled: false,
      },
      whatsapp: {
        enabled: false,
        provider_configured: false,
        external_delivery_enabled: false,
      },
    },
    event_categories: {
      hearing_updates: true,
      tracked_case_changes: true,
      compliance_deadlines: true,
      billing_credit_warnings: true,
      connector_failures: true,
      document_processing_failures: true,
      provider_operation_failures: true,
    },
    digest_frequency: "immediate",
    quiet_hours: {
      enabled: false,
      start: null,
      end: null,
      timezone: "Asia/Kolkata",
    },
    escalation_rules: [],
    opt_out_categories: [],
    external_delivery_policy: "disabled_until_configured",
    created_at: now,
    updated_at: now,
  };
}
