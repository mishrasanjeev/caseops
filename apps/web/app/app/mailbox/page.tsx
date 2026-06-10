"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Inbox, Loader2, Mail, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  fetchMailboxImports,
  importRecentGmailMessages,
  reviewMailboxImport,
} from "@/lib/api/endpoints";
import { apiErrorMessage } from "@/lib/api/config";
import type { MailboxMessageImportRecord } from "@/lib/api/schemas";

function statusTone(status: string): "success" | "warning" | "neutral" | "brand" {
  if (["imported", "linked_metadata", "content_imported"].includes(status)) return "success";
  if (["failed", "dead_letter", "content_import_requested"].includes(status)) return "warning";
  if (["ignored", "duplicate", "resolved"].includes(status)) return "neutral";
  return "brand";
}

function when(value: string | null) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function MessageRow({
  row,
  selected,
  onSelected,
  matterId,
  onAction,
  busy,
}: {
  row: MailboxMessageImportRecord;
  selected: boolean;
  onSelected: (checked: boolean) => void;
  matterId: string;
  onAction: (action: "link_metadata" | "request_content_import" | "ignore") => void;
  busy: boolean;
}) {
  return (
    <div className="grid gap-3 border-b border-[var(--color-line)] px-4 py-3 last:border-b-0 lg:grid-cols-[32px_1.4fr_1fr_auto]">
      <label className="flex items-center">
        <input
          aria-label={`Select ${row.subject ?? row.provider_message_id}`}
          checked={selected}
          className="h-4 w-4"
          type="checkbox"
          onChange={(event) => onSelected(event.target.checked)}
        />
      </label>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate text-sm font-semibold text-[var(--color-ink)]">
            {row.subject || "(no subject)"}
          </span>
          <Badge tone={statusTone(row.status)}>{row.status.replaceAll("_", " ")}</Badge>
          <Badge tone="neutral">{row.provider.replaceAll("_", " ")}</Badge>
        </div>
        <div className="mt-1 line-clamp-2 text-sm text-[var(--color-mute)]">
          {row.snippet || "No snippet"}
        </div>
        <div className="mt-1 text-xs text-[var(--color-mute)]">
          {row.sender_name || "Unknown sender"} - {when(row.occurred_at)}
        </div>
      </div>
      <div className="text-xs text-[var(--color-mute)]">
        <div>Matter: {row.matter_id ?? "unlinked"}</div>
        <div>Attachments: {row.attachment_count}</div>
        {row.last_error_redacted ? (
          <div className="mt-1 text-amber-800">{row.last_error_redacted}</div>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-2 lg:justify-end">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy || (!row.matter_id && !matterId)}
          onClick={() => onAction("link_metadata")}
        >
          Link
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy || (!row.matter_id && !matterId)}
          onClick={() => onAction("request_content_import")}
        >
          Request
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={busy}
          onClick={() => onAction("ignore")}
        >
          Ignore
        </Button>
      </div>
    </div>
  );
}

export default function MailboxPage() {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("");
  const [provider, setProvider] = useState<"gmail" | "outlook_mail" | "">("");
  const [matterId, setMatterId] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const query = useQuery({
    queryKey: ["mailbox-imports", status, provider],
    queryFn: () =>
      fetchMailboxImports({
        provider: provider || undefined,
        status: status || undefined,
        limit: 75,
      }),
  });
  const rows = query.data?.imports ?? [];
  const selectedRows = useMemo(
    () => rows.filter((row) => selected.has(row.id)),
    [rows, selected],
  );
  const syncMutation = useMutation({
    mutationFn: () => importRecentGmailMessages({ limit: 25 }),
    onSuccess: () => {
      toast.success("Gmail metadata synced");
      queryClient.invalidateQueries({ queryKey: ["mailbox-imports"] });
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not sync Gmail metadata.")),
  });
  const reviewMutation = useMutation({
    mutationFn: (input: {
      importId: string;
      action: "link_metadata" | "request_content_import" | "ignore";
    }) =>
      reviewMailboxImport({
        importId: input.importId,
        action: input.action,
        matterId: matterId || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mailbox-imports"] });
      setSelected(new Set());
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not review message.")),
  });
  const bulkIgnore = async () => {
    for (const row of selectedRows) {
      await reviewMutation.mutateAsync({ importId: row.id, action: "ignore" });
    }
    toast.success("Selected messages ignored");
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Mailbox"
        title="Review queue"
        description="Gmail and Outlook metadata candidates."
        actions={
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={selectedRows.length === 0 || reviewMutation.isPending}
              onClick={bulkIgnore}
            >
              Ignore selected
            </Button>
            <Button
              type="button"
              disabled={syncMutation.isPending}
              onClick={() => syncMutation.mutate()}
            >
              {syncMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <RefreshCw className="h-4 w-4" aria-hidden />
              )}
              Sync Gmail
            </Button>
          </div>
        }
      />

      <Card>
        <CardContent className="grid gap-3 md:grid-cols-3">
          <div>
            <Label htmlFor="mailbox-provider">Provider</Label>
            <select
              id="mailbox-provider"
              className="mt-1 h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
              value={provider}
              onChange={(event) => setProvider(event.target.value as typeof provider)}
            >
              <option value="">All</option>
              <option value="gmail">Gmail</option>
              <option value="outlook_mail">Outlook</option>
            </select>
          </div>
          <div>
            <Label htmlFor="mailbox-status">Status</Label>
            <Input
              id="mailbox-status"
              placeholder="new, imported, failed"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="mailbox-matter">Matter id for actions</Label>
            <Input
              id="mailbox-matter"
              placeholder="matter id"
              value={matterId}
              onChange={(event) => setMatterId(event.target.value)}
            />
          </div>
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
          title="Could not load mailbox queue"
          error={query.error}
          onRetry={query.refetch}
        />
      ) : rows.length === 0 ? (
        <EmptyState icon={Mail} title="No message candidates" description="The queue is empty." />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle as="h2">Messages</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {rows.map((row) => (
              <MessageRow
                key={row.id}
                row={row}
                selected={selected.has(row.id)}
                matterId={matterId}
                busy={reviewMutation.isPending}
                onSelected={(checked) => {
                  const next = new Set(selected);
                  if (checked) next.add(row.id);
                  else next.delete(row.id);
                  setSelected(next);
                }}
                onAction={(action) =>
                  reviewMutation.mutate({ importId: row.id, action })
                }
              />
            ))}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="flex items-center gap-3 text-sm text-[var(--color-mute)]">
          <Inbox className="h-4 w-4" aria-hidden />
          Raw bodies and attachment bytes are not imported from this page.
        </CardContent>
      </Card>
    </div>
  );
}
