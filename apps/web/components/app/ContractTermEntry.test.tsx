import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { ContractTermEntry } from "./ContractTermEntry";

const { create } = vi.hoisted(() => ({ create: vi.fn() }));
vi.mock("@/lib/api/endpoints", () => ({ createContractTermSuggestion: create }));
beforeEach(() => { create.mockReset(); });
function setup() {
  const onSaved = vi.fn().mockResolvedValue(undefined);
  render(<QueryClientProvider client={new QueryClient()}><ContractTermEntry contractId="c1" attachments={[{ id: "a1", original_filename: "signed.docx" }]} onSaved={onSaved} /></QueryClientProvider>);
  return { user: userEvent.setup(), onSaved };
}
it("creates only explicitly entered suggestions with evidence, leaving canonical writes to review", async () => {
  create.mockResolvedValue({});
  const { user, onSaved } = setup();
  await user.click(screen.getByRole("button", { name: "Add term suggestion" }));
  expect(screen.getByRole("button", { name: "Save suggestion" })).toBeDisabled();
  await user.type(screen.getByLabelText("Suggested effective date"), "2026-11-15");
  await user.type(screen.getByLabelText("Suggested duration (months)"), "12");
  await user.selectOptions(screen.getByLabelText("Source document"), "a1");
  await user.type(screen.getByLabelText("Source evidence"), "Commences on 15 November 2026.");
  await user.click(screen.getByRole("button", { name: "Save suggestion" }));
  await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
  expect(create).toHaveBeenCalledWith({ contractId: "c1", source_attachment_id: "a1",
    suggested_effective_on: "2026-11-15", suggested_expires_on: null, suggested_renewal_on: null,
    suggested_duration_months: 12, evidence_json: { quote: "Commences on 15 November 2026." } });
});
it("retains entered values and displays API rejection without fabricating a success", async () => {
  create.mockRejectedValue(new Error("Source document is unavailable"));
  const { user, onSaved } = setup();
  await user.click(screen.getByRole("button", { name: "Add term suggestion" }));
  await user.type(screen.getByLabelText("Suggested renewal date"), "2027-10-01");
  await user.click(screen.getByRole("button", { name: "Save suggestion" }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("Suggested renewal date")).toHaveValue("2027-10-01");
  expect(onSaved).not.toHaveBeenCalled();
});
