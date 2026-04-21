import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchWorkspaceMock, useCapabilityMock } = vi.hoisted(() => ({
  fetchWorkspaceMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchContractWorkspace: fetchWorkspaceMock,
  uploadContractAttachment: vi.fn(),
  extractContractClauses: vi.fn(),
  extractContractObligations: vi.fn(),
  installDefaultPlaybook: vi.fn(),
  comparePlaybook: vi.fn(),
  fetchContractAttachmentRedline: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (cap: string) => useCapabilityMock(cap),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "c1" }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import ContractDetailPage from "@/app/app/contracts/[id]/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("ContractDetailPage", () => {
  beforeEach(() => {
    fetchWorkspaceMock.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockImplementation(() => false);
    fetchWorkspaceMock.mockResolvedValue({
      contract: {
        id: "c1",
        contract_code: "CT-1",
        title: "Vendor MSA",
        contract_type: "msa",
        counterparty_name: "Acme Corp",
        status: "draft",
        effective_on: null,
        expires_on: null,
        governing_law: null,
        summary: null,
      },
      attachments: [],
      clauses: [],
      obligations: [],
      playbook_rules: [],
    });
  });

  it("renders the contract header and the Clauses tab label after fetch", async () => {
    render(withClient(<ContractDetailPage />));
    await waitFor(() => expect(fetchWorkspaceMock).toHaveBeenCalledWith("c1"));
    expect(await screen.findByText("Vendor MSA")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Clauses/i })).toBeInTheDocument();
  });
});
