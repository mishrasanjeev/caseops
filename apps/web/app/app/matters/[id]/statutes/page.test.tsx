import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  listMatterStatuteReferencesMock,
  listStatutesMock,
  listStatuteSectionsMock,
} = vi.hoisted(() => ({
  listMatterStatuteReferencesMock: vi.fn(),
  listStatutesMock: vi.fn(),
  listStatuteSectionsMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listMatterStatuteReferences: listMatterStatuteReferencesMock,
  listStatutes: listStatutesMock,
  listStatuteSections: listStatuteSectionsMock,
  addMatterStatuteReference: vi.fn(),
  deleteMatterStatuteReference: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m-1" }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import MatterStatutesPage from "@/app/app/matters/[id]/statutes/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("MatterStatutesPage", () => {
  beforeEach(() => {
    listMatterStatuteReferencesMock.mockReset();
    listStatutesMock.mockReset();
    listStatuteSectionsMock.mockReset();
  });

  it("renders empty state + 'Add reference' trigger when no refs exist", async () => {
    listMatterStatuteReferencesMock.mockResolvedValue({
      matter_id: "m-1",
      references: [],
    });
    render(withClient(<MatterStatutesPage />));
    expect(
      await screen.findByText(/No statutes attached yet/i),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("matter-statute-add-trigger"),
    ).toBeInTheDocument();
  });

  it("renders one row per attached reference with relevance badge + click-through", async () => {
    listMatterStatuteReferencesMock.mockResolvedValue({
      matter_id: "m-1",
      references: [
        {
          id: "r-1",
          matter_id: "m-1",
          section_id: "sec-482",
          statute_id: "crpc-1973",
          statute_short_name: "CrPC",
          section_number: "Section 482",
          section_label: "Saving of inherent powers of High Court",
          section_url:
            "https://www.indiacode.nic.in/handle/123456789/15272",
          relevance: "cited",
          notes: null,
          created_at: "2026-04-25T12:00:00Z",
        },
        {
          id: "r-2",
          matter_id: "m-1",
          section_id: "sec-302",
          statute_id: "ipc-1860",
          statute_short_name: "IPC",
          section_number: "Section 302",
          section_label: "Punishment for murder",
          section_url:
            "https://www.indiacode.nic.in/handle/123456789/2263",
          relevance: "opposing",
          notes: null,
          created_at: "2026-04-25T12:01:00Z",
        },
      ],
    });
    render(withClient(<MatterStatutesPage />));
    const crpcLink = await screen.findByRole("link", {
      name: /CrPC.*Section 482/i,
    });
    expect(crpcLink).toHaveAttribute(
      "href",
      "/app/statutes/crpc-1973/sections/Section%20482",
    );
    const ipcLink = screen.getByRole("link", {
      name: /IPC.*Section 302/i,
    });
    expect(ipcLink).toHaveAttribute(
      "href",
      "/app/statutes/ipc-1860/sections/Section%20302",
    );
    expect(screen.getByText(/cited/i)).toBeInTheDocument();
    expect(screen.getByText(/opposing/i)).toBeInTheDocument();
  });
});
