import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { createMatterHearingMock, fetchNotificationPreferencesMock } = vi.hoisted(() => ({
  createMatterHearingMock: vi.fn(),
  fetchNotificationPreferencesMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  createMatterHearing: createMatterHearingMock,
  fetchNotificationPreferences: fetchNotificationPreferencesMock,
}));

import { ScheduleHearingDialog } from "@/components/matters/ScheduleHearingDialog";

function withClient(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function preferences(sms: { enabled: boolean; provider_configured: boolean }) {
  const channel = (enabled: boolean, configured: boolean) => ({
    enabled,
    provider_configured: configured,
    external_delivery_enabled: enabled && configured,
  });
  return {
    tenant: {
      channels: {
        in_app: channel(true, true),
        email: channel(false, false),
        sms: channel(sms.enabled, sms.provider_configured),
        whatsapp: channel(false, false),
      },
    },
  };
}

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Hearing date"), "2026-12-01");
  await user.type(screen.getByLabelText("Forum / bench"), "Delhi High Court");
  await user.type(screen.getByLabelText("Purpose / stage"), "Arguments");
}

describe("ScheduleHearingDialog phone reminders", () => {
  beforeEach(() => {
    createMatterHearingMock.mockReset().mockResolvedValue({});
    fetchNotificationPreferencesMock.mockReset();
  });

  it("offers SMS only when the workspace enabled it and the provider is ready", async () => {
    const user = userEvent.setup();
    fetchNotificationPreferencesMock.mockResolvedValue(
      preferences({ enabled: true, provider_configured: false }),
    );
    render(withClient(<ScheduleHearingDialog matterId="matter-1" />));
    await user.click(screen.getByTestId("schedule-hearing-open"));
    await fillAndSubmit(user);
    expect(screen.queryByText("Text message (SMS)")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("schedule-hearing-submit"));
    expect(createMatterHearingMock).toHaveBeenCalledWith(
      expect.not.objectContaining({ reminder_channels: expect.anything() }),
    );
  });

  it("adds SMS to the reminder channels by default and lets the user skip it", async () => {
    const user = userEvent.setup();
    fetchNotificationPreferencesMock.mockResolvedValue(
      preferences({ enabled: true, provider_configured: true }),
    );
    render(withClient(<ScheduleHearingDialog matterId="matter-1" />));
    await user.click(screen.getByTestId("schedule-hearing-open"));
    await fillAndSubmit(user);
    const sms = await screen.findByRole("checkbox", { name: "Text message (SMS)" });
    expect(sms).toBeChecked();
    await user.click(screen.getByTestId("schedule-hearing-submit"));
    expect(createMatterHearingMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ reminder_channels: ["in_app", "email", "sms"] }),
    );
  });
});
