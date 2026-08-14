/**
 * Ram workbook 2026-08-14, BUG-003.
 *
 * Duplicates were already excluded from creation, but the page rendered them
 * as validation errors, so the user was told to correct a file that needed no
 * correction. A skipped duplicate must read as skipped: neutral tone, out of
 * the validation-error count, and never blocking the confirm action.
 */
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

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: pushMock }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/capabilities", () => ({ useCapability: () => true }));

import BulkMatterImportPage from "@/app/app/matters/imports/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const jobWithDuplicates = {
  id: "job-dup",
  company_id: "company-1",
  filename: "matters.csv",
  content_type: "text/csv",
  manifest_format: "csv" as const,
  file_size_bytes: 400,
  source_sha256: "b".repeat(64),
  status: "validated" as const,
  total_rows: 2,
  valid_rows: 1,
  invalid_rows: 0,
  duplicate_rows: 1,
  created_count: 0,
  failed_count: 0,
  validation_error_count: 0,
  error_message: null,
  uploaded_by_membership_id: "membership-1",
  uploaded_by_name: "Ram",
  uploaded_by_email: "ram@testfirm.com",
  created_at: "2026-08-14T10:00:00Z",
  updated_at: "2026-08-14T10:00:00Z",
  expires_at: "2026-08-15T10:00:00Z",
  imported_at: null,
  cancelled_at: null,
  rows: [
    {
      id: "row-1",
      row_number: 2,
      status: "valid" as const,
      normalized: { matter_code: "RAM814-KEEP", title: "Keeper" },
      errors: [],
      created_matter_id: null,
    },
    {
      id: "row-2",
      row_number: 3,
      status: "duplicate" as const,
      normalized: { matter_code: "RAM814-KEEP", title: "Keeper" },
      errors: ["Duplicate matter code in this import file."],
      created_matter_id: null,
    },
  ],
};

async function validateFile() {
  render(withClient(<BulkMatterImportPage />));
  const file = new File(["header\nrow"], "matters.csv", { type: "text/csv" });
  fireEvent.change(screen.getByTestId("matter-import-file"), {
    target: { files: [file] },
  });
  fireEvent.click(screen.getByTestId("matter-import-validate"));
  await waitFor(() => expect(previewMatterImportMock).toHaveBeenCalledWith(file));
}

describe("BulkMatterImportPage duplicate handling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listMatterImportsMock.mockResolvedValue({ imports: [], total: 0 });
    previewMatterImportMock.mockResolvedValue(jobWithDuplicates);
    getMatterImportMock.mockResolvedValue(jobWithDuplicates);
  });

  it("labels a duplicate row as skipped rather than as an error to correct", async () => {
    await validateFile();

    expect(await screen.findByText(/Skipped — already exists/)).toBeInTheDocument();
    // The duplicate reason is still visible so the user knows what was excluded.
    expect(
      screen.getByText(/Duplicate matter code in this import file\./),
    ).toBeInTheDocument();
    // ...but it is not painted as a validation failure.
    expect(screen.getByText("Validation errors").parentElement).toHaveTextContent("0");
    expect(screen.getByText("Duplicates skipped").parentElement).toHaveTextContent("1");
  });

  it("keeps confirm enabled and counts only the rows that will be created", async () => {
    await validateFile();

    const confirm = await screen.findByTestId("matter-import-confirm");
    expect(confirm).toBeEnabled();
    expect(confirm).toHaveTextContent("Confirm import (1)");
  });

  it("does not tint a skipped duplicate row with the error background", async () => {
    await validateFile();

    const skipped = await screen.findByText(/Skipped — already exists/);
    const row = skipped.closest("tr");
    expect(row).not.toBeNull();
    expect(row?.className ?? "").not.toContain("danger");
  });
});
