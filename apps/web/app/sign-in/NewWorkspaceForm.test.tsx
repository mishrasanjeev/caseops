import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { bootstrapCompanyMock, storeSessionMock, toastSuccess, toastError, routerReplace } =
  vi.hoisted(() => ({
    bootstrapCompanyMock: vi.fn(),
    storeSessionMock: vi.fn(),
    toastSuccess: vi.fn(),
    toastError: vi.fn(),
    routerReplace: vi.fn(),
  }));

vi.mock("@/lib/api/auth", () => ({
  bootstrapCompany: bootstrapCompanyMock,
}));

vi.mock("@/lib/session", () => ({
  storeSession: storeSessionMock,
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplace, push: vi.fn(), refresh: vi.fn() }),
}));

import { NewWorkspaceForm } from "@/app/sign-in/NewWorkspaceForm";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

// AQ-002 (2026-04-25): every test in this file types ~60 characters
// across 5 form fields with userEvent. Under v8 coverage, each
// keystroke gets instrumented and the cumulative cost exceeds the
// 5000ms default. The bare run completes in ~1.5 s per test; the
// coverage run sits between 5 s and 8 s on Linux runners. Bumping the
// per-describe timeout to 15 s leaves headroom without papering over
// real flakes.
describe("NewWorkspaceForm", { timeout: 15_000 }, () => {
  beforeEach(() => {
    bootstrapCompanyMock.mockReset();
    storeSessionMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
    routerReplace.mockReset();
  });

  it("rejects a weak password and does not call the API", async () => {
    const user = userEvent.setup();
    render(withClient(<NewWorkspaceForm />));

    await user.type(screen.getByLabelText(/Firm \/ organisation name/i), "Aster Legal");
    await user.type(screen.getByLabelText(/Workspace slug/i), "aster-legal");
    await user.type(screen.getByLabelText(/Your full name/i), "Priya Sharma");
    await user.type(screen.getByLabelText(/Your work email/i), "priya@aster.in");
    await user.type(screen.getByLabelText(/^Password$/i), "weakpass");
    await user.click(screen.getByTestId("new-workspace-submit"));

    expect(await screen.findByText(/At least 12 characters/i)).toBeInTheDocument();
    expect(bootstrapCompanyMock).not.toHaveBeenCalled();
  });

  it("rejects an invalid slug regex", async () => {
    const user = userEvent.setup();
    render(withClient(<NewWorkspaceForm />));

    await user.type(screen.getByLabelText(/Firm \/ organisation name/i), "Aster Legal");
    await user.type(screen.getByLabelText(/Workspace slug/i), "Aster Legal!");
    await user.type(screen.getByLabelText(/Your full name/i), "Priya Sharma");
    await user.type(screen.getByLabelText(/Your work email/i), "priya@aster.in");
    await user.type(screen.getByLabelText(/^Password$/i), "StrongPass!234");
    await user.click(screen.getByTestId("new-workspace-submit"));

    expect(
      await screen.findByText(/Lowercase letters, digits, and hyphens only/i),
    ).toBeInTheDocument();
    expect(bootstrapCompanyMock).not.toHaveBeenCalled();
  });

  it("submits, stores the session, and routes on success", async () => {
    const user = userEvent.setup();
    bootstrapCompanyMock.mockResolvedValue({
      access_token: "t",
      token_type: "bearer",
      user: {
        id: "u1",
        full_name: "Priya Sharma",
        email: "priya@aster.in",
        is_active: true,
        created_at: "",
      },
      company: {
        id: "c1",
        name: "Aster Legal",
        slug: "aster-legal",
        company_type: "law_firm",
        tenant_key: "k",
        is_active: true,
        created_at: "",
      },
      membership: { id: "m1", role: "owner", is_active: true, created_at: "" },
    });

    render(withClient(<NewWorkspaceForm />));
    await user.type(screen.getByLabelText(/Firm \/ organisation name/i), "Aster Legal");
    await user.type(screen.getByLabelText(/Workspace slug/i), "aster-legal");
    await user.type(screen.getByLabelText(/Your full name/i), "Priya Sharma");
    await user.type(screen.getByLabelText(/Your work email/i), "priya@aster.in");
    await user.type(screen.getByLabelText(/^Password$/i), "StrongPass!234");
    await user.click(screen.getByTestId("new-workspace-submit"));

    await waitFor(() => expect(bootstrapCompanyMock).toHaveBeenCalledTimes(1));
    expect(bootstrapCompanyMock).toHaveBeenCalledWith({
      companyName: "Aster Legal",
      companySlug: "aster-legal",
      companyType: "law_firm",
      ownerFullName: "Priya Sharma",
      ownerEmail: "priya@aster.in",
      ownerPassword: "StrongPass!234",
    });
    await waitFor(() => expect(storeSessionMock).toHaveBeenCalledTimes(1));
    expect(toastSuccess).toHaveBeenCalled();
    expect(routerReplace).toHaveBeenCalledWith("/app");
  });

  it("surfaces an API error as a toast", async () => {
    const user = userEvent.setup();
    const { ApiError } = await import("@/lib/api/config");
    bootstrapCompanyMock.mockRejectedValue(
      new ApiError(409, "Workspace slug already exists.", null),
    );

    render(withClient(<NewWorkspaceForm />));
    await user.type(screen.getByLabelText(/Firm \/ organisation name/i), "Aster Legal");
    await user.type(screen.getByLabelText(/Workspace slug/i), "aster-legal");
    await user.type(screen.getByLabelText(/Your full name/i), "Priya Sharma");
    await user.type(screen.getByLabelText(/Your work email/i), "priya@aster.in");
    await user.type(screen.getByLabelText(/^Password$/i), "StrongPass!234");
    await user.click(screen.getByTestId("new-workspace-submit"));

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith("Workspace slug already exists."),
    );
    expect(storeSessionMock).not.toHaveBeenCalled();
    expect(routerReplace).not.toHaveBeenCalled();
  });
});
