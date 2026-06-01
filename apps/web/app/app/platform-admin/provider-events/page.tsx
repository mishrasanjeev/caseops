"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RefreshCw, Search } from "lucide-react";
import { useState } from "react";
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
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { apiErrorMessage } from "@/lib/api/config";
import {
  fetchPlatformProviderEvents,
  reprocessPlatformProviderEvent,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

function providerTone(status: string | undefined): "neutral" | "brand" | "success" | "warning" {
  if (status === "processed") return "success";
  if (status === "failed") return "warning";
  if (status === "duplicate") return "neutral";
  return "brand";
}

export default function PlatformProviderEventsPage() {
  const canPlatform = useCapability("platform:admin");
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [submittedQ, setSubmittedQ] = useState("");
  const eventsQuery = useQuery({
    queryKey: ["platform-admin", "provider-events", submittedQ],
    queryFn: () => fetchPlatformProviderEvents({ q: submittedQ || undefined }),
    enabled: canPlatform,
  });
  const reprocessMutation = useMutation({
    mutationFn: reprocessPlatformProviderEvent,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-admin", "provider-events"] });
      toast.success("Reprocess request recorded.");
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not request reprocess.")),
  });

  if (!canPlatform) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          eyebrow="Platform"
          title="Access denied"
          description="Provider reconciliation is restricted to the configured founder super-admin."
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Founder console"
        title="Provider events and reconciliation"
        description="Plural payment, subscription, adjustment, and refund events with idempotent processing status."
      />

      <Card>
        <CardHeader>
          <CardTitle as="h2">Search provider events</CardTitle>
          <CardDescription>
            Search by provider event id, order id, company id, or event type.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              setSubmittedQ(q.trim());
            }}
          >
            <div className="flex min-w-72 flex-1 flex-col gap-1.5">
              <Label htmlFor="provider-event-search">Search</Label>
              <Input
                id="provider-event-search"
                value={q}
                onChange={(event) => setQ(event.target.value)}
                placeholder="event id, order id, company id"
              />
            </div>
            <Button type="submit">
              <Search className="h-4 w-4" aria-hidden />
              Search
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle as="h2">Event inbox</CardTitle>
          <CardDescription>
            Duplicate and out-of-order events should not duplicate credits or downgrade paid orders.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {eventsQuery.isPending ? (
            <div className="flex items-center gap-2 text-sm text-[var(--color-mute)]">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              Loading provider events...
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="border-b border-[var(--color-line)] text-xs uppercase text-[var(--color-mute)]">
                  <tr>
                    <th className="py-2 pr-4">Received</th>
                    <th className="py-2 pr-4">Event</th>
                    <th className="py-2 pr-4">Provider id</th>
                    <th className="py-2 pr-4">Order</th>
                    <th className="py-2 pr-4">Status</th>
                    <th className="py-2 pr-4">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {(eventsQuery.data?.events ?? []).map((event) => (
                    <tr key={event.id} className="border-b border-[var(--color-line-2)]">
                      <td className="py-3 pr-4">
                        {event.received_at
                          ? new Date(event.received_at).toLocaleString()
                          : "-"}
                      </td>
                      <td className="py-3 pr-4 font-medium">{event.event_type ?? "-"}</td>
                      <td className="py-3 pr-4">{event.provider_event_id ?? "-"}</td>
                      <td className="py-3 pr-4">{event.provider_order_id ?? "-"}</td>
                      <td className="py-3 pr-4">
                        <Badge tone={providerTone(event.processing_status)}>
                          {event.processing_status ?? "unknown"}
                        </Badge>
                      </td>
                      <td className="py-3 pr-4">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={reprocessMutation.isPending}
                          onClick={() => reprocessMutation.mutate(event.id)}
                        >
                          <RefreshCw className="h-4 w-4" aria-hidden />
                          Reprocess
                        </Button>
                      </td>
                    </tr>
                  ))}
                  {(eventsQuery.data?.events ?? []).length === 0 ? (
                    <tr>
                      <td className="py-4 text-[var(--color-mute)]" colSpan={6}>
                        No provider events found.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
