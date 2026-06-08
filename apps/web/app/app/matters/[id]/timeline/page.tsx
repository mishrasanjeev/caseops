"use client";

import { useQuery } from "@tanstack/react-query";
import {
  CalendarDays,
  CheckCircle2,
  ClipboardList,
  FileText,
  Gavel,
  ScrollText,
} from "lucide-react";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { OrderBadges } from "@/components/matters/OrderBadges";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { fetchMatterTimeline } from "@/lib/api/endpoints";
import type { MatterTimelineItem } from "@/lib/api/schemas";
import type { WorkspaceHearing } from "@/lib/api/workspace-types";
import { formatLegalDate } from "@/lib/dates";
import { useMatterWorkspace } from "@/lib/use-matter-workspace";

const EVENT_TYPES = [
  ["all", "All events"],
  ["hearing", "Hearings"],
  ["court_order", "Orders"],
  ["document", "Documents"],
  ["deadline", "Deadlines"],
  ["task", "Tasks"],
  ["activity", "Activity"],
] as const;

const EVENT_LABELS: Record<string, string> = {
  hearing: "Hearing",
  court_order: "Order",
  document: "Document",
  deadline: "Deadline",
  task: "Task",
  activity: "Activity",
};

const DOCUMENT_TYPE_LABELS: Record<string, string> = {
  complaint_petition: "Complaint / petition",
  notice: "Notice",
  vakalatnama: "Vakalatnama",
  pleading_reply: "Pleading / reply",
  affidavit: "Affidavit",
  evidence: "Evidence",
  written_submission: "Written submission",
  interim_application: "Interim application",
  order_judgment: "Order / judgment",
  correspondence: "Correspondence",
  research: "Research",
  billing: "Billing",
  other: "Other",
};

const LIFECYCLE_STAGE_LABELS: Record<string, string> = {
  initiation: "Initiation",
  pleadings: "Pleadings",
  interim_applications: "Interim applications",
  evidence: "Evidence",
  arguments: "Arguments",
  orders: "Orders",
  post_order: "Post-order",
  administrative: "Administrative",
  other: "Other",
};

function formatDate(value: string | null | undefined): string {
  return formatLegalDate(value, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function hearingTitle(hearing: WorkspaceHearing): string {
  return hearing.purpose ?? hearing.hearing_type ?? "Hearing";
}

function hearingDate(hearing: WorkspaceHearing): string | null | undefined {
  return hearing.hearing_on ?? hearing.scheduled_for ?? hearing.listing_date;
}

function splitHearings(hearings: WorkspaceHearing[]) {
  const completed = hearings.filter((hearing) => hearing.status === "completed");
  const cancelled = hearings.filter((hearing) => hearing.status === "cancelled");
  const upcoming = hearings.filter(
    (hearing) => hearing.status !== "completed" && hearing.status !== "cancelled",
  );
  return { cancelled, completed, upcoming };
}

function eventIcon(type: string) {
  if (type === "hearing") return Gavel;
  if (type === "court_order") return ScrollText;
  if (type === "document") return FileText;
  if (type === "deadline") return CalendarDays;
  if (type === "task") return ClipboardList;
  return CheckCircle2;
}

function stringMetadata(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

export default function MatterTimelinePage() {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const [sort, setSort] = useState<"asc" | "desc">("asc");
  const [type, setType] = useState<string>("all");
  const { data: workspace } = useMatterWorkspace(matterId);
  const timelineQuery = useQuery({
    queryKey: ["matters", matterId, "timeline", sort, type],
    queryFn: () => fetchMatterTimeline({ matterId, sort, type, limit: 200 }),
    enabled: Boolean(matterId),
  });

  const { cancelled, completed, upcoming } = useMemo(
    () => splitHearings(workspace?.hearings ?? []),
    [workspace?.hearings],
  );
  const items = timelineQuery.data?.items ?? [];

  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-4 lg:grid-cols-2">
        <HearingSection title="Upcoming hearings" hearings={upcoming} />
        <HearingSection title="Completed hearings" hearings={completed} completed />
        <HearingSection title="Cancelled hearings" hearings={cancelled} cancelled />
      </div>

      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
          <div>
            <CardTitle>Matter timeline</CardTitle>
            <CardDescription>
              Hearings, orders, documents, deadlines, tasks, and material activity.
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Select value={type} onValueChange={setType}>
              <SelectTrigger className="w-40" aria-label="Timeline type filter">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {EVENT_TYPES.map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              type="button"
              variant={sort === "asc" ? "secondary" : "outline"}
              onClick={() => setSort("asc")}
            >
              Oldest first
            </Button>
            <Button
              type="button"
              variant={sort === "desc" ? "secondary" : "outline"}
              onClick={() => setSort("desc")}
            >
              Latest first
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {timelineQuery.isPending ? (
            <div className="space-y-3">
              <div className="h-12 rounded-lg bg-[var(--color-bg-2)]" />
              <div className="h-12 rounded-lg bg-[var(--color-bg-2)]" />
              <div className="h-12 rounded-lg bg-[var(--color-bg-2)]" />
            </div>
          ) : items.length === 0 ? (
            <EmptyState
              icon={ScrollText}
              title="No timeline events"
              description="Events appear here as hearings, orders, documents, deadlines, tasks, and activity are added."
            />
          ) : (
            <ol className="flex flex-col gap-3">
              {items.map((item) => (
                <TimelineRow key={item.id} item={item} />
              ))}
            </ol>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function HearingSection({
  title,
  hearings,
  completed = false,
  cancelled = false,
}: {
  title: string;
  hearings: WorkspaceHearing[];
  completed?: boolean;
  cancelled?: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>
          {cancelled
            ? "Listings removed from active calendars and reminder queues."
            : completed
              ? "Closed listings on this matter."
              : "Active listings and adjourned dates."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {hearings.length === 0 ? (
          <p className="text-sm text-[var(--color-mute)]">No {title.toLowerCase()}.</p>
        ) : (
          <ul className="flex flex-col gap-2.5">
            {hearings.map((hearing) => (
              <li
                key={hearing.id}
                className="flex items-start justify-between gap-3 rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] px-3 py-2.5"
              >
                <div className="min-w-0">
                  <div className="text-sm font-medium text-[var(--color-ink)]">
                    {hearingTitle(hearing)}
                  </div>
                  <div className="mt-0.5 text-xs text-[var(--color-mute)]">
                    {formatDate(hearingDate(hearing))}
                    {hearing.forum_name ? ` - ${hearing.forum_name}` : ""}
                  </div>
                  {hearing.outcome_note ?? hearing.outcome_notes ? (
                    <p className="mt-1 line-clamp-2 text-xs text-[var(--color-ink-2)]">
                      {hearing.outcome_note ?? hearing.outcome_notes}
                    </p>
                  ) : null}
                </div>
                <StatusBadge status={hearing.status ?? "scheduled"} />
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function TimelineRow({ item }: { item: MatterTimelineItem }) {
  const Icon = eventIcon(item.event_type);
  const documentType = stringMetadata(item.metadata.document_type);
  const lifecycleStage = stringMetadata(item.metadata.lifecycle_stage);
  const documentDate = stringMetadata(item.metadata.document_date);
  return (
    <li className="grid gap-3 rounded-lg border border-[var(--color-line)] bg-white p-3 md:grid-cols-[110px_1fr]">
      <div className="flex items-center gap-2 text-xs font-medium text-[var(--color-mute)] md:flex-col md:items-start md:gap-1">
        <span className="tabular-nums">{formatDate(item.event_date)}</span>
        <Badge tone="neutral" className="py-0.5">
          {EVENT_LABELS[item.event_type] ?? item.event_type}
        </Badge>
      </div>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Icon className="h-4 w-4 text-[var(--color-ink-3)]" aria-hidden />
          <h3 className="text-sm font-semibold text-[var(--color-ink)]">
            {item.title}
          </h3>
          {item.status ? <StatusBadge status={item.status} /> : null}
          {item.event_type === "court_order" ? <OrderBadges order={item} /> : null}
        </div>
        {item.summary ? (
          <p className="mt-1.5 text-sm leading-relaxed text-[var(--color-mute)]">
            {item.summary}
          </p>
        ) : null}
        <div className="mt-2 flex flex-wrap gap-2 text-xs text-[var(--color-mute-2)]">
          {item.metadata.forum ? <span>{item.metadata.forum}</span> : null}
          {item.metadata.bench_name ? <span>{item.metadata.bench_name}</span> : null}
          {item.metadata.judge_names ? <span>{item.metadata.judge_names}</span> : null}
          {documentType ? (
            <span>{DOCUMENT_TYPE_LABELS[documentType] ?? "Document"}</span>
          ) : null}
          {lifecycleStage ? (
            <span>{LIFECYCLE_STAGE_LABELS[lifecycleStage] ?? lifecycleStage}</span>
          ) : null}
          {documentDate ? <span>{formatDate(documentDate)}</span> : null}
          {typeof item.metadata.sequence_index === "number" ? (
            <span>Seq {item.metadata.sequence_index}</span>
          ) : null}
          {item.links.document ? (
            <a
              href={item.links.document}
              className="font-medium text-[var(--color-brand-700)] hover:underline"
            >
              Linked document
            </a>
          ) : null}
        </div>
      </div>
    </li>
  );
}
