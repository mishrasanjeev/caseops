import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkspaceMatter } from "@/lib/api/workspace-types";

const {
  fetchForumCatalogMock,
  updateMatterMock,
  useCapabilityMock,
  toastSuccess,
  toastError,
} = vi.hoisted(() => ({
  fetchForumCatalogMock: vi.fn(),
  updateMatterMock: vi.fn(),
  useCapabilityMock: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchForumCatalog: fetchForumCatalogMock,
  updateMatter: updateMatterMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => useCapabilityMock(capability),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

import { MatterForumCard } from "@/components/matters/MatterForumCard";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const CATALOG = {
  entries: [
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
      display_order: 20,
    },
    {
      id: "hc:karnataka",
      parent_id: null,
      court_id: "karnataka-hc",
      name: "Karnataka High Court",
      forum_type: "high_court",
      forum_level: "high_court",
      state: "Karnataka",
      district: null,
      city: "Bengaluru",
      consumer_level: null,
      source_name: "CaseOps LW-S4 baseline forum catalog",
      source_url: null,
      lineage: "High Court > Karnataka > Karnataka High Court",
      display_order: 21,
    },
    {
      id: "district:india-gov:delhi:southwestdelhi",
      parent_id: null,
      court_id: null,
      name: "Dwarka Court South West Delhi | India",
      forum_type: "district_court",
      forum_level: "lower_court",
      state: "Delhi",
      district: "South West Delhi",
      city: null,
      consumer_level: null,
      source_name: "India.gov.in District Courts Contact Directory",
      source_url: "https://southwestdelhi.dcourts.gov.in",
      lineage: "District Court > Delhi > South West Delhi > Dwarka Court South West Delhi | India",
      display_order: 9004,
    },
  ],
};

describe("MatterForumCard", () => {
  beforeEach(() => {
    fetchForumCatalogMock.mockReset();
    fetchForumCatalogMock.mockResolvedValue(CATALOG);
    updateMatterMock.mockReset();
    updateMatterMock.mockResolvedValue({ id: "m-1" });
    useCapabilityMock.mockReset();
    useCapabilityMock.mockImplementation((capability: string) => capability === "matters:edit");
    toastSuccess.mockReset();
    toastError.mockReset();
  });

  it("updates a legacy matter to a structured forum selection", async () => {
    const user = userEvent.setup();
    render(
      withClient(
        <MatterForumCard
          matter={
            {
              id: "m-1",
              matter_code: "LW-S4-1",
              title: "Legacy forum matter",
              status: "active",
              practice_area: "Commercial",
              forum_level: "arbitration",
              court_name: "SIAC",
              created_at: "2026-05-05T00:00:00Z",
            } as WorkspaceMatter
          }
        />,
      ),
    );

    expect(screen.getByText("SIAC")).toBeInTheDocument();
    await user.click(screen.getByTestId("matter-forum-edit"));
    await waitFor(() => expect(fetchForumCatalogMock).toHaveBeenCalledTimes(1));

    await user.selectOptions(
      screen.getByTestId("matter-edit-forum-category"),
      "high_court",
    );
    await user.selectOptions(screen.getByTestId("matter-edit-forum-state"), "Karnataka");
    await user.click(screen.getByTestId("matter-forum-save"));

    await waitFor(() => expect(updateMatterMock).toHaveBeenCalledTimes(1));
    expect(updateMatterMock).toHaveBeenCalledWith({
      matterId: "m-1",
      forum_level: "high_court",
      court_id: "karnataka-hc",
      court_name: "Karnataka High Court",
      forum_catalog_entry_id: "hc:karnataka",
      forum_state: "Karnataka",
      forum_district: null,
      forum_city: "Bengaluru",
      forum_consumer_level: null,
    });
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Forum updated."));
  });

  it("edits an uncatalogued district court matter without dropping its state metadata", async () => {
    const user = userEvent.setup();
    render(
      withClient(
        <MatterForumCard
          matter={
            {
              id: "m-assam",
              matter_code: "ASM-001",
              title: "Assam district matter",
              status: "active",
              practice_area: "Commercial",
              forum_level: "lower_court",
              court_id: null,
              court_name: "Kamrup Metro District Court",
              forum_catalog_entry_id: null,
              forum_state: "Assam",
              forum_district: "Kamrup Metro",
              forum_city: null,
              created_at: "2026-06-24T00:00:00Z",
            } as WorkspaceMatter
          }
        />,
      ),
    );

    await user.click(screen.getByTestId("matter-forum-edit"));
    await waitFor(() => expect(fetchForumCatalogMock).toHaveBeenCalledTimes(1));

    expect(screen.getByTestId("matter-edit-forum-category")).toHaveValue(
      "district_court",
    );
    expect(screen.getByTestId("matter-edit-forum-district-state")).toHaveValue(
      "Assam",
    );
    expect(screen.getByTestId("matter-edit-forum-district")).toHaveValue(
      "__uncatalogued_district_court__",
    );
    expect(screen.getByTestId("matter-edit-forum-district-name")).toHaveValue(
      "Kamrup Metro",
    );
    expect(screen.getByTestId("matter-edit-forum-district-court")).toHaveValue(
      "Kamrup Metro District Court",
    );

    await user.clear(screen.getByTestId("matter-edit-forum-district-court"));
    expect(screen.getByTestId("matter-forum-save")).toBeDisabled();
    await user.type(
      screen.getByTestId("matter-edit-forum-district-court"),
      "Kamrup Metro Civil Court",
    );
    await user.click(screen.getByTestId("matter-forum-save"));

    await waitFor(() => expect(updateMatterMock).toHaveBeenCalledTimes(1));
    expect(updateMatterMock).toHaveBeenCalledWith({
      matterId: "m-assam",
      forum_level: "lower_court",
      court_id: null,
      court_name: "Kamrup Metro Civil Court",
      forum_catalog_entry_id: null,
      forum_state: "Assam",
      forum_district: "Kamrup Metro",
      forum_city: null,
      forum_consumer_level: null,
    });
  });
  it("normalizes stale inactive district catalog IDs to editable fallback metadata", async () => {
    const user = userEvent.setup();
    render(
      withClient(
        <MatterForumCard
          matter={
            {
              id: "m-stale-district",
              matter_code: "DW-OLD",
              title: "Legacy Dwarka district matter",
              status: "active",
              practice_area: "Commercial",
              forum_level: "lower_court",
              court_id: null,
              court_name: "Dwarka Courts Complex",
              forum_catalog_entry_id: "district:delhi:dwarka",
              forum_state: "Delhi",
              forum_district: "South-West",
              forum_city: "Dwarka",
              created_at: "2026-06-23T00:00:00Z",
            } as WorkspaceMatter
          }
        />,
      ),
    );

    await user.click(screen.getByTestId("matter-forum-edit"));
    await waitFor(() => expect(fetchForumCatalogMock).toHaveBeenCalledTimes(1));

    expect(screen.getByTestId("matter-edit-forum-category")).toHaveValue(
      "district_court",
    );
    expect(screen.getByTestId("matter-edit-forum-district-state")).toHaveValue(
      "Delhi",
    );
    expect(screen.getByTestId("matter-edit-forum-district")).toHaveValue(
      "__uncatalogued_district_court__",
    );
    expect(screen.getByTestId("matter-edit-forum-district-name")).toHaveValue(
      "South-West",
    );
    expect(screen.getByTestId("matter-edit-forum-district-court")).toHaveValue(
      "Dwarka Courts Complex",
    );

    await user.click(screen.getByTestId("matter-forum-save"));

    await waitFor(() => expect(updateMatterMock).toHaveBeenCalledTimes(1));
    expect(updateMatterMock).toHaveBeenCalledWith({
      matterId: "m-stale-district",
      forum_level: "lower_court",
      court_id: null,
      court_name: "Dwarka Courts Complex",
      forum_catalog_entry_id: null,
      forum_state: "Delhi",
      forum_district: "South-West",
      forum_city: "Dwarka",
      forum_consumer_level: null,
    });
  });

  it("shows a catalog error and blocks unsafe structured saves while editing", async () => {
    const user = userEvent.setup();
    fetchForumCatalogMock.mockRejectedValue(new Error("catalog down"));
    render(
      withClient(
        <MatterForumCard
          matter={
            {
              id: "m-1",
              matter_code: "LW-S4-ERR",
              title: "Catalogued matter",
              status: "active",
              practice_area: "Commercial",
              forum_level: "high_court",
              court_id: "delhi-hc",
              court_name: "Delhi High Court",
              forum_catalog_entry_id: "hc:delhi",
              forum_state: "Delhi",
              forum_city: "New Delhi",
              created_at: "2026-05-05T00:00:00Z",
            } as WorkspaceMatter
          }
        />,
      ),
    );

    await user.click(screen.getByTestId("matter-forum-edit"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Forum catalog could not be loaded/i,
    );
    expect(screen.getByTestId("matter-forum-save")).toBeDisabled();
    expect(updateMatterMock).not.toHaveBeenCalled();
  });
});
