import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listJudgeAliasesMock } = vi.hoisted(() => ({
  listJudgeAliasesMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listJudgeAliases: listJudgeAliasesMock,
}));

import JudgeAliasesAdminPage from "@/app/app/admin/judge-aliases/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("JudgeAliasesAdminPage", () => {
  beforeEach(() => {
    listJudgeAliasesMock.mockReset();
  });

  it("renders the header + a card per judge with all aliases", async () => {
    listJudgeAliasesMock.mockResolvedValue({
      aliases: [
        {
          id: "a1",
          judge_id: "j1",
          judge_full_name: "Atul Sharachchandra Chandurkar",
          court_id: "supreme-court-india",
          court_short_name: "SC",
          alias_text: "Justice A.S. Chandurkar",
          source: "auto_extract",
          created_at: "2026-04-25T12:00:00Z",
        },
        {
          id: "a2",
          judge_id: "j1",
          judge_full_name: "Atul Sharachchandra Chandurkar",
          court_id: "supreme-court-india",
          court_short_name: "SC",
          alias_text: "Justice Atul Sharachchandra Chandurkar",
          source: "auto_extract",
          created_at: "2026-04-25T12:00:00Z",
        },
      ],
      judge_count: 1,
      alias_count: 2,
    });
    render(withClient(<JudgeAliasesAdminPage />));
    // Wait for the link to the judge profile (only visible after the
    // query resolves). The judge name appears multiple times in the
    // rendered DOM (link + label + alias chip) so anchor on the
    // /app/courts/judges/{id} href specifically.
    const profileLinks = await screen.findAllByRole("link", {
      name: /Atul Sharachchandra Chandurkar/i,
    });
    expect(profileLinks[0]).toHaveAttribute(
      "href",
      "/app/courts/judges/j1",
    );
    expect(screen.getByText(/Justice A\.S\. Chandurkar/i)).toBeInTheDocument();
    expect(listJudgeAliasesMock).toHaveBeenCalled();
  });

  it("shows the empty state when no aliases are recorded yet", async () => {
    listJudgeAliasesMock.mockResolvedValue({
      aliases: [],
      judge_count: 0,
      alias_count: 0,
    });
    render(withClient(<JudgeAliasesAdminPage />));
    expect(
      await screen.findByText(/No aliases recorded yet/i),
    ).toBeInTheDocument();
  });

  it("surfaces an error state when the endpoint throws", async () => {
    listJudgeAliasesMock.mockRejectedValue(new Error("network"));
    render(withClient(<JudgeAliasesAdminPage />));
    expect(
      await screen.findByText(/Could not load judge aliases/i),
    ).toBeInTheDocument();
  });
});
