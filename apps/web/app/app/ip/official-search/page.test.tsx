import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { capabilityMock, dismissMock, linkMock, listMock, stageMock, uploadMock } = vi.hoisted(() => ({
  capabilityMock: vi.fn(),
  dismissMock: vi.fn(),
  linkMock: vi.fn(),
  listMock: vi.fn(),
  stageMock: vi.fn(),
  uploadMock: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => capabilityMock(capability),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/api/ip-official-search", () => ({
  dismissIpOfficialSearchImport: dismissMock,
  linkIpOfficialSearchImport: linkMock,
  listIpOfficialSearchImports: listMock,
  stageIpOfficialSearchImport: stageMock,
  uploadIpOfficialSearchPage: uploadMock,
}));

import OfficialSearchPage from "@/app/app/ip/official-search/page";

const RECORD = {
  id: "import-1",
  source_kind: "ipindia_estatus" as const,
  official_url: "https://tmrsearch.ipindia.gov.in/estatus",
  search_query: { application_number: "7012345" },
  original_filename: "estatus.html",
  content_kind: "html" as const,
  byte_size: 2048,
  file_sha256: "a".repeat(64),
  parser_version: "ipindia-official-page-v1",
  parse_status: "needs_review" as const,
  fields: { application_number: "7012345", status: "Registered", mark: "<img src=x onerror=alert(1)>" },
  published_values: { filing_date: "31/02/2024" },
  review_items: [{ field: "filing_date", reason: "unrecognised_date" }],
  attribution: "Office of the Controller General of Patents, Designs and Trade Marks, Government of India (ipindia.gov.in)",
  resolution_status: "pending" as const,
  resolution_reason: null,
  linked_docket_id: null,
  linked_application_id: null,
  registry_snapshot_id: null,
  import_job_id: null,
  uploaded_by_membership_id: "member-1",
  uploaded_by_label: "Synthetic Associate",
  uploaded_at: "2026-11-23T05:00:00Z",
  resolved_at: null,
  version: 1,
  matches: [
    { docket_id: "docket-1", docket_title: "SYNTHETIC ASTRA", application_id: "application-1", application_number: "7012345" },
  ],
};

function renderPage(ui: ReactNode = <OfficialSearchPage />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  capabilityMock.mockReturnValue(true);
  listMock.mockResolvedValue({ records: [RECORD], total: 1, limit: 25, offset: 0 });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("IPLF-052D official trade mark search page", () => {
  it("opens the official page in a new tab with what to enter and the verification note", async () => {
    const user = userEvent.setup();
    renderPage();
    const open = screen.getByRole("link", { name: /Open IP India e-status/ });
    expect(open).toHaveAttribute("href", "https://tmrsearch.ipindia.gov.in/estatus");
    expect(open).toHaveAttribute("target", "_blank");
    expect(open).toHaveAttribute("rel", "noopener noreferrer");
    expect(open).toHaveAttribute("aria-disabled", "true");
    await user.type(screen.getByLabelText("Application number"), "7012345");
    expect(open).toHaveAttribute("aria-disabled", "false");
    expect(screen.getByRole("button", { name: "Copy application number" })).toBeInTheDocument();
    expect(screen.getByText(/CaseOps never fills it in, sees it or searches IP India for you/)).toBeInTheDocument();
  });

  it("shows TMview as a pre-search aid with no upload", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("radio", { name: /Pre-search in TMview/ }));
    await user.type(screen.getByLabelText("Word mark"), "ASTRA");
    await user.type(screen.getByLabelText("Class"), "9");
    const open = screen.getByRole("link", { name: /Open TMview/ });
    expect(open.getAttribute("href")).toContain("https://www.tmdn.org/tmview/#/tmview/results?");
    expect(screen.getByText(/not the official register/)).toBeInTheDocument();
    expect(screen.getByText(/Note the date TMview shows/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Saved result page")).not.toBeInTheDocument();
  });

  it("uploads the saved page with only the search fields", async () => {
    const user = userEvent.setup();
    uploadMock.mockResolvedValue({ record: RECORD, duplicate_upload: false });
    renderPage();
    await user.type(screen.getByLabelText("Application number"), "7012345");
    const file = new File(["<html></html>"], "estatus.html", { type: "text/html" });
    await user.upload(screen.getByLabelText("Saved result page"), file);
    await user.click(screen.getByRole("button", { name: "Import page" }));
    await waitFor(() => expect(uploadMock).toHaveBeenCalledTimes(1));
    expect(uploadMock.mock.calls[0][0]).toEqual({
      metadata: { source_kind: "ipindia_estatus", application_number: "7012345" },
      file,
    });
  });

  it("shows read fields as text, review reasons, lineage, and links a match", async () => {
    const user = userEvent.setup();
    linkMock.mockResolvedValue({ record: RECORD, registry_link_id: "link-1", diff_count: 2, no_change: false });
    const { container } = renderPage();
    const item = (await screen.findByText("SYNTHETIC ASTRA")).closest("li")!.parentElement!.closest("li")!;
    expect(within(item).getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(within(item).getByText(/The date is not in a format CaseOps can read/)).toBeInTheDocument();
    expect(within(item).getByText(/As published: 31\/02\/2024/)).toBeInTheDocument();
    expect(within(item).getByText("a".repeat(64))).toBeInTheDocument();
    expect(within(item).getByText(/Office of the Controller General/)).toBeInTheDocument();
    await user.click(within(item).getByRole("button", { name: "Link as registry evidence" }));
    await waitFor(() => expect(linkMock).toHaveBeenCalledTimes(1));
    expect(linkMock.mock.calls[0][0]).toEqual({ importId: "import-1", expectedVersion: 1, applicationId: "application-1" });
  });

  it("hides linking without registry permission and offers an unmatched page as a new record", async () => {
    const user = userEvent.setup();
    capabilityMock.mockImplementation((capability: string) => capability !== "ip:registry_sync");
    listMock.mockResolvedValue({
      records: [RECORD, { ...RECORD, id: "import-2", file_sha256: "b".repeat(64), matches: [], review_items: [] }],
      total: 2,
      limit: 25,
      offset: 0,
    });
    stageMock.mockResolvedValue({ ...RECORD, resolution_status: "staged_new_record", import_job_id: "job-1" });
    renderPage();
    await screen.findByText("SYNTHETIC ASTRA");
    expect(screen.queryByRole("button", { name: "Link as registry evidence" })).not.toBeInTheDocument();
    expect(screen.getByText("An IP workspace admin links pages to records.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Offer as a new record" }));
    await waitFor(() => expect(stageMock).toHaveBeenCalledTimes(1));
    expect(stageMock.mock.calls[0][0]).toEqual({ importId: "import-2", expectedVersion: 1 });
  });

  it("links a staged record to the portfolio import preview", async () => {
    listMock.mockResolvedValue({
      records: [{ ...RECORD, resolution_status: "staged_new_record", import_job_id: "job-1", matches: [] }],
      total: 1,
      limit: 25,
      offset: 0,
    });
    renderPage();
    const link = await screen.findByRole("link", { name: "Review and confirm the staged record" });
    expect(link).toHaveAttribute("href", "/app/ip/portfolio/imports?job=job-1");
  });

  it("lets a staged page link to its newly created record", async () => {
    const user = userEvent.setup();
    linkMock.mockResolvedValue({ record: RECORD, registry_link_id: "link-1", diff_count: 0, no_change: true });
    listMock.mockResolvedValue({
      records: [{ ...RECORD, resolution_status: "staged_new_record", import_job_id: "job-1", version: 2 }],
      total: 1,
      limit: 25,
      offset: 0,
    });
    renderPage();
    await screen.findByRole("link", { name: "Review and confirm the staged record" });
    await user.click(screen.getByRole("button", { name: "Link as registry evidence" }));
    await waitFor(() => expect(linkMock).toHaveBeenCalledTimes(1));
    expect(linkMock.mock.calls[0][0]).toEqual({ importId: "import-1", expectedVersion: 2, applicationId: "application-1" });
  });

  it("reads older imports on request with the server total until the last page", async () => {
    const user = userEvent.setup();
    const older = (id: string, sha: string) => ({ ...RECORD, id, file_sha256: sha.repeat(64), matches: [], review_items: [] });
    // The page that still needs a decision is the oldest, on the third page.
    const pages = [
      [older("import-new", "c")],
      [older("import-mid", "d")],
      [{ ...RECORD, id: "import-oldest" }],
    ];
    listMock.mockImplementation(async ({ offset = 0 }: { offset?: number } = {}) => ({
      records: pages[offset],
      total: 3,
      limit: 1,
      offset,
    }));
    renderPage();
    expect(await screen.findByText("Showing 1 of 3 imported pages")).toBeInTheDocument();
    expect(screen.queryByText("SYNTHETIC ASTRA")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Load more imported pages" }));
    expect(await screen.findByText("Showing 2 of 3 imported pages")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Load more imported pages" }));
    expect(await screen.findByText("SYNTHETIC ASTRA")).toBeInTheDocument();
    expect(screen.getByText("Showing 3 of 3 imported pages")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more imported pages" })).not.toBeInTheDocument();
    expect(listMock.mock.calls.map(([options]) => options.offset)).toEqual([0, 1, 2]);
  });

  it("requires IP read access", () => {
    capabilityMock.mockReturnValue(false);
    renderPage();
    expect(screen.getByText("IP access required")).toBeInTheDocument();
    expect(listMock).not.toHaveBeenCalled();
  });
});
