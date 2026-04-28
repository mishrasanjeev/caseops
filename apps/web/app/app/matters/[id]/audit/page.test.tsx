import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { useMatterWorkspaceMock } = vi.hoisted(() => ({
  useMatterWorkspaceMock: vi.fn(),
}));

vi.mock("@/lib/use-matter-workspace", () => ({
  useMatterWorkspace: useMatterWorkspaceMock,
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

const BASE_MATTER = { id: "m-1", title: "Test Matter", matter_code: "T-1" };

describe("MatterAuditPage", () => {
  beforeEach(() => {
    useMatterWorkspaceMock.mockReset();
  });

  it("renders nothing while workspace data is loading", () => {
    useMatterWorkspaceMock.mockReturnValue({ data: undefined });
    const { container } = render(withClient(<MatterAuditPage />));
    expect(container.firstChild).toBeNull();
  });

  it("renders empty-state copy when activity feed is empty", () => {
    useMatterWorkspaceMock.mockReturnValue({
      data: { matter: BASE_MATTER, activity: [] },
    });
    render(withClient(<MatterAuditPage />));
    expect(screen.getByText(/Audit trail/i)).toBeInTheDocument();
    expect(screen.getByText(/No activity yet/i)).toBeInTheDocument();
  });

  it("renders activity entries with actor, type, and detail", () => {
    useMatterWorkspaceMock.mockReturnValue({
      data: {
        matter: BASE_MATTER,
        activity: [
          {
            id: "a-1",
            title: "Matter created",
            event_type: "matter.created",
            detail: "Initial intake from client",
            actor_name: "Lawyer A",
            created_at: "2026-04-15T10:30:00.000Z",
          },
          {
            id: "a-2",
            title: "Document uploaded",
            event_type: "matter.document.uploaded",
            detail: null,
            actor_name: null,
            created_at: "2026-04-16T14:00:00.000Z",
          },
        ],
      },
    });
    render(withClient(<MatterAuditPage />));
    expect(screen.getByText("Matter created")).toBeInTheDocument();
    expect(screen.getByText("Document uploaded")).toBeInTheDocument();
    expect(screen.getByText(/Initial intake from client/)).toBeInTheDocument();
    expect(screen.getByText("matter.created")).toBeInTheDocument();
    // Anonymous events fall back to "system" in the actor row.
    const systemActor = screen.getAllByText(/^system /).length;
    expect(systemActor).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Lawyer A/)).toBeInTheDocument();
  });
});
