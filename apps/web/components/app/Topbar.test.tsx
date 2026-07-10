import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/config";

const {
  routerPushMock,
  routerReplaceMock,
  signOutMock,
  toastErrorMock,
  toastSuccessMock,
} = vi.hoisted(() => ({
  routerPushMock: vi.fn(),
  routerReplaceMock: vi.fn(),
  signOutMock: vi.fn(),
  toastErrorMock: vi.fn(),
  toastSuccessMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/app",
  useRouter: () => ({
    push: routerPushMock,
    replace: routerReplaceMock,
  }),
}));

vi.mock("@/components/app/Sidebar", () => ({
  SidebarBody: () => null,
}));

vi.mock("@/lib/use-session", () => ({
  useSession: () => ({
    context: {
      company: { name: "Aster Legal" },
      user: {
        email: "asha@aster.example",
        full_name: "Asha Legal",
      },
    },
    signOut: signOutMock,
  }),
}));

vi.mock("sonner", () => ({
  toast: {
    error: toastErrorMock,
    success: toastSuccessMock,
  },
}));

import { Topbar } from "./Topbar";

describe("Topbar", () => {
  beforeEach(() => {
    routerPushMock.mockReset();
    routerReplaceMock.mockReset();
    signOutMock.mockReset();
    toastErrorMock.mockReset();
    toastSuccessMock.mockReset();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  it("does not report success when server logout is rejected", async () => {
    const user = userEvent.setup();
    const rejection = Promise.reject(
      new ApiError(
        403,
        "CSRF token did not match.",
        { type: "csrf_failed" },
        "csrf_failed",
      ),
    );
    void rejection.catch(() => undefined);
    signOutMock.mockReturnValue(rejection);

    render(<Topbar />);
    await user.click(
      screen.getByRole("button", { name: "Open user menu" }),
    );
    await user.click(await screen.findByTestId("sign-out"));

    await waitFor(() =>
      expect(toastErrorMock).toHaveBeenCalledWith(
        "CSRF token did not match.",
      ),
    );
    expect(toastSuccessMock).not.toHaveBeenCalled();
    expect(routerReplaceMock).toHaveBeenCalledWith("/sign-in");
  });
});
