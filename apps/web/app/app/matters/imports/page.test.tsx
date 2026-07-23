import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  cancelMatterImportMock,
  commitMatterImportMock,
  downloadMatterImportErrorsMock,
  downloadMatterImportTemplateMock,
  getMatterImportMock,
  listMatterImportsMock,
  previewMatterImportMock,
  pushMock,
} = vi.hoisted(() => ({
  cancelMatterImportMock: vi.fn(),
  commitMatterImportMock: vi.fn(),
  downloadMatterImportErrorsMock: vi.fn(),
  downloadMatterImportTemplateMock: vi.fn(),
  getMatterImportMock: vi.fn(),
  listMatterImportsMock: vi.fn(),
  previewMatterImportMock: vi.fn(),
  pushMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  cancelMatterImport: cancelMatterImportMock,
  commitMatterImport: commitMatterImportMock,
  downloadMatterImportErrors: downloadMatterImportErrorsMock,
  downloadMatterImportTemplate: downloadMatterImportTemplateMock,
  getMatterImport: getMatterImportMock,
  listMatterImports: listMatterImportsMock,
  previewMatterImport: previewMatterImportMock,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: () => true,
}));

import BulkMatterImportPage from "@/app/app/matters/imports/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const validatedJob = {
  id: "job-1",
  company_id: "company-1",
  filename: "matters.csv",
  content_type: "text/csv",
  manifest_format: "csv" as const,
  file_size_bytes: 250,
  source_sha256: "a".repeat(64),
  status: "validated" as const,
  total_rows: 2,
  valid_rows: 1,
  invalid_rows: 1,
  created_count: 0,
  failed_count: 0,
  validation_error_count: 2,
  error_message: null,
  uploaded_by_membership_id: "membership-1",
  uploaded_by_name: "Sanjay Mishra",
  uploaded_by_email: "owner@example.com",
  created_at: "2026-07-17T10:00:00Z",
  updated_at: "2026-07-17T10:00:00Z",
  expires_at: "2026-07-18T10:00:00Z",
  imported_at: null,
  cancelled_at: null,
  rows: [
    {
      id: "row-1",
      row_number: 2,
      status: "valid" as const,
      normalized: {
        matter_code: "BULK-1",
        title: "Valid matter",
        client_name: "Acme",
        court_forum_number: "Court #7 / Bench-A",
      },
      errors: [],
      created_matter_id: null,
    },
    {
      id: "row-2",
      row_number: 3,
      status: "invalid" as const,
      normalized: {
        matter_code: "BULK/2#",
        title: "Invalid matter",
      },
      errors: ["Matter code may contain only letters, numbers, and hyphens."],
      created_matter_id: null,
    },
  ],
};

describe("BulkMatterImportPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listMatterImportsMock.mockResolvedValue({ imports: [], total: 0 });
    previewMatterImportMock.mockResolvedValue(validatedJob);
    commitMatterImportMock.mockResolvedValue({
      job: {
        ...validatedJob,
        status: "completed_with_errors",
        created_count: 1,
        failed_count: 1,
        rows: [
          { ...validatedJob.rows[0], status: "created", created_matter_id: "matter-1" },
          validatedJob.rows[1],
        ],
      },
      created_matter_ids: ["matter-1"],
    });
    getMatterImportMock.mockResolvedValue(validatedJob);
  });

  it("downloads the canonical XLSX template and explains compatibility rules", async () => {
    downloadMatterImportTemplateMock.mockReturnValue(new Promise<Blob>(() => undefined));
    render(withClient(<BulkMatterImportPage />));

    fireEvent.click(screen.getByTestId("matter-import-template-xlsx"));

    await waitFor(() =>
      expect(downloadMatterImportTemplateMock).toHaveBeenCalledWith("xlsx"),
    );
    expect(screen.getByTestId("matter-import-compatibility-guidance")).toHaveTextContent(
      /Court Forum Number is stored separately/i,
    );
  });

  it("validates, displays every error first, and commits all valid matter rows", async () => {
    render(withClient(<BulkMatterImportPage />));

    const file = new File(["header\nrow"], "matters.csv", { type: "text/csv" });
    fireEvent.change(screen.getByTestId("matter-import-file"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByTestId("matter-import-validate"));

    await waitFor(() => expect(previewMatterImportMock).toHaveBeenCalledWith(file));
    expect(await screen.findByText(/letters, numbers, and hyphens/)).toBeInTheDocument();
    expect(screen.getByText("BULK-1")).toBeInTheDocument();
    expect(screen.getByText("BULK/2#")).toBeInTheDocument();
    expect(screen.getByText("Court #7 / Bench-A")).toBeInTheDocument();
    expect(screen.getByText("Validation errors").parentElement).toHaveTextContent("2");

    fireEvent.click(screen.getByTestId("matter-import-confirm"));
    await waitFor(() => expect(commitMatterImportMock).toHaveBeenCalledWith("job-1"));
    expect(await screen.findByText("completed with errors")).toBeInTheDocument();
  });

  it("searches import history by file or uploader", async () => {
    render(withClient(<BulkMatterImportPage />));
    await waitFor(() => expect(listMatterImportsMock).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText("Search"), {
      target: { value: "migration-july" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() =>
      expect(listMatterImportsMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ q: "migration-july" }),
      ),
    );
  });
});
