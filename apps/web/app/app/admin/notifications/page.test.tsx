import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  createNotificationRuleMock,
  deleteNotificationRuleMock,
  listAdminNotificationsMock,
  listNotificationRulesMock,
  updateNotificationRuleMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  createNotificationRuleMock: vi.fn(),
  deleteNotificationRuleMock: vi.fn(),
  listAdminNotificationsMock: vi.fn(),
  listNotificationRulesMock: vi.fn(),
  updateNotificationRuleMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  createNotificationRule: createNotificationRuleMock,
  deleteNotificationRule: deleteNotificationRuleMock,
  listAdminNotifications: listAdminNotificationsMock,
  listNotificationRules: listNotificationRulesMock,
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
    expect(await screen.findByText("Hearing reminders")).toBeInTheDocument();
    expect(await screen.findByText("Notification rules")).toBeInTheDocument();
    expect(screen.getByText(/Durable foundation available/i)).toBeInTheDocument();
    expect(screen.getByTestId("notification-rule-create")).toBeInTheDocument();
    expect(screen.getByTestId("notification-rule-rule-1")).toBeInTheDocument();
    expect(screen.getByText("Queued")).toBeInTheDocument();
    expect(screen.getByText("Sent")).toBeInTheDocument();
    expect(screen.getByText("Delivered")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("does not call the API while waiting for capability resolution", () => {
    useCapabilityMock.mockReturnValue(false);
    render(withClient(<AdminNotificationsPage />));
    expect(listAdminNotificationsMock).not.toHaveBeenCalled();
    expect(listNotificationRulesMock).not.toHaveBeenCalled();
  });
});
