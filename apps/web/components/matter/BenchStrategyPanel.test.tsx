import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchMock } = vi.hoisted(() => ({
  fetchMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchBenchStrategy: fetchMock,
}));

import { BenchStrategyPanel } from "./BenchStrategyPanel";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const STRONG_DATA = {
  matter_id: "m-1",
  bench_judge_ids: ["j-1", "j-2"],
  total_decisions_indexed: 42,
  evidence_quality: "strong" as const,
  top_authorities: [
    {
      authority_id: "a-1",
      title: "Maneka Gandhi v. Union of India",
      citation_count: 12,
      last_year: 2023,
      sample_judgment_id: "j-x",
    },
  ],
  top_statute_sections: [
    {
      statute_section_id: "s-1",
      statute_id: "ipc-1860",
      section_number: "300",
      section_label: "Murder",
      citation_count: 8,
      last_year: 2024,
      sample_judgment_id: "j-y",
    },
  ],
  disclaimer:
    "Statistical analysis based on indexed decisions only. Not legal advice.",
};

describe("BenchStrategyPanel", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  it("renders the quality chip + statute + authority + disclaimer when strong", async () => {
    fetchMock.mockResolvedValue(STRONG_DATA);
    render(withClient(<BenchStrategyPanel matterId="m-1" />));
    await waitFor(() =>
      expect(screen.getByTestId("bench-strategy-panel")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("bench-strategy-quality-chip")).toHaveTextContent(
      /Strong evidence base/i,
    );
    expect(screen.getByTestId("bench-strategy-statutes")).toBeInTheDocument();
    expect(screen.getByTestId("bench-strategy-authorities")).toBeInTheDocument();
    expect(screen.getByTestId("bench-strategy-disclaimer")).toHaveTextContent(
      /not legal advice/i,
    );
    // Statute section + authority titles
    expect(screen.getByText(/ipc-1860/i)).toBeInTheDocument();
    expect(screen.getByText("Murder")).toBeInTheDocument();
    expect(screen.getByText(/Maneka Gandhi/)).toBeInTheDocument();
  });

  it("renders the insufficient-evidence note when bench history is thin", async () => {
    fetchMock.mockResolvedValue({
      ...STRONG_DATA,
      bench_judge_ids: [],
      total_decisions_indexed: 0,
      evidence_quality: "insufficient",
      top_authorities: [],
      top_statute_sections: [],
    });
    render(withClient(<BenchStrategyPanel matterId="m-1" />));
    await waitFor(() =>
      expect(screen.getByTestId("bench-strategy-panel")).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("bench-strategy-insufficient-note"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("bench-strategy-statutes"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("bench-strategy-authorities"),
    ).not.toBeInTheDocument();
    // Disclaimer still shown
    expect(screen.getByTestId("bench-strategy-disclaimer")).toBeInTheDocument();
  });

  it("renders the no-aggregates info when bench is resolved but L-B/L-C are empty", async () => {
    fetchMock.mockResolvedValue({
      ...STRONG_DATA,
      total_decisions_indexed: 12,
      evidence_quality: "partial",
      top_authorities: [],
      top_statute_sections: [],
    });
    render(withClient(<BenchStrategyPanel matterId="m-1" />));
    await waitFor(() =>
      expect(screen.getByTestId("bench-strategy-panel")).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("bench-strategy-no-aggregates"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("bench-strategy-insufficient-note"),
    ).not.toBeInTheDocument();
  });
});
