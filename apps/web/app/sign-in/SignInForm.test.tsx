import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// vi.mock factories are hoisted above `const` declarations, so use
// vi.hoisted() to keep the stubs accessible from both the factory and
// the tests below.
const { signInMock, storeSessionMock, toastSuccess, toastError } = vi.hoisted(
  () => ({
    signInMock: vi.fn(),
    storeSessionMock: vi.fn(),
    toastSuccess: vi.fn(),
    toastError: vi.fn(),
  }),
);

vi.mock("@/lib/api/endpoints", () => ({
  signIn: signInMock,
}));

vi.mock("@/lib/session", () => ({
  storeSession: storeSessionMock,
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

import { SignInForm } from "@/app/sign-in/SignInForm";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("SignInForm", () => {
  beforeEach(() => {
    signInMock.mockReset();
    storeSessionMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
  });

  it("renders the h1 page heading for screen readers", () => {
    render(withClient(<SignInForm />));
    expect(
      screen.getByRole("heading", { level: 1, name: /Sign in to your workspace/i }),
    ).toBeInTheDocument();
  });

  it("rejects invalid slug, email, and missing password with announced errors", async () => {
    const user = userEvent.setup();
    render(withClient(<SignInForm />));

    await user.type(screen.getByLabelText("Company slug"), "Not A Slug");
    await user.type(screen.getByLabelText("Work email"), "not-an-email");
    // Password left blank.
    await user.click(screen.getByRole("button", { name: /^Sign in$/ }));

    const slugError = await screen.findByText(
      /Lowercase letters, digits, and hyphens only/i,
    );
    expect(slugError).toHaveAttribute("role", "alert");
    expect(
      await screen.findByText(/Enter a valid work email/i),
    ).toBeInTheDocument();
    expect(await screen.findByText(/Password is required/i)).toBeInTheDocument();

    // aria-invalid and aria-describedby wire-up.
    const slug = screen.getByLabelText("Company slug");
    expect(slug).toHaveAttribute("aria-invalid", "true");
    const describedBy = slug.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    expect(document.getElementById(describedBy as string)).toBe(slugError);

    // The mutation never fired.
    expect(signInMock).not.toHaveBeenCalled();
  });

  it("calls signIn and stores the session on happy-path submit", async () => {
    const user = userEvent.setup();
    signInMock.mockResolvedValue({
      access_token: "t",
      token_type: "bearer",
      user: { id: "u1", full_name: "Asha Legal", email: "asha@ex.com", is_active: true, created_at: "" },
      company: {
        id: "c1",
        name: "Aster",
        slug: "aster",
        company_type: "law_firm",
        tenant_key: "k",
        is_active: true,
        created_at: "",
      },
      membership: { id: "m1", role: "owner", is_active: true, created_at: "" },
    });

    render(withClient(<SignInForm />));
    await user.type(screen.getByLabelText("Company slug"), "aster");
    await user.type(screen.getByLabelText("Work email"), "asha@ex.com");
    await user.type(screen.getByLabelText("Password"), "correcthorse");
    await user.click(screen.getByRole("button", { name: /^Sign in$/ }));

    await waitFor(() => expect(signInMock).toHaveBeenCalledTimes(1));
    expect(signInMock).toHaveBeenCalledWith({
      email: "asha@ex.com",
      password: "correcthorse",
      companySlug: "aster",
    });
    await waitFor(() => expect(storeSessionMock).toHaveBeenCalledTimes(1));
    expect(toastSuccess).toHaveBeenCalled();
  });

  it("surfaces an API error as a toast without storing a session", async () => {
    const user = userEvent.setup();
    const { ApiError } = await import("@/lib/api/config");
    signInMock.mockRejectedValue(new ApiError(401, "Bad credentials", null));

    render(withClient(<SignInForm />));
    await user.type(screen.getByLabelText("Company slug"), "aster");
    await user.type(screen.getByLabelText("Work email"), "asha@ex.com");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: /^Sign in$/ }));

    await waitFor(() => expect(toastError).toHaveBeenCalledWith("Bad credentials"));
    expect(storeSessionMock).not.toHaveBeenCalled();
  });
});
