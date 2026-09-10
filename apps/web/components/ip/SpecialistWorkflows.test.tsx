import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ apiRequest: mocks.api }));
vi.mock("@/lib/capabilities", () => ({ useCapability: () => true }));

import { specialistRecordSchema } from "@/lib/api/ip-specialist";
import { obligationSchema, workflowKey, workflowRecordSchema } from "@/lib/api/ip-specialist-workflows";
import { ContractWork, WorkflowForm } from "./SpecialistWorkflows";

const id = (n: number) => `10000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const source = { document_id: id(5), document_version_id: id(6), content_sha256: "a".repeat(64), locator: "Clause 9" };
const record = specialistRecordSchema.parse({ id: id(1), docket_id: id(2), asset_id: id(3), contract_version: "OTHER-IP-2026-09-10.2",
  version: 1, lifecycle_version: 0, lifecycle_status: "draft", is_active: true, created_at: "2026-09-10T00:00:00Z",
  facts: { title: "Instrument", client_id: id(4), jurisdiction_as_supplied: "As supplied", details: {
    domain: "licensing", grantor: "Owner", grantee: "Licensee", affected_rights_as_supplied: "Work", territory: "As supplied",
  } },
});
const workflow = workflowRecordSchema.parse({ id: id(7), record_id: record.id, version: 2, lifecycle_version: 0,
  canonical_proceeding_id: null, canonical_title_interest_id: id(8), recorded_at: "2026-09-10T00:00:00Z", facts: {
    kind: "licence", title: "Reviewed licence", source_set: { id: id(9), version: 1 }, occurred_on: "2026-09-10", account: "Retained agreement",
    grantor: "Owner", grantee: "Licensee", transaction: "licence", exclusivity: "nonexclusive", rights: "Reproduction", territory: "As supplied",
    field_of_use: "Clause 1", sublicensing: "Clause 2", quality_control: "Clause 3", prosecution_control: "Clause 4", enforcement_control: "Clause 5",
    renewal_terms: "Clause 6", termination_terms: "Clause 7", notice_terms: "Clause 8", effective_from: "2026-01-01", interpretation: "reviewed", review_reason: "Reviewed clauses", status: "active",
  } });
const work = obligationSchema.parse({ id: id(10), task_id: id(11), deadline_id: id(12), due_on: "2026-10-01", kind: "notice", title: "Notice due", status: "open", source, cost_item_id: null });
const base = `/api/ip/specialist/records/${record.id}/workflows/${workflow.id}/obligations`;
const receipt = { id: id(13), obligation_id: work.id, action: "complete", occurred_on: "2026-09-10", account: "Notice delivered with retained receipt", source, cost_item_id: null, recorded_at: "2026-09-10T01:00:00Z" };

function mount(canWrite = true) {
  const query = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={query}><ContractWork record={record} workflow={workflow} canWrite={canWrite}
    options={[{ label: "Receipt / Version 1", source }]} /></QueryClientProvider>);
  return query;
}

async function fillPerformance() {
  fireEvent.click(await screen.findByRole("button", { name: "Performance history" }));
  const form = await screen.findByRole("form", { name: "Record contract performance" });
  fireEvent.change(within(form).getByLabelText("Performance date"), { target: { value: receipt.occurred_on } });
  fireEvent.change(within(form).getByLabelText("Performance evidence account"), { target: { value: receipt.account } });
  fireEvent.change(within(form).getByLabelText("Source document version"), { target: { value: source.document_version_id } });
  fireEvent.change(within(form).getByLabelText("Page or locator"), { target: { value: source.locator } });
  return form;
}

describe("Contract obligations and performance", () => {
  beforeEach(() => {
    let completed = false;
    mocks.api.mockReset();
    mocks.api.mockImplementation(async (path: string, options?: { method?: string }) => {
      if (path.endsWith("/cost-options")) return { records: [], next_cursor: null };
      if (path === base && !options?.method) return { records: [{ ...work, status: completed ? "completed" : "open" }], next_cursor: null };
      if (path === `${base}/${work.id}/performance` && options?.method === "POST") { completed = true; return receipt; }
      if (path === `${base}/${work.id}/performance`) return { records: completed ? [receipt] : [], next_cursor: null };
      throw new Error(`Unexpected request: ${path}`);
    });
  });

  it("completes an obligation, reloads its status and shows exact retained performance without an alert", async () => {
    mount();
    const form = await fillPerformance();
    fireEvent.submit(form);
    expect(await screen.findByText("2026-10-01 / completed")).toBeVisible();
    expect(within(screen.getByRole("list", { name: "Performance evidence" })).getByText(receipt.account)).toBeVisible();
    expect(screen.queryByRole("form", { name: "Record contract performance" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(mocks.api).toHaveBeenCalledWith(`${base}/${work.id}/performance`, expect.objectContaining({ method: "POST",
      body: { action: "complete", occurred_on: receipt.occurred_on, account: receipt.account, source, replacement_cost_item_id: null, expected_lifecycle_version: 0, expected_status: "open" },
    }));
  });

  it("retains rejected performance inputs and unchanged evidence", async () => {
    const original = mocks.api.getMockImplementation()!;
    mocks.api.mockImplementation((path, options) => options?.method === "POST" ? Promise.reject(new Error("Contract source retired")) : original(path, options));
    mount();
    fireEvent.submit(await fillPerformance());
    expect(await screen.findByRole("alert")).toHaveTextContent("Contract source retired");
    expect(screen.getByLabelText("Performance evidence account")).toHaveValue(receipt.account);
    expect(screen.getByText("2026-10-01 / open")).toBeVisible();
    expect(screen.getByText("No performance evidence recorded.")).toBeVisible();
    expect(screen.queryByText("Performance evidence retained.")).not.toBeInTheDocument();
  });

  it("does not offer creation before authoritative discovery or after discovery fails", async () => {
    let reject!: (error: Error) => void;
    mocks.api.mockImplementation(() => new Promise((_, fail) => { reject = fail; }));
    mount();
    expect(screen.queryByRole("button", { name: "Create obligation" })).not.toBeInTheDocument();
    await waitFor(() => expect(reject).toBeDefined());
    reject(new Error("Obligation access unavailable"));
    expect(await screen.findByText("Could not load obligations")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Create obligation" })).not.toBeInTheDocument();
  });

  it("retains read-only history without exposing operational commands on a terminal parent", async () => {
    mount(false);
    fireEvent.click(await screen.findByRole("button", { name: "Performance history" }));
    expect(await screen.findByText("No performance evidence recorded.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Record performance" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create obligation" })).not.toBeInTheDocument();
  });

  it("records sourced nonbillable cost evidence without a client-invented identifier", async () => {
    const original = mocks.api.getMockImplementation()!;
    mocks.api.mockImplementation((path, options) => path.endsWith("/cost-evidence") && options?.method === "POST"
      ? Promise.resolve({ id: id(14), description: "Receipt amount" }) : original(path, options));
    mount();
    const summary = await screen.findByText("Nonbillable cost evidence");
    fireEvent.click(summary);
    const form = screen.getByRole("form", { name: "Record cost evidence" });
    fireEvent.change(within(form).getByLabelText("Amount in minor currency units"), { target: { value: "25000" } });
    fireEvent.change(within(form).getByLabelText("Currency code"), { target: { value: "inr" } });
    fireEvent.change(within(form).getByLabelText("Cost description"), { target: { value: "Receipt amount" } });
    fireEvent.change(within(form).getByLabelText("Source document version"), { target: { value: source.document_version_id } });
    fireEvent.change(within(form).getByLabelText("Page or locator"), { target: { value: source.locator } });
    fireEvent.submit(form);
    expect(await screen.findByText("Cost evidence retained.")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(mocks.api).toHaveBeenCalledWith(base.replace(/\/obligations$/, "/cost-evidence"), expect.objectContaining({ body: {
      description: "Receipt amount", amount_minor: 25000, currency: "INR", cost_nature: "actual", source, expected_lifecycle_version: 0,
    } }));
  });

  it("pages reference choices independently, preserves edits and explicitly selects the exact new source revision", async () => {
    const query = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const sourceSet = workflowRecordSchema.parse({ id: id(9), record_id: record.id, version: 2, lifecycle_version: 0,
      canonical_proceeding_id: null, canonical_title_interest_id: null, recorded_at: "2026-09-10T00:00:00Z",
      facts: { kind: "source_set", purpose: "instrument", title: "Older retained instrument", members: [{ role: "Agreement", source }] } });
    query.setQueryData([...workflowKey(record.id), "list", undefined], { records: Array.from({ length: 10 }, (_, n) => ({
      ...sourceSet, id: id(20 + n), facts: { ...sourceSet.facts, purpose: "proceeding_evidence", title: `Proceeding ${n}` },
    })), next_cursor: id(29) });
    const onSaved = vi.fn();
    mocks.api.mockImplementation(async (path, options) => {
      if (path.endsWith(`?limit=10&cursor=${id(29)}`)) return { records: [sourceSet], next_cursor: null };
      if (path.endsWith("/revisions") && options?.method === "POST") return { ...workflow, version: 3, facts: options.body.facts };
      throw new Error(`Unexpected request: ${path}`);
    });
    render(<QueryClientProvider client={query}><WorkflowForm record={record} kind="licence" initial={workflow} options={[]}
      onSaved={onSaved} onCancel={vi.fn()} /></QueryClientProvider>);
    expect(mocks.api).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("title"), { target: { value: "Unsaved revised licence" } });
    fireEvent.change(screen.getByLabelText("Revision reason"), { target: { value: "Replace with retained amendment" } });
    fireEvent.click(screen.getByRole("button", { name: "Next reference page" }));
    expect(await screen.findByRole("option", { name: "Older retained instrument / Version 2" })).toBeInTheDocument();
    expect(screen.getByLabelText("title")).toHaveValue("Unsaved revised licence");
    expect(screen.getByLabelText("Source set")).toHaveValue(`${id(9)}:1`);
    expect(screen.getByRole("option", { name: "Retained source set / Version 1" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Source set"), { target: { value: `${id(9)}:2` } });
    fireEvent.click(screen.getByRole("button", { name: "First reference page" }));
    expect(screen.getByLabelText("Source set")).toHaveValue(`${id(9)}:2`);
    expect(screen.getByLabelText("title")).toHaveValue("Unsaved revised licence");
    fireEvent.submit(screen.getByRole("form", { name: "Revise domain workflow" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
    expect(onSaved.mock.calls[0][0]).toEqual(expect.objectContaining({ version: 3,
      facts: expect.objectContaining({ title: "Unsaved revised licence", source_set: { id: id(9), version: 2 } }),
    }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(mocks.api.mock.calls.filter(([, options]) => !options?.method)).toHaveLength(1);
  });

  it("retains edits and permits cancellation when independent reference discovery fails", async () => {
    const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    query.setQueryData([...workflowKey(record.id), "list", undefined], { records: [], next_cursor: id(29) });
    const cancel = vi.fn();
    mocks.api.mockRejectedValue(new Error("Reference access was revoked"));
    render(<QueryClientProvider client={query}><WorkflowForm record={record} kind="licence" initial={workflow} options={[]}
      onSaved={vi.fn()} onCancel={cancel} /></QueryClientProvider>);
    fireEvent.change(screen.getByLabelText("title"), { target: { value: "Retained local edit" } });
    fireEvent.click(screen.getByRole("button", { name: "Next reference page" }));
    expect(await screen.findByText("Could not load reference choices")).toBeVisible();
    expect(screen.getByLabelText("title")).toHaveValue("Retained local edit");
    expect(screen.getByRole("button", { name: "Save revision" })).toBeDisabled();
    fireEvent.submit(screen.getByRole("form", { name: "Revise domain workflow" }));
    expect(mocks.api.mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(cancel).toHaveBeenCalledOnce();
  });
});
