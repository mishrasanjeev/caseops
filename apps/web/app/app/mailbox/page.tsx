"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Inbox, Loader2, Mail, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
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
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  fetchGmailMailboxStatus,
  fetchMailboxImports,
  importRecentGmailMessages,
  reviewMailboxImport,
  startGmailMailboxConnection,
} from "@/lib/api/endpoints";
import { apiErrorMessage } from "@/lib/api/config";
import type { MailboxMessageImportRecord, Matter } from "@/lib/api/schemas";

// The review validator (services/gmail_sync.py) links only to a Matter the
// reviewer can open and that can still take operational work.
function matterBlockedReason(matter: Matter): string | null {
  return OPERATIONAL_MATTER_STATUSES.has(matter.status)
    ? null
    : "closed Matters cannot take new correspondence";
}

const STATUS_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "", label: "All statuses" },
  { value: "new", label: "New" },
  { value: "queued", label: "Queued" },
  { value: "unmatched", label: "Unmatched" },
  { value: "linked_metadata", label: "Linked" },
  { value: "content_import_requested", label: "Import requested" },
  { value: "content_imported", label: "Content imported" },
  { value: "imported", label: "Imported" },
  { value: "duplicate", label: "Duplicate" },
  { value: "failed", label: "Failed" },
  { value: "dead_letter", label: "Dead letter" },
  { value: "ignored", label: "Ignored" },
  { value: "resolved", label: "Resolved" },
];

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
      <div className="min-w-0 text-xs text-[var(--color-mute)]">
        <div>Matter: <MatterName matterId={row.matter_id} fallback="unlinked" /></div>
        {row.matter_id || matterId ? null : (
          <div className="mt-1">Choose a Matter for Link and Request above to link this message.</div>
        )}
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
  const [matterBlocked, setMatterBlocked] = useState<string | null>(null);
  const actionMatterId = matterBlocked ? "" : matterId;
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
  const connectionQuery = useQuery({
    queryKey: ["mailbox", "gmail", "status"],
    queryFn: fetchGmailMailboxStatus,
  });
  const connected = connectionQuery.data?.connections.some(
    (connection) => connection.status === "connected",
  ) ?? false;
  const needsReconnect = connectionQuery.data?.connections.some(
    (connection) => connection.status === "error",
  ) ?? false;
  const connectMutation = useMutation({
    mutationFn: startGmailMailboxConnection,
    onSuccess: (result) => {
      if (result.auth_url) {
        window.location.assign(result.auth_url);
        return;
      }
      toast.error(result.unavailable_reason ?? "Gmail connection is unavailable.");
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not connect Gmail.")),
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
      queryClient.invalidateQueries({ queryKey: ["mailbox", "gmail", "status"] });
    },
    onError: (error) => {
      queryClient.invalidateQueries({ queryKey: ["mailbox", "gmail", "status"] });
      toast.error(apiErrorMessage(error, "Could not sync Gmail metadata."));
    },
  });
  const reviewMutation = useMutation({
    mutationFn: (input: {
      importId: string;
      action: "link_metadata" | "request_content_import" | "ignore";
    }) =>
      reviewMailboxImport({
        importId: input.importId,
        action: input.action,
        matterId: actionMatterId || null,
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
              variant="outline"
              disabled={connectMutation.isPending || connectionQuery.isPending}
              onClick={() => connectMutation.mutate()}
            >
              {connected || needsReconnect ? "Reconnect Gmail" : "Connect Gmail"}
            </Button>
            <Button
              type="button"
              disabled={syncMutation.isPending || connectionQuery.isPending || !connected}
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

      {needsReconnect ? (
        <p role="status" className="text-sm text-amber-800">
          Gmail authorization needs to be reconnected. Existing mailbox items are retained.
        </p>
      ) : null}

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
          <div className="min-w-0">
            <Label htmlFor="mailbox-status">Status</Label>
            <select
              id="mailbox-status"
              className="mt-1 h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </div>
          <div className="min-w-0">
            <MatterPicker
              id="mailbox-matter"
              label="Matter for Link and Request"
              searchLabel="Search Matters for Link and Request"
              value={matterId}
              disabledReason={matterBlockedReason}
              error={matterBlocked ? `This Matter cannot be used: ${matterBlocked}.` : null}
              onChange={(next, matter) => {
                setMatterId(next);
                setMatterBlocked(matter ? matterBlockedReason(matter) : null);
              }}
            />
            <p className="mt-1 text-xs text-[var(--color-mute)]">
              Used for messages not yet linked. A linked message stays on its Matter unless you choose another here.
            </p>
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
                matterId={actionMatterId}
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
