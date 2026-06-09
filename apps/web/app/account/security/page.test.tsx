import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  completeMfaStepUpMock,
  disableMfaMock,
  fetchAccountSecurityMock,
  regenerateMfaRecoveryCodesMock,
  startMfaEnrollmentMock,
  verifyMfaEnrollmentMock,
} = vi.hoisted(() => ({
  completeMfaStepUpMock: vi.fn(),
  disableMfaMock: vi.fn(),
  fetchAccountSecurityMock: vi.fn(),
  regenerateMfaRecoveryCodesMock: vi.fn(),
  startMfaEnrollmentMock: vi.fn(),
  verifyMfaEnrollmentMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  completeMfaStepUp: completeMfaStepUpMock,
  disableMfa: disableMfaMock,
  fetchAccountSecurity: fetchAccountSecurityMock,
  regenerateMfaRecoveryCodes: regenerateMfaRecoveryCodesMock,
  startMfaEnrollment: startMfaEnrollmentMock,
  verifyMfaEnrollment: verifyMfaEnrollmentMock,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import AccountSecurityPage from "@/app/account/security/page";

function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("AccountSecurityPage", () => {
  beforeEach(() => {
    completeMfaStepUpMock.mockReset();
    disableMfaMock.mockReset();
    fetchAccountSecurityMock.mockReset();
    regenerateMfaRecoveryCodesMock.mockReset();
    startMfaEnrollmentMock.mockReset();
    verifyMfaEnrollmentMock.mockReset();
    fetchAccountSecurityMock.mockResolvedValue({
      mfa_status: "not_enrolled",
      mfa_required: true,
      mfa_enforced_at: "2026-06-16T00:00:00Z",
      grace_period_ends_at: "2026-06-16T00:00:00Z",
      recent_step_up_expires_at: null,
      recovery_codes_remaining: 0,
      platform_admin_required: true,
      tenant_admin_required: false,
      all_users_required: false,
    });
    startMfaEnrollmentMock.mockResolvedValue({
      enrollment_id: "enroll-1",
      secret: "JBSWY3DPEHPK3PXP",
      otpauth_url: "otpauth://totp/CaseOps:owner@example.com",
      qr_svg: "<svg></svg>",
      status: "pending",
    });
    verifyMfaEnrollmentMock.mockResolvedValue({
      status: "enrolled",
      recovery_codes: ["caseops-111111", "caseops-222222"],
    });
    completeMfaStepUpMock.mockResolvedValue({
      status: "verified",
      expires_at: "2026-06-09T00:15:00Z",
    });
    regenerateMfaRecoveryCodesMock.mockResolvedValue({
      recovery_codes: ["caseops-333333"],
    });
    disableMfaMock.mockResolvedValue(undefined);
  });

  it("enrolls MFA, completes step-up, regenerates codes, and disables MFA", async () => {
    const user = userEvent.setup();
    renderWithQuery(<AccountSecurityPage />);

    expect(await screen.findByText("MFA status")).toBeInTheDocument();
    expect(await screen.findByText("not_enrolled")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /start enrollment/i }));
    expect(await screen.findByText("JBSWY3DPEHPK3PXP")).toBeInTheDocument();
    await user.type(screen.getByLabelText("MFA verification code"), "123456");
    await user.click(screen.getByRole("button", { name: /^verify$/i }));
    expect(await screen.findByText("caseops-111111")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Step-up code"), "654321");
    await user.click(screen.getByRole("button", { name: /verify step-up/i }));
    expect(completeMfaStepUpMock.mock.calls[0][0]).toEqual({
      code: "654321",
      purpose: "step_up",
    });

    await user.click(screen.getByRole("button", { name: /regenerate recovery codes/i }));
    expect(await screen.findByText("caseops-333333")).toBeInTheDocument();

    await user.type(screen.getByLabelText("MFA disable code"), "123456");
    await user.click(screen.getByRole("button", { name: /disable mfa/i }));
    await waitFor(() =>
      expect(disableMfaMock.mock.calls[0][0]).toEqual({
        code: "123456",
        reason: "User requested MFA reset",
      }),
    );
  });
});
