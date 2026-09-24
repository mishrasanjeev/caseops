import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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
});
