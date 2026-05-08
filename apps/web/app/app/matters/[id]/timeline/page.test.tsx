import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchMatterTimelineMock, workspaceData } = vi.hoisted(() => ({
  fetchMatterTimelineMock: vi.fn(),
  workspaceData: {
    current: {
      matter: { id: "m1", matter_code: "X", title: "T", status: "active" },
      hearings: [
        {
          id: "h-upcoming",
          hearing_on: "2026-06-10",
          purpose: "Arguments",
          status: "scheduled",
          forum_name: "Delhi High Court",
        },
        {
          id: "h-completed",
          hearing_on: "2026-05-01",
          purpose: "Interim hearing",
          status: "completed",
          outcome_note: "Stay continued.",
        },
      ],
      attachments: [],
      invoices: [],
      time_entries: [],
      activity: [],
      tasks: [],
      notes: [],
      court_orders: [],
      cause_list_entries: [],
    } as unknown,
  },
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchMatterTimeline: fetchMatterTimelineMock,
}));

vi.mock("@/lib/use-matter-workspace", () => ({
  useMatterWorkspace: () => ({ data: workspaceData.current }),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m1" }),
}));

import MatterTimelinePage from "@/app/app/matters/[id]/timeline/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("MatterTimelinePage", () => {
  beforeEach(() => {
    fetchMatterTimelineMock.mockReset();
    fetchMatterTimelineMock.mockResolvedValue({
      matter_id: "m1",
      sort: "asc",
      generated_at: "2026-05-05T00:00:00Z",
      next_cursor: null,
      items: [
        {
          id: "court_order:o1",
          event_type: "court_order",
          event_date: "2026-05-03",
          title: "Interim stay granted",
          summary: "Stay granted until next listing.",
          source_type: "matter_court_order",
          source_id: "o1",
          badges: ["interim", "stay:granted"],
          links: { matter: "/app/matters/m1", document: "/app/matters/m1/documents/a1/view" },
          order_kind: "interim_order",
          is_interim_order: true,
          stay_status: "granted",
          linked_attachment_id: "a1",
          metadata: { bench_name: "Division Bench" },
        },
        {
          id: "document:a1",
          event_type: "document",
          event_date: "2026-05-04",
          title: "interim-order.pdf",
          summary: "application/pdf",
          status: "indexed",
          source_type: "matter_attachment",
          source_id: "a1",
          badges: ["indexed"],
          links: { matter: "/app/matters/m1", document: "/app/matters/m1/documents/a1/view" },
          metadata: {
            document_type: "order_judgment",
            lifecycle_stage: "orders",
            document_date: "2026-05-03",
            sequence_index: 40,
          },
        },
      ],
    });
  });

  it("renders hearing split, timeline rows, and stay/interim badges", async () => {
    render(withClient(<MatterTimelinePage />));

    expect(screen.getByText(/Upcoming hearings/i)).toBeInTheDocument();
    expect(screen.getByText(/Completed hearings/i)).toBeInTheDocument();
    expect(screen.getByText("Arguments")).toBeInTheDocument();
    expect(screen.getByText("Interim hearing")).toBeInTheDocument();
    expect(await screen.findByText("Interim stay granted")).toBeInTheDocument();
    expect(screen.getByText("Interim order")).toBeInTheDocument();
    expect(screen.getByText("Stay granted")).toBeInTheDocument();
    expect(screen.getAllByText("Linked document")[0]).toHaveAttribute(
      "href",
      "/app/matters/m1/documents/a1/view",
    );
    expect(screen.getByText("Order / judgment")).toBeInTheDocument();
    expect(screen.getByText("Orders")).toBeInTheDocument();
    expect(screen.getByText("Seq 40")).toBeInTheDocument();
  });

  it("requests latest-first sorting when the sort toggle changes", async () => {
    render(withClient(<MatterTimelinePage />));
    await waitFor(() =>
      expect(fetchMatterTimelineMock).toHaveBeenCalledWith(
        expect.objectContaining({ sort: "asc" }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Latest first" }));

    await waitFor(() =>
      expect(fetchMatterTimelineMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ sort: "desc" }),
      ),
    );
  });
});
