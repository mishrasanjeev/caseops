import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  listMatterStatuteReferencesMock,
  listStatutesMock,
  listStatuteSectionsMock,
} = vi.hoisted(() => ({
  listMatterStatuteReferencesMock: vi.fn(),
  listStatutesMock: vi.fn(),
  listStatuteSectionsMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listMatterStatuteReferences: listMatterStatuteReferencesMock,
  listStatutes: listStatutesMock,
  listStatuteSections: listStatuteSectionsMock,
  addMatterStatuteReference: vi.fn(),
  deleteMatterStatuteReference: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m-1" }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import MatterStatutesPage from "@/app/app/matters/[id]/statutes/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("MatterStatutesPage", () => {
  beforeEach(() => {
    listMatterStatuteReferencesMock.mockReset();
    listStatutesMock.mockReset();
    listStatuteSectionsMock.mockReset();
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
    const select = await screen.findByTestId("matter-statute-act-select");
    expect(
      within(select).getByRole("option", { name: /Catalog-only Act/ }),
    ).toBeDisabled();
    expect(
      within(select).getByRole("option", {
        name: /Source-backed Act \(2 verified of 2 catalogued\)/,
      }),
    ).toBeInTheDocument();
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
    await user.selectOptions(
      screen.getByTestId("matter-statute-act-select"),
      "verified-act",
    );
    const sectionSelect = await screen.findByTestId(
      "matter-statute-section-select",
    );
    expect(
      within(sectionSelect).getByRole("option", { name: /Section 1/ }),
    ).toBeEnabled();
    expect(
      within(sectionSelect).getByRole("option", { name: /Section 2/ }),
    ).toBeDisabled();
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

  it("distinguishes a catalog load failure from a genuinely empty verified catalog", async () => {
    listMatterStatuteReferencesMock.mockResolvedValue({
      matter_id: "m-1",
      references: [],
    });
    listStatutesMock.mockRejectedValue(new Error("catalog unavailable"));
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
  });
});
