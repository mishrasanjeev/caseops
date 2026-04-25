import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listStatuteSectionsMock } = vi.hoisted(() => ({
  listStatuteSectionsMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listStatuteSections: listStatuteSectionsMock,
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
  });

  it("surfaces an error state when the endpoint throws", async () => {
    listStatuteSectionsMock.mockRejectedValue(new Error("network"));
    render(withClient(<StatuteDetailPage />));
    expect(
      await screen.findByText(/Could not load this Act/i),
    ).toBeInTheDocument();
  });
});
