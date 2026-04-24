import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { sessionMock, mattersMock, logoutMock, routerReplaceMock } = vi.hoisted(
  () => ({
    sessionMock: vi.fn(),
    mattersMock: vi.fn(),
    logoutMock: vi.fn(),
    routerReplaceMock: vi.fn(),
  }),
);

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplaceMock, push: vi.fn() }),
}));

vi.mock("@/lib/api/portal", () => ({
  fetchPortalSession: sessionMock,
  fetchPortalOcMatters: mattersMock,
  logoutPortal: logoutMock,
}));

import PortalOcLandingPage from "@/app/portal/oc/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("PortalOcLandingPage", () => {
  beforeEach(() => {
    sessionMock.mockReset();
    mattersMock.mockReset();
    logoutMock.mockReset();
    routerReplaceMock.mockReset();
  });

  it("lists assigned OC matters with deep links", async () => {
    sessionMock.mockResolvedValue({
      portal_user: {
        id: "p-1",
        company_id: "co-1",
        email: "oc@example.com",
        full_name: "Counsel One",
        role: "outside_counsel",
        last_signed_in_at: null,
      },
      grants: [],
    });
    mattersMock.mockResolvedValue({
      matters: [
        {
          id: "m-1",
          title: "Contract dispute",
          matter_code: "OC-1",
          status: "active",
          practice_area: "commercial",
          forum_level: "high_court",
          court_name: "Bombay High Court",
          next_hearing_on: null,
        },
      ],
    });
    render(withClient(<PortalOcLandingPage />));
    await waitFor(() =>
      expect(screen.getByText(/Welcome, Counsel/i)).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(screen.getByTestId("portal-oc-matter-m-1")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Contract dispute/)).toBeInTheDocument();
  });

  it("renders an empty state when no matters are assigned", async () => {
    sessionMock.mockResolvedValue({
      portal_user: {
        id: "p-1",
        company_id: "co-1",
        email: "oc@example.com",
        full_name: "Counsel One",
        role: "outside_counsel",
        last_signed_in_at: null,
      },
      grants: [],
    });
    mattersMock.mockResolvedValue({ matters: [] });
    render(withClient(<PortalOcLandingPage />));
    await waitFor(() =>
      expect(screen.getByText(/No assigned matters/i)).toBeInTheDocument(),
    );
  });

  it("redirects to sign-in on session error", async () => {
    sessionMock.mockRejectedValue(
      Object.assign(new Error("unauth"), {
        name: "ApiError",
        status: 401,
        detail: "Not signed in.",
      }),
    );
    render(withClient(<PortalOcLandingPage />));
    await waitFor(() =>
      expect(screen.getByText(/Sign in to your portal/i)).toBeInTheDocument(),
    );
  });
});
