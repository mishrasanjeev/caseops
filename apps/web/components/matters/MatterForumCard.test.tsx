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
