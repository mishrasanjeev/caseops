import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  extractDraftingDataMock,
  listDraftingDataMock,
  listDraftsMock,
  reviewDraftingDataFieldMock,
  routerPushMock,
} = vi.hoisted(() => ({
  extractDraftingDataMock: vi.fn(),
  listDraftingDataMock: vi.fn(),
  listDraftsMock: vi.fn(),
  reviewDraftingDataFieldMock: vi.fn(),
  routerPushMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  extractDraftingData: extractDraftingDataMock,
  listDraftingData: listDraftingDataMock,
  listDrafts: listDraftsMock,
  reviewDraftingDataField: reviewDraftingDataFieldMock,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m-1" }),
  useRouter: () => ({ push: routerPushMock }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import MatterDraftsPage from "@/app/app/matters/[id]/drafts/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const FIELD = {
  id: "field-1",
  matter_id: "m-1",
  source_attachment_id: "att-1",
  field_key: "fir_number",
  label: "FIR number",
  proposed_value: "42/2026",
  reviewed_value: null,
  effective_value: null,
  confidence_band: "high" as const,
  status: "suggested" as const,
  source_snippet: "FIR No. 42/2026 was registered at Police Station Indiranagar.",
  source_verified: true,
  reviewed_by_membership_id: null,
  reviewed_at: null,
  created_at: "2026-05-24T08:00:00Z",
  updated_at: "2026-05-24T08:00:00Z",
};

const DRAFTING_DATA_RESPONSE = {
  matter_id: "m-1",
  fields: [FIELD],
  counts: {
    suggested: 1,
    needs_review: 0,
    confirmed: 0,
    overridden: 0,
    rejected: 0,
  },
  created_count: 0,
  updated_count: 0,
  source_attachment_count: 1,
};

describe("MatterDraftsPage drafting data review queue", () => {
  beforeEach(() => {
    extractDraftingDataMock.mockReset();
    listDraftingDataMock.mockReset();
    listDraftsMock.mockReset();
    reviewDraftingDataFieldMock.mockReset();
    routerPushMock.mockReset();

    listDraftsMock.mockResolvedValue({ drafts: [], next_cursor: null });
    listDraftingDataMock.mockResolvedValue(DRAFTING_DATA_RESPONSE);
    extractDraftingDataMock.mockResolvedValue({
      ...DRAFTING_DATA_RESPONSE,
      created_count: 1,
    });
    reviewDraftingDataFieldMock.mockResolvedValue({
      ...FIELD,
      status: "confirmed",
      reviewed_value: "42/2026",
      effective_value: "42/2026",
      reviewed_by_membership_id: "mem-1",
      reviewed_at: "2026-05-24T08:05:00Z",
    });
  });

  it("renders source-bounded suggestions and supports review actions", async () => {
    render(withClient(<MatterDraftsPage />));

    expect(await screen.findByText("Drafting data review queue")).toBeInTheDocument();
    expect(await screen.findByText("FIR number")).toBeInTheDocument();
    expect(screen.getByText("42/2026")).toBeInTheDocument();
    expect(screen.getByText(/FIR No\. 42\/2026/)).toBeInTheDocument();

    await userEvent.click(screen.getByTestId("drafting-data-confirm-fir_number"));
    await waitFor(() =>
      expect(reviewDraftingDataFieldMock).toHaveBeenCalledWith({
        matterId: "m-1",
        fieldId: "field-1",
        action: "confirm",
        overrideValue: undefined,
      }),
    );

    await userEvent.type(
      screen.getByTestId("drafting-data-override-input-fir_number"),
      "FIR 42/2026",
    );
    await userEvent.click(screen.getByTestId("drafting-data-override-fir_number"));
    await waitFor(() =>
      expect(reviewDraftingDataFieldMock).toHaveBeenCalledWith({
        matterId: "m-1",
        fieldId: "field-1",
        action: "override",
        overrideValue: "FIR 42/2026",
      }),
    );

    await userEvent.click(screen.getByTestId("drafting-data-extract"));
    await waitFor(() => expect(extractDraftingDataMock).toHaveBeenCalledWith("m-1"));
  });
});
