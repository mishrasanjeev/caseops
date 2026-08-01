import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchStatuteSectionMock } = vi.hoisted(() => ({
  fetchStatuteSectionMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchStatuteSection: fetchStatuteSectionMock,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({
    statute_id: "ipc-1860",
    section_number: "Section%20302",
  }),
}));

import StatuteSectionDetailPage from "@/app/app/statutes/[statute_id]/sections/[section_number]/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("StatuteSectionDetailPage", () => {
  beforeEach(() => {
    fetchStatuteSectionMock.mockReset();
  });

  it("renders bare text when present", async () => {
    fetchStatuteSectionMock.mockResolvedValue({
      statute: {
        id: "ipc-1860",
        short_name: "IPC",
        long_name: "Indian Penal Code, 1860",
        enacted_year: 1860,
        jurisdiction: "india",
        source_url: "https://www.indiacode.nic.in/handle/123456789/2263",
      },
      section: {
        id: "sec-302",
        statute_id: "ipc-1860",
        section_number: "Section 302",
        section_label: "Punishment for murder",
        section_text:
          "Whoever commits murder shall be punished with death, or imprisonment for life, and shall also be liable to fine.",
        verification_status: "verified_official",
        source_publisher: "India Code",
        source_version: 2,
        source_sha256: "a".repeat(64),
        source_action: {
          state: "available",
          label: "Open source",
          open_url: "/api/source-actions/open?url=official",
          source_reference: "https://www.indiacode.nic.in/handle/123456789/2263",
          reason: null,
          opens_new_tab: true,
        },
        section_url: "https://www.indiacode.nic.in/handle/123456789/2263",
        parent_section_id: null,
        ordinal: 6,
      },
      parent_section: null,
      child_sections: [],
    });
    render(withClient(<StatuteSectionDetailPage />));
    const heading = await screen.findByRole("heading", {
      name: /Section 302/i,
    });
    expect(heading).toBeInTheDocument();
    expect(screen.getByTestId("statute-section-text")).toHaveTextContent(
      /Whoever commits murder/i,
    );
  });

  it("withholds unverified text even if an older response includes it", async () => {
    fetchStatuteSectionMock.mockResolvedValue({
      statute: {
        id: "ipc-1860",
        short_name: "IPC",
        long_name: "Indian Penal Code, 1860",
      },
      section: {
        id: "sec-302",
        statute_id: "ipc-1860",
        section_number: "Section 302",
        section_label: "Punishment for murder",
        section_text: "Unverified legacy cache text must not render.",
        verification_status: "unverified",
        source_version: 1,
        source_action: {
          state: "unverified",
          label: "Open source",
          open_url: null,
          source_reference: null,
          reason: "Curator verification required.",
          opens_new_tab: true,
        },
        section_url: null,
        parent_section_id: null,
        ordinal: 6,
      },
      parent_section: null,
      child_sections: [],
    });
    render(withClient(<StatuteSectionDetailPage />));
    expect(await screen.findByText(/Bare text not yet indexed/i)).toBeInTheDocument();
    expect(screen.queryByText(/Unverified legacy cache text/)).not.toBeInTheDocument();
  });

  it("shows empty state when section_text is null", async () => {
    fetchStatuteSectionMock.mockResolvedValue({
      statute: {
        id: "ipc-1860",
        short_name: "IPC",
        long_name: "Indian Penal Code, 1860",
        enacted_year: 1860,
        jurisdiction: "india",
        source_url: "https://www.indiacode.nic.in/handle/123456789/2263",
      },
      section: {
        id: "sec-302",
        statute_id: "ipc-1860",
        section_number: "Section 302",
        section_label: "Punishment for murder",
        section_text: null,
        section_url: "https://www.indiacode.nic.in/handle/123456789/2263",
        parent_section_id: null,
        ordinal: 6,
      },
      parent_section: null,
      child_sections: [],
    });
    render(withClient(<StatuteSectionDetailPage />));
    expect(
      await screen.findByText(/Bare text not yet indexed/i),
    ).toBeInTheDocument();
  });
});
