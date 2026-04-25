import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { workspaceData, useCapabilityMock } = vi.hoisted(() => ({
  workspaceData: {
    current: {
      matter: { id: "m1", matter_code: "X", title: "T", status: "active" },
      hearings: [],
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
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  createMatterHearing: vi.fn(),
  pullMatterCourtSync: vi.fn(),
}));

vi.mock("@/lib/use-matter-workspace", () => ({
  useMatterWorkspace: () => ({ data: workspaceData.current }),
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (cap: string) => useCapabilityMock(cap),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m1" }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import MatterHearingsPage from "@/app/app/matters/[id]/hearings/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("MatterHearingsPage", () => {
  beforeEach(() => {
    useCapabilityMock.mockReset();
    useCapabilityMock.mockImplementation(() => false);
  });

  it("renders the Scheduled hearings card and the Schedule hearing trigger", () => {
    render(withClient(<MatterHearingsPage />));
    expect(screen.getByText(/Scheduled hearings/i)).toBeInTheDocument();
    expect(screen.getByTestId("schedule-hearing-open")).toBeInTheDocument();
  });

  it("renders cause-list bench as clickable judge links when resolved", () => {
    workspaceData.current = {
      ...(workspaceData.current as { matter: unknown }),
      matter: {
        id: "m1",
        matter_code: "X",
        title: "T",
        status: "active",
      },
      hearings: [],
      attachments: [],
      invoices: [],
      time_entries: [],
      activity: [],
      tasks: [],
      notes: [],
      court_orders: [],
      cause_list_entries: [
        {
          id: "cle1",
          listing_date: "2026-05-01",
          bench_name: "Justice Aalia Banerjee & Justice Brijesh Karandikar",
          item_number: "12",
          stage: "for arguments",
          resolved_bench: [
            {
              judge_id: "j-aalia",
              matched_alias: "Justice Aalia Banerjee",
              confidence: "exact",
            },
            {
              judge_id: "j-brijesh",
              matched_alias: "Justice Brijesh Karandikar",
              confidence: "initial_surname",
            },
          ],
        },
      ],
    } as unknown;

    render(withClient(<MatterHearingsPage />));

    expect(screen.getByTestId("cause-list-bench-resolved")).toBeInTheDocument();
    const aaliaLink = screen.getByRole("link", {
      name: /Justice Aalia Banerjee/i,
    });
    expect(aaliaLink).toHaveAttribute("href", "/app/courts/judges/j-aalia");
    const brijeshLink = screen.getByRole("link", {
      name: /Justice Brijesh Karandikar/i,
    });
    expect(brijeshLink).toHaveAttribute(
      "href",
      "/app/courts/judges/j-brijesh",
    );
  });

  it("falls back to free-text bench_name when resolved_bench is null", () => {
    workspaceData.current = {
      ...(workspaceData.current as { matter: unknown }),
      matter: {
        id: "m1",
        matter_code: "X",
        title: "T",
        status: "active",
      },
      hearings: [],
      attachments: [],
      invoices: [],
      time_entries: [],
      activity: [],
      tasks: [],
      notes: [],
      court_orders: [],
      cause_list_entries: [
        {
          id: "cle2",
          listing_date: "2026-05-02",
          bench_name: "Some unresolvable bench string",
          item_number: "13",
          stage: "for arguments",
          resolved_bench: null,
        },
      ],
    } as unknown;
    render(withClient(<MatterHearingsPage />));
    expect(
      screen.getByText(/Some unresolvable bench string/i),
    ).toBeInTheDocument();
    // No clickable judge link when resolved_bench is null.
    expect(screen.queryByTestId("cause-list-bench-resolved")).toBeNull();
  });
});
