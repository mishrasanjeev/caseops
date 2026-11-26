"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, Loader2, Users } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { ClientPicker } from "@/components/clients/ClientPicker";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { apiErrorMessage } from "@/lib/api/config";
import {
  assignClientToMatter,
  fetchMatterClientVerification,
  unassignClientFromMatter,
  type ClientKycStatus,
  type MatterClientVerificationRecord,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

// services/matter_operational_guard.py: only these lifecycle states take new
// client links or unlinks (disposed Matters answer 409).
const OPERATIONAL_STATUSES = new Set(["intake", "active", "on_hold"]);

export function matterClientsQueryKey(matterId: string) {
  return ["matters", matterId, "clients"] as const;
}

/** The linked clients of one Matter (GET /api/matters/{id}/client-verification). */
export function useMatterClients(matterId: string, enabled = true) {
  return useQuery({
    queryKey: matterClientsQueryKey(matterId),
    queryFn: () => fetchMatterClientVerification(matterId),
    enabled,
  });
}

export function kycTone(status: ClientKycStatus): "success" | "warning" | "brand" | "neutral" {
  if (status === "verified") return "success";
  if (status === "rejected" || status === "expired" || status === "required") return "warning";
  if (status === "submitted" || status === "under_review" || status === "requested") return "brand";
  return "neutral";
}

/** Why the signed-in user cannot change this Matter's client links, or null. */
export function clientLinkBlockedReason(canEdit: boolean, matterStatus: string): string | null {
  if (!canEdit) return "Your role can view linked clients but cannot link or unlink them.";
  if (!OPERATIONAL_STATUSES.has(matterStatus)) {
    return "This matter is disposed, so its client links can no longer change.";
  }
  return null;
}

type MatterClientsCardProps = {
  matter: { id: string; status: string; client_name?: string | null };
  className?: string;
};

export function MatterClientsCard({ matter, className }: MatterClientsCardProps) {
  const queryClient = useQueryClient();
  const canEdit = useCapability("clients:edit");
  const blockedReason = clientLinkBlockedReason(canEdit, matter.status);
  const clients = useMatterClients(matter.id);
  const linked = clients.data?.clients ?? [];
  const hasPrimary = linked.some((client) => client.is_primary);

  const [linking, setLinking] = useState(false);
  const [clientId, setClientId] = useState("");
  const [role, setRole] = useState("");
  const [makePrimary, setMakePrimary] = useState<boolean | null>(null);
  const [confirmUnlink, setConfirmUnlink] = useState<string | null>(null);
  const primaryChecked = makePrimary ?? !hasPrimary;

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["matters"] }),
      queryClient.invalidateQueries({ queryKey: ["clients"] }),
    ]);
  };
  const resetForm = () => {
    setLinking(false);
    setClientId("");
    setRole("");
    setMakePrimary(null);
  };

  const linkMutation = useMutation({
    mutationFn: () =>
      assignClientToMatter({
        matterId: matter.id,
        clientId,
        role: role.trim() || null,
        isPrimary: primaryChecked,
      }),
    onSuccess: async () => {
      toast.success("Client linked to this matter.");
      resetForm();
      await refresh();
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not link the client.")),
  });
  const unlinkMutation = useMutation({
    mutationFn: (targetId: string) =>
      unassignClientFromMatter({ matterId: matter.id, clientId: targetId }),
    onSuccess: async () => {
      toast.success("Client unlinked from this matter.");
      setConfirmUnlink(null);
      await refresh();
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not unlink the client.")),
  });

  return (
    <Card className={className} data-testid="matter-clients-card">
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3 space-y-0">
        <div className="min-w-0">
          <CardTitle>Clients</CardTitle>
          <CardDescription>
            Client records linked to this matter. The primary client&apos;s name is the
            matter&apos;s client name.
          </CardDescription>
        </div>
        <div className="flex min-w-0 flex-col items-end gap-1">
          <Button
            type="button"
            size="sm"
            variant={linking ? "ghost" : "outline"}
            disabled={Boolean(blockedReason)}
            aria-describedby={blockedReason ? "matter-clients-blocked" : undefined}
            onClick={() => (linking ? resetForm() : setLinking(true))}
            data-testid="matter-clients-link-open"
          >
            <Link2 className="h-4 w-4" aria-hidden />
            {linking ? "Cancel" : "Link client"}
          </Button>
          {blockedReason ? (
            <p id="matter-clients-blocked" className="max-w-xs text-right text-xs text-[var(--color-mute)]">
              {blockedReason}
            </p>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {linking && !blockedReason ? (
          <form
            className="grid gap-3 rounded-md border border-[var(--color-line)] p-3 md:grid-cols-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (clientId) linkMutation.mutate();
            }}
            data-testid="matter-clients-link-form"
          >
            <ClientPicker
              className="md:col-span-2"
              id="matter-clients-picker"
              label="Client to link"
              value={clientId}
              onChange={(next) => setClientId(next)}
              disabledReason={(client) =>
                linked.some((row) => row.client_id === client.id) ? "already linked" : null
              }
            />
            <div className="flex min-w-0 flex-col gap-1.5">
              <Label htmlFor="matter-clients-role">Role on this matter (optional)</Label>
              <Input
                id="matter-clients-role"
                value={role}
                maxLength={60}
                placeholder="Petitioner, respondent, guarantor…"
                onChange={(event) => setRole(event.target.value)}
              />
            </div>
            <label className="flex items-center gap-2 self-end pb-2 text-sm text-[var(--color-ink)]">
              <input
                type="checkbox"
                checked={primaryChecked}
                onChange={(event) => setMakePrimary(event.target.checked)}
                data-testid="matter-clients-primary"
              />
              {hasPrimary ? "Make primary (replaces the current primary client)" : "Primary client"}
            </label>
            <div className="flex justify-end gap-2 md:col-span-2">
              <Button type="button" variant="outline" size="sm" onClick={resetForm}>
                Cancel
              </Button>
              <Button
                type="submit"
                size="sm"
                disabled={!clientId || linkMutation.isPending}
                data-testid="matter-clients-link-submit"
              >
                {linkMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
                Link client
              </Button>
            </div>
          </form>
        ) : null}

        {clients.isPending ? (
          <p className="text-sm text-[var(--color-mute)]">Loading linked clients…</p>
        ) : clients.isError ? (
          <div role="alert" className="flex flex-wrap items-center gap-2 text-sm text-[var(--color-danger-500)]">
            <span>Linked clients could not be loaded: {apiErrorMessage(clients.error, "Request failed.")}</span>
            <Button type="button" size="sm" variant="outline" onClick={() => clients.refetch()}>
              Retry
            </Button>
          </div>
        ) : linked.length === 0 ? (
          <EmptyState
            icon={Users}
            title="No client record linked"
            description={
              matter.client_name
                ? `The matter names “${matter.client_name}” as typed text only. Link the client record to see its contact and KYC details here.`
                : "Link the client record to see its contact and KYC details here."
            }
          />
        ) : (
          <ul className="flex flex-col divide-y divide-[var(--color-line)]" data-testid="matter-clients-list">
            {linked.map((client) => (
              <LinkedClientRow
                key={client.client_id}
                client={client}
                matterClientName={matter.client_name ?? null}
                blockedReason={blockedReason}
                confirming={confirmUnlink === client.client_id}
                pending={unlinkMutation.isPending && unlinkMutation.variables === client.client_id}
                onAskUnlink={() => setConfirmUnlink(client.client_id)}
                onCancelUnlink={() => setConfirmUnlink(null)}
                onConfirmUnlink={() => unlinkMutation.mutate(client.client_id)}
              />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function LinkedClientRow({
  client,
  matterClientName,
  blockedReason,
  confirming,
  pending,
  onAskUnlink,
  onCancelUnlink,
  onConfirmUnlink,
}: {
  client: MatterClientVerificationRecord;
  matterClientName: string | null;
  blockedReason: string | null;
  confirming: boolean;
  pending: boolean;
  onAskUnlink: () => void;
  onCancelUnlink: () => void;
  onConfirmUnlink: () => void;
}) {
  return (
    <li className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0" data-testid="matter-client-row">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Link
            href={`/app/clients/${client.client_id}`}
            className="min-w-0 break-words text-sm font-semibold text-[var(--color-brand-700)] hover:underline"
          >
            {client.client_name}
          </Link>
          {client.is_primary ? <Badge tone="brand">Primary</Badge> : null}
          {client.role ? <Badge tone="neutral">{client.role}</Badge> : null}
          <Badge tone={kycTone(client.status)}>KYC {client.status.replace(/_/g, " ")}</Badge>
          {client.client_is_active ? null : <Badge tone="warning">Archived</Badge>}
        </div>
        {confirming ? null : (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={Boolean(blockedReason)}
            title={blockedReason ?? undefined}
            onClick={onAskUnlink}
            aria-label={`Unlink ${client.client_name}`}
          >
            Unlink
          </Button>
        )}
      </div>
      <p className="text-xs capitalize text-[var(--color-mute)]">{client.client_type}</p>
      {confirming ? (
        <div
          role="alert"
          className="flex flex-col gap-2 rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] p-3 text-sm"
        >
          <p className="text-[var(--color-ink)]">
            Unlink {client.client_name} from this matter?
            {client.is_primary && matterClientName
              ? ` The matter keeps “${matterClientName}” as its client name until you link another primary client or edit it.`
              : ""}
          </p>
          <div className="flex justify-end gap-2">
            <Button type="button" size="sm" variant="outline" onClick={onCancelUnlink}>
              Keep linked
            </Button>
            <Button type="button" size="sm" disabled={pending} onClick={onConfirmUnlink}>
              {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
              Unlink client
            </Button>
          </div>
        </div>
      ) : null}
    </li>
  );
}
