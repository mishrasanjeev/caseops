"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Inbox, Loader2, Plus } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  createInboundEmailAlias,
  fetchInboundEmailAliases,
  fetchInboundEmailEvents,
  updateInboundEmailAlias,
} from "@/lib/api/endpoints";
import { apiErrorMessage } from "@/lib/api/config";

export default function InboundEmailAdminPage() {
  const queryClient = useQueryClient();
  const aliasesQuery = useQuery({
    queryKey: ["inbound-email-aliases"],
    queryFn: fetchInboundEmailAliases,
  });
  const eventsQuery = useQuery({
    queryKey: ["inbound-email-events"],
    queryFn: () => fetchInboundEmailEvents({ limit: 25 }),
  });
  const createMutation = useMutation({
    mutationFn: () => createInboundEmailAlias({ status: "disabled" }),
    onSuccess: () => {
      toast.success("Alias created");
      queryClient.invalidateQueries({ queryKey: ["inbound-email-aliases"] });
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not create alias.")),
  });
  const toggleMutation = useMutation({
    mutationFn: (input: { aliasId: string; status: "enabled" | "disabled" }) =>
      updateInboundEmailAlias(input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["inbound-email-aliases"] }),
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not update alias.")),
  });
  const aliases = aliasesQuery.data?.aliases ?? [];
  const events = eventsQuery.data?.events ?? [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Admin"
        title="Inbound email"
        description="Tenant and matter aliases."
        actions={
          <Button
            type="button"
            disabled={createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            {createMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Plus className="h-4 w-4" aria-hidden />
            )}
            Tenant alias
          </Button>
        }
      />

      {aliasesQuery.isPending ? (
        <Card>
          <CardContent className="space-y-3">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </CardContent>
        </Card>
      ) : aliasesQuery.isError ? (
        <QueryErrorState
          title="Could not load aliases"
          error={aliasesQuery.error}
          onRetry={aliasesQuery.refetch}
        />
      ) : aliases.length === 0 ? (
        <EmptyState icon={Inbox} title="No aliases" description="No inbound aliases exist." />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle as="h2">Aliases</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {aliases.map((alias) => (
              <div
                key={alias.id}
                className="grid gap-3 border-b border-[var(--color-line)] px-4 py-3 last:border-b-0 md:grid-cols-[1fr_auto]"
              >
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-[var(--color-ink)]">
                      {alias.alias_address}
                    </span>
                    <Badge tone={alias.status === "enabled" ? "success" : "neutral"}>
                      {alias.status}
                    </Badge>
                    <Badge tone="neutral">{alias.alias_type}</Badge>
                  </div>
                  <div className="mt-1 text-xs text-[var(--color-mute)]">
                    {alias.spam_security_status} - retention {alias.retention_days} days
                  </div>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={toggleMutation.isPending}
                  onClick={() =>
                    toggleMutation.mutate({
                      aliasId: alias.id,
                      status: alias.status === "enabled" ? "disabled" : "enabled",
                    })
                  }
                >
                  {alias.status === "enabled" ? "Disable" : "Enable"}
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle as="h2">Events</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {eventsQuery.isPending ? (
            <div className="p-4">
              <Skeleton className="h-16 w-full" />
            </div>
          ) : eventsQuery.isError ? (
            <div className="p-4">
              <QueryErrorState
                title="Could not load inbound events"
                error={eventsQuery.error}
                onRetry={eventsQuery.refetch}
              />
            </div>
          ) : events.length === 0 ? (
            <div className="p-4 text-sm text-[var(--color-mute)]">No events.</div>
          ) : (
            events.map((event) => (
              <div
                key={event.id}
                className="border-b border-[var(--color-line)] px-4 py-3 text-sm last:border-b-0"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-[var(--color-ink)]">
                    {event.subject || "(no subject)"}
                  </span>
                  <Badge tone={event.status === "new" ? "brand" : "neutral"}>
                    {event.status.replaceAll("_", " ")}
                  </Badge>
                </div>
                <div className="mt-1 text-xs text-[var(--color-mute)]">
                  {event.from_display || "Unknown sender"} - {new Date(event.received_at).toLocaleString()}
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
