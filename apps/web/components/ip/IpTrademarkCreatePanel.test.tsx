import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { createManualTrademarkApplicationMock, fetchIpNiceClassesMock, listMattersMock } = vi.hoisted(() => ({
  createManualTrademarkApplicationMock: vi.fn(),
  fetchIpNiceClassesMock: vi.fn(),
  listMattersMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  TRADEMARK_MARK_KINDS: ["word", "device", "composite", "label", "colour", "shape", "sound", "other"],
  createManualTrademarkApplication: createManualTrademarkApplicationMock,
  fetchIpNiceClasses: fetchIpNiceClassesMock,
  listMatters: listMattersMock,
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { IpTrademarkCreatePanel } from "@/components/ip/IpTrademarkCreatePanel";
import { ApiError } from "@/lib/api/config";

const MATTERS = [
  { id: "matter-aster", title: "Aster brand clearance", matter_code: "IP-001", client_name: "Aster LLP" },
  { id: "matter-birch", title: "Birch portfolio", matter_code: "IP-002", client_name: "Birch Ltd" },
];

function catalogue() {
  return {
    edition: "NCL 13-2026",
    in_force_from: "2026-01-01",
    source_url: "https://nclpub.wipo.int/enfr/?version=20260101",
    source_data_url: "https://www.wipo.int/classifications/data/nice/20260101.zip",
    retrieved_on: "2026-10-31",
    headings_sha256: "a".repeat(64),
    attribution: "Nice Classification, 13th edition, version 2026 (NCL 13-2026). Copyright World Intellectual Property Organization (WIPO).",
    classes: Array.from({ length: 45 }, (_, index) => ({
      number: index + 1,
      kind: index + 1 <= 34 ? "goods" : "services",
      heading: index + 1 === 9 ? "Scientific apparatus; computer software." : `Class ${index + 1} heading.`,
      note: null,
    })),
  };
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const onCreated = vi.fn();
  const view = render(
    <QueryClientProvider client={client}>
      <IpTrademarkCreatePanel onCreated={onCreated} onCancel={vi.fn()} />
    </QueryClientProvider>,
  );
  return { ...view, onCreated };
}

async function fillApplication(user: ReturnType<typeof userEvent.setup>, mark = "ASTER") {
  await user.type(screen.getByLabelText("Docket title"), "Aster filing");
  await user.type(screen.getByLabelText("Word mark"), mark);
  await user.type(screen.getByLabelText("Applicant"), "Aster Applicant LLP");
  await user.type(screen.getByLabelText("Representation evidence reference"), "attachment:aster");
  const picker = screen.getByRole("combobox", { name: "Nice class, row 1" });
  await waitFor(() => expect(picker).toBeEnabled());
  await user.click(picker);
  await user.type(picker, "9");
  await user.click(within(screen.getByRole("listbox")).getByRole("option", { name: /^Class 9, goods:/ }));
  await user.type(screen.getByLabelText("Goods and services, row 1"), "Downloadable software");
}

const created = {
  docket: { id: "docket-new" },
  asset: { id: "asset-new" },
  application: { id: "application-new" },
  identifier: null,
  duplicate_candidates: [],
};

describe("IpTrademarkCreatePanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchIpNiceClassesMock.mockResolvedValue(catalogue());
    listMattersMock.mockResolvedValue({ matters: MATTERS, next_cursor: null });
    createManualTrademarkApplicationMock.mockResolvedValue(created);
  });

  it("BUG-001 shows the Matter list loading, then names the empty state and the path to create a Matter", async () => {
    let resolve: (value: unknown) => void = () => {};
    listMattersMock.mockReturnValue(new Promise((done) => { resolve = done; }));
    renderPanel();

    const matter = screen.getByRole("combobox", { name: "Matter" });
    expect(matter).toBeDisabled();
    expect(screen.getByText("Loading matters…")).toBeVisible();

    resolve({ matters: [], next_cursor: null });
    expect(await screen.findByText(/No matters yet\./)).toBeVisible();
    expect(screen.getByRole("link", { name: "create a Matter" })).toHaveAttribute("href", "/app/matters");
    // Only "No Matter" would be offered, so the select is not a dead control.
    expect(matter).toBeDisabled();
    expect(matter.getAttribute("aria-describedby")).toContain("ip-tm-matter-status");
  });

  it("BUG-001 offers a retry when the Matter list fails, then lists the matters", async () => {
    const user = userEvent.setup();
    listMattersMock
      .mockRejectedValueOnce(new ApiError(503, "The matter service is unavailable.", null))
      .mockResolvedValue({ matters: MATTERS, next_cursor: null });
    renderPanel();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The matter service is unavailable.");
    expect(screen.getByRole("combobox", { name: "Matter" })).toBeDisabled();
    await user.click(within(alert).getByRole("button", { name: "Try again" }));

    const matter = screen.getByRole("combobox", { name: "Matter" });
    await waitFor(() => expect(matter).toBeEnabled());
    expect(within(matter).getByRole("option", { name: "Aster brand clearance · IP-001 · Aster LLP" })).toBeInTheDocument();
  });

  it("BUG-001 tells a member who cannot list matters that the record is created without one", async () => {
    listMattersMock.mockRejectedValue(new ApiError(403, "Forbidden", null));
    renderPanel();

    expect(await screen.findByText(/Your role cannot list matters/)).toBeVisible();
    expect(screen.getByLabelText("Find a Matter (optional)")).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Matter" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("BUG-001 searches matters on the server, keeps the chosen Matter and sends its id", async () => {
    const user = userEvent.setup();
    listMattersMock.mockImplementation(async ({ q }: { q?: string }) => ({
      matters: q ? MATTERS.filter((row) => row.title.toLowerCase().includes(q.toLowerCase())) : MATTERS,
      next_cursor: null,
    }));
    const { onCreated } = renderPanel();

    const matter = screen.getByRole("combobox", { name: "Matter" });
    await waitFor(() => expect(matter).toBeEnabled());
    await user.selectOptions(matter, "matter-aster");
    await user.type(screen.getByLabelText("Find a Matter (optional)"), "zzz");
    expect(await screen.findByText("No Matter matches “zzz”.")).toBeVisible();
    await waitFor(() => expect(listMattersMock).toHaveBeenCalledWith({ limit: 50, q: "zzz" }));
    // The chosen Matter stays selected and offered although the search no longer returns it.
    expect(matter).toHaveValue("matter-aster");
    expect(within(matter).getByRole("option", { name: "Aster brand clearance · IP-001 · Aster LLP" })).toBeInTheDocument();

    await fillApplication(user);
    await user.click(screen.getByRole("button", { name: "Create application" }));
    await waitFor(() => expect(createManualTrademarkApplicationMock).toHaveBeenCalledTimes(1));
    expect(createManualTrademarkApplicationMock).toHaveBeenCalledWith(expect.objectContaining({ matterId: "matter-aster" }));
    expect(onCreated).toHaveBeenCalledWith(created.docket);
  });

  it("BUG-001 sends no Matter when No Matter is chosen", async () => {
    const user = userEvent.setup();
    renderPanel();

    const matter = screen.getByRole("combobox", { name: "Matter" });
    await waitFor(() => expect(matter).toBeEnabled());
    await user.selectOptions(matter, "matter-birch");
    await user.selectOptions(matter, "");
    await fillApplication(user);
    await user.click(screen.getByRole("button", { name: "Create application" }));
    await waitFor(() => expect(createManualTrademarkApplicationMock).toHaveBeenCalledTimes(1));
    expect(createManualTrademarkApplicationMock).toHaveBeenCalledWith(expect.objectContaining({ matterId: null }));
  });

  it("BUG-002 keeps submit disabled with a reason until the mark has the 2 characters the API requires", async () => {
    const user = userEvent.setup();
    renderPanel();

    await fillApplication(user, "A");
    const submit = screen.getByRole("button", { name: "Create application" });
    expect(submit).toBeDisabled();
    const reason = document.getElementById(submit.getAttribute("aria-describedby")!);
    expect(reason).toHaveTextContent("the word mark (at least 2 characters)");

    await user.type(screen.getByLabelText("Word mark"), "B");
    await waitFor(() => expect(submit).toBeEnabled());
    await user.click(submit);
    await waitFor(() => expect(createManualTrademarkApplicationMock).toHaveBeenCalledTimes(1));
    expect(createManualTrademarkApplicationMock).toHaveBeenCalledWith(
      expect.objectContaining({ assetTitle: "AB", markText: "AB", markKind: "word" }),
    );
  });

  it("BUG-002 records the mark kind the API accepts and trims the mark", async () => {
    const user = userEvent.setup();
    renderPanel();

    const kind = screen.getByRole("combobox", { name: "Mark kind" });
    expect(Array.from((kind as HTMLSelectElement).options).map((option) => option.value)).toEqual([
      "word", "device", "composite", "label", "colour", "shape", "sound", "other",
    ]);
    await fillApplication(user, "  Tiger device  ");
    await user.selectOptions(kind, "device");
    expect(screen.getByLabelText("Mark name or verbal element")).toHaveValue("  Tiger device  ");
    await user.click(screen.getByRole("button", { name: "Create application" }));
    await waitFor(() => expect(createManualTrademarkApplicationMock).toHaveBeenCalledTimes(1));
    expect(createManualTrademarkApplicationMock).toHaveBeenCalledWith(
      expect.objectContaining({ markKind: "device", assetTitle: "Tiger device", markText: "Tiger device" }),
    );
  });
});
