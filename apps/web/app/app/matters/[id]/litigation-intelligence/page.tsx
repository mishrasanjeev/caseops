"use client";

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  FileSearch,
  Loader2,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Badge } from "@/components/ui/Badge";
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
import { fetchLitigationIntelligenceReview } from "@/lib/api/endpoints";
import type {
  LitigationIntelligenceReviewItem,
  LitigationIntelligenceReviewResponse,
  LitigationIntelligenceReviewSource,
} from "@/lib/api/schemas";

const TYPE_LABELS: Record<LitigationIntelligenceReviewItem["item_type"], string> = {
  proceeding_signal: "Proceeding signals",
  affidavit_statement: "Affidavit statements",
  affidavit_question: "Affidavit questions",
  mock_hearing_session: "Mock hearing sessions",
  mock_hearing_response: "Mock hearing responses",
  predictive_signal: "Predictive limitations",
  bench_context: "Bench context",
};

const STATUS_LABELS: Record<LitigationIntelligenceReviewItem["status"], string> = {
  review_required: "Review required",
  reviewed: "Reviewed",
  auto_promoted: "Auto-promoted",
  insufficient_evidence: "Insufficient evidence",
  supported: "Supported",
  limited_context: "Limited context",
  active: "Active",
  completed: "Completed",
};

const PRIORITY_TONE: Record<
  LitigationIntelligenceReviewItem["priority"],
  "warning" | "neutral"
> = {
  high: "warning",
  medium: "warning",
  low: "neutral",
};

export default function LitigationIntelligenceReviewPage() {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const query = useQuery({
    queryKey: ["matters", matterId, "litigation-intelligence-review"],
    queryFn: () => fetchLitigationIntelligenceReview({ matterId }),
    enabled: Boolean(matterId),
  });
  const refetchReview = query.refetch;

  if (query.isPending) return <LoadingState />;

  if (query.isError) {
    return (
      <QueryErrorState
        title="Could not load litigation intelligence review"
        error={query.error}
        onRetry={() => void refetchReview()}
      />
    );
  }

  if (!query.data) {
    return (
      <QueryErrorState
        title="Litigation intelligence review unavailable"
        error={new Error("No response was returned for this matter.")}
        onRetry={() => void refetchReview()}
      />
    );
  }

  return <ReviewView data={query.data} matterId={matterId} />;
}

function ReviewView({
  data,
  matterId,
}: {
  data: LitigationIntelligenceReviewResponse;
  matterId: string;
}) {
  const grouped = groupItems(data.items);

  return (
    <div className="flex flex-col gap-5" data-testid="litigation-review-page">
      <Card>
        <CardHeader className="gap-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="brand">Litigation Intelligence</Badge>
                <Badge tone={data.summary.review_required_count ? "warning" : "success"}>
                  {data.summary.review_required_count} review item
                  {data.summary.review_required_count === 1 ? "" : "s"}
                </Badge>
                <Badge tone="neutral">
                  <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
                  Source-linked
                </Badge>
              </div>
              <CardTitle as="h1" className="mt-3 text-xl">
                Litigation Intelligence Review
              </CardTitle>
              <CardDescription className="mt-1 max-w-3xl">
                Matter-scoped review queue for proceeding extraction,
                affidavit preparation, mock hearings, and predictive context
                limitations.
              </CardDescription>
            </div>
            <div className="grid min-w-full grid-cols-2 gap-2 text-sm sm:min-w-[28rem] sm:grid-cols-4">
              <SummaryMetric label="Total items" value={String(data.summary.total_items)} />
              <SummaryMetric
                label="Review required"
                value={String(data.summary.review_required_count)}
              />
              <SummaryMetric
                label="Source linked"
                value={String(data.summary.source_linked_count)}
              />
              <SummaryMetric label="Generated" value={formatDateTime(data.generated_at)} />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <p
            className="rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] px-3 py-2 text-xs leading-relaxed text-[var(--color-mute)]"
            data-testid="litigation-review-disclaimer"
          >
            {data.disclaimer}
          </p>
        </CardContent>
      </Card>

      {data.items.length === 0 ? (
        <div data-testid="litigation-review-empty">
          <EmptyState
            icon={CheckCircle2}
            title="No litigation intelligence review items"
            description="Source-backed proceeding, affidavit, mock hearing, and predictive context items will appear here when review is required."
          />
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_18rem]">
          <section className="space-y-4">
            {grouped.map(([type, items]) => (
              <ReviewGroup key={type} type={type} items={items} matterId={matterId} />
            ))}
          </section>
          <ReviewSidebar data={data} />
        </div>
      )}
    </div>
  );
}

function ReviewGroup({
  type,
  items,
  matterId,
}: {
  type: LitigationIntelligenceReviewItem["item_type"];
  items: LitigationIntelligenceReviewItem[];
  matterId: string;
}) {
  return (
    <Card data-testid={`litigation-review-group-${type}`}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle className="text-base">{TYPE_LABELS[type]}</CardTitle>
            <CardDescription>{items.length} source-backed item{items.length === 1 ? "" : "s"}</CardDescription>
          </div>
          <Badge tone="neutral">{items.length}</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-hidden rounded-md border border-[var(--color-line)]">
          <ul className="divide-y divide-[var(--color-line)]">
            {items.map((item) => (
              <ReviewItemRow key={item.id} item={item} matterId={matterId} />
            ))}
          </ul>
        </div>
      </CardContent>
    </Card>
  );
}

function ReviewItemRow({
  item,
  matterId,
}: {
  item: LitigationIntelligenceReviewItem;
  matterId: string;
}) {
  const href = sourceHref(item.source, matterId);
  return (
    <li className="bg-white p-3" data-testid={`litigation-review-item-${item.id}`}>
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={PRIORITY_TONE[item.priority]}>
              {item.priority} priority
            </Badge>
            <StatusBadge status={item.status} />
            {item.confidence_label ? (
              <Badge tone="neutral">Confidence {item.confidence_label}</Badge>
            ) : null}
            {item.sample_size != null ? (
              <Badge tone="neutral">Sample {item.sample_size}</Badge>
            ) : null}
          </div>
          <h3 className="mt-2 text-sm font-semibold text-[var(--color-ink)]">
            {item.title}
          </h3>
          <p className="mt-1 text-sm leading-relaxed text-[var(--color-ink-2)]">
            {item.description}
          </p>
          <p className="mt-2 text-xs leading-relaxed text-[var(--color-mute)]">
            {item.review_reason}
          </p>
        </div>
        <div className="shrink-0 text-left lg:w-56 lg:text-right">
          <div className="text-xs text-[var(--color-mute)]">
            {item.due_on ? `Due ${formatDate(item.due_on)}` : formatDateTime(item.created_at)}
          </div>
          {href ? (
            <Link
              href={href}
              className="mt-2 inline-flex items-center gap-1 rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] px-2 py-1 text-xs font-medium text-[var(--color-ink-2)] hover:text-[var(--color-ink)]"
              data-testid={`litigation-review-source-link-${item.id}`}
            >
              <FileSearch className="h-3.5 w-3.5" aria-hidden />
              View source
            </Link>
          ) : null}
        </div>
      </div>
      <div className="mt-3 grid gap-2 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,0.6fr)]">
        <SourceBlock source={item.source} />
        <div className="rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] px-3 py-2">
          <div className="text-[11px] font-semibold uppercase text-[var(--color-mute)]">
            Limitation
          </div>
          <p className="mt-1 text-xs leading-relaxed text-[var(--color-mute)]">
            {item.limitation_note}
          </p>
        </div>
      </div>
    </li>
  );
}

function SourceBlock({ source }: { source: LitigationIntelligenceReviewSource }) {
  return (
    <div className="rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] px-3 py-2">
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--color-mute)]">
        <span>{sourceLabel(source.source_type)}</span>
        {source.reference ? <span>{source.reference}</span> : null}
        {source.page_reference ? <span>{source.page_reference}</span> : null}
      </div>
      <div className="mt-1 text-xs font-semibold text-[var(--color-ink)]">
        {source.label}
      </div>
      {source.snippet ? (
        <p className="mt-1 line-clamp-3 text-xs leading-relaxed text-[var(--color-mute)]">
          {source.snippet}
        </p>
      ) : null}
    </div>
  );
}

function ReviewSidebar({ data }: { data: LitigationIntelligenceReviewResponse }) {
  return (
    <aside className="space-y-3">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <ClipboardCheck className="h-4 w-4" aria-hidden />
            Queue mix
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <SideList title="By type" values={data.summary.by_type} />
          <SideList title="By status" values={data.summary.by_status} />
        </CardContent>
      </Card>
      <Card>
        <CardContent className="flex gap-2 p-3 text-xs leading-relaxed text-[var(--color-mute)]">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>
            Items are aggregated from existing source-backed intelligence
            slices. This page does not create new predictions or advice.
          </span>
        </CardContent>
      </Card>
    </aside>
  );
}

function SideList({ title, values }: { title: string; values: Record<string, number> }) {
  const entries = Object.entries(values);
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase text-[var(--color-mute)]">
        {title}
      </div>
      {entries.length === 0 ? (
        <p className="mt-1 text-xs text-[var(--color-mute)]">No items</p>
      ) : (
        <ul className="mt-2 space-y-1">
          {entries.map(([key, value]) => (
            <li key={key} className="flex items-center justify-between gap-3 text-xs">
              <span className="text-[var(--color-mute)]">{labelFromKey(key)}</span>
              <span className="font-semibold text-[var(--color-ink)]">{value}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SummaryMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-[var(--color-line)] bg-white px-3 py-2">
      <div className="text-[11px] font-medium uppercase text-[var(--color-mute)]">
        {label}
      </div>
      <div className="mt-1 text-sm font-semibold text-[var(--color-ink)]">
        {value}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: LitigationIntelligenceReviewItem["status"] }) {
  const tone =
    status === "review_required" || status === "insufficient_evidence"
      ? "warning"
      : status === "reviewed" || status === "supported" || status === "completed"
        ? "success"
        : "neutral";
  return <Badge tone={tone}>{STATUS_LABELS[status]}</Badge>;
}

function LoadingState() {
  return (
    <div className="flex flex-col gap-4" data-testid="litigation-review-loading">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            Loading litigation intelligence review
          </CardTitle>
          <CardDescription>Reading source-linked review items.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-2 sm:grid-cols-4">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </CardContent>
      </Card>
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

function groupItems(
  items: LitigationIntelligenceReviewItem[],
): [LitigationIntelligenceReviewItem["item_type"], LitigationIntelligenceReviewItem[]][] {
  const order = Object.keys(TYPE_LABELS) as LitigationIntelligenceReviewItem["item_type"][];
  return order
    .map((type) => [type, items.filter((item) => item.item_type === type)] as const)
    .filter(([, group]) => group.length > 0)
    .map(([type, group]) => [type, group]);
}

function sourceHref(
  source: LitigationIntelligenceReviewSource,
  matterId: string,
): string | null {
  const base = `/app/matters/${encodeURIComponent(matterId)}`;
  switch (source.source_type) {
    case "matter_court_order":
    case "matter_cause_list_entry":
      return `${base}/timeline`;
    case "matter_document":
    case "matter_attachment_chunk":
    case "affidavit_statement":
    case "affidavit_question":
      return `${base}/documents`;
    case "mock_hearing_session":
      return `${base}/hearings`;
    case "predictive_signal_run":
    case "authority_document":
    case "aggregate_snapshot":
      return `${base}/predictive-intelligence`;
    default:
      return null;
  }
}

function sourceLabel(sourceType: LitigationIntelligenceReviewSource["source_type"]): string {
  return labelFromKey(sourceType);
}

function labelFromKey(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium" }).format(date);
}
