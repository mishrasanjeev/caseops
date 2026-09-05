import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  canManage: true,
  fetchForumCatalog: vi.fn(),
  fetchPlatformForumAliases: vi.fn(),
  createPlatformForumAlias: vi.fn(),
  updatePlatformForumAlias: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: () => mocks.canManage,
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchForumCatalog: mocks.fetchForumCatalog,
  fetchPlatformForumAliases: mocks.fetchPlatformForumAliases,
  createPlatformForumAlias: mocks.createPlatformForumAlias,
  updatePlatformForumAlias: mocks.updatePlatformForumAlias,
}));

vi.mock("sonner", () => ({
  toast: { success: mocks.success, error: mocks.error },
}));

import PlatformForumAliasesPage from "@/app/app/platform-admin/forum-aliases/page";

const CATALOG_ENTRY = {
  id: "district:india-gov:kerala:ernakulam",
  parent_id: null,
  court_id: null,
  name: "District Court, Ernakulam",
  forum_type: "district_court",
  forum_level: "lower_court",
  state: "Kerala",
  district: "Ernakulam",
  city: "Kochi",
  consumer_level: null,
  source_name: "India.gov court directory",
  source_url: "https://www.india.gov.in/",
  lineage: "District Court > Kerala > Ernakulam",
  display_order: 1,
  aliases: [],
};

const ALIAS = {
  id: "alias-1",
  forum_catalog_entry_id: CATALOG_ENTRY.id,
  canonical_name: CATALOG_ENTRY.name,
  forum_type: CATALOG_ENTRY.forum_type,
  forum_level: CATALOG_ENTRY.forum_level,
  state: CATALOG_ENTRY.state,
  district: CATALOG_ENTRY.district,
  city: CATALOG_ENTRY.city,
  lineage: CATALOG_ENTRY.lineage,
  alias: "Ernakulam Court Complex",
  normalized_alias: "ernakulam",
  alias_type: "court_complex" as const,
  source_name: "Kerala courts directory",
  source_url: "https://districts.ecourts.gov.in/",
  verification_status: "verified" as const,
  is_active: true,
  reviewed_at: "2026-09-04T10:00:00Z",
  record_version: 3,
  created_by_platform_admin_id: "platform-admin-1",
  reviewed_by_platform_admin_id: "platform-admin-1",
  updated_by_platform_admin_id: "platform-admin-1",
  created_at: "2026-09-04T09:00:00Z",
  updated_at: "2026-09-04T10:00:00Z",
};

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("PlatformForumAliasesPage", () => {
  beforeEach(() => {
    mocks.canManage = true;
    for (const mock of [
      mocks.fetchForumCatalog,
      mocks.fetchPlatformForumAliases,
      mocks.createPlatformForumAlias,
      mocks.updatePlatformForumAlias,
      mocks.success,
      mocks.error,
    ]) {
      mock.mockReset();
    }
    mocks.fetchForumCatalog.mockResolvedValue({ entries: [CATALOG_ENTRY] });
    mocks.fetchPlatformForumAliases.mockResolvedValue({
      aliases: [ALIAS],
      returned_count: 1,
      limit: 200,
      has_more: false,
    });
    mocks.createPlatformForumAlias.mockResolvedValue(ALIAS);
    mocks.updatePlatformForumAlias.mockResolvedValue({
      ...ALIAS,
      is_active: false,
      record_version: 4,
    });
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("denies the global mutation surface without platform catalog capability", () => {
    mocks.canManage = false;

    render(withClient(<PlatformForumAliasesPage />));

    expect(screen.getByText("Catalog curator access required")).toBeVisible();
    expect(mocks.fetchPlatformForumAliases).not.toHaveBeenCalled();
  });

  it("creates a verified non-Delhi alias with source evidence and a reason", async () => {
    const user = userEvent.setup();
    render(withClient(<PlatformForumAliasesPage />));
    await screen.findByTestId("forum-alias-registry");

    await user.type(screen.getByLabelText("Find canonical forum"), "Ernakulam");
    await user.selectOptions(screen.getByLabelText("Canonical forum"), CATALOG_ENTRY.id);
    await user.type(screen.getByLabelText("Alias"), "Ernakulam District Complex");
    await user.selectOptions(screen.getByLabelText("Alias type"), "provider_label");
    await user.selectOptions(screen.getByLabelText("Verification"), "verified");
    await user.type(screen.getByLabelText("Source name"), "Official eCourts directory");
    await user.type(
      screen.getByLabelText("Source URL"),
      "https://districts.ecourts.gov.in/",
    );
    await user.type(
      screen.getByLabelText("Change reason"),
      "Add the reviewed Kerala provider label.",
    );
    await user.click(screen.getByRole("button", { name: "Add alias" }));

    await waitFor(() =>
      expect(mocks.createPlatformForumAlias).toHaveBeenCalledWith({
        forum_catalog_entry_id: CATALOG_ENTRY.id,
        alias: "Ernakulam District Complex",
        alias_type: "provider_label",
        source_name: "Official eCourts directory",
        source_url: "https://districts.ecourts.gov.in/",
        verification_status: "verified",
        is_active: true,
        reason: "Add the reviewed Kerala provider label.",
      }),
    );
  });

  it("contains the accessible action heading inside the horizontal table scroller", async () => {
    render(withClient(<PlatformForumAliasesPage />));
    const table = await screen.findByTestId("forum-alias-registry");
    expect(table.parentElement).toHaveClass("relative", "overflow-x-auto");
    expect(within(table).getByRole("columnheader", { name: "Actions" })).toBeInTheDocument();
  });

  it("updates and deactivates through optimistic concurrency", async () => {
    const user = userEvent.setup();
    render(withClient(<PlatformForumAliasesPage />));
    const row = await screen.findByTestId("forum-alias-row-alias-1");

    await user.click(within(row).getByRole("button", { name: "Edit" }));
    await user.click(screen.getByLabelText("Active registry row"));
    await user.type(
      screen.getByLabelText("Change reason"),
      "Retire an obsolete registry label.",
    );
    await user.click(screen.getByRole("button", { name: "Save alias" }));

    await waitFor(() =>
      expect(mocks.updatePlatformForumAlias).toHaveBeenCalledWith(
        "alias-1",
        expect.objectContaining({
          is_active: false,
          expected_record_version: 3,
          reason: "Retire an obsolete registry label.",
        }),
      ),
    );
  });
});
