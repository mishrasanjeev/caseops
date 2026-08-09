import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  createNotificationRuleMock,
  deleteNotificationRuleMock,
  listAdminNotificationsMock,
  listNotificationRulesMock,
  previewNotificationRecoveryMock,
  recoverEmailSuppressionMock,
  recoverNotificationIntentMock,
  testCurrentUserNotificationMock,
  updateNotificationRuleMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  createNotificationRuleMock: vi.fn(),
  deleteNotificationRuleMock: vi.fn(),
  listAdminNotificationsMock: vi.fn(),
  listNotificationRulesMock: vi.fn(),
  previewNotificationRecoveryMock: vi.fn(),
  recoverEmailSuppressionMock: vi.fn(),
  recoverNotificationIntentMock: vi.fn(),
  testCurrentUserNotificationMock: vi.fn(),
  updateNotificationRuleMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  createNotificationRule: createNotificationRuleMock,
  deleteNotificationRule: deleteNotificationRuleMock,
  listAdminNotifications: listAdminNotificationsMock,
  listNotificationRules: listNotificationRulesMock,
  previewNotificationRecovery: previewNotificationRecoveryMock,
  recoverEmailSuppression: recoverEmailSuppressionMock,
  recoverNotificationIntent: recoverNotificationIntentMock,
  testCurrentUserNotification: testCurrentUserNotificationMock,
  updateNotificationRule: updateNotificationRuleMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: useCapabilityMock,
}));

import AdminNotificationsPage from "@/app/app/admin/notifications/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("AdminNotificationsPage", () => {
  beforeEach(() => {
    createNotificationRuleMock.mockReset();
    deleteNotificationRuleMock.mockReset();
    listAdminNotificationsMock.mockReset();
    listNotificationRulesMock.mockReset();
    previewNotificationRecoveryMock.mockReset();
    recoverEmailSuppressionMock.mockReset();
    recoverNotificationIntentMock.mockReset();
    testCurrentUserNotificationMock.mockReset();
    updateNotificationRuleMock.mockReset();
    useCapabilityMock.mockReset();
    listNotificationRulesMock.mockResolvedValue({
      durable_delivery: "wtd_5_3_foundation_available",
      rules: [],
    });
  });

  it("renders access refusal when caller lacks notifications:manage", () => {
    useCapabilityMock.mockReturnValue(false);
    render(withClient(<AdminNotificationsPage />));
    expect(screen.getByText(/Notifications access required/i)).toBeInTheDocument();
    expect(listAdminNotificationsMock).not.toHaveBeenCalled();
    expect(listNotificationRulesMock).not.toHaveBeenCalled();
  });

  it("renders KPI tiles, rule controls, and durable delivery foundation state", async () => {
    useCapabilityMock.mockReturnValue(true);
    listAdminNotificationsMock.mockResolvedValue({
      total_queued: 4,
      total_sent: 12,
      total_delivered: 10,
      total_failed: 2,
      reminders: [],
      intents: [
        {
          id: "intent-1",
          attempts: 1,
          channel: "in_app",
          created_at: "2026-08-05T15:00:00Z",
          critical: false,
          destination: null,
          destination_version: 1,
          event_type: "notification_test",
          fallback_intent_id: null,
          last_error_redacted: null,
          recovery_of_intent_id: null,
          scheduled_for: "2026-08-05T15:00:00Z",
          source_id: "membership-1",
          source_type: "self_test",
          status: "delivered",
          superseded_by_intent_id: null,
          suppression_reason: null,
          updated_at: "2026-08-05T15:00:01Z",
        },
      ],
      suppressions: [],
      metrics: {
        due: 4,
        attempted: 12,
        delivered: 10,
        suppressed: 1,
        bounced: 1,
        failed: 2,
        fallback: 2,
        stale_queue: 0,
        critical_alerts: 1,
      },
    });
    listNotificationRulesMock.mockResolvedValue({
      durable_delivery: "wtd_5_3_foundation_available",
      rules: [
        {
          id: "rule-1",
          company_id: "c1",
          scope_type: "company",
          scope_id: null,
          event_type: "new_order_uploaded",
          channels: ["in_app"],
          offset_minutes: null,
          enabled: true,
          created_by_membership_id: "m1",
          durable_delivery: "wtd_5_3_foundation_available",
          created_at: "2026-05-07T00:00:00Z",
          updated_at: "2026-05-07T00:00:00Z",
        },
      ],
    });
    render(withClient(<AdminNotificationsPage />));
    expect(await screen.findByText("Notification delivery and recovery")).toBeInTheDocument();
    expect(await screen.findByText("Notification rules")).toBeInTheDocument();
    expect(screen.getByText(/Durable foundation available/i)).toBeInTheDocument();
    expect(screen.getByTestId("notification-rule-create")).toBeInTheDocument();
    expect(screen.getByTestId("notification-rule-rule-1")).toBeInTheDocument();
    expect(screen.getByText("Due")).toBeInTheDocument();
    expect(screen.getByText("Attempted")).toBeInTheDocument();
    expect(screen.getByText("Delivered")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("Suppressed")).toBeInTheDocument();
    expect(screen.getByText("Bounced")).toBeInTheDocument();
    expect(screen.getByText("Fallback")).toBeInTheDocument();
    expect(screen.getByText("Critical alerts")).toBeInTheDocument();
    expect(screen.getByTestId("notification-self-test")).toBeInTheDocument();
    expect(screen.getByText("Recent delivery intents")).toBeInTheDocument();
    expect(screen.getByTestId("notification-intent-intent-1")).toHaveTextContent(
      /delivered.*notification test.*in_app.*No external destination/i,
    );
  });

  it("does not call the API while waiting for capability resolution", () => {
    useCapabilityMock.mockReturnValue(false);
    render(withClient(<AdminNotificationsPage />));
    expect(listAdminNotificationsMock).not.toHaveBeenCalled();
    expect(listNotificationRulesMock).not.toHaveBeenCalled();
  });

  it("renders the committed self-test intent before authoritative refetch completes", async () => {
    useCapabilityMock.mockReturnValue(true);
    const initial = {
      total_queued: 0,
      total_sent: 0,
      total_delivered: 0,
      total_failed: 0,
      reminders: [],
      intents: [],
      suppressions: [],
      metrics: {
        due: 0,
        attempted: 0,
        delivered: 0,
        suppressed: 0,
        bounced: 0,
        failed: 0,
        fallback: 0,
        stale_queue: 0,
        critical_alerts: 0,
      },
    };
    listAdminNotificationsMock.mockResolvedValueOnce(initial).mockImplementation(
      () => new Promise(() => undefined),
    );
    testCurrentUserNotificationMock.mockResolvedValue({
      intent: {
        id: "intent-committed",
        attempts: 1,
        channel: "in_app",
        created_at: "2026-08-07T04:22:14Z",
        critical: false,
        destination: null,
        destination_version: 1,
        event_type: "notification_test",
        fallback_intent_id: null,
        last_error_redacted: null,
        recovery_of_intent_id: null,
        scheduled_for: "2026-08-07T04:22:14Z",
        source_id: "membership-1",
        source_type: "self_service_test",
        status: "delivered",
        superseded_by_intent_id: null,
        suppression_reason: null,
        updated_at: "2026-08-07T04:22:15Z",
      },
      message: "In-app test delivered without contacting an external provider.",
    });

    render(withClient(<AdminNotificationsPage />));
    await screen.findByText("No delivery intents");
    const selfTest = screen.getByTestId("notification-self-test");
    await waitFor(() => expect(selfTest).toBeEnabled());
    fireEvent.click(selfTest);

    expect(await screen.findByTestId("notification-intent-intent-committed")).toHaveTextContent(
      /delivered.*notification test.*in_app.*No external destination/i,
    );
    expect(screen.getByText("Delivered").parentElement).toHaveTextContent("1");
  });

  it("waits for the initial intent snapshot before enabling the self-test", async () => {
    useCapabilityMock.mockReturnValue(true);
    let resolveInitial: ((value: unknown) => void) | undefined;
    listAdminNotificationsMock.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveInitial = resolve;
        }),
    );

    render(withClient(<AdminNotificationsPage />));

    const selfTest = screen.getByTestId("notification-self-test");
    expect(selfTest).toBeDisabled();
    fireEvent.click(selfTest);
    expect(testCurrentUserNotificationMock).not.toHaveBeenCalled();

    resolveInitial?.({
      total_queued: 0,
      total_sent: 0,
      total_delivered: 0,
      total_failed: 0,
      reminders: [],
      intents: [],
      suppressions: [],
      metrics: {
        due: 0,
        attempted: 0,
        delivered: 0,
        suppressed: 0,
        bounced: 0,
        failed: 0,
        fallback: 0,
        stale_queue: 0,
        critical_alerts: 0,
      },
    });

    expect(await screen.findByText("No delivery intents")).toBeInTheDocument();
    await waitFor(() => expect(selfTest).toBeEnabled());
  });
});
