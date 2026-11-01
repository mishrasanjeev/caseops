import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  dockets: vi.fn(), docket: vi.fn(), taxonomy: vi.fn(), shareable: vi.fn(), grants: vi.fn(), instructions: vi.fn(),
  invite: vi.fn(), revoke: vi.fn(), publishDocument: vi.fn(), acknowledge: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({ useCapability: () => true }));
vi.mock("@/lib/api/endpoints", () => ({
  fetchIpDockets: mocks.dockets,
  fetchIpDocket: mocks.docket,
  fetchIpDocumentTaxonomy: mocks.taxonomy,
}));
vi.mock("@/lib/api/portal", () => ({
  fetchAdminPortalIpGrants: mocks.grants,
  fetchFirmPortalInstructions: mocks.instructions,
  fetchPortalGrantShareableDocuments: mocks.shareable,
  invitePortalUser: mocks.invite,
  revokePortalIpGrant: mocks.revoke,
  publishIpDocumentToPortal: mocks.publishDocument,
  acknowledgePortalInstruction: mocks.acknowledge,
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import IpClientPortalPage from "@/app/app/ip/client-portal/page";

const GRANT = { id: "grant-1", portal_user_id: "user-1", portal_user_name: "Asha Rao", portal_user_email: "asha@example.com", ip_docket_record_id: "docket-1", docket_title: "ASTER DEVICE", scope: {}, granted_at: "2026-08-25T00:00:00Z", expires_at: null, revoked_at: null, row_version: 1, active: true, publishable: true, publication_blocked_reason: null };

function renderPage() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><IpClientPortalPage /></QueryClientProvider>);
}

function deadSelects() {
  return Array.from(document.querySelectorAll("select")).filter(
    (select) => !select.disabled && !Array.from(select.options).some((option) => option.value && !option.disabled),
  ).map((select) => select.id);
}

describe("IpClientPortalPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.dockets.mockResolvedValue({ dockets: [{ id: "docket-1", title: "ASTER DEVICE", primary_identifier: "5012345", record_type: "trademark" }], count: 1, has_more: false, next_cursor: null, total_count: 1 });
    mocks.taxonomy.mockResolvedValue({ taxonomy_version: "ip-taxonomy-2026.1", entries: [
      { key: "evidence", label: "Evidence", is_active: true, version: 1 },
      { key: "correspondence", label: "Correspondence", is_active: true, version: 1 },
      { key: "strategy", label: "Strategy", is_active: true, version: 1 },
      { key: "retired", label: "Retired", is_active: false, version: 1 },
    ] });
    mocks.grants.mockResolvedValue({ grants: [GRANT] });
    mocks.shareable.mockResolvedValue({ grant_id: "grant-1", docket_title: "ASTER DEVICE", document_categories: ["evidence"], documents: [
      { document_id: "doc-safe", document_title: "Accepted evidence", version_number: 2, version_state: "accepted", display_name: "evidence.pdf", taxonomy_key: "evidence", taxonomy_label: "Evidence" },
    ] });
    mocks.instructions.mockResolvedValue({ instructions: [{ id: "instruction-1", docket_title: "ASTER DEVICE", decision: "proceed", note: "Proceed with evidence", status: "pending", row_version: 1 }] });
    mocks.invite.mockResolvedValue({ portal_user: { id: "user-1" }, grants: [] });
    mocks.revoke.mockResolvedValue({ active: false });
    mocks.publishDocument.mockResolvedValue({ id: "publication-1" });
    mocks.acknowledge.mockResolvedValue({ id: "instruction-1", status: "accepted" });
  });

  it("grants one IP docket chosen in the picker with categories from the workspace taxonomy", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(await screen.findByLabelText("Client name"), "Asha Rao");
    await user.type(screen.getByLabelText("Work email"), "asha@example.com");
    const docket = screen.getByRole<HTMLSelectElement>("combobox", { name: "IP docket" });
    await waitFor(() => expect(docket).toBeEnabled());
    await user.selectOptions(docket, "docket-1");
    expect(await screen.findByRole("checkbox", { name: "Evidence" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Correspondence" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Strategy" })).not.toBeChecked();
    expect(screen.queryByRole("checkbox", { name: "Retired" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Correspondence" }));
    await user.click(screen.getByRole("button", { name: "Grant access" }));
    await waitFor(() => expect(mocks.invite).toHaveBeenCalledWith(expect.objectContaining({
      ipDocketIds: ["docket-1"], documentCategories: ["evidence"], canSubmitInstructions: true,
    })));
  });

  it("B4-ADJ-01 anchors a refused docket grant to the docket field when the docket is walled after it was chosen", async () => {
    const { ApiError } = await import("@/lib/api/config");
    mocks.invite.mockRejectedValueOnce(new ApiError(404, "IP record not found.", null));
    const user = userEvent.setup();
    renderPage();
    await user.type(await screen.findByLabelText("Client name"), "Asha Rao");
    await user.type(screen.getByLabelText("Work email"), "asha@example.com");
    const docket = screen.getByRole<HTMLSelectElement>("combobox", { name: "IP docket" });
    await waitFor(() => expect(docket).toBeEnabled());
    await user.selectOptions(docket, "docket-1");
    await user.click(screen.getByRole("button", { name: "Grant access" }));
    await waitFor(() => expect(docket).toHaveAttribute("aria-invalid", "true"));
    expect(docket).toHaveAccessibleDescription(/This docket is no longer available to you/);
    await user.selectOptions(docket, "docket-1");
    await waitFor(() => expect(docket).not.toHaveAttribute("aria-invalid"));
  });

  it("BUG-015 lists only the versions the chosen grant can publish and publishes one", async () => {
    const user = userEvent.setup();
    renderPage();
    const version = await screen.findByRole<HTMLSelectElement>("combobox", { name: "Approved version" });
    expect(version).toBeDisabled();
    expect(version.options[0]).toHaveTextContent("Choose a client grant first");
    expect(mocks.shareable).not.toHaveBeenCalled();
    const grant = screen.getByRole<HTMLSelectElement>("combobox", { name: "Client grant" });
    await waitFor(() => expect(grant).toBeEnabled());
    await user.selectOptions(grant, "grant-1");
    await waitFor(() => expect(version).toBeEnabled());
    expect(mocks.shareable).toHaveBeenCalledWith("grant-1");
    expect(Array.from(version.options, (option) => option.value)).toEqual(["", "doc-safe:2"]);
    await user.selectOptions(version, "doc-safe:2");
    await user.type(screen.getByLabelText("Client title"), "Approved evidence");
    await user.click(screen.getByRole("button", { name: "Publish approved version" }));
    await waitFor(() => expect(mocks.publishDocument).toHaveBeenCalledWith(expect.objectContaining({
      portalUserId: "user-1", grantId: "grant-1", documentId: "doc-safe", versionNumber: 2, title: "Approved evidence",
    })));
    expect(deadSelects()).toEqual([]);
  });

  it("BUG-015 names what is missing when the grant has nothing shareable", async () => {
    const user = userEvent.setup();
    mocks.shareable.mockResolvedValue({ grant_id: "grant-1", docket_title: "ASTER DEVICE", document_categories: ["evidence"], documents: [] });
    renderPage();
    const grant = await screen.findByRole<HTMLSelectElement>("combobox", { name: "Client grant" });
    await waitFor(() => expect(grant).toBeEnabled());
    await user.selectOptions(grant, "grant-1");
    const version = screen.getByRole<HTMLSelectElement>("combobox", { name: "Approved version" });
    await waitFor(() => expect(version.options[0]).toHaveTextContent("No shareable version on this docket"));
    expect(version).toBeDisabled();
    expect(version).toHaveAccessibleDescription(/ASTER DEVICE is in a category this grant shares \(evidence\)/);
    expect(screen.getByRole("link", { name: "Approve a version in the IP workspace Documents tab" })).toHaveAttribute("href", "/app/ip?docket=docket-1&tab=documents");
    expect(screen.getByRole("button", { name: "Publish approved version" })).toBeDisabled();
    expect(deadSelects()).toEqual([]);
  });

  it("BUG-015 disables the grant choice when no client has active access", async () => {
    mocks.grants.mockResolvedValue({ grants: [{ ...GRANT, active: false, publishable: false, publication_blocked_reason: "revoked", revoked_at: "2026-09-01T00:00:00Z" }] });
    renderPage();
    const grant = await screen.findByRole<HTMLSelectElement>("combobox", { name: "Client grant" });
    await waitFor(() => expect(grant.options[0]).toHaveTextContent("No client grant can receive documents"));
    expect(grant).toBeDisabled();
    expect(grant).toHaveAccessibleDescription(/No client has active access\. Grant a client access to an open docket above/);
    expect(await screen.findByText("Revoked")).toBeVisible();
    expect(deadSelects()).toEqual([]);
  });

  it("BUG-015 never offers a grant whose docket was closed after the grant", async () => {
    mocks.grants.mockResolvedValue({ grants: [
      { ...GRANT, id: "grant-closed", docket_title: "CLOSED MARK", publishable: false, publication_blocked_reason: "docket_closed" },
      GRANT,
    ] });
    renderPage();
    const grant = await screen.findByRole<HTMLSelectElement>("combobox", { name: "Client grant" });
    await waitFor(() => expect(grant).toBeEnabled());
    expect(Array.from(grant.options, (option) => option.value)).toEqual(["", "grant-1"]);
    // The grant list says why the closed-docket grant is not offered; it can still be revoked.
    expect(screen.getByText("Docket closed")).toBeVisible();
    expect(screen.getAllByRole("button", { name: "Revoke" })).toHaveLength(2);
    expect(mocks.shareable).not.toHaveBeenCalledWith("grant-closed");
  });

  it("BUG-015 explains why every active grant is blocked", async () => {
    mocks.grants.mockResolvedValue({ grants: [{ ...GRANT, publishable: false, publication_blocked_reason: "docket_closed" }] });
    renderPage();
    const grant = await screen.findByRole<HTMLSelectElement>("combobox", { name: "Client grant" });
    await waitFor(() => expect(grant).toHaveAccessibleDescription(/The only active grant is on a closed or restricted docket/));
    expect(grant).toBeDisabled();
    expect(deadSelects()).toEqual([]);
  });

  it("BUG-015 shows a grant load failure with a retry instead of an empty reason", async () => {
    const user = userEvent.setup();
    mocks.grants.mockRejectedValueOnce(new Error("Grant list unavailable."));
    renderPage();
    const grant = await screen.findByRole<HTMLSelectElement>("combobox", { name: "Client grant" });
    await waitFor(() => expect(grant.options[0]).toHaveTextContent("Grants could not be loaded"));
    expect(grant).toHaveAccessibleDescription(/Grant list unavailable\./);
    const retries = screen.getAllByRole("button", { name: /Retry|Try again/ });
    await user.click(retries[retries.length - 1]);
    await waitFor(() => expect(grant).toBeEnabled());
  });

  it("asks for confirmation before granting access that shares no documents", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(await screen.findByLabelText("Client name"), "Asha Rao");
    await user.type(screen.getByLabelText("Work email"), "asha@example.com");
    const docket = screen.getByRole<HTMLSelectElement>("combobox", { name: "IP docket" });
    await waitFor(() => expect(docket).toBeEnabled());
    await user.selectOptions(docket, "docket-1");
    await user.click(await screen.findByRole("checkbox", { name: "Evidence" }));
    await user.click(screen.getByRole("checkbox", { name: "Correspondence" }));
    const submit = screen.getByRole("button", { name: "Grant access" });
    expect(submit).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: /this client will see no documents/ }));
    expect(submit).toBeEnabled();
    await user.click(submit);
    await waitFor(() => expect(mocks.invite).toHaveBeenCalledWith(expect.objectContaining({ documentCategories: [] })));
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
