"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  RotateCcw,
  ServerCog,
  ShieldAlert,
  XCircle,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  fetchProviderReadiness,
  ignoreProviderOperation,
  listProviderOperations,
  markProviderOperationResolved,
  replayProviderOperation,
} from "@/lib/api/endpoints";
import type {
  ProviderOperationRecord,
  ProviderReadinessRecord,
} from "@/lib/api/schemas";
import { useCapability } from "@/lib/capabilities";

function toneForStatus(status: string): "success" | "warning" | "neutral" | "brand" {
  if (status === "synced" || status === "delivered" || status === "ready") {
    return "success";
  }
  if (
    status === "failed" ||
    status === "dead_letter" ||
    status === "blocked" ||
    status.startsWith("blocked")
  ) {
    return "warning";
  }
  if (status === "retry_scheduled" || status === "queued" || status === "pending") {
    return "brand";
  }
  return "neutral";
}

function formatWhen(value: string | null): string {
  if (!value) return "None";
  try {
    return new Date(value).toLocaleString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

type PendingAction = {
  action: "replay" | "ignore" | "mark_resolved";
  operation: ProviderOperationRecord;
};

function actionLabel(action: PendingAction["action"]): string {
  if (action === "mark_resolved") return "Mark resolved";
  return action[0].toUpperCase() + action.slice(1);
}

export default function ProviderOperationsPage() {
  const canAdmin = useCapability("workspace:admin");
  const queryClient = useQueryClient();
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [actionReason, setActionReason] = useState("");
  const operationsQuery = useQuery({
    queryKey: ["admin", "provider-operations", "jobs"],
    queryFn: () => listProviderOperations({ includeResolved: true, limit: 100 }),
    enabled: canAdmin,
  });
  const readinessQuery = useQuery({
    queryKey: ["admin", "provider-operations", "readiness"],
    queryFn: fetchProviderReadiness,
    enabled: canAdmin,
  });

  const refreshJobs = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["admin", "provider-operations", "jobs"],
    });
  };
  const closeActionDialog = () => {
    setPendingAction(null);
    setActionReason("");
  };
  const replayMutation = useMutation({
    mutationFn: replayProviderOperation,
    onSuccess: async (result) => {
      toast.success(result.message);
      closeActionDialog();
      await refreshJobs();
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not replay provider operation.")),
  });
  const ignoreMutation = useMutation({
    mutationFn: ignoreProviderOperation,
    onSuccess: async (result) => {
      toast.success(result.message);
      closeActionDialog();
      await refreshJobs();
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not ignore provider operation.")),
  });
  const resolveMutation = useMutation({
    mutationFn: markProviderOperationResolved,
    onSuccess: async (result) => {
      toast.success(result.message);
      closeActionDialog();
      await refreshJobs();
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not resolve provider operation.")),
  });
  const actionBusy =
    replayMutation.isPending || ignoreMutation.isPending || resolveMutation.isPending;
  const openActionDialog = (
    action: PendingAction["action"],
    operation: ProviderOperationRecord,
  ) => {
    setPendingAction({ action, operation });
    setActionReason("");
  };
  const submitAction = () => {
    if (!pendingAction) return;
    const reason = actionReason.trim();
    if (reason.length < 8) return;
    const input = { operationId: pendingAction.operation.id, reason };
    if (pendingAction.action === "replay") {
      replayMutation.mutate(input);
    } else if (pendingAction.action === "ignore") {
      ignoreMutation.mutate(input);
    } else {
      resolveMutation.mutate(input);
    }
  };

  if (!canAdmin) {
    return (
      <EmptyState
        icon={ServerCog}
        title="Workspace admin required"
        description="Provider operations are limited to workspace owners and admins."
      />
    );
  }

  const operations = operationsQuery.data?.operations ?? [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Admin - Provider operations"
        title="Provider operations"
        description="Retry, dead-letter, and readiness status for tenant-scoped provider automation."
      />

      <section className="grid gap-3 md:grid-cols-4">
        <Kpi label="Open" value={operationsQuery.data?.open_count ?? 0} />
        <Kpi label="Replayable" value={operationsQuery.data?.replayable_count ?? 0} />
        <Kpi label="Ignored" value={operationsQuery.data?.ignored_count ?? 0} />
        <Kpi label="Resolved" value={operationsQuery.data?.resolved_count ?? 0} />
      </section>

      <Card>
        <CardHeader>
          <CardTitle as="h2">Readiness gates</CardTitle>
        </CardHeader>
        <CardContent>
          {readinessQuery.isPending ? (
            <Skeleton className="h-28 w-full" />
          ) : readinessQuery.isError ? (
            <QueryErrorState
              title="Could not load provider readiness"
              error={readinessQuery.error}
              onRetry={readinessQuery.refetch}
            />
          ) : (
            <div className="grid gap-3 lg:grid-cols-3">
              {readinessQuery.data.providers.map((provider) => (
                <ReadinessTile key={provider.provider} provider={provider} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle as="h2">Failed and blocked jobs</CardTitle>
        </CardHeader>
        <CardContent>
          {operationsQuery.isPending ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
            </div>
          ) : operationsQuery.isError ? (
            <QueryErrorState
              title="Could not load provider operations"
              error={operationsQuery.error}
              onRetry={operationsQuery.refetch}
            />
          ) : operations.length === 0 ? (
            <EmptyState
              icon={ShieldAlert}
              title="No provider operations need attention"
              description="Failed, blocked, or dead-letter provider jobs will appear here."
            />
          ) : (
            <ul className="divide-y divide-[var(--color-line)]">
              {operations.map((operation) => (
                <OperationRow
                  key={operation.id}
                  operation={operation}
                  busy={actionBusy}
                  onReplay={() => openActionDialog("replay", operation)}
                  onIgnore={() => openActionDialog("ignore", operation)}
                  onResolve={() => openActionDialog("mark_resolved", operation)}
                />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={pendingAction !== null}
        onOpenChange={(open) => {
          if (!open && !actionBusy) closeActionDialog();
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {pendingAction ? `${actionLabel(pendingAction.action)} provider operation` : ""}
            </DialogTitle>
            <DialogDescription>
              This action writes an audit event and applies only to the selected
              tenant-scoped provider job.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <label
              htmlFor="provider-operation-reason"
              className="text-sm font-medium text-[var(--color-ink)]"
            >
              Reason
            </label>
            <Textarea
              id="provider-operation-reason"
              value={actionReason}
              onChange={(event) => setActionReason(event.target.value)}
              disabled={actionBusy}
              maxLength={500}
              placeholder="Record the operator reason for audit."
            />
            <div className="text-xs text-[var(--color-mute)]">
              {actionReason.trim().length}/500
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={closeActionDialog}
              disabled={actionBusy}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={submitAction}
              disabled={actionBusy || actionReason.trim().length < 8}
              data-testid="provider-operation-confirm-action"
            >
              {pendingAction ? actionLabel(pendingAction.action) : "Confirm"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-[var(--color-line)] bg-white px-3 py-2">
      <div className="text-xs text-[var(--color-mute)]">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums text-[var(--color-ink)]">
        {value}
      </div>
    </div>
  );
}

function ReadinessTile({ provider }: { provider: ProviderReadinessRecord }) {
  const missing = [
    ...provider.missing_config_names,
    ...provider.missing_approval_keys,
  ];
  return (
    <div
      className="rounded-md border border-[var(--color-line)] bg-white p-3"
      data-testid={`readiness-${provider.provider}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-medium text-[var(--color-mute)]">
            {provider.adp_slice}
          </div>
          <h3 className="mt-1 text-sm font-semibold text-[var(--color-ink)]">
            {provider.display_name}
          </h3>
        </div>
        <Badge tone={toneForStatus(provider.state)}>
          {provider.state.replaceAll("_", " ")}
        </Badge>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <Badge tone={provider.enabled ? "success" : "neutral"}>
          {provider.enabled ? "enabled" : "disabled"}
        </Badge>
        <Badge tone={provider.external_calls_enabled ? "success" : "warning"}>
          {provider.external_calls_enabled ? "external calls on" : "external calls off"}
        </Badge>
        <Badge tone={provider.durable_workflow_available ? "success" : "neutral"}>
          {provider.durable_workflow_available ? "workflow ready" : "workflow gated"}
        </Badge>
      </div>
      {missing.length ? (
        <div className="mt-3 text-xs text-[var(--color-mute)]">
          Missing: {missing.slice(0, 4).join(", ")}
          {missing.length > 4 ? ` +${missing.length - 4}` : ""}
        </div>
      ) : null}
      <div className="mt-2 text-xs text-[var(--color-mute)]">
        {provider.retry_dead_letter}
      </div>
    </div>
  );
}

function OperationRow({
  operation,
  busy,
  onReplay,
  onIgnore,
  onResolve,
}: {
  operation: ProviderOperationRecord;
  busy: boolean;
  onReplay: () => void;
  onIgnore: () => void;
  onResolve: () => void;
}) {
  return (
    <li className="flex flex-col gap-3 py-3" data-testid={`provider-operation-${operation.id}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={toneForStatus(operation.status)}>
              {operation.status.replaceAll("_", " ")}
            </Badge>
            <Badge tone={operation.operator_state === "open" ? "brand" : "neutral"}>
              {operation.operator_state}
            </Badge>
            <span className="text-sm font-medium text-[var(--color-ink)]">
              {operation.job_kind.replaceAll("_", " ")}
            </span>
          </div>
          <div className="mt-1 text-xs text-[var(--color-mute)]">
            {operation.provider}
            {operation.source_type ? ` - ${operation.source_type}` : ""}
            {operation.source_ref ? ` - ${operation.source_ref}` : ""}
            {" - "}
            attempts {operation.attempts}/{operation.max_attempts}
            {" - "}
            next retry {formatWhen(operation.next_attempt_at)}
          </div>
          {operation.error_redacted ? (
            <div className="mt-1 text-xs text-[var(--color-warn-700,#a55400)]">
              {operation.error_redacted}
            </div>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={onReplay}
            disabled={busy || !operation.replay_available}
            data-testid={`provider-operation-replay-${operation.id}`}
          >
            <RotateCcw className="h-4 w-4" aria-hidden /> Replay
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={onIgnore}
            disabled={busy || !operation.ignore_available}
            data-testid={`provider-operation-ignore-${operation.id}`}
          >
            <XCircle className="h-4 w-4" aria-hidden /> Ignore
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={onResolve}
            disabled={busy || !operation.mark_resolved_available}
            data-testid={`provider-operation-resolve-${operation.id}`}
          >
            <CheckCircle2 className="h-4 w-4" aria-hidden /> Resolve
          </Button>
        </div>
      </div>
      {operation.notes.length ? (
        <div className="text-xs text-[var(--color-mute)]">
          {operation.notes.join(" ")}
        </div>
      ) : null}
    </li>
  );
}
