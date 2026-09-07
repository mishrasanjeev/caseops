import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PatentFamily, PatentParty, PatentPartyPage } from "@/lib/api/ip-patents";

const mocks = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn(), sources: vi.fn(), clients: vi.fn(), download: vi.fn(), document: vi.fn() }));
vi.mock("@/lib/api/ip-patents", async (original) => ({
  ...await original<typeof import("@/lib/api/ip-patents")>(), fetchPatentParties: mocks.list, createPatentParty: mocks.create,
}));
vi.mock("@/lib/api/endpoints", () => ({
  fetchIpDocumentsForDocket: mocks.sources, listClients: mocks.clients,
  fetchIpDocument: mocks.document, downloadApiFile: mocks.download,
}));
import { PatentParties } from "./PatentParties";

const id = (last: string) => `10000000-0000-4000-8000-00000000000${last}`;
const source = { kind: "document_version" as const, document_id: id("4"), document_version_id: id("5"), content_sha256: "a".repeat(64) };
const family: PatentFamily = {
  id: id("1"), docket_id: id("2"), asset_id: id("3"), record_kind: "patent_family", version: 1,
  lifecycle_version: 0, lifecycle_status: "draft", is_active: true,
  created_at: "2026-09-07T00:00:00Z", updated_at: "2026-09-07T00:00:00Z",
  facts: { title: "Family", client_id: id("6"), disclosure_date: "2026-09-05",
    disclosure_narrative: "Original disclosure", confidentiality: "restricted", source: null },
};
const party: PatentParty = {
  id: id("7"), docket_id: family.docket_id, sequence: 1, anchor_version: 1, lifecycle_version: 0,
  supersedes_party_id: null, is_current: true, reason: "Original signed inventor facts.", created_at: family.created_at,
  fact: { role: "inventor", name: "Original inventor", client_id: null,
    address: { address_lines: ["Original street", "Unit 2"], city: "Delhi", region: "Delhi", postal_code: "110001", country_code: "IN" },
    effective_from: "2026-09-01", effective_until: null, source },
};
const page: PatentPartyPage = { docket_id: family.docket_id, collection_sequence: 1, parties: [party], next_cursor: null };
const replacement: PatentParty = { ...party, id: id("8"), sequence: 2, supersedes_party_id: party.id,
  fact: { ...party.fact, name: "Saved inventor" }, reason: "Correct the source transcription." };
const key = ["ip", "patent-parties", family.docket_id, false, null, null];
function mount(record = family, canWrite = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const open = vi.fn();
  const result = render(<QueryClientProvider client={client}><PatentParties record={record} canWrite={canWrite} onOpenDocuments={open} /></QueryClientProvider>);
  return { client, open, ...result };
}
async function edit() {
  const button = await screen.findByRole("button", { name: "Replace facts" });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await screen.findByRole("option", { name: "Signed source - version 1" });
  return screen.getByRole("form", { name: "Replace patent party" });
}

describe("Sourced patent party workspace", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.list.mockResolvedValue(page);
    mocks.create.mockImplementation(async () => {
      mocks.list.mockResolvedValue({ ...page, collection_sequence: 2, parties: [replacement] });
      return replacement;
    });
    mocks.sources.mockResolvedValue({ items: [{ id: source.document_id, title: "Signed source", versions: [{ id: source.document_version_id, version: 1, sha256_hex: source.content_sha256 }] }], total: 1 });
    mocks.clients.mockResolvedValue({ clients: [{ id: family.facts.client_id, name: "Saved client", is_active: true }] });
  });

  it("waits for authoritative discovery, then hydrates every saved field before editing", async () => {
    let resolve!: (value: PatentPartyPage) => void;
    mocks.list.mockReturnValue(new Promise<PatentPartyPage>((done) => { resolve = done; }));
    mount();
    expect(screen.getByRole("button", { name: "Add party" })).toBeDisabled();
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
    await act(async () => resolve(page));
    const form = await edit();
    expect(within(form).getByLabelText("Party name")).toHaveValue(party.fact.name);
    expect(within(form).getByLabelText("Address lines")).toHaveValue("Original street\nUnit 2");
    expect(within(form).getByLabelText("Country code")).toHaveValue("IN");
    expect(within(form).getByLabelText("Effective from")).toHaveValue("2026-09-01");
    expect(within(form).getByLabelText("Party source version")).toHaveValue(source.document_version_id);
    expect(mocks.create).not.toHaveBeenCalled();
  });

  it("retains unsaved edits and their original collection version across a background read", async () => {
    const { client } = mount();
    const form = await edit();
    fireEvent.change(within(form).getByLabelText("Party name"), { target: { value: "Unsaved inventor" } });
    act(() => { client.setQueryData(key, { ...page, collection_sequence: 3 }); });
    expect(within(form).getByLabelText("Party name")).toHaveValue("Unsaved inventor");
    fireEvent.change(within(form).getByLabelText("Party change reason"), { target: { value: "Keep original review boundary." } });
    fireEvent.click(within(form).getByRole("button", { name: "Save party facts" }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(family, 1,
      { ...party.fact, name: "Unsaved inventor" }, "Keep original review boundary.", party.id, expect.stringMatching(/^[a-f0-9-]{36}$/)));
  });

  it("cancels an older in-flight list read so it cannot erase a successful replacement", async () => {
    const { client } = mount();
    const form = await edit();
    let resolveOld!: (value: PatentPartyPage) => void;
    let oldSignal: AbortSignal | undefined;
    mocks.list.mockImplementationOnce((_id, _history, _continuation, signal) => {
      oldSignal = signal;
      return new Promise<PatentPartyPage>((done) => { resolveOld = done; });
    });
    act(() => { void client.invalidateQueries({ queryKey: key, exact: true }); });
    await waitFor(() => expect(oldSignal).toBeDefined());
    fireEvent.change(within(form).getByLabelText("Party change reason"), { target: { value: replacement.reason } });
    fireEvent.click(within(form).getByRole("button", { name: "Save party facts" }));
    await screen.findByRole("heading", { name: "Saved inventor" });
    expect(oldSignal!.aborted).toBe(true);
    await act(async () => resolveOld(page));
    expect(screen.getByRole("heading", { name: "Saved inventor" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Original inventor" })).not.toBeInTheDocument();
    expect(mocks.create).toHaveBeenCalledOnce();
  });

  it("does not admit a blank create path when discovery fails", async () => {
    mocks.list.mockRejectedValue(new Error("Party access revoked"));
    mount();
    await screen.findByText("Could not load patent parties");
    expect(screen.getByRole("button", { name: "Add party" })).toBeDisabled();
    expect(screen.queryByLabelText("Party name")).not.toBeInTheDocument();
    expect(mocks.sources).not.toHaveBeenCalled();
  });

  it("shows source-load failure and blocks saving without silently substituting evidence", async () => {
    mocks.sources.mockRejectedValue(new Error("Source unavailable"));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Replace facts" }));
    await screen.findByText("Could not load party sources");
    expect(screen.getByRole("button", { name: "Save party facts" })).toBeDisabled();
    expect(mocks.create).not.toHaveBeenCalled();
  });

  it("keeps superseded history and closed records readable without offering mutations", async () => {
    mocks.list.mockImplementation((_id, history) => Promise.resolve(history
      ? { ...page, parties: [{ ...party, is_current: false }] } : page));
    mount({ ...family, is_active: false, lifecycle_status: "closed", lifecycle_version: 1 });
    await screen.findByRole("heading", { name: "Original inventor" });
    expect(screen.queryByRole("button", { name: "Add party" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Replace facts" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Include superseded facts"));
    await screen.findByText("Superseded");
    expect(screen.getByRole("button", { name: "Download source version" })).toBeVisible();
  });

  it("preserves a stale draft until the user explicitly reloads the record", async () => {
    mocks.create.mockRejectedValue(new Error("The record or parties changed. Reload before saving."));
    mount();
    const form = await edit();
    fireEvent.change(within(form).getByLabelText("Party change reason"), { target: { value: "Sourced replacement facts." } });
    fireEvent.click(within(form).getByRole("button", { name: "Save party facts" }));
    await within(form).findByRole("alert");
    expect(within(form).getByLabelText("Party name")).toHaveValue(party.fact.name);
    fireEvent.click(within(form).getByRole("button", { name: "Reload record" }));
    await waitFor(() => expect(screen.queryByRole("form")).not.toBeInTheDocument());
    expect(mocks.create).toHaveBeenCalledOnce();
  });
});
