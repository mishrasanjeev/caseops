import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  archiveClientMock,
  fetchClientMock,
  rejectClientKycMock,
  submitClientKycMock,
  unarchiveClientMock,
  verifyClientKycMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  archiveClientMock: vi.fn(),
  fetchClientMock: vi.fn(),
  rejectClientKycMock: vi.fn(),
  submitClientKycMock: vi.fn(),
  unarchiveClientMock: vi.fn(),
  verifyClientKycMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "client-1" }),
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => useCapabilityMock(capability),
}));

vi.mock("@/lib/api/endpoints", () => ({
  archiveClient: archiveClientMock,
  fetchClient: fetchClientMock,
  rejectClientKyc: rejectClientKycMock,
  submitClientKyc: submitClientKycMock,
  unarchiveClient: unarchiveClientMock,
  verifyClientKyc: verifyClientKycMock,
}));

import ClientProfilePage from "@/app/app/clients/[id]/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function clientRecord(overrides: Record<string, unknown> = {}) {
  return {
    id: "client-1",
    company_id: "company-1",
    name: "Aster Client",
    client_type: "individual",
    primary_contact_name: "Client Contact",
    primary_contact_email: "client@example.test",
    primary_contact_phone: null,
    address_line_1: null,
    address_line_2: null,
    city: "Mumbai",
    state: "Maharashtra",
    postal_code: null,
    country: "India",
    pan: null,
    gstin: null,
    internal_notes: null,
    kyc_status: "submitted",
    kyc_submitted_at: "2026-05-24T10:00:00Z",
    kyc_verified_at: null,
    kyc_verified_by_membership_id: null,
    kyc_rejection_reason: null,
    kyc_documents: [
      {
        name: "Identity reference",
        document_type: "identity_proof",
        status: "submitted",
        note: null,
        attachment_id: "att-1",
        expires_on: null,
      },
    ],
    is_active: true,
    active_matters_count: 1,
    total_matters_count: 1,
    matters: [],
    created_at: "2026-05-24T09:00:00Z",
    updated_at: "2026-05-24T09:00:00Z",
    ...overrides,
  };
}

describe("ClientProfilePage verification workflow", () => {
  beforeEach(() => {
    archiveClientMock.mockReset();
    fetchClientMock.mockReset();
    rejectClientKycMock.mockReset();
    submitClientKycMock.mockReset();
    unarchiveClientMock.mockReset();
    verifyClientKycMock.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockImplementation((capability: string) =>
      ["clients:kyc_submit", "clients:kyc_review"].includes(capability),
    );
  });

  it("shows submitted verification as reviewable", async () => {
    fetchClientMock.mockResolvedValue(clientRecord());
    render(withClient(<ClientProfilePage />));

    expect(await screen.findByText("Aster Client")).toBeInTheDocument();
    expect(screen.getAllByText("submitted").length).toBeGreaterThan(0);
    expect(screen.getByTestId("kyc-verify")).toBeInTheDocument();
    expect(screen.getByTestId("kyc-reject-toggle")).toBeInTheDocument();
  });

  it("submits verification documents from not-required state", async () => {
    fetchClientMock.mockResolvedValue(
      clientRecord({
        kyc_status: "not_required",
        kyc_submitted_at: null,
        kyc_documents: [],
      }),
    );
    submitClientKycMock.mockResolvedValue(clientRecord({ kyc_status: "submitted" }));
    const user = userEvent.setup();
    render(withClient(<ClientProfilePage />));

    await screen.findByText("Aster Client");
    await user.click(screen.getByTestId("kyc-submit-toggle"));
    await user.click(screen.getByTestId("kyc-submit"));

    await waitFor(() => expect(submitClientKycMock).toHaveBeenCalled());
    expect(submitClientKycMock.mock.calls[0][0].clientId).toBe("client-1");
    expect(submitClientKycMock.mock.calls[0][0].documents.length).toBeGreaterThan(0);
  });
});
