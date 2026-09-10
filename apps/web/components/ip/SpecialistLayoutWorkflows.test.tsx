import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ api: vi.fn(), documents: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ apiRequest: mocks.api }));
vi.mock("@/lib/api/endpoints", () => ({ fetchIpDocumentsForDocket: mocks.documents }));
vi.mock("@/lib/capabilities", () => ({ useCapability: () => true }));

import { specialistRecordSchema } from "@/lib/api/ip-specialist";
import { workflowFactsSchema, workflowRecordSchema, type WorkflowRecord } from "@/lib/api/ip-specialist-workflows";
import { SpecialistWorkflows } from "./SpecialistWorkflows";

const id = (n: number) => `20000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const pin = { document_id: id(5), document_version_id: id(6), content_sha256: "a".repeat(64), locator: "Sheet 1" };
const registryPin = { document_id: id(15), document_version_id: id(16), content_sha256: "b".repeat(64), locator: "Publication page 2" };
const record = specialistRecordSchema.parse({ id: id(1), docket_id: id(2), asset_id: id(3), contract_version: "OTHER-IP-2026-09-10.3",
  version: 1, lifecycle_version: 0, lifecycle_status: "draft", is_active: true, created_at: "2026-09-10T00:00:00Z",
  facts: { title: "Restricted semiconductor layout", client_id: id(4), jurisdiction_as_supplied: "Supplied jurisdiction", details: {
    domain: "semiconductor_layout", creator: "Source creator", proprietor_as_supplied: "Client", layout_description: "Retained deposit",
  } },
});
const envelope = { record_id: record.id, version: 1, lifecycle_version: 0, canonical_proceeding_id: null, canonical_title_interest_id: null, recorded_at: "2026-09-10T00:00:00Z" };
const deposit = workflowRecordSchema.parse({ ...envelope, id: id(7), facts: { kind: "source_set", purpose: "layout_deposit", title: "Restricted layout deposit", members: [{ role: "Layout", source: pin }] } });
const prepared = workflowRecordSchema.parse({ ...envelope, id: id(8), facts: { kind: "layout_application", title: "Layout application", source_set: { id: deposit.id, version: 1 },
  occurred_on: "2026-09-10", account: "Source-reported application", registry: "Source office", jurisdiction: "Supplied jurisdiction" } });
const base = `/api/ip/specialist/records/${record.id}/workflows`;
let saved: WorkflowRecord;

function mount() {
  const query = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={query}><SpecialistWorkflows record={record} canWrite onEvidence={vi.fn()} /></QueryClientProvider>);
}
async function openApplication() {
  const list = await screen.findByRole("list", { name: "Saved domain workflows" });
  const row = (await within(list).findByText("Layout application")).closest("li")!;
  fireEvent.click(within(row).getByRole("button", { name: "Open" }));
  return screen.findByRole("form", { name: "Revise domain workflow" });
}

describe("Source-bounded layout workflows", () => {
  beforeEach(() => {
    saved = structuredClone(prepared);
    mocks.api.mockReset();
    mocks.documents.mockResolvedValue({ items: [pin, registryPin].map((source, index) => ({ id: source.document_id,
      title: index ? "Registry publication" : "Layout deposit", versions: [{ id: source.document_version_id, version: 1, state: "retained", sha256_hex: source.content_sha256 }] })) });
    mocks.api.mockImplementation(async (path: string, options?: { method?: string; body?: { facts: unknown } }) => {
      if (path === `${base}?limit=10`) return { records: [deposit, saved], next_cursor: null };
      if (path.endsWith("/cost-options") || path.endsWith("/obligations")) return { records: [], next_cursor: null };
      if (path === `${base}/${saved.id}/revisions` && options?.method === "POST") {
        saved = workflowRecordSchema.parse({ ...saved, version: saved.version + 1, facts: options.body?.facts });
        return saved;
      }
      throw new Error(`Unexpected request: ${path}`);
    });
  });

  it("files a layout application with the canonical source pin, renders the saved stage and reloads without error feedback", async () => {
    const view = mount();
    const form = await openApplication();
    fireEvent.change(within(form).getByLabelText("stage"), { target: { value: "filed" } });
    fireEvent.change(within(form).getByLabelText("identifier as supplied"), { target: { value: "LAYOUT-F-42" } });
    fireEvent.change(within(form).getByLabelText("Revision reason"), { target: { value: "Retained filing receipt" } });
    fireEvent.submit(form);
    expect(await screen.findByText("layout application / Version 2 / filed")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(saved.facts).toMatchObject({ kind: "layout_application", stage: "filed", identifier_as_supplied: "LAYOUT-F-42",
      source_set: { id: deposit.id, version: 1 }, legal_eligibility: "not_determined", rights_effect: "not_determined_by_registration" });
    view.unmount();
    mount();
    const reloaded = await openApplication();
    expect(within(reloaded).getByLabelText("stage")).toHaveValue("filed");
    expect(within(reloaded).getByLabelText("identifier as supplied")).toHaveValue("LAYOUT-F-42");
    expect(screen.getByRole("region", { name: "Layout application work" })).toBeVisible();
    expect(screen.queryByRole("region", { name: "Contract obligations" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("retains registry publication inputs when current source validation rejects the save", async () => {
    const original = mocks.api.getMockImplementation()!;
    mocks.api.mockImplementation((path, options) => options?.method === "POST" ? Promise.reject(new Error("Registry source retired")) : original(path, options));
    mount();
    const form = await openApplication();
    fireEvent.change(within(form).getByLabelText("publication"), { target: { value: "reported_published" } });
    fireEvent.change(within(form).getByLabelText("publication on"), { target: { value: "2026-09-10" } });
    fireEvent.change(within(form).getByLabelText("Source document version"), { target: { value: registryPin.document_version_id } });
    fireEvent.change(within(form).getByLabelText("Page or locator"), { target: { value: registryPin.locator } });
    fireEvent.change(within(form).getByLabelText("Revision reason"), { target: { value: "Source-reported registry publication" } });
    fireEvent.submit(form);
    expect(await screen.findByRole("alert")).toHaveTextContent("Registry source retired");
    expect(within(form).getByLabelText("publication")).toHaveValue("reported_published");
    expect(within(form).getByLabelText("Page or locator")).toHaveValue(registryPin.locator);
    expect(saved).toEqual(prepared);
    expect(screen.getByText("layout application / Version 1 / prepared")).toBeVisible();
  });

  it("does not offer deposit publication or trademark proceeding channels for a layout", async () => {
    mount();
    await screen.findByRole("list", { name: "Saved domain workflows" });
    await waitFor(() => expect(screen.getByRole("button", { name: "New workflow" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "New workflow" }));
    expect(screen.getByLabelText("purpose")).toHaveValue("layout_deposit");
    expect(screen.getByLabelText("confidentiality")).toHaveValue("restricted");
    expect(screen.queryByRole("option", { name: "publication authorized" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Cancel$/ }));
    fireEvent.change(screen.getByLabelText("Workflow", { exact: true }), { target: { value: "proceeding" } });
    fireEvent.click(screen.getByRole("button", { name: "New workflow" }));
    expect(screen.getByRole("option", { name: "layout opposition" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "design cancellation" })).not.toBeInTheDocument();
  });

  it("strictly validates the complete nested layout evidence contract", () => {
    expect(workflowFactsSchema.safeParse({ ...prepared.facts, legal_eligibility: "verified" }).success).toBe(false);
    expect(workflowFactsSchema.safeParse({ ...prepared.facts, publication: "reported_published", publication_on: "2026-09-10" }).success).toBe(false);
    expect(workflowFactsSchema.safeParse({ ...prepared.facts, registry_source: { ...registryPin, invented: true } }).success).toBe(false);
    expect(workflowFactsSchema.safeParse({ ...prepared.facts, first_exploitation_on_as_supplied: "2025-01-01" }).success).toBe(false);
  });

  it("clears publication-only evidence when a supplied publication is withdrawn", async () => {
    saved = workflowRecordSchema.parse({ ...prepared, facts: { ...prepared.facts,
      publication: "reported_published", publication_on: "2026-09-10", registry_source: registryPin } });
    mount();
    const form = await openApplication();
    fireEvent.change(within(form).getByLabelText("publication"), { target: { value: "not_recorded" } });
    expect(within(form).queryByLabelText("Page or locator")).not.toBeInTheDocument();
    expect(within(form).getByLabelText("publication on")).toHaveValue("");
    fireEvent.change(within(form).getByLabelText("Revision reason"), { target: { value: "Correct withdrawn report" } });
    fireEvent.submit(form);
    expect(await screen.findByText("layout application / Version 2 / prepared")).toBeVisible();
    expect(saved.facts).toMatchObject({ publication: "not_recorded", publication_on: null, registry_source: null });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
