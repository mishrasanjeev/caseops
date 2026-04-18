import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { createMock, toastSuccess, toastError, routerPush } = vi.hoisted(() => ({
  createMock: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  routerPush: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  createContract: createMock,
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush, replace: vi.fn(), refresh: vi.fn() }),
}));

import { NewContractDialog } from "@/components/app/NewContractDialog";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("NewContractDialog", () => {
  beforeEach(() => {
    createMock.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
    routerPush.mockReset();
  });

  it("uppercases the contract code and pushes to the detail page on success", async () => {
    const user = userEvent.setup();
    createMock.mockResolvedValue({ id: "c-123" });

    render(withClient(<NewContractDialog />));
    await user.click(screen.getByTestId("new-contract-trigger"));
    await user.type(screen.getByLabelText(/Title/i), "MSA with Acme India");
    await user.clear(screen.getByLabelText(/Code/i));
    await user.type(screen.getByLabelText(/Code/i), "c-acme-001");
    await user.type(screen.getByLabelText(/Counterparty/i), "Acme India Pvt Ltd");
    await user.click(screen.getByTestId("new-contract-submit"));

    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    const call = createMock.mock.calls[0][0];
    expect(call.contractCode).toBe("C-ACME-001");
    expect(call.title).toBe("MSA with Acme India");
    expect(call.counterpartyName).toBe("Acme India Pvt Ltd");
    await waitFor(() => expect(routerPush).toHaveBeenCalledWith("/app/contracts/c-123"));
  });

  it("rejects a bad contract code and does not call the API", async () => {
    const user = userEvent.setup();
    render(withClient(<NewContractDialog />));
    await user.click(screen.getByTestId("new-contract-trigger"));
    await user.type(screen.getByLabelText(/Title/i), "Title here");
    await user.clear(screen.getByLabelText(/Code/i));
    await user.type(screen.getByLabelText(/Code/i), "NOT OK WITH SPACES!");
    await user.click(screen.getByTestId("new-contract-submit"));

    expect(
      await screen.findByText(/Letters, digits, hyphen/i),
    ).toBeInTheDocument();
    expect(createMock).not.toHaveBeenCalled();
  });
});
