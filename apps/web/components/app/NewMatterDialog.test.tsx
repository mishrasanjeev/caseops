import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

async function openDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId("new-matter-trigger"));
}

async function fillRequiredMatterFields(
  user: ReturnType<typeof userEvent.setup>,
) {
  await user.type(await screen.findByLabelText("Title"), "Spine matter");
  await user.type(screen.getByLabelText("Matter code"), "blr-001");
  await user.type(screen.getByLabelText("Practice area"), "Commercial");
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
    render(withClient(<NewMatterDialog />));

    await openDialog(user);
    await waitFor(() => expect(fetchForumCatalogMock).toHaveBeenCalledTimes(1));
    // Submitting the dialog with no fields filled trips the zod schema.
    await user.click(
      await screen.findByRole("button", { name: /Create matter/i }),
    );

    const titleInput = await screen.findByLabelText("Title");
    expect(titleInput).toHaveAttribute("aria-invalid", "true");
    const errorId = titleInput.getAttribute("aria-describedby");
    expect(errorId).toBeTruthy();
    const errorNode = document.getElementById(errorId as string);
    expect(errorNode).toBeInTheDocument();
    expect(errorNode).toHaveAttribute("role", "alert");
    expect(errorNode?.textContent).toMatch(/At least 3 characters/i);

    expect(createMatterMock).not.toHaveBeenCalled();
  });

  it("keeps creation disabled while the forum catalog is loading", async () => {
    const user = userEvent.setup();
    let resolveCatalog: (value: { entries: [] }) => void = () => {};
    fetchForumCatalogMock.mockReturnValue(
      new Promise<{ entries: [] }>((resolve) => {
        resolveCatalog = resolve;
      }),
    );
    render(withClient(<NewMatterDialog />));

    await openDialog(user);

    expect(
      screen.getByRole("button", { name: /Create matter/i }),
    ).toBeDisabled();
    resolveCatalog({ entries: [] });
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
    render(withClient(<NewMatterDialog />));

    await openDialog(user);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Forum catalog could not be loaded/i,
    );
    await fillRequiredMatterFields(user);
    expect(
      screen.getByRole("button", { name: /Create matter/i }),
    ).toBeDisabled();

    await user.selectOptions(
      screen.getByTestId("new-matter-forum-category"),
      "legacy",
    );
    expect(
      screen.getByRole("button", { name: /Create matter/i }),
    ).toBeDisabled();

    await user.type(
      screen.getByTestId("new-matter-forum-legacy-court"),
      "SIAC",
    );
    await user.click(screen.getByRole("button", { name: /Create matter/i }));

    await waitFor(() => expect(createMatterMock).toHaveBeenCalledTimes(1));
    expect(createMatterMock).toHaveBeenCalledWith(
      expect.objectContaining({
        court_id: null,
        court_name: "SIAC",
        forum_catalog_entry_id: null,
      }),
    );
  });

  it("blocks hierarchy submission when the forum catalog is empty", async () => {
    const user = userEvent.setup();
    fetchForumCatalogMock.mockResolvedValue({ entries: [] });
    render(withClient(<NewMatterDialog />));

    await openDialog(user);
    expect(
      await screen.findByText(/Forum catalog is empty/i),
    ).toBeInTheDocument();
    await fillRequiredMatterFields(user);

    expect(
      screen.getByRole("button", { name: /Create matter/i }),
    ).toBeDisabled();
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
    render(withClient(<NewMatterDialog />));

    await openDialog(user);
    await waitFor(() =>
      expect(screen.getByTestId("new-matter-forum-state")).toHaveValue("Delhi"),
    );
    await user.type(await screen.findByLabelText("Title"), "  Spine matter  ");
    await user.type(screen.getByLabelText("Matter code"), "  blr-001  ");
    await user.type(screen.getByLabelText("Practice area"), "Commercial");
    await user.type(screen.getByLabelText("Case number"), " WP(C) 1/2026 ");
    await user.type(
      screen.getByLabelText("CNR number"),
      " dlhc-0100-1234-2026 ",
    );
    await user.click(screen.getByRole("button", { name: /Create matter/i }));

    await waitFor(() => expect(createMatterMock).toHaveBeenCalledTimes(1));
    expect(createMatterMock).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Spine matter",
        matter_code: "BLR-001",
        practice_area: "Commercial",
        case_number: "WP(C) 1/2026",
        cnr_number: "dlhc-0100-1234-2026",
        forum_level: "high_court",
        court_id: "delhi-hc",
        court_name: "Delhi High Court",
        forum_catalog_entry_id: "hc:delhi",
        forum_state: "Delhi",
        forum_district: null,
        forum_city: "New Delhi",
        forum_consumer_level: null,
        status: "active",
      }),
    );
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
  });

  it("rejects matter codes with spaces, slashes, or other special characters before submit", async () => {
    const user = userEvent.setup();
    render(withClient(<NewMatterDialog />));

    await openDialog(user);
    await waitFor(() =>
      expect(screen.getByTestId("new-matter-forum-state")).toHaveValue("Delhi"),
    );
    await user.type(
      await screen.findByLabelText("Title"),
      "Invalid code matter",
    );
    await user.type(screen.getByLabelText("Matter code"), "BAD CODE/1");
    await user.type(screen.getByLabelText("Practice area"), "Commercial");
    await user.click(screen.getByRole("button", { name: /Create matter/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /letters, numbers, and hyphens only/i,
    );
    expect(createMatterMock).not.toHaveBeenCalled();
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
    render(withClient(<NewMatterDialog />));

    await openDialog(user);
    await waitFor(() =>
      expect(screen.getByTestId("new-matter-forum-state")).toHaveValue("Delhi"),
    );
    await fillRequiredMatterFields(user);

    const statusTrigger = screen.getByRole("combobox", { name: "Status" });
    expect(statusTrigger).toHaveTextContent("Active");
    await user.click(statusTrigger);
    const listbox = await screen.findByRole("listbox");
    expect(within(listbox).getByText("Active")).toBeInTheDocument();
    expect(within(listbox).queryByText("Dispose")).not.toBeInTheDocument();
    expect(within(listbox).queryByText("Close")).not.toBeInTheDocument();
    expect(within(listbox).queryByText("Closed")).not.toBeInTheDocument();
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: /Create matter/i }));

    await waitFor(() => expect(createMatterMock).toHaveBeenCalledTimes(1));
    expect(createMatterMock).toHaveBeenCalledWith(
      expect.objectContaining({
        status: "active",
      }),
    );
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
    render(withClient(<NewMatterDialog />, client));

    await openDialog(user);
    await waitFor(() =>
      expect(screen.getByTestId("new-matter-forum-state")).toHaveValue("Delhi"),
    );
    await fillRequiredMatterFields(user);
    await user.click(screen.getByRole("button", { name: /Create matter/i }));

    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: /New matter/i }),
      ).not.toBeInTheDocument(),
    );
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
    render(withClient(<NewMatterDialog />));

    await openDialog(user);
    await fillRequiredMatterFields(user);
    await waitFor(() =>
      expect(screen.getByTestId("new-matter-forum-state")).toHaveValue("Delhi"),
    );
    await user.selectOptions(
      screen.getByTestId("new-matter-forum-category"),
      "district_court",
    );
    await user.selectOptions(
      screen.getByTestId("new-matter-forum-district-state"),
      "Assam",
    );

    await waitFor(() =>
      expect(screen.getByTestId("new-matter-forum-district-state")).toHaveValue(
        "Assam",
      ),
    );
    expect(screen.getByTestId("new-matter-forum-district")).toHaveValue(
      "__uncatalogued_district_court__",
    );
    expect(
      screen.getByRole("button", { name: /Create matter/i }),
    ).toBeDisabled();

    await user.type(
      screen.getByTestId("new-matter-forum-district-name"),
      "Kamrup Metro",
    );
    expect(
      screen.getByRole("button", { name: /Create matter/i }),
    ).toBeDisabled();

    await user.type(
      screen.getByTestId("new-matter-forum-district-court"),
      "Kamrup Metro District Court",
    );
    await user.click(screen.getByRole("button", { name: /Create matter/i }));

    await waitFor(() => expect(createMatterMock).toHaveBeenCalledTimes(1));
    expect(createMatterMock).toHaveBeenCalledWith(
      expect.objectContaining({
        forum_level: "lower_court",
        court_id: null,
        court_name: "Kamrup Metro District Court",
        forum_catalog_entry_id: null,
        forum_state: "Assam",
        forum_district: "Kamrup Metro",
        forum_city: null,
        forum_consumer_level: null,
      }),
    );
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
    render(withClient(<NewMatterDialog />));

    await openDialog(user);
    await fillRequiredMatterFields(user);
    await waitFor(() =>
      expect(screen.getByTestId("new-matter-forum-state")).toHaveValue("Delhi"),
    );
    await user.selectOptions(
      screen.getByTestId("new-matter-forum-category"),
      "district_commission",
    );
    await user.selectOptions(
      screen.getByTestId("new-matter-forum-consumer-state"),
      "Rajasthan",
    );

    expect(
      screen.getByTestId("new-matter-forum-consumer-district"),
    ).toHaveValue("consumer:dcdrc:11080086");
    await user.click(screen.getByRole("button", { name: /Create matter/i }));

    await waitFor(() => expect(createMatterMock).toHaveBeenCalledTimes(1));
    expect(createMatterMock).toHaveBeenLastCalledWith(
      expect.objectContaining({
        forum_level: "tribunal",
        court_id: null,
        court_name: "Ajmer District Consumer Disputes Redressal Commission",
        forum_catalog_entry_id: "consumer:dcdrc:11080086",
        forum_state: "Rajasthan",
        forum_district: "Ajmer",
        forum_city: null,
        forum_consumer_level: "district",
      }),
    );

    createMatterMock.mockClear();
    await openDialog(user);
    await fillRequiredMatterFields(user);
    await user.selectOptions(
      screen.getByTestId("new-matter-forum-category"),
      "district_commission",
    );
    await user.selectOptions(
      screen.getByTestId("new-matter-forum-consumer-state"),
      "Rajasthan",
    );
    await user.selectOptions(
      screen.getByTestId("new-matter-forum-consumer-district"),
      "__uncatalogued_consumer_district__",
    );
    expect(
      screen.getByTestId("new-matter-forum-consumer-district-name"),
    ).toHaveValue("");
    expect(
      screen.getByTestId("new-matter-forum-consumer-forum-name"),
    ).toHaveValue("");
    expect(
      screen.getByRole("button", { name: /Create matter/i }),
    ).toBeDisabled();

    await user.type(
      screen.getByTestId("new-matter-forum-consumer-district-name"),
      "South II",
    );
    expect(
      screen.getByRole("button", { name: /Create matter/i }),
    ).toBeDisabled();
    await user.type(
      screen.getByTestId("new-matter-forum-consumer-forum-name"),
      "South II DCDRC Annex",
    );
    await user.click(screen.getByRole("button", { name: /Create matter/i }));

    await waitFor(() => expect(createMatterMock).toHaveBeenCalledTimes(1));
    expect(createMatterMock).toHaveBeenLastCalledWith(
      expect.objectContaining({
        forum_level: "tribunal",
        court_id: null,
        court_name: "South II DCDRC Annex",
        forum_catalog_entry_id: null,
        forum_state: "Rajasthan",
        forum_district: "South II",
        forum_city: null,
        forum_consumer_level: "district",
      }),
    );
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
    render(withClient(<NewMatterDialog />));

    await openDialog(user);
    await fillRequiredMatterFields(user);
    await user.selectOptions(
      screen.getByTestId("new-matter-forum-category"),
      "district_court",
    );
    await waitFor(() =>
      expect(screen.getByTestId("new-matter-forum-district")).toHaveValue(
        "district:delhi:dwarka",
      ),
    );
    await user.click(screen.getByRole("button", { name: /Create matter/i }));

    await waitFor(() => expect(createMatterMock).toHaveBeenCalledTimes(1));
    expect(createMatterMock).toHaveBeenCalledWith(
      expect.objectContaining({
        forum_level: "lower_court",
        court_id: null,
        court_name: "Dwarka Courts Complex",
        forum_catalog_entry_id: "district:delhi:dwarka",
        forum_state: "Delhi",
        forum_district: "South-West",
        forum_city: "Dwarka",
      }),
    );
  });
});
