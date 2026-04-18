import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { createTimeEntryMock, toastSuccess, toastError } = vi.hoisted(() => ({
  createTimeEntryMock: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  createMatterTimeEntry: createTimeEntryMock,
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

import { NewTimeEntryDialog } from "@/components/app/NewTimeEntryDialog";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("NewTimeEntryDialog", () => {
  beforeEach(() => {
    createTimeEntryMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
  });

  it("rejects invalid duration and empty description", async () => {
    const user = userEvent.setup();
    render(withClient(<NewTimeEntryDialog matterId="m1" />));
    await user.click(screen.getByTestId("new-time-entry-trigger"));
    const duration = await screen.findByLabelText(/Duration \(minutes\)/i);
    await user.clear(duration);
    await user.type(duration, "2000");
    await user.click(screen.getByTestId("new-time-entry-submit"));
    expect(await screen.findByText(/Can't exceed 24h/i)).toBeInTheDocument();
    expect(createTimeEntryMock).not.toHaveBeenCalled();
  });

  it("submits with INR rate converted to minor units", async () => {
    const user = userEvent.setup();
    createTimeEntryMock.mockResolvedValue({ id: "t1" });

    render(withClient(<NewTimeEntryDialog matterId="m1" />));
    await user.click(screen.getByTestId("new-time-entry-trigger"));
    await user.type(
      screen.getByLabelText(/What did you work on/i),
      "Drafted reply brief",
    );
    const duration = screen.getByLabelText(/Duration \(minutes\)/i);
    await user.clear(duration);
    await user.type(duration, "90");
    await user.type(screen.getByLabelText(/Hourly rate/i), "8500");
    await user.click(screen.getByTestId("new-time-entry-submit"));

    await waitFor(() => expect(createTimeEntryMock).toHaveBeenCalledTimes(1));
    const call = createTimeEntryMock.mock.calls[0][0];
    expect(call.matterId).toBe("m1");
    expect(call.description).toBe("Drafted reply brief");
    expect(call.durationMinutes).toBe(90);
    expect(call.billable).toBe(true);
    expect(call.rateCurrency).toBe("INR");
    expect(call.rateAmountMinor).toBe(850_000);
  });
});
