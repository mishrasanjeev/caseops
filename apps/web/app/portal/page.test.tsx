import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { sessionMock, logoutMock, replaceMock, mattersMock, ipRecordsMock, publicationsMock } = vi.hoisted(
  () => ({
    sessionMock: vi.fn(),
    logoutMock: vi.fn(),
    replaceMock: vi.fn(),
    mattersMock: vi.fn(),
    ipRecordsMock: vi.fn(),
    publicationsMock: vi.fn(),
  }),
);

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
}));

vi.mock("@/lib/api/portal", () => ({
  fetchPortalSession: sessionMock,
  logoutPortal: logoutMock,
  fetchPortalMatters: mattersMock,
  fetchPortalIpRecords: ipRecordsMock,
  fetchPortalPublications: publicationsMock,
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
    mattersMock.mockReset();
    ipRecordsMock.mockReset();
    publicationsMock.mockReset();
    mattersMock.mockResolvedValue({ matters: [] });
    ipRecordsMock.mockResolvedValue({ records: [] });
    publicationsMock.mockResolvedValue({ publications: [] });
  });

  it("shows explicitly granted IP records and approved publication state", async () => {
    sessionMock.mockResolvedValue({
      portal_user: { id: "pu-ip", company_id: "c-1", email: "ip@client.example", full_name: "IP Client", role: "client", last_signed_in_at: null },
      grants: [],
    });
    ipRecordsMock.mockResolvedValue({ records: [{ id: "docket-1", title: "ASTER DEVICE", record_type: "trademark", status: "filed", primary_identifier: "TM-421", identifiers: ["TM-421", "OPP-88"], events: [], upcoming_dates: [], grant_expires_at: null }] });
    publicationsMock.mockResolvedValue({ publications: [{ id: "pub-1", publication_kind: "report", title: "Opposition status", status: "published", access_state: "available", delivery_status: "delivered", targets: [] }] });
    render(withClient(<PortalLandingPage />));
    expect(await screen.findByTestId("portal-ip-docket-1")).toBeInTheDocument();
    expect(screen.getByText("TM-421")).toBeInTheDocument();
    expect(screen.getByText("Opposition status")).toBeInTheDocument();
    expect(screen.getByText("available")).toBeInTheDocument();
  });

  it("renders signed-in greeting + matters list (C-2)", async () => {
    sessionMock.mockResolvedValue({
      portal_user: {
        id: "pu-1",
        company_id: "c-1",
        email: "client@firm.example",
        full_name: "Test Client",
        role: "client",
        last_signed_in_at: null,
      },
      grants: [],
    });
    mattersMock.mockResolvedValue({
      matters: [
        {
          id: "m-1",
          title: "Bail Application — State v Kumar",
          matter_code: "BAIL-001",
          status: "active",
          practice_area: "criminal",
          forum_level: "high_court",
          court_name: "Delhi High Court",
          next_hearing_on: "2026-05-15",
        },
      ],
    });
    render(withClient(<PortalLandingPage />));
    await waitFor(() =>
      expect(screen.getByText(/welcome, test/i)).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(screen.getByTestId("portal-matter-m-1")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Bail Application/)).toBeInTheDocument();
    expect(screen.getByText(/Next hearing/)).toHaveTextContent(/15/);
  });

  it("shows the empty state when no matters exist (C-2)", async () => {
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
    mattersMock.mockResolvedValue({ matters: [] });
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
