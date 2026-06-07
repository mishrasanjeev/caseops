import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  completePasswordResetMock,
  storeSessionMock,
  routerReplaceMock,
  searchParamsGetMock,
  toastSuccess,
  toastError,
} = vi.hoisted(() => ({
  completePasswordResetMock: vi.fn(),
  storeSessionMock: vi.fn(),
  routerReplaceMock: vi.fn(),
  searchParamsGetMock: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/api/auth", () => ({
  completePasswordReset: completePasswordResetMock,
}));

vi.mock("@/lib/session", () => ({
  storeSession: storeSessionMock,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplaceMock, push: vi.fn(), back: vi.fn() }),
  useSearchParams: () => ({ get: searchParamsGetMock }),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

import { ResetPasswordForm as ResetPasswordPage } from "@/app/account/reset-password/ResetPasswordForm";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("ResetPasswordPage", () => {
  beforeEach(() => {
    completePasswordResetMock.mockReset();
    storeSessionMock.mockReset();
    routerReplaceMock.mockReset();
    searchParamsGetMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
  });

  it("renders the h1 heading for screen readers", () => {
    searchParamsGetMock.mockReturnValue("any-token");
    render(withClient(<ResetPasswordPage />));
    expect(
      screen.getByRole("heading", { level: 1, name: /Reset your CaseOps password/i }),
    ).toBeInTheDocument();
  });

  it("shows actionable missing-token state when ?token is absent", () => {
    searchParamsGetMock.mockReturnValue("");
    render(withClient(<ResetPasswordPage />));

    expect(
      screen.getByTestId("reset-password-missing-token"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/password-reset link is missing a token/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Request a new reset link/i }),
    ).toHaveAttribute("href", "/account/forgot-password");
    expect(screen.queryByTestId("reset-password-submit")).not.toBeInTheDocument();
    expect(completePasswordResetMock).not.toHaveBeenCalled();
  });

  it("rejects short passwords and mismatched confirms before calling the API", async () => {
    searchParamsGetMock.mockReturnValue("reset-token-abc");
    const user = userEvent.setup();
    render(withClient(<ResetPasswordPage />));

    await user.type(screen.getByTestId("reset-password-password"), "short");
    await user.type(screen.getByTestId("reset-password-confirm"), "different");
    await user.click(screen.getByTestId("reset-password-submit"));

    expect(
      await screen.findByText(/use at least 12 characters/i),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/passwords don't match/i),
    ).toBeInTheDocument();
    expect(completePasswordResetMock).not.toHaveBeenCalled();
  });

  it("calls completePasswordReset, stores session, and redirects to /app on success", async () => {
    searchParamsGetMock.mockReturnValue("reset-token-abc");
    completePasswordResetMock.mockResolvedValue({
      access_token: "t",
      token_type: "bearer",
      user: {
        id: "u1",
        full_name: "Riya Counsel",
        email: "riya@ex.com",
        is_active: true,
        created_at: "",
      },
      company: {
        id: "c1",
        name: "Aster",
        slug: "aster",
        company_type: "law_firm",
        tenant_key: "k",
        is_active: true,
        created_at: "",
      },
      membership: { id: "m1", role: "member", is_active: true, created_at: "" },
    });

    const user = userEvent.setup();
    render(withClient(<ResetPasswordPage />));

    await user.type(screen.getByTestId("reset-password-password"), "FreshPass4567!");
    await user.type(screen.getByTestId("reset-password-confirm"), "FreshPass4567!");
    await user.click(screen.getByTestId("reset-password-submit"));

    await waitFor(() => expect(completePasswordResetMock).toHaveBeenCalledTimes(1));
    expect(completePasswordResetMock).toHaveBeenCalledWith({
      token: "reset-token-abc",
      password: "FreshPass4567!",
    });
    await waitFor(() => expect(storeSessionMock).toHaveBeenCalledTimes(1));
    expect(routerReplaceMock).toHaveBeenCalledWith("/app");
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("renders the submit-error panel with the backend detail when the token is rejected", async () => {
    searchParamsGetMock.mockReturnValue("dead-token");
    const { ApiError } = await import("@/lib/api/config");
    completePasswordResetMock.mockRejectedValue(
      new ApiError(400, "Invalid or expired password-reset token.", null),
    );

    const user = userEvent.setup();
    render(withClient(<ResetPasswordPage />));

    await user.type(screen.getByTestId("reset-password-password"), "FreshPass4567!");
    await user.type(screen.getByTestId("reset-password-confirm"), "FreshPass4567!");
    await user.click(screen.getByTestId("reset-password-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("reset-password-submit-error")).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/Invalid or expired password-reset token\./i),
    ).toBeInTheDocument();
    expect(toastError).toHaveBeenCalledWith(
      "Invalid or expired password-reset token.",
    );
    expect(
      screen.getByRole("link", { name: /Request a new reset link/i }),
    ).toHaveAttribute("href", "/account/forgot-password");
    expect(storeSessionMock).not.toHaveBeenCalled();
    expect(routerReplaceMock).not.toHaveBeenCalled();
  });
});
