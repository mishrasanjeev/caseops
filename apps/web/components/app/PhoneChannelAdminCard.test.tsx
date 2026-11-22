import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchAdminPhoneChannelsMock, updateTenantNotificationPreferencesMock } = vi.hoisted(
  () => ({
    fetchAdminPhoneChannelsMock: vi.fn(),
    updateTenantNotificationPreferencesMock: vi.fn(),
  }),
);

vi.mock("@/lib/api/endpoints", () => ({
  fetchAdminPhoneChannels: fetchAdminPhoneChannelsMock,
  updateTenantNotificationPreferences: updateTenantNotificationPreferencesMock,
}));

import { PhoneChannelAdminCard } from "@/components/app/PhoneChannelAdminCard";

function withClient(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function row(channel: "sms" | "whatsapp", overrides: Record<string, unknown> = {}) {
  return {
    channel,
    provider: channel === "sms" ? "msg91" : "meta-whatsapp",
    tenant_enabled: false,
    provider_ready: true,
    kill_switch_active: false,
    transport: "live",
    missing_configuration: [],
    not_ready_reason: null,
    opted_in_members: 0,
    ...overrides,
  };
}

describe("PhoneChannelAdminCard", () => {
  beforeEach(() => {
    fetchAdminPhoneChannelsMock.mockReset();
    updateTenantNotificationPreferencesMock.mockReset().mockResolvedValue({});
  });

  it("shows readiness, missing configuration and opted-in counts", async () => {
    fetchAdminPhoneChannelsMock.mockResolvedValue({
      channels: {
        sms: row("sms", { tenant_enabled: true, opted_in_members: 3 }),
        whatsapp: row("whatsapp", {
          provider_ready: false,
          not_ready_reason: "provider_incomplete",
          missing_configuration: ["CASEOPS_WHATSAPP_ACCESS_TOKEN"],
        }),
      },
    });
    render(withClient(<PhoneChannelAdminCard />));
    const sms = await screen.findByTestId("phone-admin-sms");
    expect(within(sms).getByText("Ready")).toBeInTheDocument();
    expect(within(sms).getByText("Enabled")).toBeInTheDocument();
    expect(within(sms).getByText("3")).toBeInTheDocument();
    const whatsapp = screen.getByTestId("phone-admin-whatsapp");
    expect(within(whatsapp).getByText("Not ready")).toBeInTheDocument();
    expect(within(whatsapp).getByText("The provider is missing configuration.")).toBeInTheDocument();
    expect(within(whatsapp).getByText(/CASEOPS_WHATSAPP_ACCESS_TOKEN/)).toBeInTheDocument();
  });

  it("enables and disables a channel for the workspace", async () => {
    const user = userEvent.setup();
    fetchAdminPhoneChannelsMock.mockResolvedValue({
      channels: { sms: row("sms", { tenant_enabled: true }), whatsapp: row("whatsapp") },
    });
    render(withClient(<PhoneChannelAdminCard />));
    await user.click(
      within(await screen.findByTestId("phone-admin-whatsapp")).getByRole("button", {
        name: "Enable",
      }),
    );
    expect(updateTenantNotificationPreferencesMock).toHaveBeenCalledWith({
      channels: { whatsapp: true },
    });
    await user.click(
      within(screen.getByTestId("phone-admin-sms")).getByRole("button", { name: "Disable" }),
    );
    expect(updateTenantNotificationPreferencesMock).toHaveBeenCalledWith({
      channels: { sms: false },
    });
  });

  it("names the kill switch when it pauses every channel", async () => {
    fetchAdminPhoneChannelsMock.mockResolvedValue({
      channels: {
        sms: row("sms", { provider_ready: false, kill_switch_active: true, not_ready_reason: "kill_switch_active" }),
        whatsapp: row("whatsapp", { provider_ready: false, kill_switch_active: true, not_ready_reason: "kill_switch_active" }),
      },
    });
    render(withClient(<PhoneChannelAdminCard />));
    expect(
      await screen.findAllByText("Paused platform-wide by the CaseOps kill switch."),
    ).toHaveLength(2);
  });
});
