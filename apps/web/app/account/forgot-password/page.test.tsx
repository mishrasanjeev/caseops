import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  startPasswordResetMock,
  searchParamsGetMock,
  toastSuccess,
  toastError,
} = vi.hoisted(() => ({
  startPasswordResetMock: vi.fn(),
  searchParamsGetMock: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/api/auth", () => ({
  startPasswordReset: startPasswordResetMock,
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: searchParamsGetMock }),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

import { ForgotPasswordForm } from "@/app/account/forgot-password/ForgotPasswordForm";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("ForgotPasswordPage", () => {
  beforeEach(() => {
    startPasswordResetMock.mockReset();
    searchParamsGetMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
    searchParamsGetMock.mockReturnValue(null);
  });

  it("renders the request form", () => {
    render(withClient(<ForgotPasswordForm />));

    expect(
      screen.getByRole("heading", { level: 1, name: /Request a password reset/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Company slug")).toBeInTheDocument();
    expect(screen.getByLabelText("Work email")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Request reset link/i }),
    ).toBeInTheDocument();
    const signInLinks = screen.getAllByRole("link", { name: /Back to sign in/i });
    expect(signInLinks).toHaveLength(2);
    expect(signInLinks[0]).toHaveAttribute("href", "/sign-in");
    expect(signInLinks[1]).toHaveAttribute("href", "/sign-in");
  });

  it("validates bad slug and email before calling the API", async () => {
    const user = userEvent.setup();
    render(withClient(<ForgotPasswordForm />));

    await user.type(screen.getByLabelText("Company slug"), "Bad Slug");
    await user.type(screen.getByLabelText("Work email"), "not-an-email");
    await user.click(screen.getByRole("button", { name: /Request reset link/i }));

    expect(
      await screen.findByText(/Lowercase letters, digits, and hyphens only/i),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/Enter a valid work email/i),
    ).toBeInTheDocument();
    expect(startPasswordResetMock).not.toHaveBeenCalled();
  });

  it("submits startPasswordReset and shows anti-enumeration success copy", async () => {
    const user = userEvent.setup();
    startPasswordResetMock.mockResolvedValue({
      delivered: true,
      debug_token: "local-only-secret-token",
    });

    render(withClient(<ForgotPasswordForm />));
    await user.type(screen.getByLabelText("Company slug"), "aster-legal");
    await user.type(screen.getByLabelText("Work email"), "lawyer@aster.example");
    await user.click(screen.getByRole("button", { name: /Request reset link/i }));

    await waitFor(() => expect(startPasswordResetMock).toHaveBeenCalledTimes(1));
    expect(startPasswordResetMock).toHaveBeenCalledWith({
      companySlug: "aster-legal",
      email: "lawyer@aster.example",
    });
    expect(
      await screen.findByText(
        /If an active CaseOps account exists for this workspace, we'll email a reset link\./i,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("local-only-secret-token")).not.toBeInTheDocument();
    expect(toastSuccess).toHaveBeenCalledWith(
      "If an active CaseOps account exists for this workspace, we'll email a reset link.",
    );
  });

  it("supports resending after a successful request", async () => {
    const user = userEvent.setup();
    startPasswordResetMock.mockResolvedValue({ delivered: true, debug_token: null });

    render(withClient(<ForgotPasswordForm />));
    await user.type(screen.getByLabelText("Company slug"), "aster-legal");
    await user.type(screen.getByLabelText("Work email"), "lawyer@aster.example");
    await user.click(screen.getByRole("button", { name: /Request reset link/i }));
    await waitFor(() => expect(startPasswordResetMock).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole("button", { name: /Resend reset link/i }));
    await waitFor(() => expect(startPasswordResetMock).toHaveBeenCalledTimes(2));
  });

  it("handles API errors with a generic message", async () => {
    const user = userEvent.setup();
    const { ApiError } = await import("@/lib/api/config");
    startPasswordResetMock.mockRejectedValue(
      new ApiError(503, "sendgrid provider unavailable", null),
    );

    render(withClient(<ForgotPasswordForm />));
    await user.type(screen.getByLabelText("Company slug"), "aster-legal");
    await user.type(screen.getByLabelText("Work email"), "lawyer@aster.example");
    await user.click(screen.getByRole("button", { name: /Request reset link/i }));

    expect(
      await screen.findByText(/We could not request a reset link\. Please try again\./i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/sendgrid provider unavailable/i)).not.toBeInTheDocument();
    expect(toastError).toHaveBeenCalledWith(
      "We could not request a reset link. Please try again.",
    );
  });

  it("prefills safe query params", () => {
    searchParamsGetMock.mockImplementation((key: string) => {
      if (key === "company_slug") return "Aster-Legal";
      if (key === "email") return "Lawyer@Aster.Example";
      return null;
    });

    render(withClient(<ForgotPasswordForm />));

    expect(screen.getByLabelText("Company slug")).toHaveValue("aster-legal");
    expect(screen.getByLabelText("Work email")).toHaveValue("lawyer@aster.example");
  });
});
