import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listAdminNotificationsMock, useCapabilityMock } = vi.hoisted(() => ({
  listAdminNotificationsMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listAdminNotifications: listAdminNotificationsMock,
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
    listAdminNotificationsMock.mockReset();
    useCapabilityMock.mockReset();
  });

  it("renders admin-only refusal when caller lacks workspace:admin", () => {
    useCapabilityMock.mockReturnValue(false);
    render(withClient(<AdminNotificationsPage />));
    expect(screen.getByText(/Admin access required/i)).toBeInTheDocument();
    expect(listAdminNotificationsMock).not.toHaveBeenCalled();
  });

  it("renders KPI tiles + status filter when caller is admin", async () => {
    useCapabilityMock.mockReturnValue(true);
    listAdminNotificationsMock.mockResolvedValue({
      total_queued: 4,
      total_sent: 12,
      total_delivered: 10,
      total_failed: 2,
      reminders: [],
    });
    render(withClient(<AdminNotificationsPage />));
    expect(await screen.findByText("Hearing reminders")).toBeInTheDocument();
    expect(screen.getByText("Queued")).toBeInTheDocument();
    expect(screen.getByText("Sent")).toBeInTheDocument();
    expect(screen.getByText("Delivered")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("does not call the API while waiting for capability resolution", () => {
    useCapabilityMock.mockReturnValue(false);
    render(withClient(<AdminNotificationsPage />));
    expect(listAdminNotificationsMock).not.toHaveBeenCalled();
  });
});
