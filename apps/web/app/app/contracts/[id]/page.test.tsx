import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchWorkspaceMock,
  useCapabilityMock,
  extractByPartyMock,
  listTenantPlaybooksMock,
  tenantCompareMock,
} = vi.hoisted(() => ({
  fetchWorkspaceMock: vi.fn(),
  useCapabilityMock: vi.fn(),
  extractByPartyMock: vi.fn(),
  listTenantPlaybooksMock: vi.fn(),
  tenantCompareMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  CONTRACT_ATTACHMENT_ROLE_OPTIONS: [
    { value: "primary_contract", label: "Primary contract" },
    { value: "amendment", label: "Amendment" },
    { value: "supporting_document", label: "Supporting document" },
    { value: "other", label: "Other" },
  ],
  CONTRACT_TYPE_OPTIONS: [
    { value: "agreement", label: "Agreement" },
    { value: "master_services_agreement", label: "Master services agreement" },
    { value: "other", label: "Other" },
  ],
  fetchContractWorkspace: fetchWorkspaceMock,
  uploadContractAttachment: vi.fn(),
  extractContractClauses: vi.fn(),
  extractContractClausesByParty: extractByPartyMock,
  extractContractObligations: vi.fn(),
  installDefaultPlaybook: vi.fn(),
  comparePlaybook: vi.fn(),
  listTenantContractPlaybooks: listTenantPlaybooksMock,
  compareContractAgainstTenantPlaybook: tenantCompareMock,
  fetchContractAttachmentRedline: vi.fn(),
  updateContractMetadata: vi.fn(),
  createContractLegalReference: vi.fn(),
  updateContractLegalReference: vi.fn(),
  acceptContractTermSuggestion: vi.fn(),
  rejectContractTermSuggestion: vi.fn(),
  updateContractAttachmentMetadata: vi.fn(),
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
    extractByPartyMock.mockReset();
    listTenantPlaybooksMock.mockReset();
    tenantCompareMock.mockReset();
    listTenantPlaybooksMock.mockResolvedValue([]);
    useCapabilityMock.mockImplementation(() => false);
    fetchWorkspaceMock.mockResolvedValue({
      contract: {
        id: "c1",
        contract_code: "CT-1",
        title: "Vendor MSA",
        contract_type: "Master services agreement",
        contract_type_key: "master_services_agreement",
        contract_type_notes: null,
        counterparty_name: "Acme Corp",
        status: "draft",
        effective_on: null,
        expires_on: null,
        renewal_on: null,
        auto_renewal: false,
        jurisdiction: null,
        summary: null,
      },
      attachments: [],
      clauses: [],
      obligations: [],
      playbook_rules: [],
      legal_references: [],
      term_suggestions: [],
    });
  });

  it("renders the contract header and the Clauses tab label after fetch", async () => {
    render(withClient(<ContractDetailPage />));
    await waitFor(() => expect(fetchWorkspaceMock).toHaveBeenCalledWith("c1"));
    expect(await screen.findByText("Vendor MSA")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Clauses/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Legal refs/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Terms/i })).toBeInTheDocument();
  });

  it("renders legal references, term suggestions, and attachment roles", async () => {
    fetchWorkspaceMock.mockResolvedValue({
      contract: {
        id: "c1",
        contract_code: "CT-1",
        title: "Vendor MSA",
        contract_type: "Legacy MSA",
        contract_type_key: null,
        contract_type_notes: null,
        counterparty_name: "Acme Corp",
        status: "under_review",
        effective_on: "2026-05-01",
        expires_on: null,
        renewal_on: null,
        auto_renewal: false,
        jurisdiction: "India",
        summary: null,
      },
      attachments: [
        {
          id: "a1",
          original_filename: "msa.pdf",
          content_type: "application/pdf",
          size_bytes: 4096,
          processing_status: "indexed",
          attachment_role: "primary_contract",
          parent_attachment_id: null,
          document_date: "2026-05-01",
          notes: "Signed source",
          created_at: "2026-05-01T00:00:00Z",
        },
        {
          id: "a2",
          original_filename: "amendment.pdf",
          content_type: "application/pdf",
          size_bytes: 2048,
          processing_status: "indexed",
          attachment_role: "amendment",
          parent_attachment_id: "a1",
          document_date: "2026-05-05",
          notes: "Pricing amendment",
          created_at: "2026-05-05T00:00:00Z",
        },
      ],
      clauses: [],
      obligations: [],
      playbook_rules: [],
      legal_references: [
        {
          id: "lr1",
          company_id: "co1",
          contract_id: "c1",
          act_name: "Indian Contract Act, 1872",
          section_label: "Section 73",
          clause_label: "Damages",
          authority_id: null,
          statute_id: null,
          source: "ai_suggested",
          confidence: 0.82,
          evidence_attachment_id: "a1",
          evidence_attachment_name: "msa.pdf",
          evidence_quote: "loss naturally arose in usual course",
          status: "suggested",
          created_by_membership_id: "m1",
          reviewed_by_membership_id: null,
          reviewed_at: null,
          created_at: "2026-05-01T00:00:00Z",
          updated_at: "2026-05-01T00:00:00Z",
        },
      ],
      term_suggestions: [
        {
          id: "ts1",
          company_id: "co1",
          contract_id: "c1",
          source_attachment_id: "a1",
          source_attachment_name: "msa.pdf",
          suggested_effective_on: "2026-05-15",
          suggested_expires_on: null,
          suggested_renewal_on: null,
          suggested_duration_months: 12,
          evidence_json: { quote: "commences on 15 May 2026" },
          status: "suggested",
          created_by_membership_id: "m1",
          reviewed_by_membership_id: null,
          reviewed_at: null,
          created_at: "2026-05-01T00:00:00Z",
          updated_at: "2026-05-01T00:00:00Z",
        },
      ],
    });
    useCapabilityMock.mockImplementation((cap: string) => cap === "contracts:edit");

    render(withClient(<ContractDetailPage />));
    expect(await screen.findByText("Vendor MSA")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /Attachments/i }));
    expect(screen.getByRole("heading", { name: "Primary contract" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Amendment" })).toBeInTheDocument();
    expect(screen.getByText("Signed source")).toBeInTheDocument();
    expect(screen.getByText(/linked to msa.pdf/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /Legal refs/i }));
    expect(screen.getByText("Indian Contract Act, 1872")).toBeInTheDocument();
    expect(screen.getByText("loss naturally arose in usual course")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /Terms/i }));
    expect(screen.getByText("2026-05-15")).toBeInTheDocument();
    expect(screen.getByText("12 months")).toBeInTheDocument();
  });

  it("runs party-perspective extraction and surfaces ambiguous + dropped items", async () => {
    fetchWorkspaceMock.mockResolvedValue({
      contract: {
        id: "c1",
        contract_code: "CT-1",
        title: "Vendor MSA",
        contract_type: "Master services agreement",
        contract_type_key: "master_services_agreement",
        contract_type_notes: null,
        counterparty_name: "Acme Corp",
        status: "draft",
        effective_on: null,
        expires_on: null,
        renewal_on: null,
        auto_renewal: false,
        jurisdiction: null,
        summary: null,
      },
      attachments: [
        {
          id: "a1",
          original_filename: "msa.pdf",
          content_type: "application/pdf",
          size_bytes: 4096,
          processing_status: "indexed",
          attachment_role: "primary_contract",
          parent_attachment_id: null,
          document_date: null,
          notes: null,
          created_at: "2026-05-01T00:00:00Z",
        },
      ],
      clauses: [],
      obligations: [],
      playbook_rules: [],
      legal_references: [],
      term_suggestions: [],
    });
    useCapabilityMock.mockImplementation((cap: string) => cap === "ai:generate");
    extractByPartyMock.mockResolvedValue({
      contract_id: "c1",
      represented_party: "first",
      first_party_name: "Acme India Pvt Ltd",
      second_party_name: "Beta Software Inc.",
      represented_items: [
        {
          category: "indemnity",
          summary: "Supplier indemnifies Customer for IP",
          assigned_party: "first",
          source: {
            attachment_id: "a1",
            locator: "Clause 12",
            snippet: "Supplier indemnifies Customer for IP infringement",
          },
        },
      ],
      counterparty_items: [
        {
          category: "payment",
          summary: "Customer pays Supplier in 30 days",
          assigned_party: "second",
          source: {
            attachment_id: "a1",
            locator: "Clause 4",
            snippet: "Customer shall pay Supplier within thirty days",
          },
        },
      ],
      ambiguous_items: [
        {
          category: "termination",
          summary: "Either party may invoke step-in rights",
          ambiguity_reason: "Either party reference is unresolved",
          source: {
            attachment_id: "a1",
            locator: "Clause 19",
            snippet: "Either party may invoke step-in rights",
          },
        },
      ],
      dropped_source_unverified_count: 2,
      provider: "mock",
      model: "mock-party-extract",
    });

    render(withClient(<ContractDetailPage />));
    expect(await screen.findByText("Vendor MSA")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /Clauses/i }));
    await userEvent.type(
      screen.getByTestId("party-first-name"),
      "Acme India Pvt Ltd",
    );
    await userEvent.type(
      screen.getByTestId("party-second-name"),
      "Beta Software Inc.",
    );
    await userEvent.type(
      screen.getByTestId("party-first-aliases"),
      "Acme, Supplier",
    );
    await userEvent.click(screen.getByTestId("party-extract-button"));

    await waitFor(() => expect(extractByPartyMock).toHaveBeenCalledTimes(1));
    const callArg = extractByPartyMock.mock.calls[0][0];
    expect(callArg.firstPartyAliases).toEqual(["Acme", "Supplier"]);
    expect(callArg.representedParty).toBe("first");

    expect(
      await screen.findByText(/Represented party — Acme India Pvt Ltd/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Counterparty — Beta Software Inc\./i),
    ).toBeInTheDocument();
    expect(screen.getByTestId("party-extract-ambiguous")).toBeInTheDocument();
    expect(screen.getByText(/Either party reference is unresolved/i)).toBeInTheDocument();
    expect(screen.getByTestId("party-extract-dropped")).toHaveTextContent(
      /2 items dropped/i,
    );
  });

  it("runs tenant playbook compare and renders matched/missing/deviation findings", async () => {
    fetchWorkspaceMock.mockResolvedValue({
      contract: {
        id: "c1",
        contract_code: "CT-1",
        title: "Vendor MSA",
        contract_type: "Master services agreement",
        contract_type_key: "master_services_agreement",
        contract_type_notes: null,
        counterparty_name: "Acme Corp",
        status: "draft",
        effective_on: null,
        expires_on: null,
        renewal_on: null,
        auto_renewal: false,
        jurisdiction: null,
        summary: null,
      },
      attachments: [],
      clauses: [],
      obligations: [],
      playbook_rules: [],
      legal_references: [],
      term_suggestions: [],
    });
    useCapabilityMock.mockImplementation(() => true);
    listTenantPlaybooksMock.mockResolvedValue([
      {
        id: "pb1",
        company_id: "co1",
        name: "Vendor MSA playbook",
        description: null,
        contract_type_key: "master_services_agreement",
        jurisdiction: "India",
        party_perspective: "first",
        is_archived: false,
        rule_count: 3,
        active_rule_count: 3,
        created_at: "2026-05-24T00:00:00Z",
        updated_at: "2026-05-24T00:00:00Z",
      },
    ]);
    tenantCompareMock.mockResolvedValue({
      contract_id: "c1",
      playbook_id: "pb1",
      playbook_name: "Vendor MSA playbook",
      findings: [
        {
          rule_id: "r1",
          rule_name: "Liability cap (12 months)",
          clause_type: "limitation_of_liability",
          severity: "high",
          status: "matched",
          expected_position: "12-month aggregate cap.",
          fallback_text: null,
          rationale: null,
          source: {
            clause_id: "cl1",
            clause_type: "limitation_of_liability",
            snippet: "Aggregate liability shall not exceed fees paid in the prior twelve months.",
          },
          note: null,
        },
        {
          rule_id: "r2",
          rule_name: "Confidentiality (mutual)",
          clause_type: "confidentiality",
          severity: "medium",
          status: "missing",
          expected_position: "Mutual confidentiality obligations.",
          fallback_text: "Insert a mutual NDA paragraph.",
          rationale: null,
          source: null,
          note: null,
        },
      ],
      summary: {
        total_rules: 2,
        matched: 1,
        missing: 1,
        deviation: 0,
        needs_review: 0,
      },
    });

    render(withClient(<ContractDetailPage />));
    expect(await screen.findByText("Vendor MSA")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /Clauses/i }));
    await waitFor(() => expect(listTenantPlaybooksMock).toHaveBeenCalled());

    const select = screen.getByTestId("tenant-playbook-select");
    await userEvent.selectOptions(select, "pb1");
    await userEvent.click(screen.getByTestId("tenant-playbook-compare-button"));

    await waitFor(() => expect(tenantCompareMock).toHaveBeenCalledTimes(1));
    expect(tenantCompareMock.mock.calls[0][0]).toEqual({
      contractId: "c1",
      playbookId: "pb1",
    });

    expect(await screen.findByTestId("tpc-summary-matched")).toHaveTextContent(
      /matched: 1/i,
    );
    expect(screen.getByTestId("tpc-summary-missing")).toHaveTextContent(
      /missing: 1/i,
    );
    expect(screen.getByText(/Liability cap \(12 months\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Insert a mutual NDA paragraph\./i)).toBeInTheDocument();
  });
});
