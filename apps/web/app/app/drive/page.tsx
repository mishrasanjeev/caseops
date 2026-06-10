"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileCheck2, HardDrive, Loader2, RefreshCw } from "lucide-react";
import { useState } from "react";
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
  fetchDriveCandidates,
  reviewDriveCandidate,
  syncGoogleDriveCandidates,
} from "@/lib/api/endpoints";
import { apiErrorMessage } from "@/lib/api/config";
import type { DriveCandidateRecord } from "@/lib/api/schemas";

function tone(status: string): "success" | "warning" | "neutral" | "brand" {
  if (status === "content_imported" || status === "linked_metadata") return "success";
  if (status === "failed" || status === "content_import_requested") return "warning";
  if (status === "ignored") return "neutral";
  return "brand";
}

function size(value: number | null | undefined) {
  if (!value) return "-";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function CandidateRow({
  row,
  matterId,
  busy,
  onAction,
}: {
  row: DriveCandidateRecord;
  matterId: string;
  busy: boolean;
  onAction: (action: "link_metadata" | "import_file" | "ignore" | "retry") => void;
}) {
  return (
    <div className="grid gap-3 border-b border-[var(--color-line)] px-4 py-3 last:border-b-0 lg:grid-cols-[1.5fr_1fr_auto]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate text-sm font-semibold text-[var(--color-ink)]">
            {row.name}
          </span>
          <Badge tone={tone(row.status)}>{row.status.replaceAll("_", " ")}</Badge>
          <Badge tone="neutral">{row.provider.replaceAll("_", " ")}</Badge>
        </div>
        <div className="mt-1 text-xs text-[var(--color-mute)]">
          {row.mime_type ?? "file"} - {size(row.size_bytes)}
        </div>
        {row.folder_path ? (
          <div className="mt-1 truncate text-xs text-[var(--color-mute)]">
            {row.folder_path}
          </div>
        ) : null}
      </div>
      <div className="text-xs text-[var(--color-mute)]">
        <div>Suggested: {row.suggested_matter_id ?? "none"}</div>
        <div>Linked: {row.linked_matter_id ?? "none"}</div>
        {row.last_error_redacted ? (
          <div className="mt-1 text-amber-800">{row.last_error_redacted}</div>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-2 lg:justify-end">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy || (!row.suggested_matter_id && !matterId)}
          onClick={() => onAction("link_metadata")}
        >
          Link
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy || (!row.suggested_matter_id && !matterId)}
          onClick={() => onAction("import_file")}
        >
          Import
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={busy}
          onClick={() => onAction(row.status === "failed" ? "retry" : "ignore")}
        >
          {row.status === "failed" ? "Retry" : "Ignore"}
        </Button>
      </div>
    </div>
  );
}

export default function DrivePage() {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("");
  const [matterId, setMatterId] = useState("");
  const query = useQuery({
    queryKey: ["drive-candidates", status],
    queryFn: () => fetchDriveCandidates({ status: status || undefined, limit: 75 }),
  });
  const rows = query.data?.candidates ?? [];
  const syncMutation = useMutation({
    mutationFn: () => syncGoogleDriveCandidates({ limit: 25 }),
    onSuccess: () => {
      toast.success("Drive metadata synced");
      queryClient.invalidateQueries({ queryKey: ["drive-candidates"] });
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not sync Drive metadata.")),
  });
  const reviewMutation = useMutation({
    mutationFn: (input: {
      candidateId: string;
      action: "link_metadata" | "import_file" | "ignore" | "retry";
    }) =>
      reviewDriveCandidate({
        candidateId: input.candidateId,
        action: input.action,
        matterId: matterId || null,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["drive-candidates"] }),
    onError: (error) => toast.error(apiErrorMessage(error, "Could not review Drive file.")),
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Drive"
        title="Document review queue"
        description="Google Drive and OneDrive/SharePoint candidates."
        actions={
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
            Sync Google Drive
          </Button>
        }
      />

      <Card>
        <CardContent className="grid gap-3 md:grid-cols-2">
          <div>
            <Label htmlFor="drive-status">Status</Label>
            <Input
              id="drive-status"
              placeholder="new, failed, content_imported"
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="drive-matter">Matter id for actions</Label>
            <Input
              id="drive-matter"
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
          title="Could not load Drive candidates"
          error={query.error}
          onRetry={query.refetch}
        />
      ) : rows.length === 0 ? (
        <EmptyState icon={HardDrive} title="No file candidates" description="The queue is empty." />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle as="h2">Files</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {rows.map((row) => (
              <CandidateRow
                key={row.id}
                row={row}
                matterId={matterId}
                busy={reviewMutation.isPending}
                onAction={(action) =>
                  reviewMutation.mutate({ candidateId: row.id, action })
                }
              />
            ))}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="flex items-center gap-3 text-sm text-[var(--color-mute)]">
          <FileCheck2 className="h-4 w-4" aria-hidden />
          Imports use the existing document upload pipeline.
        </CardContent>
      </Card>
    </div>
  );
}
