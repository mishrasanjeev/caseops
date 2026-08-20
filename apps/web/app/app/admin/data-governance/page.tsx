"use client";

import { useQuery } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  fetchTenantDataGovernanceIntegrity,
  fetchTenantDataOperationDryRun,
  listTenantDataOperationDryRuns,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

function tone(status: "ok" | "findings" | "unavailable"): "success" | "warning" | "neutral" {
  return status === "ok" ? "success" : status === "findings" ? "warning" : "neutral";
}

export default function DataGovernancePage() {
  const canAudit = useCapability("audit:export");
  const [selectedOperationId, setSelectedOperationId] = useState<string | null>(null);
  const report = useQuery({
    queryKey: ["admin", "data-governance", "integrity"],
    queryFn: fetchTenantDataGovernanceIntegrity,
    enabled: canAudit,
  });
  const history = useQuery({
    queryKey: ["admin", "data-governance", "dry-runs"],
    queryFn: () => listTenantDataOperationDryRuns(20),
    enabled: canAudit,
  });
  const selectedManifest = useQuery({
    queryKey: ["admin", "data-governance", "dry-runs", selectedOperationId],
    queryFn: () => fetchTenantDataOperationDryRun(selectedOperationId!),
    enabled: canAudit && selectedOperationId !== null,
  });

  if (!canAudit) {
    return <EmptyState icon={ShieldAlert} title="Workspace owner required" description="Data-governance review is limited to the workspace owner." />;
  }

  return (
    <div className="flex flex-col gap-6">
      <Link href="/app/admin" className="text-sm text-[var(--color-mute)] hover:text-[var(--color-ink)]">← Back to admin</Link>
      <PageHeader eyebrow="Admin · Data governance" title="Data-governance integrity" description="Review-only control visibility. This page cannot approve, export, purge, offboard, restore, or execute a tenant data operation." />
      <Card>
        <CardHeader><CardTitle as="h2">Current integrity checks</CardTitle><CardDescription>Unavailable checks are intentionally not shown as healthy.</CardDescription></CardHeader>
        <CardContent>
          {report.isPending ? <Skeleton className="h-40 w-full" /> : report.isError ? <QueryErrorState title="Could not load governance integrity" error={report.error} onRetry={report.refetch} /> : (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-[var(--color-mute)]">{report.data.finding_count} finding(s), {report.data.unavailable_count} unavailable check(s).</p>
              {report.data.checks.map((check) => <div key={check.check_id} className="rounded-lg border border-[var(--color-line)] p-4" data-testid={`governance-check-${check.check_id}`}><div className="flex flex-wrap items-center justify-between gap-2"><span className="font-medium">{check.check_id}</span><Badge tone={tone(check.status)}>{check.status}</Badge></div><p className="mt-2 text-sm text-[var(--color-mute)]">{check.summary}</p>{check.blocked_by ? <p className="mt-2 text-xs text-[var(--color-mute)]">Blocked by: {check.blocked_by}</p> : null}</div>)}
            </div>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle as="h2">Dry-run manifests</CardTitle><CardDescription>Immutable review records only. Selecting a manifest does not request approval or execute an operation.</CardDescription></CardHeader>
        <CardContent>
          {history.isPending ? <Skeleton className="h-32 w-full" /> : history.isError ? <QueryErrorState title="Could not load dry-run manifests" error={history.error} onRetry={history.refetch} /> : history.data.operations.length === 0 ? <p className="text-sm text-[var(--color-mute)]">No dry-run manifests are available for this workspace.</p> : <div className="flex flex-col gap-2">{history.data.operations.map((operation) => <button key={operation.id} type="button" data-testid={`dry-run-${operation.id}`} onClick={() => setSelectedOperationId(operation.id)} className="rounded-lg border border-[var(--color-line)] p-4 text-left hover:bg-[var(--color-surface-muted)]"><div className="flex flex-wrap items-center justify-between gap-2"><span className="font-medium">{operation.operation_type.replaceAll("_", " ")}</span><Badge tone={operation.approval_status === "rejected" ? "warning" : "neutral"}>{operation.approval_status}</Badge></div><p className="mt-2 text-xs text-[var(--color-mute)]">{operation.completed_at} · {operation.id}</p></button>)}</div>}
        </CardContent>
      </Card>
      {selectedOperationId ? <Card data-testid="dry-run-detail"><CardHeader><CardTitle as="h2">Manifest detail</CardTitle><CardDescription>Target references remain hashed or redacted. This detail is not an execution authorization.</CardDescription></CardHeader><CardContent>{selectedManifest.isPending ? <Skeleton className="h-28 w-full" /> : selectedManifest.isError ? <QueryErrorState title="Could not load manifest detail" error={selectedManifest.error} onRetry={selectedManifest.refetch} /> : <dl className="grid gap-3 text-sm"><div><dt className="text-[var(--color-mute)]">Operation</dt><dd>{selectedManifest.data.operation_type}</dd></div><div><dt className="text-[var(--color-mute)]">Manifest hash</dt><dd className="break-all font-mono text-xs">{selectedManifest.data.manifest_hash}</dd></div><div><dt className="text-[var(--color-mute)]">Request scope hash</dt><dd className="break-all font-mono text-xs">{selectedManifest.data.request_scope_hash}</dd></div><div><dt className="text-[var(--color-mute)]">Reviewable items</dt><dd>{selectedManifest.data.items.length} item(s), {selectedManifest.data.exclusions.length} exclusion(s)</dd></div></dl>}</CardContent></Card> : null}
    </div>
  );
}
