import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listStatuteSectionsMock, fetchStatuteAmendmentHistoryMock } = vi.hoisted(() => ({
  listStatuteSectionsMock: vi.fn(),
  fetchStatuteAmendmentHistoryMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listStatuteSections: listStatuteSectionsMock,
  fetchStatuteAmendmentHistory: fetchStatuteAmendmentHistoryMock,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ statute_id: "crpc-1973" }),
}));

import StatuteDetailPage from "@/app/app/statutes/[statute_id]/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("StatuteDetailPage", () => {
  beforeEach(() => {
    listStatuteSectionsMock.mockReset();
    fetchStatuteAmendmentHistoryMock.mockReset();
    fetchStatuteAmendmentHistoryMock.mockResolvedValue({
      statute_id: "crpc-1973",
      events: [],
    });
  });

  it("renders sections list with click-through to section detail", async () => {
    listStatuteSectionsMock.mockResolvedValue({
      statute: {
        id: "crpc-1973",
        short_name: "CrPC",
        long_name: "Code of Criminal Procedure, 1973",
        enacted_year: 1973,
        jurisdiction: "india",
        source_url: "https://www.indiacode.nic.in/handle/123456789/15272",
      },
      sections: [
        {
          id: "sec-1",
          statute_id: "crpc-1973",
          section_number: "Section 482",
          section_label: "Saving of inherent powers of High Court",
          section_text: null,
          section_url: null,
          parent_section_id: null,
          ordinal: 1,
        },
      ],
    });
    fetchStatuteAmendmentHistoryMock.mockResolvedValue({
      statute_id: "crpc-1973",
      events: [
        {
          id: "evt-1",
          statute_id: "crpc-1973",
          source_record_id: "src-1",
          change_type: "amendment",
          title: "CrPC amendment notification",
          sections_changed: ["Section 482"],
          summary: "Source-backed amendment summary.",
          comparison: {},
          published_date: "2026-05-26",
          effective_date: null,
          source_url: "https://prsindia.org/acts/parliament/crpc-amendment",
          created_at: "2026-05-26T00:00:00Z",
        },
      ],
    });
    render(withClient(<StatuteDetailPage />));
    expect(
      await screen.findByText(/Code of Criminal Procedure/i),
    ).toBeInTheDocument();
    const sectionLink = screen.getByRole("link", {
      name: /Section 482.*Saving of inherent powers/i,
    });
    expect(sectionLink).toHaveAttribute(
      "href",
      "/app/statutes/crpc-1973/sections/Section%20482",
    );
    expect(await screen.findByTestId("statute-amendment-history")).toBeInTheDocument();
    expect(screen.getByText("CrPC amendment notification")).toBeInTheDocument();
    expect(screen.getByText(/Source-backed amendment summary/i)).toBeInTheDocument();
  });

  it("surfaces an error state when the endpoint throws", async () => {
    listStatuteSectionsMock.mockRejectedValue(new Error("network"));
    render(withClient(<StatuteDetailPage />));
    expect(
      await screen.findByText(/Could not load this Act/i),
    ).toBeInTheDocument();
  });
});
