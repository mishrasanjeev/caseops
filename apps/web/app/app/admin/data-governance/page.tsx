"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  fetchTenantDataGovernanceIntegrity,
  fetchTenantDataOperationDryRun,
  fetchTenantLegalHoldSummary,
  createTenantDataOperationDryRun,
  listTenantDataOperationDryRuns,
  requestTenantDataOperationReview,
  approveTenantDataOperationReview,
  rejectTenantDataOperationReview,
} from "@/lib/api/endpoints";
import { apiErrorMessage } from "@/lib/api/config";
import { useCapability } from "@/lib/capabilities";

function tone(status: "ok" | "findings" | "unavailable"): "success" | "warning" | "neutral" {
  return status === "ok" ? "success" : status === "findings" ? "warning" : "neutral";
}

export default function DataGovernancePage() {
  const canAudit = useCapability("audit:export");
  // Reviewing is a separate capability from tenant oversight on purpose: a
  // four-eyes control reachable only by owners cannot be satisfied by a
  // one-owner tenant. An admin holds this and not audit:export.
  const canReview = useCapability("data_operations:review");
  const [approverLabel, setApproverLabel] = useState("");
  const [rejectionReason, setRejectionReason] = useState("");
  const [reviewError, setReviewError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const [selectedOperationId, setSelectedOperationId] = useState<string | null>(null);
  const [operationType, setOperationType] = useState<"tenant_export" | "retention_purge" | "tenant_offboarding" | "restore_validation">("tenant_export");
  const [requestEvidenceRef, setRequestEvidenceRef] = useState("");
  const [dataClassId, setDataClassId] = useState("");
  const [targetType, setTargetType] = useState("tenant");
  const [targetReferenceHash, setTargetReferenceHash] = useState("");
  const [requestError, setRequestError] = useState<string | null>(null);
  const report = useQuery({
    queryKey: ["admin", "data-governance", "integrity"],
    queryFn: fetchTenantDataGovernanceIntegrity,
    enabled: canAudit,
  });
  const history = useQuery({
    queryKey: ["admin", "data-governance", "dry-runs"],
    queryFn: () => listTenantDataOperationDryRuns(20),
    enabled: canAudit || canReview,
  });
  const legalHoldSummary = useQuery({
    queryKey: ["admin", "data-governance", "legal-hold-summary"],
    queryFn: fetchTenantLegalHoldSummary,
    enabled: canAudit,
  });
  const selectedManifest = useQuery({
    queryKey: ["admin", "data-governance", "dry-runs", selectedOperationId],
    queryFn: () => fetchTenantDataOperationDryRun(selectedOperationId!),
    enabled: (canAudit || canReview) && selectedOperationId !== null,
  });
  const createDryRun = useMutation({
    mutationFn: () => createTenantDataOperationDryRun({
      operationType,
      requestEvidenceRef: requestEvidenceRef.trim(),
      items: [{ dataClassId: dataClassId.trim(), targetType: targetType.trim(), targetReferenceHash: targetReferenceHash.trim().toLowerCase(), candidateRecordCount: 0, estimatedBytes: 0 }],
    }),
    onSuccess: (operation) => {
      setSelectedOperationId(operation.id);
      setRequestError(null);
      queryClient.invalidateQueries({ queryKey: ["admin", "data-governance", "dry-runs"] });
    },
    onError: () => setRequestError("The dry-run manifest could not be created. Verify the registered class ID and the 64-character SHA-256 target reference."),
  });

  const reviewMutation = useMutation({
    mutationFn: async (action: { kind: "request" } | { kind: "approve" } | { kind: "reject" }) => {
      const id = selectedOperationId!;
      if (action.kind === "request") return requestTenantDataOperationReview(id);
      if (action.kind === "approve") return approveTenantDataOperationReview(id, approverLabel.trim());
      return rejectTenantDataOperationReview(id, rejectionReason.trim());
    },
    onSuccess: () => {
      setReviewError(null);
      setRejectionReason("");
      queryClient.invalidateQueries({ queryKey: ["admin", "data-governance", "dry-runs"] });
    },
    // The API distinguishes its refusals by a machine-readable type and each
    // has a different remedy, so surface the server's own sentence rather than
    // one generic line that sends the reviewer to the wrong fix.
    onError: (error) => setReviewError(apiErrorMessage(error, "The review action could not be completed.")),
  });

  function submitDryRun(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!requestEvidenceRef.trim() || !dataClassId.trim() || !targetType.trim() || !/^[0-9a-f]{64}$/i.test(targetReferenceHash.trim())) {
      setRequestError("Enter an evidence reference, a registered class ID, a target type, and a 64-character SHA-256 target reference.");
      return;
    }
    setRequestError(null);
    createDryRun.mutate();
  }

  if (!canAudit && !canReview) {
    return <EmptyState icon={ShieldAlert} title="Data-governance access required" description="Tenant oversight is limited to the workspace owner. Reviewing a data operation additionally requires the data-operation review capability." />;
  }

  return (
    <div className="flex flex-col gap-6">
      <Link href="/app/admin" className="text-sm text-[var(--color-mute)] hover:text-[var(--color-ink)]">← Back to admin</Link>
      {/* The old copy said this page "cannot approve". It can now, so saying
          otherwise would be a false assurance on the one screen where a false
          assurance matters most. What stays true, and is what the reader needs,
          is that approving authorises an execution and never performs one. */}
      <PageHeader eyebrow="Admin · Data governance" title="Data-governance integrity" description="Control visibility and data-operation review. Approving a manifest authorises an execution under dual approval; it never exports, purges, offboards, restores, or executes anything here." />
      {canAudit ? (
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
      ) : null}
      {canAudit ? (
      <Card>
        <CardHeader><CardTitle as="h2">Legal-hold preservation</CardTitle><CardDescription>Aggregate preservation visibility only. Hold records, scopes, authorities, and held-item references are never shown here.</CardDescription></CardHeader>
        <CardContent>
          {legalHoldSummary.isPending ? <Skeleton className="h-28 w-full" /> : legalHoldSummary.isError ? <QueryErrorState title="Could not load legal-hold preservation" error={legalHoldSummary.error} onRetry={legalHoldSummary.refetch} /> : (
            <div className="flex flex-col gap-4" data-testid="legal-hold-summary">
              <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-medium">Current preservation state</span><Badge tone={legalHoldSummary.data.preservation_effective ? "success" : "warning"}>{legalHoldSummary.data.preservation_effective ? "preservation effective" : "preservation not effective"}</Badge></div>
              <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4"><div><dt className="text-[var(--color-mute)]">Active holds</dt><dd>{legalHoldSummary.data.active_count}</dd></div><div><dt className="text-[var(--color-mute)]">Company-wide</dt><dd>{legalHoldSummary.data.active_company_wide_count}</dd></div><div><dt className="text-[var(--color-mute)]">Scoped</dt><dd>{legalHoldSummary.data.active_scoped_count}</dd></div><div><dt className="text-[var(--color-mute)]">Held items</dt><dd>{legalHoldSummary.data.active_item_count}</dd></div></dl>
              <p className="text-xs text-[var(--color-mute)]">Draft: {legalHoldSummary.data.draft_count} · Released: {legalHoldSummary.data.released_count} · Cancelled: {legalHoldSummary.data.cancelled_count}</p>
            </div>
          )}
        </CardContent>
      </Card>
      ) : null}
      {canAudit ? (
      <Card>
        <CardHeader><CardTitle as="h2">Prepare dry-run manifest</CardTitle><CardDescription>Creates only an immutable review record. Use a registered class ID and a SHA-256 target reference; do not enter client, matter, or document identifiers.</CardDescription></CardHeader>
        <CardContent>
          <form className="grid gap-4" onSubmit={submitDryRun}>
            <div className="grid gap-2"><Label htmlFor="dry-run-operation-type">Operation type</Label><select id="dry-run-operation-type" value={operationType} onChange={(event) => setOperationType(event.target.value as typeof operationType)} className="h-10 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"><option value="tenant_export">Tenant export</option><option value="retention_purge">Retention purge</option><option value="tenant_offboarding">Tenant offboarding</option><option value="restore_validation">Restore validation</option></select></div>
            <div className="grid gap-2"><Label htmlFor="dry-run-evidence">Evidence reference</Label><Input id="dry-run-evidence" value={requestEvidenceRef} onChange={(event) => setRequestEvidenceRef(event.target.value)} placeholder="ticket://reviewed-request" /></div>
            <div className="grid gap-2 md:grid-cols-2"><div className="grid gap-2"><Label htmlFor="dry-run-data-class">Registered data class ID</Label><Input id="dry-run-data-class" value={dataClassId} onChange={(event) => setDataClassId(event.target.value)} placeholder="tenant_data_operations" /></div><div className="grid gap-2"><Label htmlFor="dry-run-target-type">Target type</Label><Input id="dry-run-target-type" value={targetType} onChange={(event) => setTargetType(event.target.value)} placeholder="tenant" /></div></div>
            <div className="grid gap-2"><Label htmlFor="dry-run-target-hash">SHA-256 target reference</Label><Input id="dry-run-target-hash" value={targetReferenceHash} onChange={(event) => setTargetReferenceHash(event.target.value)} placeholder="64 lowercase hexadecimal characters" spellCheck={false} /></div>
            {requestError ? <p role="alert" className="text-sm text-[var(--color-danger-700)]">{requestError}</p> : null}
            <div><Button type="submit" disabled={createDryRun.isPending}>{createDryRun.isPending ? "Preparing…" : "Create non-executable dry run"}</Button></div>
          </form>
        </CardContent>
      </Card>
      ) : null}
      <Card>
        <CardHeader><CardTitle as="h2">Dry-run manifests</CardTitle><CardDescription>Immutable review records only. Selecting a manifest does not request approval or execute an operation.</CardDescription></CardHeader>
        <CardContent>
          {history.isPending ? <Skeleton className="h-32 w-full" /> : history.isError ? <QueryErrorState title="Could not load dry-run manifests" error={history.error} onRetry={history.refetch} /> : history.data.operations.length === 0 ? <p className="text-sm text-[var(--color-mute)]">No dry-run manifests are available for this workspace.</p> : <div className="flex flex-col gap-2">{history.data.operations.map((operation) => <button key={operation.id} type="button" data-testid={`dry-run-${operation.id}`} onClick={() => setSelectedOperationId(operation.id)} className="rounded-lg border border-[var(--color-line)] p-4 text-left hover:bg-[var(--color-surface-muted)]"><div className="flex flex-wrap items-center justify-between gap-2"><span className="font-medium">{operation.operation_type.replaceAll("_", " ")}</span><Badge tone={operation.approval_status === "rejected" ? "warning" : "neutral"}>{operation.approval_status}</Badge></div><p className="mt-2 text-xs text-[var(--color-mute)]">{operation.completed_at} · {operation.id}</p></button>)}</div>}
        </CardContent>
      </Card>
      {selectedOperationId && canReview ? (
        <Card data-testid="data-operation-review">
          <CardHeader>
            <CardTitle as="h2">Review this operation</CardTitle>
            <CardDescription>
              Approving authorises an execution. It does not run one — export, purge, offboarding and restore all remain refused.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            {selectedManifest.isPending ? <Skeleton className="h-24 w-full" /> : selectedManifest.isError ? null : (
              <>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span className="text-sm text-[var(--color-mute)]">Review state</span>
                  <Badge tone={selectedManifest.data.approved_operation_id ? "success" : selectedManifest.data.approval_status === "rejected" ? "warning" : "neutral"}>
                    {selectedManifest.data.approved_operation_id
                      ? "authorised, not executed"
                      : selectedManifest.data.approval_status === "requested"
                        ? "awaiting a second approver"
                        : selectedManifest.data.approval_status === "rejected"
                          ? "refused"
                          : "not submitted"}
                  </Badge>
                </div>

                {selectedManifest.data.approved_operation_id ? (
                  <div className="rounded-lg border border-[var(--color-line)] p-4 text-sm">
                    <p>This manifest was approved. It authorised operation <span className="break-all font-mono text-xs">{selectedManifest.data.approved_operation_id}</span>, which is planned and has not run.</p>
                    <p className="mt-2 text-[var(--color-mute)]">A signed authorisation is withdrawn by an explicit revocation, not by refusing the manifest afterwards.</p>
                  </div>
                ) : selectedManifest.data.approval_status === "rejected" ? (
                  <div className="rounded-lg border border-[var(--color-line)] p-4 text-sm">
                    <p>Refused: {selectedManifest.data.rejection_reason}</p>
                    <p className="mt-2 text-[var(--color-mute)]">A refusal is final. Prepare a fresh dry run if the operation is still needed — whatever was objected to may change what the manifest should contain.</p>
                  </div>
                ) : selectedManifest.data.approval_status === "not_requested" ? (
                  <div className="flex flex-col gap-3">
                    <p className="text-sm text-[var(--color-mute)]">Submitting asks a second person to approve. It authorises nothing on its own.</p>
                    <div><Button type="button" onClick={() => reviewMutation.mutate({ kind: "request" })} disabled={reviewMutation.isPending}>Submit for approval</Button></div>
                  </div>
                ) : (
                  <div className="flex flex-col gap-5">
                    <p className="text-sm text-[var(--color-mute)]">
                      Approval requires a second person and a recent MFA step-up. The colleague who requested this operation cannot approve it, and refusing needs neither — an approver who cannot complete MFA must still be able to stop it.
                    </p>
                    <div className="grid gap-2">
                      <Label htmlFor="review-approver-label">Approve as</Label>
                      <Input id="review-approver-label" value={approverLabel} onChange={(event) => setApproverLabel(event.target.value)} placeholder="Records Partner" />
                      <div><Button type="button" onClick={() => reviewMutation.mutate({ kind: "approve" })} disabled={approverLabel.trim().length < 2 || reviewMutation.isPending}>Approve — authorise, do not run</Button></div>
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="review-rejection-reason">Refuse, with a reason</Label>
                      <Input id="review-rejection-reason" value={rejectionReason} onChange={(event) => setRejectionReason(event.target.value)} placeholder="The retention schedule cited here has not been approved." />
                      <div><Button type="button" variant="secondary" onClick={() => reviewMutation.mutate({ kind: "reject" })} disabled={rejectionReason.trim().length < 1 || reviewMutation.isPending}>Refuse this operation</Button></div>
                    </div>
                  </div>
                )}
                {reviewError ? <p role="alert" className="text-sm text-[var(--color-danger-700)]">{reviewError}</p> : null}
              </>
            )}
          </CardContent>
        </Card>
      ) : null}
      {selectedOperationId ? <Card data-testid="dry-run-detail"><CardHeader><CardTitle as="h2">Manifest detail</CardTitle><CardDescription>Target references remain hashed or redacted. This detail is not an execution authorization.</CardDescription></CardHeader><CardContent>{selectedManifest.isPending ? <Skeleton className="h-28 w-full" /> : selectedManifest.isError ? <QueryErrorState title="Could not load manifest detail" error={selectedManifest.error} onRetry={selectedManifest.refetch} /> : <dl className="grid gap-3 text-sm"><div><dt className="text-[var(--color-mute)]">Operation</dt><dd>{selectedManifest.data.operation_type}</dd></div><div><dt className="text-[var(--color-mute)]">Manifest hash</dt><dd className="break-all font-mono text-xs">{selectedManifest.data.manifest_hash}</dd></div><div><dt className="text-[var(--color-mute)]">Request scope hash</dt><dd className="break-all font-mono text-xs">{selectedManifest.data.request_scope_hash}</dd></div><div><dt className="text-[var(--color-mute)]">Reviewable items</dt><dd>{selectedManifest.data.items.length} item(s), {selectedManifest.data.exclusions.length} exclusion(s)</dd></div></dl>}</CardContent></Card> : null}
    </div>
  );
}
