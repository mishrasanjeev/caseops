import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { ContractMetadataEditor } from "./ContractMetadataEditor";
import { ApiError } from "@/lib/api/config";
import type { EditableContractMetadata } from "@/lib/api/contracts";

const { save } = vi.hoisted(() => ({ save: vi.fn() }));
vi.mock("@/lib/api/contracts", () => ({ updateContractDetails: save }));
const contract: EditableContractMetadata = {
  title: "Synthetic vendor agreement", counterparty_name: "Synthetic supplier", contract_type: "Agreement",
  contract_type_key: "agreement", contract_type_notes: null, effective_on: "2026-11-01", expires_on: null,
  renewal_on: null, auto_renewal: false, summary: "Original description", updated_at: "2026-11-11T10:00:00Z",
};
beforeEach(() => { save.mockReset(); });
function setup(canEdit = true) {
  const onSaved = vi.fn().mockResolvedValue(undefined);
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const view = render(<QueryClientProvider client={client}><ContractMetadataEditor contractId="c1" contract={contract} canEdit={canEdit} onSaved={onSaved} /></QueryClientProvider>);
  return { ...view, onSaved, user: userEvent.setup(), client };
}

it("sends all edited fields and the loaded version, without unrelated fields", async () => {
  save.mockResolvedValue({});
  const { user, onSaved } = setup();
  await user.click(screen.getByRole("button", { name: "Edit contract" }));
  await user.clear(screen.getByLabelText("Contract title"));
  await user.type(screen.getByLabelText("Contract title"), "Corrected synthetic agreement");
  await user.clear(screen.getByLabelText("Counterparty"));
  await user.selectOptions(screen.getByLabelText("Contract type"), "lease");
  await user.type(screen.getByLabelText("Expiry date"), "2027-10-31");
  await user.type(screen.getByLabelText("Renewal date"), "2027-09-01");
  await user.click(screen.getByLabelText("Auto-renewal"));
  await user.clear(screen.getByLabelText("Description"));
  await user.click(screen.getByRole("button", { name: "Save contract" }));
  await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
  expect(save).toHaveBeenCalledWith("c1", {
    title: "Corrected synthetic agreement", counterparty_name: null, contract_type: "Lease", contract_type_key: "lease",
    expires_on: "2027-10-31", renewal_on: "2027-09-01", auto_renewal: true, summary: null,
    expected_updated_at: contract.updated_at,
  });
  expect(screen.queryByRole("button", { name: "Save contract" })).not.toBeInTheDocument();
});

it("keeps an in-progress draft and loaded version across a refreshed parent, then exposes stale reload", async () => {
  save.mockRejectedValue(new ApiError(409, "Reload before saving your changes.", null));
  const { user, rerender, client, onSaved } = setup();
  await user.click(screen.getByRole("button", { name: "Edit contract" }));
  await user.clear(screen.getByLabelText("Contract title"));
  await user.type(screen.getByLabelText("Contract title"), "Unsaved draft title");
  rerender(<QueryClientProvider client={client}><ContractMetadataEditor contractId="c1" contract={{ ...contract, title: "New server title", updated_at: "2026-11-11T11:00:00Z" }} canEdit onSaved={onSaved} /></QueryClientProvider>);
  expect(screen.getByLabelText("Contract title")).toHaveValue("Unsaved draft title");
  await user.click(screen.getByRole("button", { name: "Save contract" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Reload before saving");
  expect(save).toHaveBeenCalledWith("c1", { title: "Unsaved draft title", expected_updated_at: contract.updated_at });
  expect(screen.getByRole("button", { name: "Save contract" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Reload contract" }));
  await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
  expect(save).toHaveBeenCalledTimes(1);
});

it("disables sibling edits during a save and does not submit a cancelled edit", async () => {
  let finish!: () => void;
  save.mockReturnValue(new Promise<void>((resolve) => { finish = resolve; }));
  const { user } = setup();
  await user.click(screen.getByRole("button", { name: "Edit contract" }));
  expect(screen.getByRole("button", { name: "Save contract" })).toBeDisabled();
  await user.type(screen.getByLabelText("Contract title"), " amended");
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(save).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Edit contract" }));
  expect(screen.getByLabelText("Contract title")).toHaveValue(contract.title);
  await user.click(screen.getByLabelText("Auto-renewal"));
  await user.click(screen.getByRole("button", { name: "Save contract" }));
  expect(screen.getByLabelText("Contract title")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  finish();
  await screen.findByRole("button", { name: "Edit contract" });
});

it("does not offer writes without edit capability", () => {
  setup(false);
  expect(screen.queryByRole("button", { name: "Edit contract" })).not.toBeInTheDocument();
});
