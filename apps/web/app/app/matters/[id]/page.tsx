"use client";

import { ClipboardList, Gavel, MessageSquareText, ScrollText } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { CounselRecommendationsCard } from "@/components/app/CounselRecommendationsCard";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useMatterWorkspace } from "@/lib/use-matter-workspace";

function formatDate(value: string | null | undefined, withTime = false): string {
  if (!value) return "—";
  try {
    const d = new Date(value);
    return withTime
      ? d.toLocaleString(undefined, {
          day: "2-digit",
          month: "short",
          year: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        })
      : d.toLocaleDateString(undefined, {
          day: "2-digit",
          month: "short",
          year: "numeric",
        });
  } catch {
    return value;
  }
}

export default function MatterOverviewPage() {
  const params = useParams<{ id: string }>();
  const { data } = useMatterWorkspace(params.id);

  if (!data) return null;

  const activeTasks = data.tasks.filter((t) => t.status !== "done").slice(0, 5);
  const upcomingHearings = data.hearings
    .filter((h) => h.hearing_on || h.scheduled_for || h.listing_date)
    .slice(0, 4);
  const latestOrder = data.court_orders[0];
  const recentActivity = data.activity.slice(0, 6);
  const recentNotes = data.notes.slice(0, 3);

  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>Matter summary</CardTitle>
          <CardDescription>
            The brief a partner should get in 30 seconds before a status call.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {data.matter.description ? (
            <p className="text-prose-wide whitespace-pre-line text-sm leading-relaxed text-[var(--color-ink-2)]">
              {data.matter.description}
            </p>
          ) : (
            <EmptyState
              icon={ClipboardList}
              title="No summary yet"
              description="Add a short description when the matter editor ships. For now, use the intake form."
            />
          )}
        </CardContent>
      </Card>

      <CounselRecommendationsCard matterId={data.matter.id} />

      <Card>
        <CardHeader>
          <CardTitle>Last court order</CardTitle>
          <CardDescription>Most recent imported or attached order.</CardDescription>
        </CardHeader>
        <CardContent>
          {latestOrder ? (
            <div className="flex flex-col gap-1.5">
              <div className="text-xs font-medium uppercase tracking-wider text-[var(--color-mute-2)]">
                {formatDate(latestOrder.order_date)}
              </div>
              <h3 className="text-sm font-semibold text-[var(--color-ink)]">
                {latestOrder.title ?? "Order"}
              </h3>
              {latestOrder.summary ? (
                <p className="line-clamp-4 text-sm text-[var(--color-mute)]">
                  {latestOrder.summary}
                </p>
              ) : null}
              {latestOrder.source ? (
                <span className="mt-1 inline-flex w-fit items-center rounded-full border border-[var(--color-line)] bg-[var(--color-bg)] px-2 py-0.5 text-[10px] uppercase tracking-wider text-[var(--color-mute)]">
                  {latestOrder.source}
                </span>
              ) : null}
            </div>
          ) : (
            <EmptyState
              icon={ScrollText}
              title="No orders yet"
              description="Orders are imported by court sync or uploaded from the Documents tab."
              action={
                <Link
                  className="inline-flex items-center justify-center gap-2 rounded-md bg-[var(--color-ink)] px-3 py-1.5 text-sm font-medium text-white hover:bg-[var(--color-ink-2)]"
                  href={`/app/matters/${data.matter.id}/hearings`}
                >
                  Go to court sync
                </Link>
              }
            />
          )}
        </CardContent>
      </Card>

      {/* BUG-011: Open tasks card only renders when there ARE tasks —
          there's no task-creation UI on the overview today, so an
          always-visible empty card reads as a broken promise. */}
      {activeTasks.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Open tasks</CardTitle>
            <CardDescription>Across this matter.</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="flex flex-col gap-3">
              {activeTasks.map((task) => (
                <li
                  key={task.id}
                  className="flex flex-col gap-1 rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] px-3 py-2"
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-sm font-medium text-[var(--color-ink)]">
                      {task.title}
                    </span>
                    <StatusBadge status={task.status} />
                  </div>
                  <div className="flex items-center justify-between text-xs text-[var(--color-mute)]">
                    <span>{task.owner_name ?? "Unassigned"}</span>
                    <span>{task.due_on ? formatDate(task.due_on) : "No due date"}</span>
                  </div>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Upcoming hearings</CardTitle>
          <CardDescription>Next four on the calendar.</CardDescription>
        </CardHeader>
        <CardContent>
          {upcomingHearings.length === 0 ? (
            <EmptyState
              icon={Gavel}
              title="No hearings scheduled"
              description="Import from the court feed or schedule one manually."
              action={
                <Link
                  className="inline-flex items-center justify-center gap-2 rounded-md bg-[var(--color-ink)] px-3 py-1.5 text-sm font-medium text-white hover:bg-[var(--color-ink-2)]"
                  href={`/app/matters/${data.matter.id}/hearings`}
                >
                  Schedule hearing
                </Link>
              }
            />
          ) : (
            <ul className="flex flex-col gap-3">
              {upcomingHearings.map((h) => (
                <li
                  key={h.id}
                  className="flex items-center justify-between rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] px-3 py-2"
                >
                  <div className="flex flex-col">
                    <span className="text-sm font-medium text-[var(--color-ink)]">
                      {h.hearing_type ?? "Hearing"}
                    </span>
                    <span className="text-xs text-[var(--color-mute)]">
                      {formatDate(h.hearing_on ?? h.scheduled_for ?? h.listing_date, true)}
                    </span>
                  </div>
                  <StatusBadge status={h.status ?? "pending"} />
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card className="lg:col-span-3">
        <CardHeader className="flex-row items-center justify-between gap-4">
          <div>
            <CardTitle>Recent activity</CardTitle>
            <CardDescription>
              Every state change on this matter. Audit on by default.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {recentActivity.length === 0 ? (
            <EmptyState
              icon={MessageSquareText}
              title="No activity yet"
              description="As you update this matter, structured events appear here."
            />
          ) : (
            <ol className="relative flex flex-col gap-4 border-l border-[var(--color-line)] pl-5">
              {recentActivity.map((event) => (
                <li key={event.id} className="relative">
                  <span
                    aria-hidden
                    className="absolute -left-[22px] top-1.5 h-2 w-2 rounded-full bg-[var(--color-brand-500)]"
                  />
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="text-sm font-semibold text-[var(--color-ink)]">
                      {event.title}
                    </span>
                    <span className="text-xs text-[var(--color-mute-2)]">
                      {formatDate(event.created_at, true)}
                    </span>
                  </div>
                  {event.detail ? (
                    <p className="mt-0.5 text-sm text-[var(--color-mute)]">{event.detail}</p>
                  ) : null}
                  <p className="mt-0.5 text-xs text-[var(--color-mute-2)]">
                    {event.actor_name ?? "system"} · {event.event_type}
                  </p>
                </li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>

      {recentNotes.length > 0 ? (
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>Recent notes</CardTitle>
            <CardDescription>Your team's private thinking on this matter.</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="flex flex-col gap-4">
              {recentNotes.map((note) => (
                <li
                  key={note.id}
                  className="rounded-xl border border-[var(--color-line)] bg-[var(--color-bg)] p-4 text-sm text-[var(--color-ink-2)]"
                >
                  <div className="mb-1 flex items-center justify-between text-xs text-[var(--color-mute)]">
                    <span>{note.author_name ?? "Unknown"}</span>
                    <span>{formatDate(note.created_at, true)}</span>
                  </div>
                  <p className="whitespace-pre-line leading-relaxed">{note.body}</p>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
