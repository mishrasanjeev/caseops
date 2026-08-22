"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Download, FileClock, FileSearch, RefreshCw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { apiErrorMessage } from "@/lib/api/config";
import {
  downloadBulkImportErrors,
  getBulkImportManifest,
  listBulkImportJobs,
  type BulkImportDomain,
  type BulkImportJobSummary,
} from "@/lib/api/endpoints";
import { cn } from "@/lib/cn";

const DOMAIN_LABELS: Record<BulkImportDomain, string> = {
  ip_trademark: "Trademarks",
  matter: "Matters",
  employee: "Employees",
};

const WORKFLOW_LINKS: Record<BulkImportDomain, string> = {
  ip_trademark: "/app/ip/portfolio/imports",
  matter: "/app/matters/imports",
  employee: "/app/admin/employees",
};

type DomainFilter = "all" | BulkImportDomain;

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function rowSummary(job: BulkImportJobSummary): string {
  if (job.committed_rows || job.failed_rows) {
    return `${job.committed_rows} committed, ${job.failed_rows} failed`;
  }
  return `${job.valid_rows} valid, ${job.invalid_rows} invalid`;
}

export default function ImportActivityPage() {
  const [domain, setDomain] = useState<DomainFilter>("all");
  const [selectedJob, setSelectedJob] = useState<BulkImportJobSummary | null>(null);
  const [downloadingKey, setDownloadingKey] = useState<string | null>(null);

  const history = useQuery({
    queryKey: ["bulk-imports", "history", domain],
    queryFn: () => listBulkImportJobs(domain === "all" ? undefined : domain),
    staleTime: 30_000,
  });
  const manifest = useQuery({
    queryKey: ["bulk-imports", "manifest", selectedJob?.domain, selectedJob?.id],
    queryFn: () => getBulkImportManifest(selectedJob!.domain, selectedJob!.id),
    enabled: selectedJob !== null,
    staleTime: 30_000,
  });

  async function downloadErrors(job: BulkImportJobSummary) {
    const key = `${job.domain}:${job.id}`;
    setDownloadingKey(key);
    try {
      const blob = await downloadBulkImportErrors(job.domain, job.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${job.domain}-${job.id}-errors.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(apiErrorMessage(error, "Could not download the error report."));
    } finally {
      setDownloadingKey(null);
    }
  }

  if (history.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (history.isError) {
    return (
      <QueryErrorState
        title="Could not load import activity"
        error={history.error}
        onRetry={() => history.refetch()}
      />
    );
  }

  const availableDomains = history.data.accessible_domains;
  const filters: Array<{ value: DomainFilter; label: string }> = [
    { value: "all", label: "All" },
    ...availableDomains.map((value) => ({ value, label: DOMAIN_LABELS[value] })),
  ];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Workspace operations"
        title="Import activity"
        description="Review import status, row outcomes, manifests, and error reports across accessible workflows."
        actions={
          <Button variant="outline" onClick={() => void history.refetch()} disabled={history.isFetching}>
            <RefreshCw className={cn("h-4 w-4", history.isFetching && "animate-spin")} aria-hidden />
            Refresh
          </Button>
        }
      />

      <div className="flex flex-wrap items-center gap-2" role="tablist" aria-label="Import domain">
        {filters.map((filter) => (
          <button
            key={filter.value}
            type="button"
            role="tab"
            aria-selected={domain === filter.value}
            className={cn(
              "h-9 rounded-md border px-3 text-sm font-medium transition-colors",
              domain === filter.value
                ? "border-[var(--color-ink)] bg-[var(--color-ink)] text-white"
                : "border-[var(--color-line)] bg-white text-[var(--color-ink-2)] hover:border-[var(--color-ink-3)]",
            )}
            onClick={() => setDomain(filter.value)}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {history.data.jobs.length ? (
        <div className="overflow-x-auto rounded-lg border border-[var(--color-line)] bg-white">
          <table className="min-w-[840px] w-full text-left text-sm" data-testid="import-activity-table">
            <thead className="border-b border-[var(--color-line)] bg-[var(--color-bg-2)] text-xs uppercase text-[var(--color-mute)]">
              <tr>
                <th className="px-4 py-3">File</th>
                <th className="px-4 py-3">Workflow</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Rows</th>
                <th className="px-4 py-3">Created</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {history.data.jobs.map((job) => {
                const downloadKey = `${job.domain}:${job.id}`;
                return (
                  <tr key={downloadKey} className="border-b border-[var(--color-line-2)] last:border-0">
                    <td className="max-w-[260px] px-4 py-3">
                      <p className="truncate font-medium text-[var(--color-ink)]" title={job.filename}>
                        {job.filename}
                      </p>
                      <p className="truncate text-xs text-[var(--color-mute)]">
                        {job.creator_label ?? "Unknown creator"}
                      </p>
                    </td>
                    <td className="px-4 py-3">{DOMAIN_LABELS[job.domain]}</td>
                    <td className="px-4 py-3"><StatusBadge status={job.status} /></td>
                    <td className="px-4 py-3 tabular-nums">
                      <p>{job.total_rows} total</p>
                      <p className="text-xs text-[var(--color-mute)]">{rowSummary(job)}</p>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">{formatDate(job.created_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`View manifest for ${job.filename}`}
                          title="View manifest"
                          onClick={() => setSelectedJob(job)}
                        >
                          <FileSearch className="h-4 w-4" aria-hidden />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Download errors for ${job.filename}`}
                          title="Download error report"
                          disabled={downloadingKey === downloadKey}
                          onClick={() => void downloadErrors(job)}
                        >
                          <Download className="h-4 w-4" aria-hidden />
                        </Button>
                        <Button
                          href={WORKFLOW_LINKS[job.domain]}
                          variant="ghost"
                          size="sm"
                          aria-label={`Open ${DOMAIN_LABELS[job.domain]} import workflow`}
                          title="Open import workflow"
                        >
                          <ArrowUpRight className="h-4 w-4" aria-hidden />
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState
          icon={FileClock}
          title="No import activity"
          description={domain === "all" ? "No accessible import jobs have been created." : `No ${DOMAIN_LABELS[domain].toLowerCase()} import jobs have been created.`}
          action={domain === "all" ? undefined : (
            <Button href={WORKFLOW_LINKS[domain]} variant="outline">
              Open {DOMAIN_LABELS[domain]} imports
              <ArrowUpRight className="h-4 w-4" aria-hidden />
            </Button>
          )}
        />
      )}

      <Dialog open={selectedJob !== null} onOpenChange={(open) => !open && setSelectedJob(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Import manifest</DialogTitle>
            <DialogDescription>{selectedJob?.filename}</DialogDescription>
          </DialogHeader>
          {manifest.isPending ? (
            <Skeleton className="h-48 w-full" />
          ) : manifest.isError ? (
            <QueryErrorState
              title="Could not load manifest"
              error={manifest.error}
              onRetry={() => manifest.refetch()}
            />
          ) : manifest.data ? (
            <div className="space-y-4 text-sm" data-testid="import-manifest">
              <div className="flex flex-wrap gap-2">
                <Badge tone={manifest.data.compatibility_mode === "canonical" ? "brand" : "neutral"}>
                  {manifest.data.compatibility_mode === "canonical" ? "Canonical" : "Legacy read-only"}
                </Badge>
                <StatusBadge status={manifest.data.job.status} />
              </div>
              <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)] gap-x-4 gap-y-3">
                <dt className="text-[var(--color-mute)]">Workflow</dt>
                <dd>{DOMAIN_LABELS[manifest.data.job.domain]}</dd>
                <dt className="text-[var(--color-mute)]">Source status</dt>
                <dd>{manifest.data.job.source_status.replace(/_/g, " ")}</dd>
                <dt className="text-[var(--color-mute)]">Checksum</dt>
                <dd className="break-all font-mono text-xs">{manifest.data.job.source_sha256 ?? "Not recorded"}</dd>
                <dt className="text-[var(--color-mute)]">Format</dt>
                <dd>{manifest.data.manifest_format ?? manifest.data.job.content_type ?? "Not recorded"}</dd>
                <dt className="text-[var(--color-mute)]">File size</dt>
                <dd>{manifest.data.file_size_bytes === null ? "Not recorded" : `${manifest.data.file_size_bytes.toLocaleString("en-IN")} bytes`}</dd>
              </dl>
              {manifest.data.limitations.length ? (
                <div className="border-l-2 border-amber-400 pl-3 text-[var(--color-ink-2)]">
                  {manifest.data.limitations.map((limitation) => <p key={limitation}>{limitation}</p>)}
                </div>
              ) : null}
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
