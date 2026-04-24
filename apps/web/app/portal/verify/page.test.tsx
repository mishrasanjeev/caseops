import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { verifyMock, replaceMock, searchParamsMock } = vi.hoisted(() => ({
  verifyMock: vi.fn(),
  replaceMock: vi.fn(),
  searchParamsMock: { get: vi.fn() },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
  useSearchParams: () => searchParamsMock,
}));

vi.mock("@/lib/api/portal", () => ({
  verifyPortalMagicLink: verifyMock,
}));

import PortalVerifyPage from "@/app/portal/verify/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("PortalVerifyPage", () => {
  beforeEach(() => {
    verifyMock.mockReset();
    replaceMock.mockReset();
    searchParamsMock.get.mockReset();
  });

  it("redirects to /portal on successful verify", async () => {
    searchParamsMock.get.mockReturnValue("good-token");
    verifyMock.mockResolvedValue({
      portal_user: {
        id: "pu-1",
        company_id: "c-1",
        email: "x@x",
        full_name: "X",
        role: "client",
        last_signed_in_at: null,
      },
      grants: [],
    });
    render(withClient(<PortalVerifyPage />));
    await waitFor(() => expect(verifyMock).toHaveBeenCalledWith("good-token"));
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/portal"));
  });

  it("shows the no-token message when ?token is absent", async () => {
    searchParamsMock.get.mockReturnValue("");
    render(withClient(<PortalVerifyPage />));
    await waitFor(() =>
      expect(screen.getByText(/no token in url/i)).toBeInTheDocument(),
    );
    expect(verifyMock).not.toHaveBeenCalled();
  });

  it("surfaces an actionable error + retry button when verify fails", async () => {
    searchParamsMock.get.mockReturnValue("bad-token");
    verifyMock.mockRejectedValue(
      Object.assign(new Error("expired"), {
        name: "ApiError",
        detail: "This link is invalid or expired.",
        status: 400,
      }),
    );
    render(withClient(<PortalVerifyPage />));
    await waitFor(() =>
      expect(screen.getByTestId("portal-verify-retry")).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/this link is invalid or expired/i),
    ).toBeInTheDocument();
  });
});
