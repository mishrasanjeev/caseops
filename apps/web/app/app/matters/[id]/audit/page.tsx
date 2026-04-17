"use client";

import { ScrollText } from "lucide-react";
import { useParams } from "next/navigation";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { useMatterWorkspace } from "@/lib/use-matter-workspace";

function formatDateTime(value: string): string {
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

export default function MatterAuditPage() {
  const params = useParams<{ id: string }>();
  const { data } = useMatterWorkspace(params.id);
  if (!data) return null;
  const activity = data.activity;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Audit trail</CardTitle>
        <CardDescription>
          Every mutating action on this matter. The system-wide audit service lands with §5.4.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {activity.length === 0 ? (
          <EmptyState
            icon={ScrollText}
            title="No activity yet"
            description="Changes you make to this matter will appear here — actor, timestamp, action, and any detail."
          />
        ) : (
          <ol className="relative flex flex-col gap-5 border-l border-[var(--color-line)] pl-5">
            {activity.map((event) => (
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
                    {formatDateTime(event.created_at)}
                  </span>
                </div>
                {event.detail ? (
                  <p className="mt-0.5 text-sm leading-relaxed text-[var(--color-mute)]">
                    {event.detail}
                  </p>
                ) : null}
                <p className="mt-0.5 text-xs text-[var(--color-mute-2)]">
                  {event.actor_name ?? "system"} · <code>{event.event_type}</code>
                </p>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
