import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  completeAccountSetupMock,
  storeSessionMock,
  routerReplaceMock,
  searchParamsGetMock,
  toastSuccess,
  toastError,
} = vi.hoisted(() => ({
  completeAccountSetupMock: vi.fn(),
  storeSessionMock: vi.fn(),
  routerReplaceMock: vi.fn(),
  searchParamsGetMock: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/api/auth", () => ({
  completeAccountSetup: completeAccountSetupMock,
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

import { AccountSetupForm as AccountSetupPage } from "@/app/account/setup/AccountSetupForm";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("AccountSetupPage", () => {
  beforeEach(() => {
    completeAccountSetupMock.mockReset();
    storeSessionMock.mockReset();
    routerReplaceMock.mockReset();
    searchParamsGetMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
  });

  it("renders the h1 heading for screen readers", () => {
    searchParamsGetMock.mockReturnValue("any-token");
    render(withClient(<AccountSetupPage />));
    expect(
      screen.getByRole("heading", { level: 1, name: /Set up your CaseOps account/i }),
    ).toBeInTheDocument();
  });

  it("shows actionable missing-token state when ?token is absent", () => {
    searchParamsGetMock.mockReturnValue(null);
    render(withClient(<AccountSetupPage />));

    expect(screen.getByTestId("account-setup-missing-token")).toBeInTheDocument();
    expect(
      screen.getByText(/setup link is missing a token/i),
    ).toBeInTheDocument();
    // The form is hidden; no submit button is present.
    expect(screen.queryByTestId("account-setup-submit")).not.toBeInTheDocument();
    expect(completeAccountSetupMock).not.toHaveBeenCalled();
  });

  it("rejects passwords shorter than 12 chars and mismatched confirms", async () => {
    searchParamsGetMock.mockReturnValue("setup-token-abc");
    const user = userEvent.setup();
    render(withClient(<AccountSetupPage />));

    await user.type(screen.getByTestId("account-setup-password"), "short");
    await user.type(screen.getByTestId("account-setup-confirm"), "different");
    await user.click(screen.getByTestId("account-setup-submit"));

    expect(
      await screen.findByText(/use at least 12 characters/i),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/passwords don't match/i),
    ).toBeInTheDocument();
    // Mutation never fired.
    expect(completeAccountSetupMock).not.toHaveBeenCalled();
  });

  it("calls completeAccountSetup, stores session, and redirects to /app on success", async () => {
    searchParamsGetMock.mockReturnValue("setup-token-abc");
    completeAccountSetupMock.mockResolvedValue({
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
    render(withClient(<AccountSetupPage />));

    await user.type(screen.getByTestId("account-setup-password"), "ValidPass1234!");
    await user.type(screen.getByTestId("account-setup-confirm"), "ValidPass1234!");
    await user.click(screen.getByTestId("account-setup-submit"));

    await waitFor(() => expect(completeAccountSetupMock).toHaveBeenCalledTimes(1));
    expect(completeAccountSetupMock).toHaveBeenCalledWith({
      token: "setup-token-abc",
      password: "ValidPass1234!",
    });
    await waitFor(() => expect(storeSessionMock).toHaveBeenCalledTimes(1));
    expect(routerReplaceMock).toHaveBeenCalledWith("/app");
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("renders the submit-error panel with the backend detail when the token is rejected", async () => {
    searchParamsGetMock.mockReturnValue("dead-token");
    const { ApiError } = await import("@/lib/api/config");
    completeAccountSetupMock.mockRejectedValue(
      new ApiError(400, "Invalid or expired account-setup token.", null),
    );

    const user = userEvent.setup();
    render(withClient(<AccountSetupPage />));

    await user.type(screen.getByTestId("account-setup-password"), "ValidPass1234!");
    await user.type(screen.getByTestId("account-setup-confirm"), "ValidPass1234!");
    await user.click(screen.getByTestId("account-setup-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("account-setup-submit-error")).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/Invalid or expired account-setup token\./i),
    ).toBeInTheDocument();
    expect(toastError).toHaveBeenCalledWith(
      "Invalid or expired account-setup token.",
    );
    expect(storeSessionMock).not.toHaveBeenCalled();
    expect(routerReplaceMock).not.toHaveBeenCalled();
  });
});
