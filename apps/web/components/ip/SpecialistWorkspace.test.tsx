import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ api: vi.fn(), push: vi.fn(), capability: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ apiRequest: mocks.api }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("@/lib/capabilities", () => ({ useCapability: mocks.capability }));

import { specialistRecordSchema, type SpecialistContract } from "@/lib/api/ip-specialist";
import { SpecialistDetail, SpecialistForm, SpecialistIndex } from "./SpecialistWorkspace";

const id = "10000000-0000-4000-8000-000000000001";
const clientId = "10000000-0000-4000-8000-000000000002";
const record = specialistRecordSchema.parse({ id, docket_id: "10000000-0000-4000-8000-000000000003",
  asset_id: "10000000-0000-4000-8000-000000000004", contract_version: "OTHER-IP-2026-09-09.1",
  version: 1, lifecycle_version: 0, lifecycle_status: "draft", is_active: true, created_at: "2026-09-09T00:00:00Z",
  facts: { title: "Lamp representation", client_id: clientId, jurisdiction_as_supplied: "India as supplied",
    details: { domain: "design", applicant: "Client applicant", article: "Lamp casing",
      classification_as_supplied: null, novelty_statement: null, representation_description: null, publication_instruction: "unknown" } } });
const contract: SpecialistContract = { domain: "design", label: "Designs", contract_version: "OTHER-IP-2026-09-09.1",
  contract_path: "docs/ip-implementation/child-prds/design-2026-09-09.md", child_prd_sha256: "a".repeat(64),
  intake_available: true, blockers: ["release_evidence_missing"], observation_kinds: ["representation_set"],
  fields: [{ key: "applicant", label: "Applicant", kind: "text", required: true, max_length: 500, options: [] },
    { key: "article", label: "Article", kind: "text", required: true, max_length: 500, options: [] }] };

function mount(component: React.ReactNode) {
  const query = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={query}>{component}</QueryClientProvider>);
  return query;
}

describe("Specialist IP typed intake", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.capability.mockReturnValue(true);
    mocks.api.mockImplementation(async (path: string, options?: { method?: string; body?: unknown }) => {
      if (path === "/api/ip/specialist/contracts") return [contract];
      if (path === "/api/clients/") return { clients: [{ id: clientId, name: "Client applicant", is_active: true }] };
      if (path.startsWith("/api/ip/specialist/records?")) return { records: [{ id, domain: "design", title: record.facts.title, version: 1, lifecycle_status: "draft" }], next_cursor: null };
      if (path.endsWith("/corrections") && options?.method === "POST") return { ...record, version: 2, facts: (options.body as { facts: unknown }).facts };
      if (path === `/api/ip/specialist/records/${id}`) return record;
      if (path === "/api/ip/specialist/records" && options?.method === "POST") return { ...record, facts: options.body };
      throw new Error(`Unexpected request: ${path}`);
    });
  });

  it("creates through the canonical nested schema and navigates without error feedback", async () => {
    mount(<SpecialistIndex />);
    await waitFor(() => expect(screen.getByRole("button", { name: "New intake" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "New intake" }));
    await screen.findByRole("option", { name: "Client applicant" });
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "New design" } });
    fireEvent.change(screen.getByLabelText("Client"), { target: { value: clientId } });
    fireEvent.change(screen.getByLabelText("Jurisdiction as supplied"), { target: { value: "India" } });
    fireEvent.change(screen.getByLabelText("Applicant"), { target: { value: "Applicant" } });
    fireEvent.change(screen.getByLabelText("Article"), { target: { value: "Casing" } });
    fireEvent.click(screen.getByRole("button", { name: "Save intake" }));
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith(`/app/ip/specialist/${id}`));
    expect(mocks.api).toHaveBeenCalledWith("/api/ip/specialist/records", expect.objectContaining({ method: "POST", body: expect.objectContaining({
      title: "New design", client_id: clientId, details: expect.objectContaining({ domain: "design", applicant: "Applicant", article: "Casing" }),
    }) }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps unavailable intake disabled without hiding retained records", async () => {
    const original = mocks.api.getMockImplementation()!;
    mocks.api.mockImplementation((path, options) => path === "/api/ip/specialist/contracts" ? Promise.resolve([{ ...contract, intake_available: false }]) : original(path, options));
    mount(<SpecialistIndex />);
    expect(await screen.findByRole("link", { name: "Lamp representation" })).toBeVisible();
    expect(screen.getByRole("button", { name: "New intake" })).toBeDisabled();
    expect(screen.getByText("Intake unavailable")).toBeVisible();
  });

  it("renders boolean contract fields as labelled, shrink-resistant controls", async () => {
    const booleanContract = { ...contract, domain: "copyright" as const,
      fields: [...contract.fields, { key: "ownership_disputed", label: "Ownership disputed", kind: "boolean" as const,
        required: false, max_length: null, options: [] }] };
    mount(<SpecialistForm contract={booleanContract} onSaved={vi.fn()} onCancel={vi.fn()} />);
    const checkbox = await screen.findByRole("checkbox", { name: "Ownership disputed" });
    expect(checkbox).toHaveClass("h-4", "w-4", "shrink-0");
    expect(checkbox.closest("label")).toHaveTextContent("Ownership disputed");
  });

  it("waits for authoritative hydration and freezes the edit concurrency token across a background read", async () => {
    let resolve!: (value: unknown) => void;
    const original = mocks.api.getMockImplementation()!;
    mocks.api.mockImplementation((path, options) => path === `/api/ip/specialist/records/${id}` ? new Promise((done) => { resolve = done; }) : original(path, options));
    const query = mount(<SpecialistDetail recordId={id} />);
    expect(screen.queryByRole("button", { name: "Correct intake" })).not.toBeInTheDocument();
    await waitFor(() => expect(resolve).toBeDefined());
    resolve(record);
    fireEvent.click(await screen.findByRole("button", { name: "Correct intake" }));
    await waitFor(() => expect(screen.getByLabelText("Title")).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Unsaved transcription" } });
    query.setQueryData(["ip", "specialist-record", id], { ...record, version: 2, facts: { ...record.facts, title: "Concurrent title" } });
    await screen.findByRole("heading", { name: "Concurrent title" });
    expect(screen.getByLabelText("Title")).toHaveValue("Unsaved transcription");
    fireEvent.change(screen.getByLabelText("Correction reason"), { target: { value: "Correct transcription" } });
    fireEvent.click(screen.getByRole("button", { name: "Save intake" }));
    await waitFor(() => expect(mocks.api).toHaveBeenCalledWith(`/api/ip/specialist/records/${id}/corrections`, expect.objectContaining({
      body: expect.objectContaining({ expected_version: 1, expected_lifecycle_version: 0, facts: expect.objectContaining({ title: "Unsaved transcription" }) }),
    })));
  });

  it("preserves rejected edits and displays the failure", async () => {
    const original = mocks.api.getMockImplementation()!;
    mocks.api.mockImplementation((path, options) => path.endsWith("/corrections") ? Promise.reject(new Error("Source access changed")) : original(path, options));
    mount(<SpecialistDetail recordId={id} />);
    fireEvent.click(await screen.findByRole("button", { name: "Correct intake" }));
    await waitFor(() => expect(screen.getByLabelText("Title")).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Retained draft" } });
    fireEvent.change(screen.getByLabelText("Correction reason"), { target: { value: "Transcription correction" } });
    fireEvent.click(screen.getByRole("button", { name: "Save intake" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Source access changed");
    expect(screen.getByLabelText("Title")).toHaveValue("Retained draft");
    expect(mocks.push).not.toHaveBeenCalled();
  });
});
