import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// vi.mock factories are hoisted above `const` declarations, so use
// vi.hoisted() to keep the stubs accessible from both the factory and
// the tests below.
const {
  signInMock,
  completeMfaLoginChallengeMock,
  storeSessionMock,
  toastSuccess,
  toastError,
  routerReplaceMock,
  searchParamsGetMock,
} = vi.hoisted(
  () => ({
    signInMock: vi.fn(),
    completeMfaLoginChallengeMock: vi.fn(),
    storeSessionMock: vi.fn(),
    toastSuccess: vi.fn(),
    toastError: vi.fn(),
    routerReplaceMock: vi.fn(),
    searchParamsGetMock: vi.fn(),
  }),
);

vi.mock("@/lib/api/auth", () => ({
  signIn: signInMock,
  completeMfaLoginChallenge: completeMfaLoginChallengeMock,
}));

vi.mock("@/lib/session", () => ({
  storeSession: storeSessionMock,
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplaceMock }),
  useSearchParams: () => ({ get: searchParamsGetMock }),
}));

import { SignInForm } from "@/app/sign-in/SignInForm";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function buildSession(overrides: Record<string, unknown> = {}) {
  return {
    access_token: "t",
    token_type: "bearer",
    user: {
      id: "u1",
      full_name: "Asha Legal",
      email: "asha@ex.com",
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
    membership: {
      id: "m1",
      role: "owner",
      is_active: true,
      created_at: "",
    },
    mfa_required: false,
    mfa_challenge_required: false,
    mfa_enrollment_required: false,
    ...overrides,
  };
}

describe("SignInForm", () => {
  beforeEach(() => {
    signInMock.mockReset();
    completeMfaLoginChallengeMock.mockReset();
    storeSessionMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
    routerReplaceMock.mockReset();
    searchParamsGetMock.mockReset();
    searchParamsGetMock.mockReturnValue(null);
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
    searchParamsGetMock.mockImplementation((key: string) =>
      key === "next" ? "/app/matters?status=open#recent" : null,
    );
    signInMock.mockResolvedValue(buildSession());

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
    expect(routerReplaceMock).toHaveBeenCalledWith(
      "/app/matters?status=open#recent",
    );
  });

  it.each([
    ["absolute URL", "https://attacker.example/phish"],
    ["protocol-relative URL", "//attacker.example/phish"],
    ["script URL", "javascript:alert(document.domain)"],
    ["backslash authority", "/\\attacker.example/phish"],
    ["non-workspace path", "/admin/users"],
  ])("rejects a malicious %s after password login", async (_label, next) => {
    const user = userEvent.setup();
    searchParamsGetMock.mockImplementation((key: string) =>
      key === "next" ? next : null,
    );
    signInMock.mockResolvedValue(buildSession());

    render(withClient(<SignInForm />));
    await user.type(screen.getByLabelText("Company slug"), "aster");
    await user.type(screen.getByLabelText("Work email"), "asha@ex.com");
    await user.type(screen.getByLabelText("Password"), "correcthorse");
    await user.click(screen.getByRole("button", { name: /^Sign in$/ }));

    await waitFor(() =>
      expect(routerReplaceMock).toHaveBeenCalledWith("/app"),
    );
  });

  it("requires MFA code before storing a policy-challenged session", async () => {
    const user = userEvent.setup();
    searchParamsGetMock.mockImplementation((key: string) =>
      key === "next" ? "///attacker.example/phish" : null,
    );
    signInMock.mockResolvedValue(buildSession({
      mfa_required: true,
      mfa_challenge_required: true,
      mfa_challenge_reason: "Complete MFA step-up before workspace access.",
    }));
    completeMfaLoginChallengeMock.mockResolvedValue({
      status: "verified",
      expires_at: "2026-06-13T12:00:00Z",
    });

    render(withClient(<SignInForm />));
    await user.type(screen.getByLabelText("Company slug"), "aster");
    await user.type(screen.getByLabelText("Work email"), "asha@ex.com");
    await user.type(screen.getByLabelText("Password"), "correcthorse");
    await user.click(screen.getByRole("button", { name: /^Sign in$/ }));

    expect(await screen.findByRole("form", { name: /MFA challenge/i })).toBeInTheDocument();
    expect(storeSessionMock).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText("MFA code"), "123456");
    await user.click(screen.getByRole("button", { name: /Verify MFA/i }));

    await waitFor(() =>
      expect(completeMfaLoginChallengeMock).toHaveBeenCalledWith({ code: "123456" }),
    );
    await waitFor(() => expect(storeSessionMock).toHaveBeenCalledTimes(1));
    expect(routerReplaceMock).toHaveBeenCalledWith("/app");
  });

  it("shows a forgot-password link and preserves typed slug and email", async () => {
    const user = userEvent.setup();
    render(withClient(<SignInForm />));

    const link = screen.getByRole("link", { name: /Forgot password\?/i });
    expect(link).toHaveAttribute("href", "/account/forgot-password");

    await user.type(screen.getByLabelText("Company slug"), "Aster-Legal");
    await user.type(screen.getByLabelText("Work email"), "Lawyer@Aster.Example");

    expect(link).toHaveAttribute(
      "href",
      "/account/forgot-password?company_slug=aster-legal&email=lawyer%40aster.example",
    );
  });

  it("switches to the New workspace tab and shows the bootstrap form", async () => {
    const user = userEvent.setup();
    render(withClient(<SignInForm />));

    // The sign-in tab is active by default; switching tabs should surface
    // the bootstrap fields which don't exist in the sign-in form.
    await user.click(screen.getByRole("tab", { name: /New workspace/i }));

    expect(
      await screen.findByRole("heading", { level: 1, name: /Create your CaseOps workspace/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/Firm \/ organisation name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Your full name/i)).toBeInTheDocument();
    expect(screen.getByTestId("new-workspace-submit")).toBeInTheDocument();
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
