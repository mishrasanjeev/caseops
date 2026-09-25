import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult, waitFor, within } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { createMatterMock, fetchForumCatalogMock, toastSuccess, toastError } =
  vi.hoisted(() => ({
    createMatterMock: vi.fn(),
    fetchForumCatalogMock: vi.fn(),
    toastSuccess: vi.fn(),
    toastError: vi.fn(),
  }));

vi.mock("@/lib/api/endpoints", () => ({
  createMatter: createMatterMock,
  fetchForumCatalog: fetchForumCatalogMock,
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

import { NewMatterDialog } from "@/components/app/NewMatterDialog";

function createTestClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function withClient(children: ReactNode, client = createTestClient()) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

// Tests query only inside their own render container, or inside a Radix portal
// resolved through its trigger's aria-controls while that container is still
// mounted. If a test ever overruns its deadline, cleanup() detaches both and
// the abandoned user flow fails instead of driving the next test's dialog.
function renderDialog(client = createTestClient()) {
  const view = render(withClient(<NewMatterDialog />, client));
  return { view, page: within(view.container) };
}

async function controlledBy(view: RenderResult, trigger: HTMLElement) {
  const id = trigger.getAttribute("aria-controls");
  expect(id).toBeTruthy();
  return waitFor(() => {
    expect(view.container).toBeInTheDocument();
    const element = document.getElementById(id as string);
    expect(element).not.toBeNull();
    return element as HTMLElement;
  });
}

// Radix portal content stays queryable after React detaches it, so every query
// on a portal scope first requires this test's page and the portal to be mounted.
function mountedWithin(view: RenderResult, element: HTMLElement) {
  const queries = within(element);
  return new Proxy(queries, {
    get(target, key) {
      const query = Reflect.get(target, key);
      if (typeof query !== "function") return query;
      return (...args: unknown[]) => {
        expect(view.container).toBeInTheDocument();
        expect(element).toBeInTheDocument();
        return query(...args);
      };
    },
  });
}

async function openDialog(user: UserEvent, view: RenderResult) {
  const trigger = within(view.container).getByTestId("new-matter-trigger");
  await user.click(trigger);
  const element = await controlledBy(view, trigger);
  expect(element).toHaveAttribute("role", "dialog");
  return { element, dialog: mountedWithin(view, element) };
}

// One paste per field: the field still receives focus and a real input event,
// but the form re-renders once per field instead of once per character.
// Paste targets whichever element has focus, so require focus first: an
// abandoned flow holding a detached field fails here instead of pasting into
// the next test's focused input.
async function enterText(user: UserEvent, field: HTMLElement, value: string) {
  await user.click(field);
  expect(field).toHaveFocus();
  await user.paste(value);
  expect(field).toHaveDisplayValue(value);
}

type Dialog = ReturnType<typeof mountedWithin>;

async function fillRequiredMatterFields(user: UserEvent, dialog: Dialog) {
  await enterText(user, await dialog.findByLabelText("Title"), "Spine matter");
  await enterText(user, dialog.getByLabelText("Matter code"), "blr-001");
  await enterText(user, dialog.getByLabelText("Practice area"), "Commercial");
}

function createButton(dialog: Dialog) {
  return dialog.getByRole("button", { name: /Create matter/i });
}

const DELHI_HIGH_COURT = {
  forum_level: "high_court",
  court_id: "delhi-hc",
  court_name: "Delhi High Court",
  forum_catalog_entry_id: "hc:delhi",
  forum_state: "Delhi",
  forum_district: null,
  forum_city: "New Delhi",
  forum_consumer_level: null,
};

// The complete createMatter payload for the required fields plus a forum.
function matterPayload(overrides: Record<string, unknown>) {
  return {
    title: "Spine matter",
    matter_code: "BLR-001",
    client_name: undefined,
    opposing_party: undefined,
    case_number: undefined,
    temporary_e_case_number: undefined,
    cnr_number: undefined,
    next_hearing_on: undefined,
    practice_area: "Commercial",
    description: undefined,
    ...DELHI_HIGH_COURT,
    status: "active",
    ...overrides,
  };
}

// A settled creation announces success once, closes and detaches the dialog.
async function expectCreatedAndClosed(dialogElement: HTMLElement) {
  await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Matter created"));
  expect(toastSuccess).toHaveBeenCalledTimes(1);
  expect(toastError).not.toHaveBeenCalled();
  await waitFor(() => expect(dialogElement).not.toBeInTheDocument());
}

describe("NewMatterDialog", () => {
  beforeEach(() => {
    createMatterMock.mockReset();
    fetchForumCatalogMock.mockReset();
    fetchForumCatalogMock.mockResolvedValue({
      entries: [
        {
          id: "sc:india",
          parent_id: null,
          court_id: "supreme-court-india",
          name: "Supreme Court of India",
          forum_type: "supreme_court",
          forum_level: "supreme_court",
          state: null,
          district: null,
          city: "New Delhi",
          consumer_level: null,
          source_name: "CaseOps LW-S4 baseline forum catalog",
          source_url: null,
          lineage: "Supreme Court > India",
          display_order: 10,
        },
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
        {
          id: "district:delhi:dwarka",
          parent_id: null,
          court_id: null,
          name: "Dwarka Courts Complex",
          forum_type: "district_court",
          forum_level: "lower_court",
          state: "Delhi",
          district: "South-West",
          city: "Dwarka",
          consumer_level: null,
          source_name: "CaseOps LW-S4 baseline forum catalog",
          source_url: null,
          lineage: "District Court > Delhi > South-West > Dwarka",
          display_order: 104,
        },
        {
          id: "consumer:ncdrc",
          parent_id: null,
          court_id: null,
          name: "National Consumer Disputes Redressal Commission",
          forum_type: "consumer_forum",
          forum_level: "tribunal",
          state: null,
          district: null,
          city: "New Delhi",
          consumer_level: "national",
          source_name: "e-Jagriti master commission directory",
          source_url:
            "https://e-jagriti.gov.in/services/master/master/v2/getAllCommission",
          lineage: "Consumer Forum > NCDRC",
          display_order: 200,
        },
        {
          id: "consumer:scdrc:11080000",
          parent_id: "consumer:ncdrc",
          court_id: null,
          name: "Rajasthan State Consumer Disputes Redressal Commission",
          forum_type: "consumer_forum",
          forum_level: "tribunal",
          state: "Rajasthan",
          district: null,
          city: null,
          consumer_level: "state",
          source_name: "e-Jagriti master commission directory",
          source_url:
            "https://e-jagriti.gov.in/services/master/master/v2/getCommissionDetailsByStateId?stateId=8",
          lineage: "Consumer Forum > SCDRC > Rajasthan",
          display_order: 280,
        },
        {
          id: "consumer:dcdrc:11080086",
          parent_id: "consumer:scdrc:11080000",
          court_id: null,
          name: "Ajmer District Consumer Disputes Redressal Commission",
          forum_type: "consumer_forum",
          forum_level: "tribunal",
          state: "Rajasthan",
          district: "Ajmer",
          city: null,
          consumer_level: "district",
          source_name: "e-Jagriti master commission directory",
          source_url:
            "https://e-jagriti.gov.in/services/master/master/v2/getCommissionDetailsByStateId?stateId=8",
          lineage: "Consumer Forum > DCDRC > Rajasthan > Ajmer",
          display_order: 108001,
        },
      ],
    });
    toastSuccess.mockReset();
    toastError.mockReset();
  });

  it("announces validation errors with aria-invalid + aria-describedby wired to the error id", async () => {
    const user = userEvent.setup();
    const { view } = renderDialog();

    const { element, dialog } = await openDialog(user, view);
    await waitFor(() => expect(fetchForumCatalogMock).toHaveBeenCalledTimes(1));
    // The default forum applies once the catalog has loaded.
    await waitFor(() =>
      expect(dialog.getByTestId("new-matter-forum-state")).toHaveValue("Delhi"),
    );
    // Submitting the dialog with no fields filled trips the zod schema.
    expect(createButton(dialog)).toBeEnabled();
    await user.click(createButton(dialog));

    const titleInput = await dialog.findByLabelText("Title");
    await waitFor(() => expect(titleInput).toHaveAttribute("aria-invalid", "true"));
    const errorId = titleInput.getAttribute("aria-describedby");
    expect(errorId).toBeTruthy();
    const errorNode = element.querySelector(`[id="${errorId}"]`);
    expect(errorNode).toBeInTheDocument();
    expect(errorNode).toHaveAttribute("role", "alert");
    expect(errorNode?.textContent).toMatch(/At least 3 characters/i);

    expect(createMatterMock).not.toHaveBeenCalled();
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("keeps creation disabled while the forum catalog is loading", async () => {
    const user = userEvent.setup();
    let resolveCatalog: (value: { entries: [] }) => void = () => {};
    fetchForumCatalogMock.mockReturnValue(
      new Promise<{ entries: [] }>((resolve) => {
        resolveCatalog = resolve;
      }),
    );
    const { view } = renderDialog();

    const { dialog } = await openDialog(user, view);

    expect(createButton(dialog)).toBeDisabled();
    resolveCatalog({ entries: [] });
    // The resolved empty catalog still blocks hierarchy submission.
    expect(await dialog.findByText(/Forum catalog is empty/i)).toBeInTheDocument();
    expect(createButton(dialog)).toBeDisabled();
    expect(createMatterMock).not.toHaveBeenCalled();
  });

  it("requires an explicit legacy fallback when the forum catalog request fails", async () => {
    const user = userEvent.setup();
    fetchForumCatalogMock.mockRejectedValue(new Error("catalog down"));
    createMatterMock.mockResolvedValue({
      id: "m-1",
      matter_code: "BLR-001",
      title: "Spine matter",
      created_at: "2026-04-17T10:00:00Z",
      status: "active",
    });
    const { view } = renderDialog();

    const { element, dialog } = await openDialog(user, view);
    expect(await dialog.findByRole("alert")).toHaveTextContent(
      /Forum catalog could not be loaded/i,
    );
    await fillRequiredMatterFields(user, dialog);
    expect(createButton(dialog)).toBeDisabled();

    await user.selectOptions(dialog.getByTestId("new-matter-forum-category"), "legacy");
    expect(createButton(dialog)).toBeDisabled();

    await enterText(user, dialog.getByTestId("new-matter-forum-legacy-court"), "SIAC");
    await user.click(createButton(dialog));

    await expectCreatedAndClosed(element);
    expect(createMatterMock).toHaveBeenCalledTimes(1);
    expect(createMatterMock.mock.calls[0]).toStrictEqual([
      matterPayload({
        forum_level: "high_court",
        court_id: null,
        court_name: "SIAC",
        forum_catalog_entry_id: null,
        forum_state: null,
        forum_district: null,
        forum_city: null,
        forum_consumer_level: null,
      }),
    ]);
  });

  it("blocks hierarchy submission when the forum catalog is empty", async () => {
    const user = userEvent.setup();
    fetchForumCatalogMock.mockResolvedValue({ entries: [] });
    const { view } = renderDialog();

    const { dialog } = await openDialog(user, view);
    expect(await dialog.findByText(/Forum catalog is empty/i)).toBeInTheDocument();
    await fillRequiredMatterFields(user, dialog);

    expect(createButton(dialog)).toBeDisabled();
    expect(createMatterMock).not.toHaveBeenCalled();
  });

  it("uppercases the matter code and trims whitespace before calling the API", async () => {
    const user = userEvent.setup();
    createMatterMock.mockResolvedValue({
      id: "m-1",
      matter_code: "BLR-001",
      title: "Test matter",
      created_at: "2026-04-17T10:00:00Z",
      status: "active",
    });
    const { view } = renderDialog();

    const { element, dialog } = await openDialog(user, view);
    await waitFor(() =>
      expect(dialog.getByTestId("new-matter-forum-state")).toHaveValue("Delhi"),
    );
    await enterText(user, await dialog.findByLabelText("Title"), "  Spine matter  ");
    await enterText(user, dialog.getByLabelText("Matter code"), "  blr-001  ");
    await enterText(user, dialog.getByLabelText("Practice area"), "Commercial");
    await enterText(user, dialog.getByLabelText("Case number"), " WP(C) 1/2026 ");
    await enterText(user, dialog.getByLabelText("Temporary E-Case number"), " TEMP/2026/00125 ");
    await enterText(user, dialog.getByLabelText("CNR number"), " dlhc-0100-1234-2026 ");
    await user.click(createButton(dialog));

    await expectCreatedAndClosed(element);
    expect(createMatterMock).toHaveBeenCalledTimes(1);
    expect(createMatterMock.mock.calls[0]).toStrictEqual([
      matterPayload({
        case_number: "WP(C) 1/2026",
        temporary_e_case_number: "TEMP/2026/00125",
        cnr_number: "dlhc-0100-1234-2026",
      }),
    ]);
  });

  it("rejects matter codes with spaces, slashes, or other special characters before submit", async () => {
    const user = userEvent.setup();
    const { view } = renderDialog();

    const { dialog } = await openDialog(user, view);
    await waitFor(() =>
      expect(dialog.getByTestId("new-matter-forum-state")).toHaveValue("Delhi"),
    );
    await enterText(user, await dialog.findByLabelText("Title"), "Invalid code matter");
    await enterText(user, dialog.getByLabelText("Matter code"), "BAD CODE/1");
    await enterText(user, dialog.getByLabelText("Practice area"), "Commercial");
    await user.click(createButton(dialog));

    expect(await dialog.findByRole("alert")).toHaveTextContent(
      /letters, numbers, and hyphens only/i,
    );
    expect(createMatterMock).not.toHaveBeenCalled();
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("defaults new matters to Active and does not offer a terminal state at creation", async () => {
    const user = userEvent.setup();
    createMatterMock.mockResolvedValue({
      id: "m-1",
      matter_code: "BLR-001",
      title: "Active matter",
      created_at: "2026-04-17T10:00:00Z",
      status: "active",
    });
    const { view } = renderDialog();

    const { element, dialog } = await openDialog(user, view);
    await waitFor(() =>
      expect(dialog.getByTestId("new-matter-forum-state")).toHaveValue("Delhi"),
    );
    await fillRequiredMatterFields(user, dialog);

    const statusTrigger = dialog.getByRole("combobox", { name: "Status" });
    expect(statusTrigger).toHaveTextContent("Active");
    await user.click(statusTrigger);
    const listboxElement = await controlledBy(view, statusTrigger);
    const listbox = mountedWithin(view, listboxElement);
    expect(listbox.getByText("Active")).toBeInTheDocument();
    expect(listbox.queryByText("Dispose")).not.toBeInTheDocument();
    expect(listbox.queryByText("Close")).not.toBeInTheDocument();
    expect(listbox.queryByText("Closed")).not.toBeInTheDocument();
    // Escape goes to the focused element; send it only while this listbox has focus.
    expect(listboxElement).toContainElement(document.activeElement as HTMLElement);
    await user.keyboard("{Escape}");
    await user.click(createButton(dialog));

    await expectCreatedAndClosed(element);
    expect(createMatterMock).toHaveBeenCalledTimes(1);
    expect(createMatterMock.mock.calls[0]).toStrictEqual([matterPayload({ status: "active" })]);
  });

  it("closes after successful creation without waiting for a slow matters refetch", async () => {
    const user = userEvent.setup();
    const client = createTestClient();
    vi.spyOn(client, "invalidateQueries").mockReturnValue(
      new Promise(() => {}),
    );
    createMatterMock.mockResolvedValue({
      id: "m-1",
      matter_code: "BLR-001",
      title: "Active matter",
      created_at: "2026-04-17T10:00:00Z",
      status: "active",
    });
    const { view } = renderDialog(client);

    const { element, dialog } = await openDialog(user, view);
    await waitFor(() =>
      expect(dialog.getByTestId("new-matter-forum-state")).toHaveValue("Delhi"),
    );
    await fillRequiredMatterFields(user, dialog);
    await user.click(createButton(dialog));

    await expectCreatedAndClosed(element);
    expect(createMatterMock).toHaveBeenCalledTimes(1);
    expect(createMatterMock.mock.calls[0]).toStrictEqual([matterPayload({})]);
    expect(client.invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["matters"],
    });
  });

  it("can create a district court matter for a state missing from the catalog", async () => {
    const user = userEvent.setup();
    createMatterMock.mockResolvedValue({
      id: "m-assam",
      matter_code: "ASM-001",
      title: "Assam district matter",
      created_at: "2026-06-24T10:00:00Z",
      status: "intake",
    });
    const { view } = renderDialog();

    const { element, dialog } = await openDialog(user, view);
    await fillRequiredMatterFields(user, dialog);
    await waitFor(() =>
      expect(dialog.getByTestId("new-matter-forum-state")).toHaveValue("Delhi"),
    );
    await user.selectOptions(dialog.getByTestId("new-matter-forum-category"), "district_court");
    await user.selectOptions(dialog.getByTestId("new-matter-forum-district-state"), "Assam");

    await waitFor(() =>
      expect(dialog.getByTestId("new-matter-forum-district-state")).toHaveValue("Assam"),
    );
    expect(dialog.getByTestId("new-matter-forum-district")).toHaveValue(
      "__uncatalogued_district_court__",
    );
    expect(createButton(dialog)).toBeDisabled();

    await enterText(user, dialog.getByTestId("new-matter-forum-district-name"), "Kamrup Metro");
    expect(createButton(dialog)).toBeDisabled();

    await enterText(
      user,
      dialog.getByTestId("new-matter-forum-district-court"),
      "Kamrup Metro District Court",
    );
    await user.click(createButton(dialog));

    await expectCreatedAndClosed(element);
    expect(createMatterMock).toHaveBeenCalledTimes(1);
    expect(createMatterMock.mock.calls[0]).toStrictEqual([
      matterPayload({
        forum_level: "lower_court",
        court_id: null,
        court_name: "Kamrup Metro District Court",
        forum_catalog_entry_id: null,
        forum_state: "Assam",
        forum_district: "Kamrup Metro",
        forum_city: null,
        forum_consumer_level: null,
      }),
    ]);
  });

  it("can create catalogued and uncatalogued DCDRC matters without stale metadata", async () => {
    const user = userEvent.setup();
    createMatterMock.mockResolvedValue({
      id: "m-consumer",
      matter_code: "CONS-001",
      title: "Rajasthan consumer matter",
      created_at: "2026-06-25T10:00:00Z",
      status: "intake",
    });
    const { view } = renderDialog();

    const first = await openDialog(user, view);
    await fillRequiredMatterFields(user, first.dialog);
    await waitFor(() =>
      expect(first.dialog.getByTestId("new-matter-forum-state")).toHaveValue("Delhi"),
    );
    await user.selectOptions(
      first.dialog.getByTestId("new-matter-forum-category"),
      "district_commission",
    );
    await user.selectOptions(
      first.dialog.getByTestId("new-matter-forum-consumer-state"),
      "Rajasthan",
    );

    expect(first.dialog.getByTestId("new-matter-forum-consumer-district")).toHaveValue(
      "consumer:dcdrc:11080086",
    );
    await user.click(createButton(first.dialog));

    await expectCreatedAndClosed(first.element);
    expect(createMatterMock).toHaveBeenCalledTimes(1);
    expect(createMatterMock.mock.calls[0]).toStrictEqual([
      matterPayload({
        forum_level: "tribunal",
        court_id: null,
        court_name: "Ajmer District Consumer Disputes Redressal Commission",
        forum_catalog_entry_id: "consumer:dcdrc:11080086",
        forum_state: "Rajasthan",
        forum_district: "Ajmer",
        forum_city: null,
        forum_consumer_level: "district",
      }),
    ]);

    createMatterMock.mockClear();
    toastSuccess.mockClear();
    const second = await openDialog(user, view);
    await fillRequiredMatterFields(user, second.dialog);
    await user.selectOptions(
      second.dialog.getByTestId("new-matter-forum-category"),
      "district_commission",
    );
    await user.selectOptions(
      second.dialog.getByTestId("new-matter-forum-consumer-state"),
      "Rajasthan",
    );
    await user.selectOptions(
      second.dialog.getByTestId("new-matter-forum-consumer-district"),
      "__uncatalogued_consumer_district__",
    );
    expect(second.dialog.getByTestId("new-matter-forum-consumer-district-name")).toHaveValue("");
    expect(second.dialog.getByTestId("new-matter-forum-consumer-forum-name")).toHaveValue("");
    expect(createButton(second.dialog)).toBeDisabled();

    await enterText(
      user,
      second.dialog.getByTestId("new-matter-forum-consumer-district-name"),
      "South II",
    );
    expect(createButton(second.dialog)).toBeDisabled();
    await enterText(
      user,
      second.dialog.getByTestId("new-matter-forum-consumer-forum-name"),
      "South II DCDRC Annex",
    );
    await user.click(createButton(second.dialog));

    await expectCreatedAndClosed(second.element);
    expect(createMatterMock).toHaveBeenCalledTimes(1);
    expect(createMatterMock.mock.calls[0]).toStrictEqual([
      matterPayload({
        forum_level: "tribunal",
        court_id: null,
        court_name: "South II DCDRC Annex",
        forum_catalog_entry_id: null,
        forum_state: "Rajasthan",
        forum_district: "South II",
        forum_city: null,
        forum_consumer_level: "district",
      }),
    ]);
  });

  it("can create a matter against a previously missing Delhi District Court entry", async () => {
    const user = userEvent.setup();
    createMatterMock.mockResolvedValue({
      id: "m-dwarka",
      matter_code: "DL-DWARKA-001",
      title: "Dwarka matter",
      created_at: "2026-06-23T10:00:00Z",
      status: "intake",
    });
    const { view } = renderDialog();

    const { element, dialog } = await openDialog(user, view);
    await fillRequiredMatterFields(user, dialog);
    await user.selectOptions(dialog.getByTestId("new-matter-forum-category"), "district_court");
    await waitFor(() =>
      expect(dialog.getByTestId("new-matter-forum-district")).toHaveValue(
        "district:delhi:dwarka",
      ),
    );
    await user.click(createButton(dialog));

    await expectCreatedAndClosed(element);
    expect(createMatterMock).toHaveBeenCalledTimes(1);
    expect(createMatterMock.mock.calls[0]).toStrictEqual([
      matterPayload({
        forum_level: "lower_court",
        court_id: null,
        court_name: "Dwarka Courts Complex",
        forum_catalog_entry_id: "district:delhi:dwarka",
        forum_state: "Delhi",
        forum_district: "South-West",
        forum_city: "Dwarka",
        forum_consumer_level: null,
      }),
    ]);
  });
});
