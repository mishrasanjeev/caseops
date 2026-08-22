import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { downloadMock, historyMock, manifestMock } = vi.hoisted(() => ({
  downloadMock: vi.fn(),
  historyMock: vi.fn(),
  manifestMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  downloadBulkImportErrors: downloadMock,
  getBulkImportManifest: manifestMock,
  listBulkImportJobs: historyMock,
}));

vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

import ImportActivityPage from "@/app/app/imports/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function job(domain: "ip_trademark" | "matter" | "employee", id: string) {
  const owner = domain === "ip_trademark"
    ? "bulk_import_jobs"
    : domain === "matter"
      ? "matter_bulk_import_jobs"
      : "employee_bulk_import_jobs";
  return {
    id,
    domain,
    source_owner: owner,
    read_only_adapter: domain !== "ip_trademark",
    filename: `${domain}-${id}.csv`,
    content_type: "text/csv",
    source_sha256: domain === "employee" ? null : "a".repeat(64),
    source_status: domain === "matter" ? "validated" : "preview_ready",
    status: "preview_ready",
    total_rows: 3,
    valid_rows: 2,
    invalid_rows: 1,
    committed_rows: 0,
    failed_rows: 0,
    created_by_membership_id: "member-1",
    creator_label: "Import Partner",
    created_at: "2026-08-21T10:00:00Z",
    updated_at: "2026-08-21T10:00:00Z",
    expires_at: "2026-08-22T10:00:00Z",
    completed_at: null,
    manifest_url: `/api/imports/${domain}/${id}/manifest`,
    error_report_url: `/api/imports/${domain}/${id}/errors`,
  };
}

describe("ImportActivityPage", () => {
  beforeEach(() => {
    historyMock.mockReset();
    manifestMock.mockReset();
    downloadMock.mockReset();
    historyMock.mockResolvedValue({
      jobs: [job("ip_trademark", "ip-1"), job("matter", "matter-1"), job("employee", "employee-1")],
      accessible_domains: ["ip_trademark", "matter", "employee"],
    });
  });

  it("shows every accessible owner and routes each row to its canonical workflow", async () => {
    render(withClient(<ImportActivityPage />));

    expect(await screen.findByRole("heading", { name: "Import activity" })).toBeInTheDocument();
    expect(screen.getByText("ip_trademark-ip-1.csv")).toBeInTheDocument();
    expect(screen.getByText("matter-matter-1.csv")).toBeInTheDocument();
    expect(screen.getByText("employee-employee-1.csv")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Trademarks import workflow" })).toHaveAttribute("href", "/app/ip/portfolio/imports");
    expect(screen.getByRole("link", { name: "Open Matters import workflow" })).toHaveAttribute("href", "/app/matters/imports");
    expect(screen.getByRole("link", { name: "Open Employees import workflow" })).toHaveAttribute("href", "/app/admin/employees");
  });

  it("filters by domain and exposes legacy manifest limitations", async () => {
    const employee = job("employee", "employee-1");
    historyMock.mockImplementation(async (domain?: string) => ({
      jobs: domain === "employee" ? [employee] : [employee],
      accessible_domains: ["ip_trademark", "matter", "employee"],
    }));
    manifestMock.mockResolvedValue({
      schema_version: "bulk-import-manifest-v1",
      compatibility_mode: "read_only_adapter",
      job: employee,
      file_size_bytes: 120,
      manifest_format: null,
      limitations: ["Legacy employee jobs did not persist an input checksum."],
    });
    const user = userEvent.setup();
    render(withClient(<ImportActivityPage />));

    await user.click(await screen.findByRole("tab", { name: "Employees" }));
    await waitFor(() => expect(historyMock).toHaveBeenLastCalledWith("employee"));
    await user.click(screen.getByRole("button", { name: "View manifest for employee-employee-1.csv" }));

    expect(await screen.findByText("Legacy read-only")).toBeInTheDocument();
    expect(screen.getByText("Legacy employee jobs did not persist an input checksum.")).toBeInTheDocument();
    expect(screen.getByText("Not recorded")).toBeInTheDocument();
  });

  it("downloads a normalized error report", async () => {
    const createObjectURL = vi.fn(() => "blob:errors");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    downloadMock.mockResolvedValue(new Blob(["row_number,status,errors"]));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const user = userEvent.setup();
    render(withClient(<ImportActivityPage />));

    await user.click(await screen.findByRole("button", { name: "Download errors for ip_trademark-ip-1.csv" }));
    await waitFor(() => expect(downloadMock).toHaveBeenCalledWith("ip_trademark", "ip-1"));
    expect(createObjectURL).toHaveBeenCalled();
    expect(click).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:errors");

    click.mockRestore();
    vi.unstubAllGlobals();
  });
});
