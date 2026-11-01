import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  createNotificationRuleMock,
  deleteNotificationRuleMock,
  fetchMatterMock,
  listMattersMock,
  listAdminNotificationsMock,
  listCompanyUsersMock,
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
  fetchMatterMock: vi.fn(),
  listMattersMock: vi.fn(),
  listAdminNotificationsMock: vi.fn(),
  listCompanyUsersMock: vi.fn(),
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
  fetchMatter: fetchMatterMock,
  listMatters: listMattersMock,
  listAdminNotifications: listAdminNotificationsMock,
  listCompanyUsers: listCompanyUsersMock,
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
    listCompanyUsersMock.mockReset().mockResolvedValue({
      company_id: "company-1",
      company_slug: "firm",
      users: [],
    });
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

  describe("B4-ADJ-02 rule scope is chosen by name", () => {
    const quiet = {
      total_queued: 0, total_sent: 0, total_delivered: 0, total_failed: 0, reminders: [], intents: [], suppressions: [],
      metrics: { due: 0, attempted: 0, delivered: 0, suppressed: 0, bounced: 0, failed: 0, fallback: 0, stale_queue: 0, critical_alerts: 0 },
    };
    beforeEach(() => {
      useCapabilityMock.mockReturnValue(true);
      listAdminNotificationsMock.mockResolvedValue(quiet);
      listMattersMock.mockReset().mockResolvedValue({
        matters: [
          { id: "matter-open", matter_code: "LIT-1", title: "Aster v Nova", client_name: "Aster", status: "active" },
          { id: "matter-closed", matter_code: "LIT-2", title: "Closed dispute", client_name: "Aster", status: "closed" },
        ],
        next_cursor: null,
      });
      fetchMatterMock.mockReset().mockResolvedValue({ id: "matter-open", matter_code: "LIT-1", title: "Aster v Nova", client_name: "Aster", status: "active" });
      listCompanyUsersMock.mockResolvedValue({
        company_id: "company-1",
        company_slug: "firm",
        users: [{ membership_id: "member-1", full_name: "Asha Rao", email: "asha@firm.example", role: "member", membership_active: true, user_active: true }],
      });
      createNotificationRuleMock.mockResolvedValue({ id: "rule-new" });
    });

    it("names Matter and colleague rules instead of printing their ids", async () => {
      listNotificationRulesMock.mockResolvedValue({
        durable_delivery: "wtd_5_3_foundation_available",
        rules: [
          { id: "rule-m", company_id: "c1", scope_type: "matter", scope_id: "matter-open", event_type: "hearing_upcoming", channels: ["in_app"], offset_minutes: null, enabled: true, created_by_membership_id: "m1", durable_delivery: "wtd_5_3_foundation_available", created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-01T00:00:00Z" },
          { id: "rule-u", company_id: "c1", scope_type: "user", scope_id: "member-1", event_type: "new_order_uploaded", channels: ["in_app"], offset_minutes: null, enabled: true, created_by_membership_id: "m1", durable_delivery: "wtd_5_3_foundation_available", created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-01T00:00:00Z" },
        ],
      });
      render(withClient(<AdminNotificationsPage />));
      const matterRule = await screen.findByTestId("notification-rule-rule-m");
      await waitFor(() => expect(matterRule).toHaveTextContent("LIT-1 · Aster v Nova · Aster"));
      expect(matterRule).not.toHaveTextContent("matter-open");
      const userRule = screen.getByTestId("notification-rule-rule-u");
      await waitFor(() => expect(userRule).toHaveTextContent("Asha Rao"));
      expect(userRule).not.toHaveTextContent("member-1");
    });

    it("offers a Matter picker for a Matter rule and a colleague picker for a user rule", async () => {
      const user = userEvent.setup();
      render(withClient(<AdminNotificationsPage />));
      const form = await screen.findByTestId("notification-rule-form");
      expect(within(form).queryByPlaceholderText(/id/i)).toBeNull();
      expect(within(form).getByText("Every Matter and colleague in the company.")).toBeVisible();

      await user.click(within(form).getAllByRole("combobox")[0]);
      await user.click(await screen.findByRole("option", { name: "Matter" }));
      const matter = await within(form).findByRole<HTMLSelectElement>("combobox", { name: "Rule Matter" });
      // The create button waits for the Matter; a closed Matter is listed with its reason.
      expect(screen.getByTestId("notification-rule-create")).toBeDisabled();
      await waitFor(() => expect(matter).toBeEnabled());
      expect(Array.from(matter.options).find((option) => option.value === "matter-closed")?.disabled).toBe(true);
      fireEvent.change(matter, { target: { value: "matter-open" } });
      await waitFor(() => expect(screen.getByTestId("notification-rule-create")).toBeEnabled());
      await user.click(screen.getByTestId("notification-rule-create"));
      await waitFor(() => expect(createNotificationRuleMock).toHaveBeenCalled());
      expect(createNotificationRuleMock.mock.calls[0][0]).toMatchObject({ scope_type: "matter", scope_id: "matter-open" });

      await user.click(within(form).getAllByRole("combobox")[0]);
      await user.click(await screen.findByRole("option", { name: "User" }));
      const person = await within(form).findByLabelText<HTMLSelectElement>("Rule colleague");
      await waitFor(() => expect(person).toBeEnabled());
      expect(person).toHaveValue("");
      fireEvent.change(person, { target: { value: "member-1" } });
      await waitFor(() => expect(screen.getByTestId("notification-rule-create")).toBeEnabled());
    });
  });
});
