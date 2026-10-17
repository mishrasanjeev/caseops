"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, RotateCcw, X } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { apiErrorMessage } from "@/lib/api/config";
import { listRecipientNotifications, updateRecipientNotification, type RecipientNotification } from "@/lib/api/in-app-notifications";

export function InAppNotificationCenter({ docketId, membershipId }: { docketId: string; membershipId: string | null }) {
  const client = useQueryClient();
  const [dismissed, setDismissed] = useState(false);
  const [cursors, setCursors] = useState<Array<string | null>>([null]);
  const key = ["in-app-notifications", membershipId, docketId];
  const query = useQuery({
    queryKey: [...key, dismissed, cursors.at(-1)],
    queryFn: () => listRecipientNotifications({ docketId, dismissed, cursor: cursors.at(-1) }),
    retry: false,
    enabled: Boolean(membershipId),
  });
  const change = useMutation({
    mutationFn: ({ note, status }: { note: RecipientNotification; status: RecipientNotification["status"] }) =>
      updateRecipientNotification({ docketId, notificationId: note.id, expectedStatus: note.status, status }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: key });
      await client.invalidateQueries({ queryKey: ["ip", "portfolio"] });
    },
    onError: async () => { await client.invalidateQueries({ queryKey: key }); },
  });
  return (
    <section className="min-w-0 space-y-3 xl:col-span-2" aria-label="Your in-app alerts" data-testid="ip-recipient-notifications">
      <h3 className="text-base font-semibold">Your in-app alerts</h3>
      <Tabs value={dismissed ? "dismissed" : "active"} onValueChange={(value) => {
        setDismissed(value === "dismissed"); setCursors([null]); change.reset();
      }}>
        <TabsList aria-label="Notification status"><TabsTrigger value="active">Active alerts</TabsTrigger><TabsTrigger value="dismissed">Dismissed alerts</TabsTrigger></TabsList>
      <TabsContent value={dismissed ? "dismissed" : "active"}>
      {query.isPending ? <p role="status" className="text-sm">Loading alerts...</p> : null}
      {query.isError ? <p role="alert" className="break-words text-sm">{apiErrorMessage(query.error, "Could not load alerts.")}</p> : null}
      {change.isError ? <p role="alert" className="break-words text-sm">{apiErrorMessage(change.error, "Could not update alert.")}</p> : null}
      {!query.isError && query.data?.items.length === 0 ? <p className="text-sm text-[var(--color-mute)]">{dismissed ? "No dismissed alerts." : "No current alerts."}</p> : null}
      <ul className="min-w-0 divide-y divide-[var(--color-line)]">
        {(query.isError ? [] : query.data?.items ?? []).map((note) => <li key={note.id} data-testid={`in-app-notification-${note.id}`} className="min-w-0 py-3">
          <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
            <h4 className="min-w-0 break-words text-sm font-semibold">{note.title}</h4>
            <span className="text-xs">{note.status}</span>
          </div>
          {note.body ? <p className="mt-1 whitespace-pre-wrap break-words text-sm" data-testid={`in-app-notification-body-${note.id}`}>{note.body}</p> : null}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <time className="text-xs text-[var(--color-mute)]" dateTime={note.created_at}>{new Date(note.created_at).toLocaleString()}</time>
            {note.status === "unread" ? <Button type="button" size="sm" variant="ghost" disabled={change.isPending} onClick={() => change.mutate({ note, status: "read" })}><Check className="h-4 w-4" aria-hidden />Mark read</Button> : null}
            <Button type="button" size="sm" variant="secondary" disabled={change.isPending} onClick={() => change.mutate({ note, status: dismissed ? "unread" : "dismissed" })}>
              {dismissed ? <RotateCcw className="h-4 w-4" aria-hidden /> : <X className="h-4 w-4" aria-hidden />}{dismissed ? "Restore alert" : "Dismiss alert"}
            </Button>
          </div>
        </li>)}
      </ul>
      <div className="flex items-center gap-2">
        <Button type="button" size="sm" variant="ghost" aria-label="Previous alerts" title="Previous alerts" disabled={cursors.length === 1 || query.isFetching} onClick={() => setCursors((current) => current.slice(0, -1))}><ArrowLeft className="h-4 w-4" aria-hidden /></Button>
        <Button type="button" size="sm" variant="ghost" aria-label="Next alerts" title="Next alerts" disabled={!query.data?.next_cursor || query.isFetching} onClick={() => setCursors((current) => [...current, query.data!.next_cursor])}><ArrowRight className="h-4 w-4" aria-hidden /></Button>
      </div>
      </TabsContent>
      </Tabs>
    </section>
  );
}
