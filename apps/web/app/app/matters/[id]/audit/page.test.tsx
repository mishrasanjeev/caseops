import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listMatterAuditEventsMock, matterAuditExportUrlMock, useCapabilityMock } =
  vi.hoisted(() => ({
    listMatterAuditEventsMock: vi.fn(),
    matterAuditExportUrlMock: vi.fn(),
    useCapabilityMock: vi.fn(),
  }));

vi.mock("@/lib/api/endpoints", () => ({
  listMatterAuditEvents: listMatterAuditEventsMock,
  matterAuditExportUrl: matterAuditExportUrlMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: useCapabilityMock,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m-1" }),
}));

import MatterAuditPage from "@/app/app/matters/[id]/audit/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const EMPTY_RESPONSE = {
  matter_id: "m-1",
  events: [],
  total: 0,
  limit: 50,
  offset: 0,
};

describe("MatterAuditPage", () => {
  beforeEach(() => {
    listMatterAuditEventsMock.mockReset();
    matterAuditExportUrlMock.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockReturnValue(true);
    matterAuditExportUrlMock.mockImplementation(
      (matterId: string, filters: { format?: "jsonl" | "csv" }) =>
        `/api/matters/${matterId}/audit-events/export?format=${filters.format}`,
    );
    listMatterAuditEventsMock.mockResolvedValue(EMPTY_RESPONSE);
  });

  it("renders audit filter controls and scoped export links", async () => {
    render(withClient(<MatterAuditPage />));

    expect(await screen.findByText("Matter audit")).toBeInTheDocument();
    expect(screen.getByTestId("audit-filter-since")).toBeInTheDocument();
    expect(screen.getByTestId("audit-filter-until")).toBeInTheDocument();
    expect(screen.getByTestId("audit-filter-actor")).toBeInTheDocument();
    expect(screen.getByTestId("audit-filter-action")).toBeInTheDocument();
    expect(screen.getByTestId("audit-filter-keyword")).toBeInTheDocument();
    expect(screen.getByTestId("matter-audit-export-jsonl")).toHaveAttribute(
      "href",
      "/api/matters/m-1/audit-events/export?format=jsonl",
    );
    expect(screen.getByTestId("matter-audit-export-csv")).toHaveAttribute(
      "href",
      "/api/matters/m-1/audit-events/export?format=csv",
    );
  });

  it("calls audit API with date actor action and keyword filters", async () => {
    render(withClient(<MatterAuditPage />));
    await screen.findByText("Matter audit");

    fireEvent.change(screen.getByTestId("audit-filter-since"), {
      target: { value: "2026-05-01" },
    });
    fireEvent.change(screen.getByTestId("audit-filter-until"), {
      target: { value: "2026-05-07" },
    });
    fireEvent.change(screen.getByTestId("audit-filter-actor"), {
      target: { value: "Priya" },
    });
    fireEvent.change(screen.getByTestId("audit-filter-action"), {
      target: { value: "matter.updated" },
    });
    fireEvent.change(screen.getByTestId("audit-filter-keyword"), {
      target: { value: "claim" },
    });

    await waitFor(() =>
      expect(listMatterAuditEventsMock).toHaveBeenLastCalledWith("m-1", {
        since: "2026-05-01T00:00:00Z",
        until: "2026-05-07T23:59:59Z",
        actor: "Priya",
        action: "matter.updated",
        keyword: "claim",
        limit: 50,
        offset: 0,
      }),
    );
  });

  it("renders audit events with actor metadata and empty state", async () => {
    listMatterAuditEventsMock.mockResolvedValueOnce({
      matter_id: "m-1",
      total: 1,
      limit: 50,
      offset: 0,
      events: [
        {
          id: "evt-1",
          company_id: "c-1",
          actor_type: "human",
          actor_membership_id: "mem-1",
          actor_label: "Lawyer A",
          matter_id: "m-1",
          action: "matter_strategy.created",
          target_type: "matter_strategy_entry",
          target_id: "s-1",
          result: "success",
          metadata: { title: "Settlement posture" },
          request_id: null,
          created_at: "2026-05-07T10:30:00Z",
        },
      ],
    });

    render(withClient(<MatterAuditPage />));

    expect(await screen.findByText("matter_strategy.created")).toBeInTheDocument();
    expect(screen.getByText(/Settlement posture/)).toBeInTheDocument();
    expect(screen.getByText(/Lawyer A/)).toBeInTheDocument();

    listMatterAuditEventsMock.mockResolvedValue(EMPTY_RESPONSE);
    fireEvent.change(screen.getByTestId("audit-filter-keyword"), {
      target: { value: "missing" },
    });
    expect(await screen.findByText(/No audit events match/i)).toBeInTheDocument();
  });

  it("hides export controls when audit export capability is absent", async () => {
    useCapabilityMock.mockReturnValue(false);
    render(withClient(<MatterAuditPage />));
    expect(await screen.findByText("Matter audit")).toBeInTheDocument();
    expect(screen.queryByTestId("matter-audit-export-jsonl")).not.toBeInTheDocument();
    expect(screen.queryByTestId("matter-audit-export-csv")).not.toBeInTheDocument();
  });
});
