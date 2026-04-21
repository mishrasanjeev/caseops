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
});
