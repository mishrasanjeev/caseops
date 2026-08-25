import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  dockets: vi.fn(), documents: vi.fn(), grants: vi.fn(), instructions: vi.fn(),
  invite: vi.fn(), revoke: vi.fn(), publishDocument: vi.fn(), acknowledge: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({ useCapability: () => true }));
vi.mock("@/lib/api/endpoints", () => ({ fetchIpDockets: mocks.dockets, fetchIpDocuments: mocks.documents }));
vi.mock("@/lib/api/portal", () => ({
  fetchAdminPortalIpGrants: mocks.grants,
  fetchFirmPortalInstructions: mocks.instructions,
  invitePortalUser: mocks.invite,
  revokePortalIpGrant: mocks.revoke,
  publishIpDocumentToPortal: mocks.publishDocument,
  acknowledgePortalInstruction: mocks.acknowledge,
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import IpClientPortalPage from "@/app/app/ip/client-portal/page";

function renderPage() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><IpClientPortalPage /></QueryClientProvider>);
}

describe("IpClientPortalPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.dockets.mockResolvedValue({ dockets: [{ id: "docket-1", title: "ASTER DEVICE" }] });
    mocks.grants.mockResolvedValue({ grants: [{ id: "grant-1", portal_user_id: "user-1", portal_user_name: "Asha Rao", portal_user_email: "asha@example.com", ip_docket_record_id: "docket-1", docket_title: "ASTER DEVICE", scope: {}, granted_at: "2026-08-25T00:00:00Z", expires_at: null, revoked_at: null, row_version: 1, active: true }] });
    mocks.documents.mockResolvedValue({ items: [
      { id: "doc-safe", title: "Accepted evidence", confidentiality: "internal", is_privileged: false, taxonomy_label: "Evidence", versions: [{ id: "v-safe", version: 1, state: "accepted" }] },
      { id: "doc-secret", title: "Strategy note", confidentiality: "internal", is_privileged: true, taxonomy_label: "Strategy", versions: [{ id: "v-secret", version: 1, state: "approved" }] },
    ] });
    mocks.instructions.mockResolvedValue({ instructions: [{ id: "instruction-1", docket_title: "ASTER DEVICE", decision: "proceed", note: "Proceed with evidence", status: "pending", row_version: 1 }] });
    mocks.invite.mockResolvedValue({ portal_user: { id: "user-1" }, grants: [] });
    mocks.revoke.mockResolvedValue({ active: false });
    mocks.publishDocument.mockResolvedValue({ id: "publication-1" });
    mocks.acknowledge.mockResolvedValue({ id: "instruction-1", status: "accepted" });
  });

  it("grants one IP docket and excludes privileged documents from publication choices", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(await screen.findByLabelText("Client name"), "Asha Rao");
    await user.type(screen.getByLabelText("Work email"), "asha@example.com");
    await user.selectOptions(screen.getByLabelText("IP docket"), "docket-1");
    await user.click(screen.getByRole("button", { name: "Grant access" }));
    await waitFor(() => expect(mocks.invite).toHaveBeenCalledWith(expect.objectContaining({ ipDocketIds: ["docket-1"], canSubmitInstructions: true })));
    expect(await screen.findByRole("option", { name: /Accepted evidence/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Strategy note/ })).not.toBeInTheDocument();
  });

  it("requires firm acknowledgement and can revoke the canonical grant", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(await screen.findByLabelText("Acknowledgement reason for ASTER DEVICE"), "Checked against the current proceeding.");
    await user.click(screen.getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(mocks.acknowledge).toHaveBeenCalledWith(expect.objectContaining({ instructionId: "instruction-1", status: "accepted" })));
    await user.type(screen.getByLabelText("Revocation reason for Asha Rao"), "Engagement scope ended.");
    await user.click(screen.getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(mocks.revoke).toHaveBeenCalledWith(expect.objectContaining({ grantId: "grant-1", rowVersion: 1 })));
  });
});
