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
