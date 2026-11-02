"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CalendarDays } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  MatterName,
  MatterPicker,
  OPERATIONAL_MATTER_STATUSES,
} from "@/components/app/MatterPicker";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  fetchCalendarProviderEventCandidates,
  reviewCalendarProviderEventCandidate,
} from "@/lib/api/endpoints";
import { apiErrorMessage } from "@/lib/api/config";
import type { Matter } from "@/lib/api/schemas";

// The accept validator (services/calendar_event_candidates.py) files an event
// only on a Matter the reviewer can open and that can still take work.
function matterBlockedReason(matter: Matter): string | null {
  return OPERATIONAL_MATTER_STATUSES.has(matter.status)
    ? null
    : "closed Matters cannot take new hearings";
}

function tone(status: string): "success" | "warning" | "neutral" | "brand" {
  if (status === "accepted") return "success";
  if (status === "conflict" || status === "failed") return "warning";
  if (["ignored", "rejected"].includes(status)) return "neutral";
  return "brand";
}

export default function CalendarConflictsPage() {
  const queryClient = useQueryClient();
  const [matterId, setMatterId] = useState("");
  const [matterBlocked, setMatterBlocked] = useState<string | null>(null);
  const actionMatterId = matterBlocked ? "" : matterId;
  const [forceOverwriteLocked, setForceOverwriteLocked] = useState(false);
  const query = useQuery({
    queryKey: ["calendar-provider-candidates"],
    queryFn: () => fetchCalendarProviderEventCandidates({ limit: 75 }),
  });
  const rows = query.data?.candidates ?? [];
  const reviewMutation = useMutation({
    mutationFn: (input: { id: string; action: "accept" | "reject" | "ignore" }) =>
      reviewCalendarProviderEventCandidate({
        candidateId: input.id,
        action: input.action,
        matterId: actionMatterId || null,
        forceOverwriteLocked,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["calendar-provider-candidates"] }),
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not review calendar candidate.")),
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Calendar"
        title="Sync conflicts"
        description="Google Calendar and Outlook event candidates."
        actions={<Button href="/app/calendar" variant="outline">Calendar</Button>}
      />

      <Card>
        <CardContent className="grid gap-3 md:grid-cols-[1fr_auto]">
          <div className="min-w-0">
            <MatterPicker
              id="calendar-matter"
              label="Matter for Accept"
              searchLabel="Search Matters for Accept"
              value={matterId}
              disabledReason={matterBlockedReason}
              error={matterBlocked ? `This Matter cannot be used: ${matterBlocked}.` : null}
              onChange={(next, matter) => {
                setMatterId(next);
                setMatterBlocked(matter ? matterBlockedReason(matter) : null);
              }}
            />
            <p className="mt-1 text-xs text-[var(--color-mute)]">
              Used for events without a linked or suggested Matter, or to file an event on a different Matter.
            </p>
          </div>
          <label className="flex items-center gap-2 self-start pt-6 text-sm text-[var(--color-ink-2)]">
            <input
              className="h-4 w-4"
              type="checkbox"
              checked={forceOverwriteLocked}
              onChange={(event) => setForceOverwriteLocked(event.target.checked)}
            />
            Override lock
          </label>
        </CardContent>
      </Card>

      {query.isPending ? (
        <Card>
          <CardContent className="space-y-3">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </CardContent>
        </Card>
      ) : query.isError ? (
        <QueryErrorState
          title="Could not load calendar candidates"
          error={query.error}
          onRetry={query.refetch}
        />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={CalendarDays}
          title="No calendar candidates"
          description="The queue is empty."
        />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle as="h2">Provider events</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {rows.map((row) => (
              <div
                key={row.id}
                className="grid gap-3 border-b border-[var(--color-line)] px-4 py-3 last:border-b-0 lg:grid-cols-[1.4fr_1fr_auto]"
              >
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-[var(--color-ink)]">
                      {row.title}
                    </span>
                    <Badge tone={tone(row.status)}>{row.status}</Badge>
                    <Badge tone="neutral">{row.provider.replaceAll("_", " ")}</Badge>
                  </div>
                  <div className="mt-1 text-xs text-[var(--color-mute)]">
                    {new Date(row.starts_at).toLocaleString()}
                    {row.location ? ` - ${row.location}` : ""}
                  </div>
                </div>
                <div className="min-w-0 text-xs text-[var(--color-mute)]">
                  {/* The list is filtered on the linked Matter, or the
                      suggestion when nothing is linked. */}
                  {row.linked_matter_id ? (
                    <div>Linked: <MatterName matterId={row.linked_matter_id} /></div>
                  ) : (
                    <div>Suggested: <MatterName matterId={row.suggested_matter_id} fallback="none" /></div>
                  )}
                  {row.linked_matter_id || row.suggested_matter_id || actionMatterId ? null : (
                    <div className="mt-1">Choose a Matter for Accept above to accept this event.</div>
                  )}
                  {row.conflict_reason ? (
                    <div className="mt-1 flex items-center gap-1 text-amber-800">
                      <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
                      {row.conflict_reason}
                    </div>
                  ) : null}
                </div>
                <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={
                      reviewMutation.isPending ||
                      (!row.linked_matter_id && !row.suggested_matter_id && !actionMatterId)
                    }
                    onClick={() => reviewMutation.mutate({ id: row.id, action: "accept" })}
                  >
                    Accept
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={reviewMutation.isPending}
                    onClick={() => reviewMutation.mutate({ id: row.id, action: "reject" })}
                  >
                    Reject
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={reviewMutation.isPending}
                    onClick={() => reviewMutation.mutate({ id: row.id, action: "ignore" })}
                  >
                    Ignore
                  </Button>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
