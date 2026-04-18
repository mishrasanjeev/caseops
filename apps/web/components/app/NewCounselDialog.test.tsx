import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { createMock, toastSuccess, toastError } = vi.hoisted(() => ({
  createMock: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  createOutsideCounselProfile: createMock,
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

import { NewCounselDialog } from "@/components/app/NewCounselDialog";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("NewCounselDialog", () => {
  beforeEach(() => {
    createMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
  });

  it("rejects an empty name and does not call the API", async () => {
    const user = userEvent.setup();
    render(withClient(<NewCounselDialog />));
    await user.click(screen.getByTestId("new-counsel-trigger"));
    await user.click(screen.getByTestId("new-counsel-submit"));
    expect(await screen.findByText(/At least 2 characters/i)).toBeInTheDocument();
    expect(createMock).not.toHaveBeenCalled();
  });

  it("submits with CSVs split into arrays and panel_status carried through", async () => {
    const user = userEvent.setup();
    createMock.mockResolvedValue({ id: "c1" });

    render(withClient(<NewCounselDialog />));
    await user.click(screen.getByTestId("new-counsel-trigger"));
    await user.type(
      screen.getByLabelText(/Firm or individual name/i),
      "Khaitan & Co.",
    );
    await user.type(
      screen.getByLabelText(/Jurisdictions/i),
      "Delhi, Bombay, SC",
    );
    await user.type(
      screen.getByLabelText(/Practice areas/i),
      "Arbitration, IP, White-collar",
    );
    await user.click(screen.getByTestId("new-counsel-submit"));

    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    const call = createMock.mock.calls[0][0];
    expect(call.name).toBe("Khaitan & Co.");
    expect(call.jurisdictions).toEqual(["Delhi", "Bombay", "SC"]);
    expect(call.practiceAreas).toEqual(["Arbitration", "IP", "White-collar"]);
    expect(call.panelStatus).toBe("active");
  });
});
