import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PhoneContactStatusResponse } from "@/lib/api/schemas";

const {
  confirmPhoneVerificationMock,
  fetchPhoneContactMock,
  removePhoneContactMock,
  setPhoneConsentMock,
  startPhoneVerificationMock,
} = vi.hoisted(() => ({
  confirmPhoneVerificationMock: vi.fn(),
  fetchPhoneContactMock: vi.fn(),
  removePhoneContactMock: vi.fn(),
  setPhoneConsentMock: vi.fn(),
  startPhoneVerificationMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  confirmPhoneVerification: confirmPhoneVerificationMock,
  fetchPhoneContact: fetchPhoneContactMock,
  removePhoneContact: removePhoneContactMock,
  setPhoneConsent: setPhoneConsentMock,
  startPhoneVerification: startPhoneVerificationMock,
}));

import { PhoneChannelPreferences } from "@/components/app/PhoneChannelPreferences";

function withClient(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function channel(
  name: "sms" | "whatsapp",
  overrides: Partial<PhoneContactStatusResponse["channels"]["sms"]> = {},
) {
  return {
    channel: name,
    opted_in: false,
    consent_at: null,
    opted_out_at: null,
    opt_out_source: null,
    tenant_enabled: true,
    provider_ready: true,
    deliverable: false,
    blocked_reason: "phone_not_registered",
    ...overrides,
  };
}

function status(overrides: Partial<PhoneContactStatusResponse> = {}): PhoneContactStatusResponse {
  return {
    phone_masked: null,
    verified: false,
    verified_at: null,
    verification_pending: false,
    verification_channel: null,
    verification_expires_at: null,
    consent_text_version: "2026-11-22",
    channels: { sms: channel("sms"), whatsapp: channel("whatsapp") },
    ...overrides,
  };
}

describe("PhoneChannelPreferences", () => {
  beforeEach(() => {
    confirmPhoneVerificationMock.mockReset();
    fetchPhoneContactMock.mockReset();
    removePhoneContactMock.mockReset();
    setPhoneConsentMock.mockReset();
    startPhoneVerificationMock.mockReset();
  });

  it("explains that the channels are unavailable when the workspace has not enabled them", async () => {
    fetchPhoneContactMock.mockResolvedValue(
      status({
        channels: {
          sms: channel("sms", { tenant_enabled: false, blocked_reason: "workspace_channel_disabled" }),
          whatsapp: channel("whatsapp", { provider_ready: false, blocked_reason: "provider_disabled" }),
        },
      }),
    );
    render(withClient(<PhoneChannelPreferences />));
    expect(await screen.findByText(/not available in this workspace yet/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Mobile number")).not.toBeInTheDocument();
    expect(screen.getByText("A workspace admin has not turned this on.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Turn on/ })).not.toBeInTheDocument();
  });

  it("verifies a number with the code before any channel can be turned on", async () => {
    const user = userEvent.setup();
    fetchPhoneContactMock.mockResolvedValue(status());
    startPhoneVerificationMock.mockResolvedValue(
      status({ phone_masked: "+91 ••••• 5678", verification_pending: true, verification_channel: "sms" }),
    );
    confirmPhoneVerificationMock.mockResolvedValue(
      status({
        phone_masked: "+91 ••••• 5678",
        verified: true,
        channels: {
          sms: channel("sms", { blocked_reason: "phone_consent_missing" }),
          whatsapp: channel("whatsapp", { blocked_reason: "phone_consent_missing" }),
        },
      }),
    );
    render(withClient(<PhoneChannelPreferences />));

    expect(await screen.findByLabelText("Mobile number")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Turn on/ })).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Mobile number"), "98123 45678");
    await user.click(screen.getByRole("radio", { name: "WhatsApp" }));
    await user.click(screen.getByRole("button", { name: "Send code" }));
    expect(startPhoneVerificationMock).toHaveBeenCalledWith({
      phoneNumber: "98123 45678",
      channel: "whatsapp",
    });

    const codeInput = await screen.findByLabelText(/Code sent to/);
    await user.type(codeInput, "12a3456");
    expect(codeInput).toHaveValue("123456");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(confirmPhoneVerificationMock).toHaveBeenCalledWith("123456");
    expect(await screen.findByText("Verified")).toBeInTheDocument();
  });

  it("requires the consent box before opting in and sends the consent version", async () => {
    const user = userEvent.setup();
    const verified = status({
      phone_masked: "+91 ••••• 5678",
      verified: true,
      channels: {
        sms: channel("sms", { blocked_reason: "phone_consent_missing" }),
        whatsapp: channel("whatsapp", { blocked_reason: "phone_consent_missing" }),
      },
    });
    fetchPhoneContactMock.mockResolvedValue(verified);
    setPhoneConsentMock.mockResolvedValue({
      ...verified,
      channels: {
        ...verified.channels,
        sms: channel("sms", { opted_in: true, deliverable: true, blocked_reason: null }),
      },
    });
    render(withClient(<PhoneChannelPreferences />));

    const sms = await screen.findByTestId("phone-channel-sms");
    const turnOn = within(sms).getByRole("button", { name: "Turn on SMS" });
    expect(turnOn).toBeDisabled();
    await user.click(within(sms).getByRole("checkbox"));
    expect(turnOn).toBeEnabled();
    await user.click(turnOn);
    expect(setPhoneConsentMock).toHaveBeenCalledWith({
      channel: "sms",
      optedIn: true,
      consentTextVersion: "2026-11-22",
    });
    await waitFor(() =>
      expect(within(screen.getByTestId("phone-channel-sms")).getByText("On")).toBeInTheDocument(),
    );
  });

  it("lets an opted-in user turn a channel off and shows a STOP opt-out", async () => {
    const user = userEvent.setup();
    const optedIn = status({
      phone_masked: "+91 ••••• 5678",
      verified: true,
      channels: {
        sms: channel("sms", { opted_in: true, deliverable: true, blocked_reason: null }),
        whatsapp: channel("whatsapp", {
          opted_out_at: "2026-11-22T10:00:00Z",
          opt_out_source: "whatsapp_stop_reply",
          blocked_reason: "phone_opted_out",
        }),
      },
    });
    fetchPhoneContactMock.mockResolvedValue(optedIn);
    setPhoneConsentMock.mockResolvedValue(optedIn);
    render(withClient(<PhoneChannelPreferences />));

    const whatsapp = await screen.findByTestId("phone-channel-whatsapp");
    expect(within(whatsapp).getByText("Off. You turned this off.")).toBeInTheDocument();
    await user.click(
      within(screen.getByTestId("phone-channel-sms")).getByRole("button", { name: "Turn off" }),
    );
    expect(setPhoneConsentMock).toHaveBeenCalledWith({
      channel: "sms",
      optedIn: false,
      consentTextVersion: "2026-11-22",
    });
  });
});
