import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const { applyMatterBulkUpdateMock, listMatterBulkUpdateHistoryMock, previewMatterBulkUpdateMock } = vi.hoisted(() => ({
  applyMatterBulkUpdateMock: vi.fn(),
  listMatterBulkUpdateHistoryMock: vi.fn().mockResolvedValue({ operations: [], total: 0 }),
  previewMatterBulkUpdateMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  applyMatterBulkUpdate: applyMatterBulkUpdateMock,
  listMatterBulkUpdateHistory: listMatterBulkUpdateHistoryMock,
  previewMatterBulkUpdate: previewMatterBulkUpdateMock,
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import MatterBulkUpdatePage from "./page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("MatterBulkUpdatePage", () => {
  it("starts with an existing-only workbook preview workflow", () => {
    render(withClient(<MatterBulkUpdatePage />));

    expect(screen.getByRole("heading", { name: "Bulk update existing matters" })).toBeTruthy();
    expect(screen.getByText(/Rows never create new matters/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Preview changes" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Apply reviewed changes" })).toBeDisabled();
    expect(previewMatterBulkUpdateMock).not.toHaveBeenCalled();
  });

  it("shows a durable row result and offers its current-access-filtered CSV", async () => {
    listMatterBulkUpdateHistoryMock.mockResolvedValueOnce({
      total: 1,
      operations: [{
        id: "operation-1", filename: "updates.csv", format: "csv", status: "completed_with_errors",
        total_rows: 2, valid_rows: 1, changed_rows: 1, invalid_rows: 1,
        applied_rows: 1, skipped_rows: 1, failed_rows: 0,
        uploader_name: "History Owner", uploader_email: null, created_at: "2026-09-24T00:00:00Z",
        rows: [
          { row_number: 2, matter_code: "VISIBLE-1", status: "applied", errors: [], changed_fields: ["title"] },
          { row_number: 3, matter_code: null, status: "redacted", errors: [], changed_fields: [] },
        ],
      }],
    });
    const createObjectURL = vi.fn((_blob: Blob) => "blob:result");
    const revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    render(withClient(<MatterBulkUpdatePage />));

    fireEvent.click(await screen.findByRole("button", { name: /^View results for updates\.csv uploaded / }));
    expect(screen.getByText(/Row 2: VISIBLE-1 — applied/)).toBeTruthy();
    expect(screen.getByText(/Row 3: Restricted matter — redacted/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^Download results for updates\.csv uploaded / }));
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:result");
    const report = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(createObjectURL.mock.calls[0][0]);
    });
    expect(report).toContain("VISIBLE-1");
    expect(report).toContain("redacted");
    expect(report).not.toContain("SECRET-1");
    click.mockRestore();
    vi.unstubAllGlobals();
  });

  it("shows final counts and prevents applying the same preview twice", async () => {
    previewMatterBulkUpdateMock.mockResolvedValueOnce({
      preview_token: "reviewed", summary: {
        total_rows: 1, matched_rows: 1, changed_rows: 1, unchanged_rows: 0, invalid_rows: 0,
      }, rows: [{ row_number: 2, matter_code: "VISIBLE-1", status: "changed", errors: [], changes: {} }],
    });
    applyMatterBulkUpdateMock.mockResolvedValueOnce({
      preview_token: "reviewed", operation_id: "operation-2", total_rows: 1, valid_rows: 1,
      applied_rows: 1, skipped_rows: 0, failed_rows: 0,
      rows: [{ row_number: 2, matter_code: "VISIBLE-1", status: "applied", errors: [], changes: {} }],
    });
    render(withClient(<MatterBulkUpdatePage />));
    fireEvent.change(screen.getByLabelText("CSV or XLSX file"), {
      target: { files: [new File(["content"], "updates.csv", { type: "text/csv" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview changes" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Apply reviewed changes" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Apply reviewed changes" }));
    await waitFor(() => expect(screen.getByTestId("bulk-update-final-result")).toHaveTextContent("1 updated"));
    expect(screen.getByTestId("bulk-update-final-result")).toHaveTextContent("0 failed");
    expect(screen.getByRole("button", { name: "Apply reviewed changes" })).toBeDisabled();
  });
  it("2026-09-25 prod shape: a retained same-name upload and a stale history read cannot hide this upload's results", async () => {
    const operation = (id: string, createdAt: string, code: string, extraRows: Array<Record<string, unknown>> = []) => ({
      id, filename: "matter-bulk-update.csv", format: "csv", status: "completed_with_errors",
      total_rows: 1 + extraRows.length, valid_rows: 1, changed_rows: 1, invalid_rows: extraRows.length,
      applied_rows: 1, skipped_rows: extraRows.length, failed_rows: 0,
      uploader_membership_id: "membership-1", uploader_name: "QA Bot", uploader_email: null, created_at: createdAt,
      rows: [
        { row_number: 2, matter_code: code, status: "applied", errors: [], changed_fields: ["title"] },
        ...extraRows,
      ],
    });
    const retained = operation("operation-retained", "2026-09-25T07:49:13Z", "BULK-RETAINED");
    const current = operation("operation-current", "2026-09-25T08:53:51Z", "BULK-CURRENT", [
      { row_number: 3, matter_code: "BULK-UNKNOWN", status: "invalid", errors: ["Matter Code must match one existing matter"], changed_fields: [] },
    ]);
    let resolveInitial: (value: unknown) => void = () => {};
    listMatterBulkUpdateHistoryMock
      .mockImplementationOnce(() => new Promise((resolve) => { resolveInitial = resolve; }))
      .mockResolvedValueOnce({ total: 2, operations: [current, retained] });
    previewMatterBulkUpdateMock.mockResolvedValueOnce({
      preview_token: "reviewed", summary: {
        total_rows: 2, matched_rows: 1, changed_rows: 1, unchanged_rows: 0, invalid_rows: 1,
      }, rows: [],
    });
    applyMatterBulkUpdateMock.mockResolvedValueOnce({
      preview_token: "reviewed", operation_id: "operation-current", total_rows: 2, valid_rows: 1,
      applied_rows: 1, skipped_rows: 1, failed_rows: 0, rows: [],
    });
    render(withClient(<MatterBulkUpdatePage />));
    fireEvent.change(screen.getByLabelText("CSV or XLSX file"), {
      target: { files: [new File(["content"], "matter-bulk-update.csv", { type: "text/csv" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview changes" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Apply reviewed changes" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Apply reviewed changes" }));
    const currentRow = await screen.findByTestId("bulk-update-operation-operation-current");

    // The slower initial read resolves last and must not replace the post-apply history.
    resolveInitial({ total: 1, operations: [retained] });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByTestId("bulk-update-operation-operation-current")).toBe(currentRow);

    expect(currentRow).toHaveAttribute("aria-current", "true");
    expect(currentRow).toHaveTextContent("This upload");
    const retainedRow = screen.getByTestId("bulk-update-operation-operation-retained");
    expect(retainedRow).not.toHaveAttribute("aria-current");
    expect(retainedRow).not.toHaveTextContent("This upload");
    const viewButtons = screen.getAllByRole("button", { name: /^View results for matter-bulk-update\.csv uploaded / });
    expect(viewButtons).toHaveLength(2);
    expect(new Set(viewButtons.map((button) => button.getAttribute("aria-label"))).size).toBe(2);

    fireEvent.click(within(currentRow).getByRole("button", { name: /^View results for / }));
    const results = screen.getByTestId("bulk-update-operation-results-operation-current");
    expect(within(results).getAllByRole("listitem")).toHaveLength(2);
    expect(results).toHaveTextContent("Row 2: BULK-CURRENT — applied (title)");
    expect(results).toHaveTextContent("Row 3: BULK-UNKNOWN — invalid");
    expect(results).not.toHaveTextContent("BULK-RETAINED");
    expect(screen.queryByTestId("bulk-update-operation-results-operation-retained")).toBeNull();
  });
});
