import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listClientsMock, useCapabilityMock } = vi.hoisted(() => ({
  listClientsMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listClients: listClientsMock,
  // NewClientDialog calls these but isn't exercised in the
  // empty/error/list paths under test, so a stub is enough.
  createClient: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: useCapabilityMock,
}));

import ClientsIndexPage from "@/app/app/clients/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("ClientsIndexPage", () => {
  beforeEach(() => {
    listClientsMock.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockReturnValue(true);
  });

  it("renders the Clients header and a card per client", async () => {
    listClientsMock.mockResolvedValue({
      clients: [
        {
          id: "c1",
          name: "Acme Industries",
          client_type: "company",
          city: "Mumbai",
          is_active: true,
          kyc_status: "verified",
          active_matters_count: 2,
          total_matters_count: 5,
        },
      ],
    });
    render(withClient(<ClientsIndexPage />));
    expect(screen.getByText(/Clients & engagements/i)).toBeInTheDocument();
    await waitFor(() => expect(listClientsMock).toHaveBeenCalled());
    expect(await screen.findByText(/Acme Industries/i)).toBeInTheDocument();
  });

  it("shows the empty state when the firm has no clients", async () => {
    listClientsMock.mockResolvedValue({ clients: [] });
    render(withClient(<ClientsIndexPage />));
    expect(await screen.findByText(/No clients yet/i)).toBeInTheDocument();
  });

  it("surfaces an error state when listClients fails", async () => {
    listClientsMock.mockRejectedValue(new Error("network"));
    render(withClient(<ClientsIndexPage />));
    expect(
      await screen.findByText(/Could not load clients/i),
    ).toBeInTheDocument();
  });
});
