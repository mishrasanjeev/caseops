"use client";

import { useQuery } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/Badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { fetchTenantDataGovernanceIntegrity } from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

function tone(status: "ok" | "findings" | "unavailable"): "success" | "warning" | "neutral" {
  return status === "ok" ? "success" : status === "findings" ? "warning" : "neutral";
}

export default function DataGovernancePage() {
  const canAudit = useCapability("audit:export");
  const report = useQuery({
    queryKey: ["admin", "data-governance", "integrity"],
    queryFn: fetchTenantDataGovernanceIntegrity,
    enabled: canAudit,
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
    </div>
  );
}
