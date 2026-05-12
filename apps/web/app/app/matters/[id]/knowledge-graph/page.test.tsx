import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ZodError } from "zod";

const { fetchLegalKnowledgeGraphMock, materializeLegalKnowledgeGraphMock } =
  vi.hoisted(() => ({
    fetchLegalKnowledgeGraphMock: vi.fn(),
    materializeLegalKnowledgeGraphMock: vi.fn(),
  }));

vi.mock("@/lib/api/endpoints", () => ({
  fetchLegalKnowledgeGraph: fetchLegalKnowledgeGraphMock,
  materializeLegalKnowledgeGraph: materializeLegalKnowledgeGraphMock,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m-1" }),
}));

import LegalKnowledgeGraphPage from "@/app/app/matters/[id]/knowledge-graph/page";
import { legalKnowledgeGraphResponse } from "@/lib/api/schemas";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const GRAPH_RESPONSE = {
  matter_id: "m-1",
  generated_at: "2026-05-12T09:30:00Z",
  run_id: "run-1",
  disclaimer:
    "Legal knowledge graph materialization is source-backed decision support, not legal advice.",
  limitation_note:
    "LI-S11 materializes a matter-scoped graph from existing CaseOps litigation intelligence records only.",
  summary: {
    status: "completed" as const,
    source_record_count: 4,
    node_count: 4,
    edge_count: 3,
    by_node_type: {
      matter: 1,
      proceeding_signal: 1,
      affidavit_question: 1,
      legal_source: 1,
    },
    by_edge_type: {
      derived_from: 2,
      relates_to: 1,
    },
    missing_data: [],
  },
  nodes: [
    {
      id: "node-matter",
      node_key: "matter:m-1",
      node_type: "matter" as const,
      label: "Acme v Beta",
      description: "Matter root",
      source_type: "matter" as const,
      source_id: "m-1",
      source_quote: null,
      confidence_label: null,
      review_status: null,
      limitation_note: "Matter root node; relationships must be source-backed.",
      created_at: "2026-05-12T09:30:00Z",
    },
    {
      id: "node-signal",
      node_key: "matter_proceeding_signal:sig-1",
      node_type: "proceeding_signal" as const,
      label: "Reply Affidavit Deadline",
      description: "Respondent shall file reply affidavit.",
      source_type: "matter_proceeding_signal" as const,
      source_id: "sig-1",
      source_quote: "Respondent shall file reply affidavit by 20.05.2026.",
      confidence_label: "high",
      review_status: "auto_promoted",
      limitation_note: "Proceeding signal extracted from raw order text.",
      created_at: "2026-05-12T09:30:00Z",
    },
    {
      id: "node-question",
      node_key: "affidavit_question:q-1",
      node_type: "affidavit_question" as const,
      label: "Document Support",
      description: "Which invoice supports the payment statement?",
      source_type: "affidavit_question" as const,
      source_id: "q-1",
      source_quote: "respondent paid Rs. 10,000 under Invoice A",
      confidence_label: "low",
      review_status: "review_required",
      limitation_note: "Affidavit question generated from a source-backed quote.",
      created_at: "2026-05-12T09:30:00Z",
    },
    {
      id: "node-source",
      node_key: "matter_court_order:order-1",
      node_type: "legal_source" as const,
      label: "Daily order sheet",
      description: "fixture:order",
      source_type: "matter_court_order" as const,
      source_id: "order-1",
      source_quote: "Respondent shall file reply affidavit by 20.05.2026.",
      confidence_label: null,
      review_status: null,
      limitation_note: "Raw court order text is the source.",
      created_at: "2026-05-12T09:30:00Z",
    },
  ],
  edges: [
    {
      id: "edge-1",
      edge_type: "derived_from" as const,
      label: "Extracted from source order",
      from_node_id: "node-signal",
      to_node_id: "node-source",
      source_type: "matter_court_order" as const,
      source_id: "order-1",
      source_quote: "Respondent shall file reply affidavit by 20.05.2026.",
      confidence_label: "high",
      limitation_note: "Source-backed relationship.",
      created_at: "2026-05-12T09:30:00Z",
    },
    {
      id: "edge-2",
      edge_type: "prompts" as const,
      label: "Question prompts review of source-backed statement",
      from_node_id: "node-question",
      to_node_id: "node-source",
      source_type: "affidavit_question" as const,
      source_id: "q-1",
      source_quote: "respondent paid Rs. 10,000 under Invoice A",
      confidence_label: "low",
      limitation_note: "Source-backed relationship.",
      created_at: "2026-05-12T09:30:00Z",
    },
  ],
};

const EMPTY_RESPONSE = {
  ...GRAPH_RESPONSE,
  run_id: null,
  summary: {
    status: "not_materialized" as const,
    source_record_count: 0,
    node_count: 0,
    edge_count: 0,
    by_node_type: {},
    by_edge_type: {},
    missing_data: ["legal_knowledge_graph_materialization_run"],
  },
  nodes: [],
  edges: [],
};

describe("LegalKnowledgeGraphPage", () => {
  beforeEach(() => {
    fetchLegalKnowledgeGraphMock.mockReset();
    materializeLegalKnowledgeGraphMock.mockReset();
  });

  it("renders source-backed nodes, relationships, source links, and disclaimer", async () => {
    fetchLegalKnowledgeGraphMock.mockResolvedValue(GRAPH_RESPONSE);

    render(withClient(<LegalKnowledgeGraphPage />));

    expect(await screen.findByTestId("legal-knowledge-graph-page")).toBeInTheDocument();
    expect(screen.getByText("Legal Knowledge Graph")).toBeInTheDocument();
    expect(screen.getByTestId("legal-knowledge-graph-disclaimer")).toHaveTextContent(
      /not legal advice/i,
    );
    expect(screen.getByTestId("legal-knowledge-graph-nodes")).toHaveTextContent(
      "Reply Affidavit Deadline",
    );
    expect(screen.getByTestId("legal-knowledge-graph-nodes")).toHaveTextContent(
      "respondent paid Rs. 10,000 under Invoice A",
    );
    expect(screen.getByTestId("legal-knowledge-graph-edges")).toHaveTextContent(
      "Extracted from source order",
    );
    expect(
      screen.getByTestId("legal-knowledge-graph-source-link-node-source"),
    ).toHaveAttribute("href", "/app/matters/m-1/timeline");
  });

  it("renders empty state and materialize action", async () => {
    fetchLegalKnowledgeGraphMock.mockResolvedValue(EMPTY_RESPONSE);
    materializeLegalKnowledgeGraphMock.mockResolvedValue(GRAPH_RESPONSE);

    render(withClient(<LegalKnowledgeGraphPage />));

    expect(await screen.findByTestId("legal-knowledge-graph-empty")).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("legal-knowledge-graph-materialize"));

    await waitFor(() => {
      expect(materializeLegalKnowledgeGraphMock).toHaveBeenCalledWith({ matterId: "m-1" });
    });
  });

  it("rejects unknown node and source types in the frontend contract", () => {
    expect(() =>
      legalKnowledgeGraphResponse.parse({
        ...GRAPH_RESPONSE,
        nodes: [
          {
            ...GRAPH_RESPONSE.nodes[0],
            node_type: "unknown_node",
          },
        ],
      }),
    ).toThrow(ZodError);

    expect(() =>
      legalKnowledgeGraphResponse.parse({
        ...GRAPH_RESPONSE,
        nodes: [
          {
            ...GRAPH_RESPONSE.nodes[0],
            source_type: "unknown_source",
          },
        ],
      }),
    ).toThrow(ZodError);
  });

  it("does not render forbidden legal or biometric copy", async () => {
    fetchLegalKnowledgeGraphMock.mockResolvedValue(GRAPH_RESPONSE);

    render(withClient(<LegalKnowledgeGraphPage />));

    await screen.findByTestId("legal-knowledge-graph-page");
    const rendered = document.body.textContent?.toLowerCase() ?? "";
    for (const phrase of [
      "guaranteed",
      "will win",
      "will lose",
      "win probability",
      "loss probability",
      "judge reputation",
      "judge likes",
      "judge dislikes",
      "favorable judge",
      "emotional instability",
      "psychological diagnosis",
      "biometric",
      "voice stress",
      "this is legal advice",
    ]) {
      expect(rendered).not.toContain(phrase);
    }
    expect(rendered).toContain("not legal advice");
  });
});
