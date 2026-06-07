import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { downloadCauseListPdfMock, previewCauseListMock } = vi.hoisted(() => ({
  downloadCauseListPdfMock: vi.fn(),
  previewCauseListMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  downloadCauseListPdf: downloadCauseListPdfMock,
  previewCauseList: previewCauseListMock,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import CauseListPage from "./page";

function withClient(node: ReactNode): ReactNode {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

describe("CauseListPage", () => {
  beforeEach(() => {
    downloadCauseListPdfMock.mockReset();
    previewCauseListMock.mockReset();
    previewCauseListMock.mockResolvedValue({
      rows: [
        {
          serial_number: 1,
          file_number: "GBA-2026-001",
          court_name: "Delhi High Court",
          case_number: "CS(COMM) 1/2026",
          case_title: "GBA Client v Respondent",
          judge_name: "Not available",
          court_number: "12",
          item_number: "4",
          lawyers_appearing: "Lead Lawyer",
          hearing_date: "2026-06-10",
          source: "hearings",
          source_ref: "hearing-1",
          matter_id: "matter-1",
          missing_field_warnings: ["Judge name not available"],
        },
      ],
      row_count: 1,
      generated_at: "2026-06-06T10:00:00Z",
    });
    downloadCauseListPdfMock.mockResolvedValue(undefined);
  });

  it("shows Dispose as the disposed status filter label", () => {
    render(withClient(<CauseListPage />));

    const statusSelect = screen.getByLabelText("Status");
    expect(within(statusSelect).getByRole("option", { name: "Dispose" })).toHaveValue(
      "disposed",
    );
    expect(within(statusSelect).queryByRole("option", { name: "Closed" })).not.toBeInTheDocument();
    expect(within(statusSelect).queryByRole("option", { name: "Close" })).not.toBeInTheDocument();
  });

  it("previews cause-list rows with explicit missing-field warnings", async () => {
    const user = userEvent.setup();
    render(withClient(<CauseListPage />));

    await user.clear(screen.getByLabelText("Court"));
    await user.type(screen.getByLabelText("Court"), "Delhi High Court");
    await user.click(screen.getByRole("button", { name: /Preview/i }));

    await waitFor(() => expect(previewCauseListMock).toHaveBeenCalledTimes(1));
    expect(previewCauseListMock).toHaveBeenCalledWith(
      expect.objectContaining({
        court: "Delhi High Court",
        matter_status: null,
        include_disposed: false,
        source: "both",
      }),
    );
    expect(await screen.findByText("GBA-2026-001")).toBeInTheDocument();
    expect(screen.getByText("Not available")).toBeInTheDocument();
    expect(screen.getByText("1 row")).toBeInTheDocument();
    expect(screen.getByText("pending")).toBeInTheDocument();
  });

  it("downloads the PDF with the current filters", async () => {
    const user = userEvent.setup();
    render(withClient(<CauseListPage />));

    await user.click(screen.getByLabelText("Include disposed"));
    await user.selectOptions(screen.getByLabelText("Status"), "disposed");
    await user.click(screen.getByRole("button", { name: /^PDF$/i }));

    await waitFor(() => expect(downloadCauseListPdfMock).toHaveBeenCalledTimes(1));
    expect(downloadCauseListPdfMock).toHaveBeenCalledWith(
      expect.objectContaining({
        include_disposed: true,
        matter_status: "disposed",
      }),
    );
  });
});
