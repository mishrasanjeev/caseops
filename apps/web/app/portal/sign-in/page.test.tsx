import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { requestMagicLinkMock } = vi.hoisted(() => ({
  requestMagicLinkMock: vi.fn(),
}));

vi.mock("@/lib/api/portal", () => ({
  requestPortalMagicLink: requestMagicLinkMock,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import PortalSignInPage from "@/app/portal/sign-in/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("PortalSignInPage", () => {
  beforeEach(() => {
    requestMagicLinkMock.mockReset();
  });

  it("requests a magic link with normalised slug + email", async () => {
    requestMagicLinkMock.mockResolvedValue({
      delivered: true,
      debug_token: null,
    });
    const user = userEvent.setup();
    render(withClient(<PortalSignInPage />));
    await user.type(
      screen.getByLabelText(/workspace handle/i),
      "Aster-LegaL",
    );
    await user.type(
      screen.getByLabelText(/email/i),
      "Client@Example.com",
    );
    await user.click(screen.getByTestId("portal-signin-submit"));
    await waitFor(() => {
      expect(requestMagicLinkMock).toHaveBeenCalledWith({
        companySlug: "aster-legal",
        email: "client@example.com",
      });
    });
    // The post-success "if registered, link sent" panel is visible.
    expect(
      screen.getByText(/if the email is registered/i),
    ).toBeInTheDocument();
  });

  it("rejects empty workspace + email before calling the API", async () => {
    requestMagicLinkMock.mockResolvedValue({
      delivered: true,
      debug_token: null,
    });
    const user = userEvent.setup();
    render(withClient(<PortalSignInPage />));
    await user.click(screen.getByTestId("portal-signin-submit"));
    expect(requestMagicLinkMock).not.toHaveBeenCalled();
  });
});
