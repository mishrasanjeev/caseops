import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { transitionMatterStatusMock, toastSuccess, toastError } = vi.hoisted(() => ({
  transitionMatterStatusMock: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  transitionMatterStatus: transitionMatterStatusMock,
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

import { MatterLifecycleDialog } from "@/components/matters/MatterLifecycleDialog";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("MatterLifecycleDialog", () => {
  beforeEach(() => {
    transitionMatterStatusMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
  });

  it("uses status and timestamp preconditions plus a mandatory reason for disposal", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    transitionMatterStatusMock.mockResolvedValue({
      id: "m-1",
      matter_code: "CASE-1",
      title: "Controlled lifecycle",
      status: "disposed",
      created_at: "2026-07-15T08:00:00Z",
      updated_at: "2026-07-15T09:00:00Z",
    });

    render(
      withClient(
        <MatterLifecycleDialog
          matter={{
            id: "m-1",
            matter_code: "CASE-1",
            status: "active",
            updated_at: "2026-07-15T08:30:00Z",
          }}
          onChanged={onChanged}
        />,
      ),
    );

    await user.click(screen.getByTestId("matter-dispose-trigger"));
    expect(screen.getByTestId("matter-lifecycle-confirm")).toBeDisabled();
    await user.type(
      screen.getByTestId("matter-lifecycle-reason"),
      "abcdefghij",
    );
    expect(screen.getByTestId("matter-lifecycle-confirm")).toBeDisabled();
    await user.clear(screen.getByTestId("matter-lifecycle-reason"));
    await user.type(
      screen.getByTestId("matter-lifecycle-reason"),
      "Final order received on 15 July.",
    );
    await user.click(screen.getByTestId("matter-lifecycle-confirm"));

    await waitFor(() => expect(transitionMatterStatusMock).toHaveBeenCalledTimes(1));
    expect(transitionMatterStatusMock).toHaveBeenCalledWith({
      matterId: "m-1",
      to_status: "disposed",
      expected_from_status: "active",
      expected_updated_at: "2026-07-15T08:30:00Z",
      reason: "Final order received on 15 July.",
    });
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("only reopens a disposed matter into Intake and exposes stale-write errors", async () => {
    const user = userEvent.setup();
    transitionMatterStatusMock.mockRejectedValue({
      name: "ApiError",
      status: 409,
      detail: "Matter changed after this page was loaded. Refresh and try again.",
      problemType: null,
      data: null,
    });

    render(
      withClient(
        <MatterLifecycleDialog
          matter={{
            id: "m-2",
            matter_code: "CASE-2",
            status: "disposed",
            updated_at: "2026-07-15T10:00:00Z",
          }}
          onChanged={vi.fn()}
        />,
      ),
    );

    await user.click(screen.getByTestId("matter-reopen-trigger"));
    expect(screen.getByText(/returns this matter to Intake/i)).toBeInTheDocument();
    await user.type(
      screen.getByTestId("matter-lifecycle-reason"),
      "Fresh instructions require restoration.",
    );
    await user.click(screen.getByTestId("matter-lifecycle-confirm"));

    expect(await screen.findByRole("alert")).toHaveTextContent(/changed after/i);
    expect(transitionMatterStatusMock).toHaveBeenCalledWith(
      expect.objectContaining({
        to_status: "intake",
        expected_from_status: "disposed",
      }),
    );
  });
});
