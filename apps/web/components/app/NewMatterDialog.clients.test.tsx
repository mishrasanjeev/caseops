import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor, within } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ClientRecord } from "@/lib/api/endpoints";

const { createMatterMock, fetchForumCatalogMock, listClientsMock, useCapabilityMock, toastSuccess, toastError } =
  vi.hoisted(() => ({
    createMatterMock: vi.fn(),
    fetchForumCatalogMock: vi.fn(),
    listClientsMock: vi.fn(),
    useCapabilityMock: vi.fn(),
    toastSuccess: vi.fn(),
    toastError: vi.fn(),
  }));

vi.mock("@/lib/api/endpoints", () => ({
  createMatter: createMatterMock,
  fetchForumCatalog: fetchForumCatalogMock,
  listClients: listClientsMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => useCapabilityMock(capability),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

import { NewMatterDialog } from "@/components/app/NewMatterDialog";

function clientRecord(index: number, overrides: Partial<ClientRecord> = {}): ClientRecord {
  return {
    id: `client-${index}`,
    company_id: "company-1",
    name: `Registered Client ${index}`,
    client_type: "corporate",
    primary_contact_name: null,
    primary_contact_email: null,
    primary_contact_phone: null,
    address_line_1: null,
    address_line_2: null,
    city: null,
    state: null,
    postal_code: null,
    country: "India",
    pan: null,
    gstin: null,
    internal_notes: null,
    kyc_status: "not_required",
    kyc_submitted_at: null,
    kyc_verified_at: null,
    kyc_verified_by_membership_id: null,
    kyc_rejection_reason: null,
    kyc_documents: [],
    is_active: true,
    active_matters_count: 0,
    total_matters_count: 0,
    matters: [],
    created_at: "2026-11-01T09:00:00Z",
    updated_at: "2026-11-01T09:00:00Z",
    ...overrides,
  };
}

async function enterText(user: UserEvent, field: HTMLElement, value: string) {
  await user.click(field);
  await user.paste(value);
  expect(field).toHaveDisplayValue(value);
}

async function openFilledDialog(user: UserEvent) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <NewMatterDialog />
    </QueryClientProvider>,
  );
  const trigger = within(view.container).getByTestId("new-matter-trigger");
  await user.click(trigger);
  const element = await waitFor(() => {
    const node = document.getElementById(trigger.getAttribute("aria-controls") as string);
    expect(node).not.toBeNull();
    return node as HTMLElement;
  });
  const dialog = within(element);
  await waitFor(() => expect(dialog.getByTestId("new-matter-forum-state")).toHaveValue("Delhi"));
  await enterText(user, dialog.getByLabelText("Title"), "Linked client matter");
  await enterText(user, dialog.getByLabelText("Matter code"), "lnk-001");
  await enterText(user, dialog.getByLabelText("Practice area"), "Commercial");
  return dialog;
}

describe("NewMatterDialog client link", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchForumCatalogMock.mockResolvedValue({
      entries: [
        {
          id: "hc:delhi",
          parent_id: null,
          court_id: "delhi-hc",
          name: "Delhi High Court",
          forum_type: "high_court",
          forum_level: "high_court",
          state: "Delhi",
          district: null,
          city: "New Delhi",
          consumer_level: null,
          source_name: "CaseOps LW-S4 baseline forum catalog",
          source_url: null,
          lineage: "High Court > Delhi > Delhi High Court",
          display_order: 24,
        },
      ],
    });
    createMatterMock.mockResolvedValue({ id: "m-1", matter_code: "LNK-001", status: "active" });
    listClientsMock.mockResolvedValue({
      clients: [
        ...Array.from({ length: 75 }, (_, index) => clientRecord(index + 1)),
        clientRecord(900, { name: "Archived Former Client", is_active: false }),
      ],
      next_cursor: null,
    });
  });

  it("links an existing client found by search and sends its id instead of a typed name", async () => {
    useCapabilityMock.mockImplementation((capability: string) => capability === "clients:edit");
    const user = userEvent.setup();
    const dialog = await openFilledDialog(user);

    const select = dialog.getByLabelText("Or link an existing client");
    await waitFor(() => expect(select).toBeEnabled());
    expect(within(select).queryByRole("option", { name: /Archived Former Client/ })).toBeNull();
    await user.type(dialog.getByLabelText("Search clients"), "Client 74");
    await user.selectOptions(select, await within(select).findByRole("option", { name: /Registered Client 74/ }));
    expect(dialog.getByTestId("new-matter-client-name")).toBeDisabled();
    expect(dialog.getByTestId("new-matter-client-name")).toHaveValue("Registered Client 74");

    await user.click(dialog.getByRole("button", { name: /Create matter/i }));
    await waitFor(() => expect(createMatterMock).toHaveBeenCalledTimes(1));
    const payload = createMatterMock.mock.calls[0][0];
    expect(payload.client_id).toBe("client-74");
    expect("client_name" in payload).toBe(false);
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Matter created"));
  });

  it("keeps the typed client name when no client is linked", async () => {
    useCapabilityMock.mockImplementation((capability: string) => capability === "clients:edit");
    const user = userEvent.setup();
    const dialog = await openFilledDialog(user);

    await enterText(user, dialog.getByTestId("new-matter-client-name"), "New Prospect Pvt Ltd");
    await user.click(dialog.getByRole("button", { name: /Create matter/i }));
    await waitFor(() => expect(createMatterMock).toHaveBeenCalledTimes(1));
    const payload = createMatterMock.mock.calls[0][0];
    expect(payload.client_name).toBe("New Prospect Pvt Ltd");
    expect("client_id" in payload).toBe(false);
  });

  it("does not offer the client picker to a role without clients:edit", async () => {
    useCapabilityMock.mockReturnValue(false);
    const user = userEvent.setup();
    const dialog = await openFilledDialog(user);

    expect(dialog.queryByLabelText("Or link an existing client")).toBeNull();
    expect(listClientsMock).not.toHaveBeenCalled();
  });
});
