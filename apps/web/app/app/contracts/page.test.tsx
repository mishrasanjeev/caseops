import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listContractsMock, useCapabilityMock } = vi.hoisted(() => ({
  listContractsMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listContracts: listContractsMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: useCapabilityMock,
}));

vi.mock("@/components/app/NewContractDialog", () => ({
  NewContractDialog: () => <button data-testid="new-contract-dialog">New contract</button>,
}));

import ContractsPage from "@/app/app/contracts/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const CONTRACTS_FIXTURE = {
  contracts: [
    {
      id: "k-1",
      contract_code: "K-001",
      title: "Master services agreement",
      counterparty_name: "Acme Industries Ltd.",
      contract_type: "MSA",
      effective_on: "2026-01-15",
      expires_on: "2027-01-14",
      total_value_minor: 1500000,
      currency: "INR",
      status: "active",
    },
    {
      id: "k-2",
      contract_code: "K-002",
      title: "Software license",
      counterparty_name: null,
      contract_type: "License",
      effective_on: null,
      expires_on: null,
      total_value_minor: null,
      currency: "INR",
      status: "draft",
    },
  ],
  next_cursor: null,
};

describe("ContractsPage", () => {
  beforeEach(() => {
    listContractsMock.mockReset();
    useCapabilityMock.mockReset();
  });

  it("renders page header on first load", async () => {
    listContractsMock.mockResolvedValue(CONTRACTS_FIXTURE);
    useCapabilityMock.mockReturnValue(false);
    render(withClient(<ContractsPage />));
    expect(await screen.findByText(/Contract repository/i)).toBeInTheDocument();
  });

  it("renders contract rows with code, title, and counterparty", async () => {
    listContractsMock.mockResolvedValue(CONTRACTS_FIXTURE);
    useCapabilityMock.mockReturnValue(false);
    render(withClient(<ContractsPage />));
    expect(await screen.findByText("K-001")).toBeInTheDocument();
    expect(screen.getByText("Master services agreement")).toBeInTheDocument();
    expect(screen.getByText(/Acme Industries Ltd\./)).toBeInTheDocument();
    expect(screen.getByText("Software license")).toBeInTheDocument();
  });

  it("hides the New contract CTA when caller lacks contracts:create", async () => {
    listContractsMock.mockResolvedValue(CONTRACTS_FIXTURE);
    useCapabilityMock.mockReturnValue(false);
    render(withClient(<ContractsPage />));
    await screen.findByText(/Contract repository/i);
    expect(screen.queryByTestId("new-contract-dialog")).not.toBeInTheDocument();
  });

  it("renders the New contract CTA when caller has contracts:create", async () => {
    listContractsMock.mockResolvedValue(CONTRACTS_FIXTURE);
    useCapabilityMock.mockReturnValue(true);
    render(withClient(<ContractsPage />));
    await screen.findByText(/Contract repository/i);
    expect(screen.getByTestId("new-contract-dialog")).toBeInTheDocument();
  });
});
