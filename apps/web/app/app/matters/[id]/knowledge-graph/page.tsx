"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GitBranch, Loader2, Network, RefreshCw, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { apiErrorMessage } from "@/lib/api/config";
import {
  fetchLegalKnowledgeGraph,
  materializeLegalKnowledgeGraph,
} from "@/lib/api/endpoints";
import type {
  LegalKnowledgeGraphEdge,
  LegalKnowledgeGraphNode,
  LegalKnowledgeGraphResponse,
} from "@/lib/api/schemas";

type NodeFilter = "all" | LegalKnowledgeGraphNode["node_type"];

export default function LegalKnowledgeGraphPage() {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["matters", matterId, "legal-knowledge-graph"],
    queryFn: () => fetchLegalKnowledgeGraph({ matterId }),
    enabled: Boolean(matterId),
  });
  const materializeMutation = useMutation({
    mutationFn: () => materializeLegalKnowledgeGraph({ matterId }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "legal-knowledge-graph"],
      });
      toast.success("Knowledge graph materialized.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not materialize knowledge graph."));
    },
  });
  const refetchGraph = query.refetch;

  if (query.isPending) return <LoadingState />;

  if (query.isError) {
    return (
      <QueryErrorState
        title="Could not load legal knowledge graph"
        error={query.error}
        onRetry={() => void refetchGraph()}
      />
    );
  }

  if (!query.data) {
    return (
      <QueryErrorState
        title="Legal knowledge graph unavailable"
        error={new Error("No response was returned for this matter.")}
        onRetry={() => void refetchGraph()}
      />
    );
  }

  return (
    <KnowledgeGraphView
      data={query.data}
      matterId={matterId}
      isMaterializing={materializeMutation.isPending}
      onMaterialize={() => materializeMutation.mutate()}
    />
  );
}

function KnowledgeGraphView({
  data,
  matterId,
  isMaterializing,
  onMaterialize,
}: {
  data: LegalKnowledgeGraphResponse;
  matterId: string;
  isMaterializing: boolean;
  onMaterialize: () => void;
}) {
  const [filter, setFilter] = useState<NodeFilter>("all");
  const nodeTypes = useMemo(
    () => Array.from(new Set(data.nodes.map((node) => node.node_type))).sort(),
    [data.nodes],
  );
  const visibleNodes =
    filter === "all" ? data.nodes : data.nodes.filter((node) => node.node_type === filter);

  return (
    <div className="flex flex-col gap-5" data-testid="legal-knowledge-graph-page">
      <Card>
        <CardHeader className="gap-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="brand">LI-S11</Badge>
                <Badge tone={data.summary.status === "completed" ? "success" : "warning"}>
                  {statusLabel(data.summary.status)}
                </Badge>
                <Badge tone="neutral">
                  <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
                  Source-backed
                </Badge>
              </div>
              <CardTitle as="h1" className="mt-3 text-xl">
                Legal Knowledge Graph
              </CardTitle>
              <CardDescription className="mt-1 max-w-3xl">
                Matter-scoped relationships materialized from proceeding,
                affidavit, mock-hearing, predictive, and review records already
                in CaseOps.
              </CardDescription>
            </div>
            <div className="grid min-w-full grid-cols-2 gap-2 text-sm sm:min-w-[28rem] sm:grid-cols-4">
              <SummaryMetric label="Nodes" value={String(data.summary.node_count)} />
              <SummaryMetric label="Edges" value={String(data.summary.edge_count)} />
              <SummaryMetric
                label="Source records"
                value={String(data.summary.source_record_count)}
              />
              <SummaryMetric label="Updated" value={formatDateTime(data.generated_at)} />
            </div>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <p
            className="rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] px-3 py-2 text-xs leading-relaxed text-[var(--color-mute)]"
            data-testid="legal-knowledge-graph-disclaimer"
          >
            {data.disclaimer}
          </p>
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <p className="max-w-3xl text-xs leading-relaxed text-[var(--color-mute)]">
              {data.limitation_note}
            </p>
            <Button
              type="button"
              onClick={onMaterialize}
              disabled={isMaterializing}
              data-testid="legal-knowledge-graph-materialize"
            >
              {isMaterializing ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <RefreshCw className="h-4 w-4" aria-hidden />
              )}
              Materialize
            </Button>
          </div>
        </CardContent>
      </Card>

      {data.nodes.length === 0 ? (
        <div data-testid="legal-knowledge-graph-empty">
          <EmptyState
            icon={Network}
            title="No graph materialized"
            description="Materialize after source-backed proceeding, affidavit, mock-hearing, predictive, or review records exist for this matter."
          />
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(22rem,0.8fr)]">
          <Card data-testid="legal-knowledge-graph-nodes">
            <CardHeader className="gap-3">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <CardTitle className="text-base">Nodes</CardTitle>
                  <CardDescription>
                    Source-linked matter artifacts and derived intelligence records.
                  </CardDescription>
                </div>
                <select
                  value={filter}
                  onChange={(event) => setFilter(event.target.value as NodeFilter)}
                  className="h-9 rounded-md border border-[var(--color-line)] bg-white px-2 text-sm text-[var(--color-ink)]"
                  aria-label="Filter graph nodes"
                >
                  <option value="all">All node types</option>
                  {nodeTypes.map((type) => (
                    <option key={type} value={type}>
                      {titleCase(type)}
                    </option>
                  ))}
                </select>
              </div>
            </CardHeader>
            <CardContent>
              <div className="overflow-hidden rounded-md border border-[var(--color-line)]">
                <table className="w-full text-left text-xs">
                  <thead className="bg-[var(--color-bg)] text-[var(--color-mute)]">
                    <tr>
                      <th className="px-3 py-2 font-semibold">Node</th>
                      <th className="px-3 py-2 font-semibold">Source</th>
                      <th className="px-3 py-2 font-semibold">Snippet / limitation</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--color-line)] bg-white">
                    {visibleNodes.map((node) => (
                      <NodeRow key={node.id} node={node} matterId={matterId} />
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          <Card data-testid="legal-knowledge-graph-edges">
            <CardHeader>
              <CardTitle className="text-base">Relationships</CardTitle>
              <CardDescription>
                Closed edge types with provenance and source snippets.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col gap-3">
                {data.edges.length === 0 ? (
                  <p className="text-sm text-[var(--color-mute)]">
                    No relationships have been materialized yet.
                  </p>
                ) : (
                  data.edges.slice(0, 12).map((edge) => (
                    <EdgeCard key={edge.id} edge={edge} />
                  ))
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

function NodeRow({
  node,
  matterId,
}: {
  node: LegalKnowledgeGraphNode;
  matterId: string;
}) {
  const href = sourceHref(node.source_type, node.source_id, matterId, node.label);
  return (
    <tr data-testid={`legal-knowledge-graph-node-${node.node_type}`}>
      <td className="px-3 py-2 align-top">
        <div className="font-semibold text-[var(--color-ink)]">{node.label}</div>
        <div className="mt-1 text-[var(--color-mute)]">{titleCase(node.node_type)}</div>
        {node.confidence_label ? (
          <div className="mt-1 text-[var(--color-mute)]">
            Confidence: {titleCase(node.confidence_label)}
          </div>
        ) : null}
      </td>
      <td className="px-3 py-2 align-top">
        <div className="font-medium text-[var(--color-ink-2)]">
          {titleCase(node.source_type)}
        </div>
        <div className="mt-1 break-all text-[var(--color-mute)]">{node.source_id}</div>
        {href ? (
          <Link
            href={href}
            className="mt-2 inline-flex text-xs font-medium text-[var(--color-accent)] hover:underline"
            data-testid={`legal-knowledge-graph-source-link-${node.id}`}
          >
            View source
          </Link>
        ) : null}
      </td>
      <td className="px-3 py-2 align-top">
        <p className="max-w-xl leading-relaxed text-[var(--color-ink-2)]">
          {node.source_quote || node.limitation_note}
        </p>
      </td>
    </tr>
  );
}

function EdgeCard({ edge }: { edge: LegalKnowledgeGraphEdge }) {
  return (
    <article className="rounded-md border border-[var(--color-line)] bg-white px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="neutral">
          <GitBranch className="h-3.5 w-3.5" aria-hidden />
          {titleCase(edge.edge_type)}
        </Badge>
        {edge.confidence_label ? (
          <span className="text-xs text-[var(--color-mute)]">
            {titleCase(edge.confidence_label)}
          </span>
        ) : null}
      </div>
      <h2 className="mt-2 text-sm font-semibold text-[var(--color-ink)]">
        {edge.label}
      </h2>
      <p className="mt-1 text-xs leading-relaxed text-[var(--color-mute)]">
        {edge.source_quote || edge.limitation_note}
      </p>
    </article>
  );
}

function SummaryMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-[var(--color-line)] bg-white px-3 py-2">
      <div className="text-[0.68rem] font-semibold uppercase tracking-[0.08em] text-[var(--color-mute)]">
        {label}
      </div>
      <div className="mt-1 font-mono text-sm tabular-nums text-[var(--color-ink)]">
        {value}
      </div>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="space-y-4" data-testid="legal-knowledge-graph-loading">
      <Skeleton className="h-36 w-full" />
      <Skeleton className="h-80 w-full" />
    </div>
  );
}

function sourceHref(
  sourceType: LegalKnowledgeGraphNode["source_type"],
  sourceId: string,
  matterId: string,
  label: string,
): string | null {
  switch (sourceType) {
    case "matter":
      return `/app/matters/${matterId}`;
    case "matter_court_order":
    case "matter_proceeding_signal":
      return `/app/matters/${matterId}/timeline`;
    case "matter_document":
    case "matter_attachment_chunk":
    case "affidavit_statement":
    case "affidavit_question":
      return `/app/matters/${matterId}/documents`;
    case "mock_hearing_session":
    case "mock_hearing_question":
    case "mock_hearing_response":
      return `/app/matters/${matterId}/hearings`;
    case "predictive_signal_item":
    case "predictive_signal_run":
    case "aggregate_snapshot":
      return `/app/matters/${matterId}/predictive-intelligence`;
    case "litigation_intelligence_review_action":
      return `/app/matters/${matterId}/litigation-intelligence`;
    case "authority_document": {
      const query = label || sourceId;
      const params = new URLSearchParams({ q: query });
      return `/app/research?${params.toString()}`;
    }
    case "unavailable":
      return null;
  }
}

function titleCase(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function statusLabel(value: string): string {
  return titleCase(value);
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
