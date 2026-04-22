"use client";

import { useQuery } from "@tanstack/react-query";
import { Bell, CircleCheck, CircleX, Clock, Mail } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Card, CardContent } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  type HearingReminderRecord,
  type HearingReminderStatus,
  listAdminNotifications,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

type StatusFilter = "all" | HearingReminderStatus;

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "queued", label: "Queued" },
  { value: "sent", label: "Sent" },
  { value: "delivered", label: "Delivered" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

function statusTone(s: HearingReminderStatus): "neutral" | "success" | "warning" | "brand" {
  if (s === "delivered") return "success";
  if (s === "failed" || s === "cancelled") return "warning";
  if (s === "sent") return "brand";
  return "neutral";
}

function formatWhen(value: string | null | undefined): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}


export default function AdminNotificationsPage() {
  const isAdmin = useCapability("workspace:admin");
  const [status, setStatus] = useState<StatusFilter>("all");
  const query = useQuery({
    queryKey: ["admin", "notifications", { status }],
    queryFn: () => listAdminNotifications({ status }),
    enabled: isAdmin,
  });

  if (!isAdmin) {
    return (
      <EmptyState
        icon={Bell}
        title="Admin access required"
        description="The notifications dashboard is limited to workspace admins."
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Admin · Notifications"
        title="Hearing reminders"
        description="Every reminder the system intends to send, with delivery status from SendGrid. Durable — rows persist even when the provider isn't wired yet."
      />

      <section className="grid gap-3 md:grid-cols-4">
        <KpiCard
          icon={Clock}
          label="Queued"
          value={query.data?.total_queued ?? 0}
        />
        <KpiCard icon={Mail} label="Sent" value={query.data?.total_sent ?? 0} />
        <KpiCard
          icon={CircleCheck}
          label="Delivered"
          value={query.data?.total_delivered ?? 0}
        />
        <KpiCard
          icon={CircleX}
          label="Failed"
          value={query.data?.total_failed ?? 0}
        />
      </section>

      <Card>
        <CardContent className="flex flex-col gap-4 pt-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <label
                htmlFor="status-filter"
                className="text-xs font-medium text-[var(--color-mute-2)]"
              >
                Status
              </label>
              <Select
                value={status}
                onValueChange={(v) => setStatus(v as StatusFilter)}
              >
                <SelectTrigger id="status-filter" className="w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STATUS_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {query.isPending ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : query.isError ? (
            <QueryErrorState
              title="Could not load notifications"
              error={query.error}
              onRetry={query.refetch}
            />
          ) : query.data.reminders.length === 0 ? (
            <EmptyState
              icon={Bell}
              title="No reminders yet"
              description="Scheduled hearings will queue reminders here at T-24h and T-1h. Rows appear the moment a hearing is saved."
            />
          ) : (
            <ul className="flex flex-col divide-y divide-[var(--color-line)]">
              {query.data.reminders.map((r) => (
                <ReminderRow key={r.id} reminder={r} />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}


function KpiCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Bell;
  label: string;
  value: number;
}) {
  return (
    <Card>
      <CardContent className="flex items-start gap-3 py-4">
        <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--color-bg)] text-[var(--color-ink-3)]">
          <Icon className="h-5 w-5" aria-hidden />
        </span>
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
            {label}
          </div>
          <div className="tabular text-xl font-semibold text-[var(--color-ink)]">
            {value}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}


function ReminderRow({
  reminder: r,
}: {
  reminder: HearingReminderRecord;
}) {
  return (
    <li className="flex items-start justify-between gap-3 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={statusTone(r.status)}>{r.status}</Badge>
          <span className="text-xs text-[var(--color-mute)]">
            {r.channel}
          </span>
          <span className="text-xs text-[var(--color-mute)]">
            · {r.recipient_email ?? "no recipient"}
          </span>
        </div>
        <div className="mt-1 text-xs text-[var(--color-mute)]">
          Scheduled: {formatWhen(r.scheduled_for)}
          {r.sent_at ? ` · Sent: ${formatWhen(r.sent_at)}` : ""}
          {r.delivered_at ? ` · Delivered: ${formatWhen(r.delivered_at)}` : ""}
        </div>
        {r.last_error ? (
          <div className="mt-1 text-xs text-[var(--color-warn-700,#a55400)]">
            {r.last_error}
          </div>
        ) : null}
      </div>
      <div className="text-right text-xs text-[var(--color-mute)]">
        {r.attempts > 0 ? `${r.attempts} attempt${r.attempts === 1 ? "" : "s"}` : ""}
      </div>
    </li>
  );
}
