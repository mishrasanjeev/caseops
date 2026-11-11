import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  listMatterStatuteReferencesMock,
  listStatutesMock,
  listStatuteSectionsMock,
  addMatterStatuteReferenceMock,
} = vi.hoisted(() => ({
  listMatterStatuteReferencesMock: vi.fn(),
  listStatutesMock: vi.fn(),
  listStatuteSectionsMock: vi.fn(),
  addMatterStatuteReferenceMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listMatterStatuteReferences: listMatterStatuteReferencesMock,
  listStatutes: listStatutesMock,
  listStatuteSections: listStatuteSectionsMock,
  addMatterStatuteReference: addMatterStatuteReferenceMock,
  deleteMatterStatuteReference: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m-1" }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import MatterStatutesPage from "@/app/app/matters/[id]/statutes/page";

function withClient(children: ReactNode, client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function recoveryCatalog() {
  listMatterStatuteReferencesMock.mockResolvedValue({ matter_id: "m-1", references: [] });
  listStatutesMock.mockResolvedValue({ statutes: [
    { id: "first", short_name: "First", long_name: "Synthetic first Act", section_count: 1 },
    { id: "second", short_name: "Second", long_name: "Synthetic second Act", section_count: 1 },
  ] });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

async function openOptions(name: string) {
  const trigger = screen.getByRole("combobox", { name });
  await waitFor(() => expect(trigger).toBeEnabled());
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false, pointerType: "mouse" });
  return screen.getByRole("listbox");
}

describe("MatterStatutesPage", () => {
  beforeEach(() => {
    listMatterStatuteReferencesMock.mockReset();
    listStatutesMock.mockReset();
    listStatuteSectionsMock.mockReset();
    addMatterStatuteReferenceMock.mockReset();
  });

  it("BUG-002 uses a bounded portalled list for long Act captions inside the modal", async () => {
    listMatterStatuteReferencesMock.mockResolvedValue({ matter_id: "m-1", references: [] });
    const statutes = Array.from({ length: 60 }, (_, index) => ({
      id: `synthetic-${index}`,
      short_name: `Fixture ${index}`,
      long_name: `Synthetic local layout fixture ${"Long caption ".repeat(12)}`,
      section_count: 1,
      catalog_section_count: 2,
    }));
    listStatutesMock.mockResolvedValue({ statutes });
    listStatuteSectionsMock.mockResolvedValue({ sections: [] });
    const user = userEvent.setup();
    render(withClient(<MatterStatutesPage />));
    await user.click(await screen.findByTestId("matter-statute-add-trigger"));
    const trigger = await screen.findByTestId("matter-statute-act-select");
    // Native selects cannot wrap their OS-owned popup; jsdom cannot prove geometry.
    expect(trigger.tagName).toBe("BUTTON");
    expect(trigger).toHaveAccessibleName("Act");
    const dialog = screen.getByRole("dialog");
    await waitFor(() => expect(trigger).toBeEnabled());
    fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false, pointerType: "mouse" });
    const listbox = screen.getByRole("listbox");
    expect(listbox).toHaveAccessibleName("Act");
    expect(dialog).not.toContainElement(listbox);
    expect(listbox).toHaveClass(
      "max-h-[min(var(--radix-select-content-available-height),22rem)]",
      "max-w-[min(var(--radix-select-content-available-width),32rem)]",
    );
    const last = within(listbox).getAllByRole("option").at(-1)!;
    expect(last).toHaveTextContent("Fixture 59");
    expect(last).toHaveClass("whitespace-normal", "[overflow-wrap:anywhere]");
    fireEvent.click(last);
    expect(trigger).toHaveTextContent("Fixture 59");
    expect(listStatuteSectionsMock).toHaveBeenCalledWith("synthetic-59");
  });

  it("renders empty state + 'Add reference' trigger when no refs exist", async () => {
    listMatterStatuteReferencesMock.mockResolvedValue({
      matter_id: "m-1",
      references: [],
    });
    render(withClient(<MatterStatutesPage />));
    expect(
      await screen.findByText(/No statutes attached yet/i),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("matter-statute-add-trigger"),
    ).toBeInTheDocument();
  });

  it("renders one row per attached reference with relevance badge + click-through", async () => {
    listMatterStatuteReferencesMock.mockResolvedValue({
      matter_id: "m-1",
      references: [
        {
          id: "r-1",
          matter_id: "m-1",
          section_id: "sec-482",
          statute_id: "crpc-1973",
          statute_short_name: "CrPC",
          section_number: "Section 482",
          section_label: "Saving of inherent powers of High Court",
          section_url: "https://www.indiacode.nic.in/handle/123456789/15272",
          relevance: "cited",
          notes: null,
          created_at: "2026-04-25T12:00:00Z",
        },
        {
          id: "r-2",
          matter_id: "m-1",
          section_id: "sec-302",
          statute_id: "ipc-1860",
          statute_short_name: "IPC",
          section_number: "Section 302",
          section_label: "Punishment for murder",
          section_url: "https://www.indiacode.nic.in/handle/123456789/2263",
          relevance: "opposing",
          notes: null,
          created_at: "2026-04-25T12:01:00Z",
        },
      ],
    });
    render(withClient(<MatterStatutesPage />));
    const crpcLink = await screen.findByRole("link", {
      name: /CrPC.*Section 482/i,
    });
    expect(crpcLink).toHaveAttribute(
      "href",
      "/app/statutes/crpc-1973/sections/Section%20482",
    );
    const ipcLink = screen.getByRole("link", {
      name: /IPC.*Section 302/i,
    });
    expect(ipcLink).toHaveAttribute(
      "href",
      "/app/statutes/ipc-1860/sections/Section%20302",
    );
    expect(screen.getByText(/cited/i)).toBeInTheDocument();
    expect(screen.getByText(/opposing/i)).toBeInTheDocument();
  });

  it("shows every catalogued Act but enables only Acts with verified sections", async () => {
    listMatterStatuteReferencesMock.mockResolvedValue({
      matter_id: "m-1",
      references: [],
    });
    listStatutesMock.mockResolvedValue({
      statutes: [
        {
          id: "empty-act",
          short_name: "Empty",
          long_name: "Catalog-only Act",
          section_count: 0,
          catalog_section_count: 20,
        },
        {
          id: "verified-act",
          short_name: "Verified",
          long_name: "Source-backed Act",
          section_count: 2,
          catalog_section_count: 2,
        },
      ],
      total_section_count: 2,
      total_catalog_section_count: 22,
    });
    listStatuteSectionsMock.mockResolvedValue({ statute: {}, sections: [] });
    const user = userEvent.setup();
    render(withClient(<MatterStatutesPage />));

    await user.click(await screen.findByTestId("matter-statute-add-trigger"));
    const select = await openOptions("Act");
    expect(
      within(select).getByRole("option", { name: /Catalog-only Act/ }),
    ).toHaveAttribute("aria-disabled", "true");
    expect(
      within(select).getByRole("option", {
        name: /Source-backed Act \(2 verified of 2 catalogued\)/,
      }),
    ).not.toHaveAttribute("aria-disabled", "true");
    fireEvent.keyDown(select, { key: "Escape" });
    expect(
      screen.getByTestId("matter-statute-catalog-coverage"),
    ).toHaveTextContent("2 verified of 22 catalogued sections across 2 Acts");
  });

  it("shows all catalogued sections while disabling unverified provisions", async () => {
    listMatterStatuteReferencesMock.mockResolvedValue({
      matter_id: "m-1",
      references: [],
    });
    listStatutesMock.mockResolvedValue({
      statutes: [
        {
          id: "verified-act",
          short_name: "Verified",
          long_name: "Source-backed Act",
          section_count: 1,
          catalog_section_count: 2,
        },
      ],
      total_section_count: 1,
      total_catalog_section_count: 2,
    });
    listStatuteSectionsMock.mockResolvedValue({
      statute: {},
      sections: [
        { id: "s-1", section_number: "Section 1", section_label: "Verified" },
      ],
      catalog_sections: [
        {
          id: "s-1",
          section_number: "Section 1",
          section_label: "Verified",
          selection_state: "verified_selectable",
        },
        {
          id: "s-2",
          section_number: "Section 2",
          section_label: "Pending",
          selection_state: "verification_pending",
        },
      ],
      verified_section_count: 1,
      catalog_section_count: 2,
      coverage_label: "1 verified of 2 catalogued sections",
    });
    const user = userEvent.setup();
    render(withClient(<MatterStatutesPage />));

    await user.click(await screen.findByTestId("matter-statute-add-trigger"));
    fireEvent.click(within(await openOptions("Act")).getByRole("option", { name: /Source-backed Act/ }));
    const sectionSelect = await openOptions("Section");
    expect(
      within(sectionSelect).getByRole("option", { name: /Section 1/ }),
    ).not.toHaveAttribute("aria-disabled", "true");
    expect(
      within(sectionSelect).getByRole("option", { name: /Section 2/ }),
    ).toHaveAttribute("aria-disabled", "true");
    fireEvent.keyDown(sectionSelect, { key: "Escape" });
    expect(
      screen.getByTestId("matter-statute-section-coverage"),
    ).toHaveTextContent("1 verified of 2 catalogued sections");
  });

  it("shows an honest empty state when no Act has a verified selectable section", async () => {
    listMatterStatuteReferencesMock.mockResolvedValue({
      matter_id: "m-1",
      references: [],
    });
    listStatutesMock.mockResolvedValue({
      statutes: [
        {
          id: "catalog-only",
          short_name: "Catalog",
          long_name: "Unverified catalog",
          section_count: 0,
          catalog_section_count: 12,
        },
      ],
      total_section_count: 0,
      total_catalog_section_count: 12,
    });
    const user = userEvent.setup();
    render(withClient(<MatterStatutesPage />));

    await user.click(await screen.findByTestId("matter-statute-add-trigger"));
    expect(
      await screen.findByTestId("matter-statute-no-selectable-acts"),
    ).toHaveTextContent("No Acts currently have source-verified sections");
  });

  it("attaches only a verified choice and clears that choice when the Act changes", async () => {
    listMatterStatuteReferencesMock.mockResolvedValue({ matter_id: "m-1", references: [] });
    listStatutesMock.mockResolvedValue({ statutes: [
      { id: "first", short_name: "First", long_name: "Synthetic first Act", section_count: 1 },
      { id: "second", short_name: "Second", long_name: "Synthetic second Act", section_count: 1 },
    ] });
    listStatuteSectionsMock.mockImplementation((id: string) => Promise.resolve({
      sections: [{ id: `${id}-verified`, section_number: "Section 1", section_label: "Verified" }],
      catalog_sections: [
        { id: `${id}-verified`, section_number: "Section 1", section_label: "Verified" },
        { id: `${id}-pending`, section_number: "Section 2", section_label: "Pending" },
      ],
    }));
    addMatterStatuteReferenceMock.mockResolvedValue({ id: "reference" });
    const user = userEvent.setup();
    render(withClient(<MatterStatutesPage />));
    await user.click(await screen.findByTestId("matter-statute-add-trigger"));
    fireEvent.click(within(await openOptions("Act")).getByRole("option", { name: /Synthetic first Act/ }));
    let options = await openOptions("Section");
    const pending = within(options).getByRole("option", { name: /Section 2/ });
    expect(pending).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(pending);
    expect(addMatterStatuteReferenceMock).not.toHaveBeenCalled();
    fireEvent.keyDown(options, { key: "Escape" });
    expect(screen.getByTestId("matter-statute-add-submit")).toBeDisabled();
    options = await openOptions("Section");
    fireEvent.click(within(options).getByRole("option", { name: /Section 1/ }));
    expect(screen.getByTestId("matter-statute-add-submit")).toBeEnabled();
    fireEvent.click(within(await openOptions("Act")).getByRole("option", { name: /Synthetic second Act/ }));
    expect(screen.getByTestId("matter-statute-add-submit")).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Section" })).not.toHaveTextContent("Section 1");
    fireEvent.click(within(await openOptions("Section")).getByRole("option", { name: /Section 1/ }));
    fireEvent.click(within(await openOptions("Relevance")).getByRole("option", { name: /context/ }));
    await user.click(screen.getByTestId("matter-statute-add-submit"));
    await waitFor(() => expect(addMatterStatuteReferenceMock).toHaveBeenCalledExactlyOnceWith("m-1", {
      section_id: "second-verified", relevance: "context",
    }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await user.click(screen.getByTestId("matter-statute-add-trigger"));
    expect(screen.getByRole("combobox", { name: "Act" })).toHaveTextContent("Select an Act");
    expect(screen.getByRole("combobox", { name: "Relevance" })).toHaveTextContent("cited");
    expect(screen.getByTestId("matter-statute-add-submit")).toBeDisabled();
  });

  it("keeps section-load failures distinct from an empty catalog and cannot submit", async () => {
    listMatterStatuteReferencesMock.mockResolvedValue({ matter_id: "m-1", references: [] });
    listStatutesMock.mockResolvedValue({ statutes: [
      { id: "verified", short_name: "Verified", long_name: "Synthetic Act", section_count: 1 },
    ] });
    listStatuteSectionsMock.mockRejectedValue(new Error("section load unavailable"));
    const user = userEvent.setup();
    render(withClient(<MatterStatutesPage />));
    await user.click(await screen.findByTestId("matter-statute-add-trigger"));
    fireEvent.click(within(await openOptions("Act")).getByRole("option", { name: /Synthetic Act/ }));
    expect(await screen.findByTestId("matter-statute-sections-error")).toHaveTextContent("Verified sections could not be loaded");
    expect(screen.getByRole("combobox", { name: "Section" })).toHaveTextContent("Could not load verified sections");
    expect(screen.getByTestId("matter-statute-add-submit")).toBeDisabled();
    expect(addMatterStatuteReferenceMock).not.toHaveBeenCalled();
  });

  it("recovers sections for the same selected Act through an explicit retry", async () => {
    listMatterStatuteReferencesMock.mockResolvedValue({ matter_id: "m-1", references: [] });
    listStatutesMock.mockResolvedValue({ statutes: [
      { id: "verified", short_name: "Verified", long_name: "Synthetic Act", section_count: 1 },
    ] });
    const recovered = deferred<{ sections: Array<{ id: string; section_number: string }> }>();
    listStatuteSectionsMock.mockRejectedValueOnce(new Error("section load unavailable"))
      .mockReturnValueOnce(recovered.promise);
    const user = userEvent.setup();
    render(withClient(<MatterStatutesPage />));
    await user.click(await screen.findByTestId("matter-statute-add-trigger"));
    fireEvent.click(within(await openOptions("Act")).getByRole("option", { name: /Synthetic Act/ }));
    expect(await screen.findByTestId("matter-statute-sections-error")).toHaveTextContent("Use Retry sections to try again");
    expect(screen.queryByTestId("matter-statute-catalog-error")).not.toBeInTheDocument();
    expect(screen.queryByTestId("matter-statute-no-selectable-acts")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry sections" }));
    expect(listStatuteSectionsMock.mock.calls).toEqual([["verified"], ["verified"]]);
    expect(listStatutesMock).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("combobox", { name: "Act" })).toHaveTextContent("Synthetic Act");
    expect(screen.getByRole("combobox", { name: "Section" })).toBeDisabled();
    expect(screen.getByTestId("matter-statute-add-submit")).toBeDisabled();
    await act(async () => recovered.resolve({ sections: [{ id: "recovered", section_number: "Section 1" }] }));
    fireEvent.click(within(await openOptions("Section")).getByRole("option", { name: "Section 1" }));
    expect(screen.getByTestId("matter-statute-add-submit")).toBeEnabled();
    expect(screen.queryByTestId("matter-statute-sections-error")).not.toBeInTheDocument();
  });

  it("selects long Act and section captions by keyboard, skips disabled options and restores Escape focus", async () => {
    const longAct = `Synthetic long Act ${"readable caption ".repeat(8)}`.trim();
    const longSection = `Verified provision ${"readable section caption ".repeat(8)}`.trim();
    listMatterStatuteReferencesMock.mockResolvedValue({ matter_id: "m-1", references: [] });
    listStatutesMock.mockResolvedValue({ statutes: [
      { id: "first", short_name: "First", long_name: "First synthetic Act", section_count: 1 },
      { id: "pending", short_name: "Pending", long_name: "Pending synthetic Act", section_count: 0 },
      { id: "last", short_name: "Last", long_name: longAct, section_count: 2 },
    ] });
    const first = { id: "s-first", section_number: "Section 1", section_label: "First" };
    const last = { id: "s-last", section_number: "Section 3", section_label: longSection };
    listStatuteSectionsMock.mockResolvedValue({ sections: [first, last], catalog_sections: [
      first, { id: "s-pending", section_number: "Section 2", section_label: "Pending" }, last,
    ] });
    const user = userEvent.setup();
    render(withClient(<MatterStatutesPage />));
    await user.click(await screen.findByTestId("matter-statute-add-trigger"));
    const actTrigger = screen.getByRole("combobox", { name: "Act" });
    await waitFor(() => expect(actTrigger).toBeEnabled());
    actTrigger.focus();
    await user.keyboard(" ");
    let list = screen.getByRole("listbox");
    const firstAct = within(list).getByRole("option", { name: /First synthetic Act/ });
    const lastAct = within(list).getByRole("option", { name: /Synthetic long Act/ });
    await waitFor(() => expect(firstAct).toHaveFocus());
    await user.keyboard("{End}");
    await waitFor(() => expect(lastAct).toHaveFocus());
    await user.keyboard("{ArrowUp}");
    await waitFor(() => expect(firstAct).toHaveFocus());
    await user.keyboard("{ArrowDown}");
    await waitFor(() => expect(lastAct).toHaveFocus());
    expect(lastAct).toHaveTextContent(longAct);
    await user.keyboard("{Escape}");
    await waitFor(() => expect(actTrigger).toHaveFocus());
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(actTrigger).toHaveTextContent("Select an Act");
    await user.keyboard(" ");
    list = screen.getByRole("listbox");
    await waitFor(() => expect(within(list).getByRole("option", { name: /First synthetic Act/ })).toHaveFocus());
    await user.keyboard("{End}");
    await waitFor(() => expect(within(list).getByRole("option", { name: /Synthetic long Act/ })).toHaveFocus());
    await user.keyboard("{Enter}");
    await waitFor(() => expect(actTrigger).toHaveFocus());
    expect(actTrigger).toHaveTextContent(longAct);
    const sectionTrigger = screen.getByRole("combobox", { name: "Section" });
    await waitFor(() => expect(sectionTrigger).toBeEnabled());
    sectionTrigger.focus();
    await user.keyboard(" ");
    list = screen.getByRole("listbox");
    const firstSection = within(list).getByRole("option", { name: /Section 1/ });
    const lastSection = within(list).getByRole("option", { name: /Section 3/ });
    await waitFor(() => expect(firstSection).toHaveFocus());
    await user.keyboard("{End}");
    await waitFor(() => expect(lastSection).toHaveFocus());
    await user.keyboard("{ArrowUp}");
    await waitFor(() => expect(firstSection).toHaveFocus());
    await user.keyboard("{ArrowDown}");
    await waitFor(() => expect(lastSection).toHaveFocus());
    expect(lastSection).toHaveClass("whitespace-normal", "[overflow-wrap:anywhere]");
    expect(lastSection).toHaveTextContent(longSection);
    await user.keyboard("{Escape}");
    await waitFor(() => expect(sectionTrigger).toHaveFocus());
    expect(screen.getByTestId("matter-statute-add-submit")).toBeDisabled();
    await user.keyboard(" ");
    list = screen.getByRole("listbox");
    await waitFor(() => expect(within(list).getByRole("option", { name: /Section 1/ })).toHaveFocus());
    await user.keyboard("{End}");
    await waitFor(() => expect(within(list).getByRole("option", { name: /Section 3/ })).toHaveFocus());
    await user.keyboard("{Enter}");
    await waitFor(() => expect(sectionTrigger).toHaveFocus());
    expect(sectionTrigger).toHaveTextContent(longSection);
    expect(screen.getByTestId("matter-statute-add-submit")).toBeEnabled();
  });

  it.each(["resolve", "reject"] as const)("ignores a late %s from a retry after the selected Act changes", async (outcome) => {
    recoveryCatalog();
    const stale = deferred<{ sections: Array<{ id: string; section_number: string }> }>();
    listStatuteSectionsMock.mockRejectedValueOnce(new Error("initial failure"))
      .mockReturnValueOnce(stale.promise)
      .mockResolvedValueOnce({ sections: [{ id: "second-current", section_number: "Current second provision" }] });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    render(withClient(<MatterStatutesPage />, client));
    await user.click(await screen.findByTestId("matter-statute-add-trigger"));
    fireEvent.click(within(await openOptions("Act")).getByRole("option", { name: /Synthetic first Act/ }));
    const retry = await screen.findByRole("button", { name: "Retry sections" });
    expect(screen.getByTestId("matter-statute-add-submit")).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Section" })).toBeDisabled();
    await user.click(retry);
    fireEvent.click(within(await openOptions("Act")).getByRole("option", { name: /Synthetic second Act/ }));
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Section" })).toBeEnabled());
    await act(async () => {
      if (outcome === "resolve") stale.resolve({ sections: [{ id: "stale", section_number: "Abandoned first provision" }] });
      else stale.reject(new Error("late first failure"));
    });
    expect(listStatuteSectionsMock.mock.calls).toEqual([["first"], ["first"], ["second"]]);
    expect(client.getQueryData(["statutes", "first", "sections"])).toBeUndefined();
    expect(screen.queryByTestId("matter-statute-sections-error")).not.toBeInTheDocument();
    const choices = await openOptions("Section");
    expect(within(choices).queryByRole("option", { name: /Abandoned/ })).not.toBeInTheDocument();
    fireEvent.click(within(choices).getByRole("option", { name: "Current second provision" }));
    expect(screen.getByTestId("matter-statute-add-submit")).toBeEnabled();
  });

  it.each(["resolve", "reject"] as const)("does not restore a closed dialog from a late retry %s", async (outcome) => {
    recoveryCatalog();
    const stale = deferred<{ sections: Array<{ id: string; section_number: string }> }>();
    listStatuteSectionsMock.mockRejectedValueOnce(new Error("initial failure"))
      .mockReturnValueOnce(stale.promise)
      .mockResolvedValueOnce({ sections: [{ id: "fresh", section_number: "Fresh reopened provision" }] });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    render(withClient(<MatterStatutesPage />, client));
    await user.click(await screen.findByTestId("matter-statute-add-trigger"));
    fireEvent.click(within(await openOptions("Act")).getByRole("option", { name: /Synthetic first Act/ }));
    await user.click(await screen.findByRole("button", { name: "Retry sections" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await user.click(screen.getByTestId("matter-statute-add-trigger"));
    await act(async () => {
      if (outcome === "resolve") stale.resolve({ sections: [{ id: "stale", section_number: "Abandoned provision" }] });
      else stale.reject(new Error("late closed failure"));
    });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Act" })).toHaveTextContent("Select an Act");
    expect(screen.getByRole("combobox", { name: "Section" })).toBeDisabled();
    expect(screen.getByTestId("matter-statute-add-submit")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Retry sections" })).not.toBeInTheDocument();
    expect(client.getQueryData(["statutes", "first", "sections"])).toBeUndefined();
    fireEvent.click(within(await openOptions("Act")).getByRole("option", { name: /Synthetic first Act/ }));
    fireEvent.click(within(await openOptions("Section")).getByRole("option", { name: "Fresh reopened provision" }));
    expect(listStatuteSectionsMock.mock.calls).toEqual([["first"], ["first"], ["first"]]);
    expect(screen.getByTestId("matter-statute-add-submit")).toBeEnabled();
  });

  it("does not cache a retry response after unmount", async () => {
    recoveryCatalog();
    const stale = deferred<{ sections: Array<{ id: string; section_number: string }> }>();
    listStatuteSectionsMock.mockRejectedValueOnce(new Error("initial failure")).mockReturnValueOnce(stale.promise);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    const view = render(withClient(<MatterStatutesPage />, client));
    await user.click(await screen.findByTestId("matter-statute-add-trigger"));
    fireEvent.click(within(await openOptions("Act")).getByRole("option", { name: /Synthetic first Act/ }));
    await user.click(await screen.findByRole("button", { name: "Retry sections" }));
    view.unmount();
    await act(async () => stale.resolve({ sections: [{ id: "stale", section_number: "Abandoned provision" }] }));
    expect(client.getQueryData(["statutes", "first", "sections"])).toBeUndefined();
    expect(addMatterStatuteReferenceMock).not.toHaveBeenCalled();
  });

  it("blocks a cached selection during a failed refetch and clears it on retry", async () => {
    recoveryCatalog();
    const fresh = deferred<{ sections: Array<{ id: string; section_number: string }> }>();
    listStatuteSectionsMock.mockResolvedValueOnce({ sections: [{ id: "old", section_number: "Original provision" }] })
      .mockRejectedValueOnce(new Error("refresh failure"))
      .mockReturnValueOnce(fresh.promise);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    render(withClient(<MatterStatutesPage />, client));
    await user.click(await screen.findByTestId("matter-statute-add-trigger"));
    fireEvent.click(within(await openOptions("Act")).getByRole("option", { name: /Synthetic first Act/ }));
    fireEvent.click(within(await openOptions("Section")).getByRole("option", { name: "Original provision" }));
    expect(screen.getByTestId("matter-statute-add-submit")).toBeEnabled();
    await act(async () => { await client.invalidateQueries({ queryKey: ["statutes", "first", "sections"], exact: true }); });
    const retry = await screen.findByRole("button", { name: "Retry sections" });
    expect(screen.getByTestId("matter-statute-add-submit")).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Section" })).toBeDisabled();
    await user.click(retry);
    expect(screen.getByTestId("matter-statute-add-submit")).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Section" })).toBeDisabled();
    await act(async () => fresh.resolve({ sections: [{ id: "fresh", section_number: "Replacement provision" }] }));
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Section" })).toBeEnabled());
    expect(screen.getByTestId("matter-statute-add-submit")).toBeDisabled();
    fireEvent.click(within(await openOptions("Section")).getByRole("option", { name: "Replacement provision" }));
    expect(screen.getByTestId("matter-statute-add-submit")).toBeEnabled();
  });

  it("distinguishes a catalog load failure from a genuinely empty verified catalog", async () => {
    listMatterStatuteReferencesMock.mockResolvedValue({
      matter_id: "m-1",
      references: [],
    });
    listStatutesMock.mockRejectedValueOnce(new Error("catalog unavailable")).mockResolvedValueOnce({ statutes: [
      { id: "verified", short_name: "Verified", long_name: "Recovered catalog Act", section_count: 1 },
    ] });
    const user = userEvent.setup();
    render(withClient(<MatterStatutesPage />));

    await user.click(await screen.findByTestId("matter-statute-add-trigger"));
    expect(
      await screen.findByTestId("matter-statute-catalog-error"),
    ).toHaveTextContent("verified statute catalog could not be loaded");
    expect(
      screen.queryByTestId("matter-statute-no-selectable-acts"),
    ).toBeNull();
    expect(screen.getByTestId("matter-statute-act-select")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Retry sections" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await user.click(screen.getByTestId("matter-statute-add-trigger"));
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Act" })).toBeEnabled());
    expect(screen.queryByTestId("matter-statute-catalog-error")).not.toBeInTheDocument();
    expect(screen.queryByTestId("matter-statute-no-selectable-acts")).not.toBeInTheDocument();
    expect(listStatutesMock).toHaveBeenCalledTimes(2);
    expect(listStatuteSectionsMock).not.toHaveBeenCalled();
  });
});
