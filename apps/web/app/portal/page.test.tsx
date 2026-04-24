import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { sessionMock, logoutMock, replaceMock } = vi.hoisted(() => ({
  sessionMock: vi.fn(),
  logoutMock: vi.fn(),
  replaceMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
}));

vi.mock("@/lib/api/portal", () => ({
  fetchPortalSession: sessionMock,
  logoutPortal: logoutMock,
}));

import PortalLandingPage from "@/app/portal/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("PortalLandingPage", () => {
  beforeEach(() => {
    sessionMock.mockReset();
    logoutMock.mockReset();
    replaceMock.mockReset();
  });

  it("renders signed-in greeting + grants list", async () => {
    sessionMock.mockResolvedValue({
      portal_user: {
        id: "pu-1",
        company_id: "c-1",
        email: "client@firm.example",
        full_name: "Test Client",
        role: "client",
        last_signed_in_at: null,
      },
      grants: [
        {
          id: "g-1",
          matter_id: "matter-abc12345",
          role: "client",
          scope_json: null,
          granted_at: "2026-04-24T00:00:00Z",
          revoked_at: null,
        },
      ],
    });
    render(withClient(<PortalLandingPage />));
    await waitFor(() =>
      expect(screen.getByText(/welcome, test/i)).toBeInTheDocument(),
    );
    expect(screen.getByTestId("portal-grant-g-1")).toBeInTheDocument();
    expect(screen.getByText(/matter matter-a/i)).toBeInTheDocument();
  });

  it("shows the empty state when no grants exist", async () => {
    sessionMock.mockResolvedValue({
      portal_user: {
        id: "pu-2",
        company_id: "c-1",
        email: "lonely@firm.example",
        full_name: "Lonely Client",
        role: "client",
        last_signed_in_at: null,
      },
      grants: [],
    });
    render(withClient(<PortalLandingPage />));
    await waitFor(() =>
      expect(screen.getByText(/no matters yet/i)).toBeInTheDocument(),
    );
  });

  it("logs out and redirects to /portal/sign-in", async () => {
    sessionMock.mockResolvedValue({
      portal_user: {
        id: "pu-3",
        company_id: "c-1",
        email: "x@y.com",
        full_name: "X Y",
        role: "client",
        last_signed_in_at: null,
      },
      grants: [],
    });
    logoutMock.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(withClient(<PortalLandingPage />));
    await waitFor(() => screen.getByTestId("portal-logout"));
    await user.click(screen.getByTestId("portal-logout"));
    await waitFor(() => expect(logoutMock).toHaveBeenCalled());
    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith("/portal/sign-in"),
    );
  });

  it("renders an error state pointing to sign-in when session fetch 401s", async () => {
    sessionMock.mockRejectedValue(
      Object.assign(new Error("unauthorized"), {
        name: "ApiError",
        detail: "Sign in to the portal to continue.",
        status: 401,
      }),
    );
    render(withClient(<PortalLandingPage />));
    await waitFor(() =>
      expect(
        screen.getByText(/sign in to your portal/i),
      ).toBeInTheDocument(),
    );
  });
});
