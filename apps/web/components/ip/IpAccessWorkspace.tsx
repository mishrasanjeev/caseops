"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import {
  applyIpAccessChange,
  fetchIpAccessPanel,
  listCompanyUsers,
  listTeams,
  previewIpAccessChange,
  type IpAccessChangeInput,
  type IpAccessPreview,
  type IpAccessSubjectType,
  type IpDocket,
} from "@/lib/api/endpoints";
import { apiErrorMessage } from "@/lib/api/config";

function toIso(value: string): string | null {
  if (!value) return null;
  return new Date(value).toISOString();
}

export function IpAccessWorkspace({
  docket,
  onChanged,
}: {
  docket: IpDocket;
  onChanged: () => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const panel = useQuery({
    queryKey: ["ip", "access", docket.id],
    queryFn: () => fetchIpAccessPanel(docket.id),
  });
  const companyUsers = useQuery({
    queryKey: ["company-users"],
    queryFn: () => listCompanyUsers(),
  });
  const teams = useQuery({
    queryKey: ["teams", "ip-access-subjects"],
    queryFn: listTeams,
  });
  const [subjectType, setSubjectType] = useState<IpAccessSubjectType>("membership");
  const [subjectId, setSubjectId] = useState("");
  const [changeKind, setChangeKind] = useState<"grant" | "add_wall">("grant");
  const [reason, setReason] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [pending, setPending] = useState<{
    input: IpAccessChangeInput;
    preview: IpAccessPreview;
  } | null>(null);

  const subjectOptions = useMemo(() => {
    if (subjectType === "team") {
      return (teams.data?.teams ?? [])
        .filter((team) => team.is_active)
        .map((team) => ({ id: team.id, label: `${team.name} (${team.member_count})` }));
    }
    return (companyUsers.data?.users ?? [])
      .filter((user) => user.membership_active && user.user_active)
      .map((user) => ({
        id: user.membership_id,
        label: `${user.full_name} · ${user.email}`,
      }));
  }, [companyUsers.data?.users, subjectType, teams.data?.teams]);

  const preview = useMutation({
    mutationFn: (input: IpAccessChangeInput) =>
      previewIpAccessChange(docket.id, input).then((result) => ({ input, result })),
    onSuccess: ({ input, result }) => setPending({ input, preview: result }),
    onError: (error) =>
      toast.error(apiErrorMessage(error, "The access preview was rejected.")),
  });
  const apply = useMutation({
    mutationFn: ({ input, result }: { input: IpAccessChangeInput; result: IpAccessPreview }) =>
      applyIpAccessChange(docket.id, input, result.preview_token),
    onSuccess: async () => {
      setPending(null);
      setReason("");
      toast.success("IP access policy updated and invalidation checks scheduled.");
      await queryClient.invalidateQueries({ queryKey: ["ip", "access", docket.id] });
      await onChanged();
    },
    onError: (error) =>
      toast.error(
        apiErrorMessage(
          error,
          "The access change failed. Refresh the preview and complete MFA step-up if required.",
        ),
      ),
  });

  const current = panel.data;
  const reasonReady = reason.trim().length >= 5;
  const previewPolicy = (restricted: boolean) => {
    if (!current || !reasonReady) return;
    preview.mutate({
      action: "set_restricted",
      expectedAccessPolicyVersion: current.access_policy_version,
      reason: reason.trim(),
      restricted,
    });
  };
  const previewSubjectChange = () => {
    if (!current || !reasonReady || !subjectId) return;
    preview.mutate({
      action: changeKind,
      expectedAccessPolicyVersion: current.access_policy_version,
      reason: reason.trim(),
      subjectType,
      subjectId,
      effectiveFrom: toIso(effectiveFrom),
      expiresAt: toIso(expiresAt),
    });
  };
  const previewRevocation = (input: { grantId?: string; wallId?: string }) => {
    if (!current || !reasonReady) return;
    preview.mutate({
      action: input.grantId ? "revoke_grant" : "revoke_wall",
      expectedAccessPolicyVersion: current.access_policy_version,
      reason: reason.trim(),
      grantId: input.grantId,
      wallId: input.wallId,
    });
  };

  return (
    <Card className="min-w-0 xl:col-span-2" data-testid="ip-access-workspace">
      <CardHeader>
        <CardTitle as="h3">Internal access and ethical walls</CardTitle>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-5">
        <p className="text-sm text-[var(--color-mute)]">
          IP access is independent from a linked Matter. Every change is previewed, version
          checked, step-up protected, and audited; portal access is managed separately.
        </p>
        {panel.isPending ? <p className="text-sm">Loading access policy…</p> : null}
        {panel.isError ? (
          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
            <p className="min-w-0 flex-1 break-words text-sm text-red-700">
              {apiErrorMessage(panel.error, "The access policy could not be loaded.")}
            </p>
            <Button className="w-full sm:w-auto" onClick={() => panel.refetch()}>
              Retry
            </Button>
          </div>
        ) : null}
        {current ? (
          <>
            <div className="grid min-w-0 gap-3 sm:grid-cols-3">
              <AccessMetric
                label="Policy"
                value={current.restricted ? "Restricted" : "Default internal"}
              />
              <AccessMetric
                label="Visible memberships"
                value={String(current.active_internal_membership_count)}
              />
              <AccessMetric
                label="Policy version"
                value={`v${current.access_policy_version}`}
              />
            </div>

            <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
              Portal grants, access-review campaigns, and emergency access are not created by
              this workflow. Linked Matter permissions are never copied.
            </div>

            <div className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <div className="min-w-0 sm:col-span-2 xl:col-span-4">
                <Label htmlFor={`ip-access-reason-${docket.id}`}>Reason for change</Label>
                <Input
                  id={`ip-access-reason-${docket.id}`}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="Conflict cleared, review assignment ended…"
                />
              </div>
              <div className="min-w-0">
                <Label htmlFor={`ip-access-change-${docket.id}`}>Change</Label>
                <select
                  id={`ip-access-change-${docket.id}`}
                  className="h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                  value={changeKind}
                  onChange={(event) =>
                    setChangeKind(event.target.value as "grant" | "add_wall")
                  }
                >
                  <option value="grant">Grant access</option>
                  <option value="add_wall">Add ethical wall</option>
                </select>
              </div>
              <div className="min-w-0">
                <Label htmlFor={`ip-access-subject-type-${docket.id}`}>Subject type</Label>
                <select
                  id={`ip-access-subject-type-${docket.id}`}
                  className="h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                  value={subjectType}
                  onChange={(event) => {
                    setSubjectType(event.target.value as IpAccessSubjectType);
                    setSubjectId("");
                  }}
                >
                  <option value="membership">Person</option>
                  <option value="team">Team</option>
                </select>
              </div>
              <div className="min-w-0 sm:col-span-2">
                <Label htmlFor={`ip-access-subject-${docket.id}`}>Person or team</Label>
                <select
                  id={`ip-access-subject-${docket.id}`}
                  className="h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                  value={subjectId}
                  onChange={(event) => setSubjectId(event.target.value)}
                >
                  <option value="">Select…</option>
                  {subjectOptions.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="min-w-0 sm:col-span-2">
                <Label htmlFor={`ip-access-effective-${docket.id}`}>Effective from</Label>
                <Input
                  id={`ip-access-effective-${docket.id}`}
                  type="datetime-local"
                  value={effectiveFrom}
                  onChange={(event) => setEffectiveFrom(event.target.value)}
                />
              </div>
              <div className="min-w-0 sm:col-span-2">
                <Label htmlFor={`ip-access-expires-${docket.id}`}>Expires at</Label>
                <Input
                  id={`ip-access-expires-${docket.id}`}
                  type="datetime-local"
                  value={expiresAt}
                  onChange={(event) => setExpiresAt(event.target.value)}
                />
              </div>
            </div>

            <div className="flex min-w-0 w-full flex-col gap-2 sm:flex-row sm:flex-wrap">
              <Button
                className="w-full sm:w-auto"
                onClick={previewSubjectChange}
                disabled={!reasonReady || !subjectId || preview.isPending}
              >
                Preview {changeKind === "grant" ? "grant" : "ethical wall"}
              </Button>
              <Button
                className="w-full sm:w-auto"
                variant="secondary"
                onClick={() => previewPolicy(!current.restricted)}
                disabled={!reasonReady || preview.isPending}
              >
                Preview {current.restricted ? "default access" : "restricted access"}
              </Button>
            </div>

            <AccessHistory
              title="Grant history"
              rows={current.grants.map((row) => ({
                id: row.id,
                label: row.subject_label,
                detail: `${row.subject_type} · ${row.reason ?? "No reason recorded"}`,
                revokedAt: row.revoked_at,
                expiresAt: row.expires_at,
              }))}
              reasonReady={reasonReady}
              onRevoke={(id) => previewRevocation({ grantId: id })}
            />
            <AccessHistory
              title="Ethical-wall history"
              rows={current.walls.map((row) => ({
                id: row.id,
                label: row.subject_label,
                detail: `${row.subject_type} · ${row.reason ?? "No reason recorded"}`,
                revokedAt: row.revoked_at,
                expiresAt: row.expires_at,
              }))}
              reasonReady={reasonReady}
              onRevoke={(id) => previewRevocation({ wallId: id })}
            />
          </>
        ) : null}

        {pending ? (
          <div
            className="min-w-0 rounded-lg border border-[var(--color-brand-500)] bg-[var(--color-brand-50)] p-4"
            data-testid="ip-access-preview"
          >
            <div className="font-semibold">Confirm previewed access change</div>
            <div className="mt-2 grid min-w-0 gap-2 text-sm sm:grid-cols-4">
              <span>Gains: {pending.preview.visibility_gain_count}</span>
              <span>Losses: {pending.preview.visibility_loss_count}</span>
              <span>Documents: {pending.preview.document_count}</span>
              <span>
                Queued deliveries: {pending.preview.queued_delivery_recheck_count}
              </span>
            </div>
            {pending.preview.affected_memberships.length ? (
              <ul className="mt-3 list-disc space-y-1 pl-5 text-sm">
                {pending.preview.affected_memberships.map((row) => (
                  <li key={row.membership_id} className="break-words">
                    {row.label}: {row.before_visible ? "visible" : "hidden"} →{" "}
                    {row.after_visible ? "visible" : "hidden"}
                  </li>
                ))}
              </ul>
            ) : null}
            {pending.preview.warnings.map((warning) => (
              <p key={warning} className="mt-2 break-words text-sm text-amber-900">
                {warning}
              </p>
            ))}
            <p className="mt-2 text-xs text-[var(--color-mute)]">
              MFA step-up is required when your tenant policy or enrollment requires it.
            </p>
            <div className="mt-3 flex min-w-0 w-full flex-col gap-2 sm:flex-row sm:flex-wrap">
              <Button
                className="w-full sm:w-auto"
                onClick={() => apply.mutate({ input: pending.input, result: pending.preview })}
                disabled={apply.isPending}
              >
                Apply access change
              </Button>
              <Button
                className="w-full sm:w-auto"
                variant="secondary"
                onClick={() => setPending(null)}
                disabled={apply.isPending}
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function AccessMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-md bg-[var(--color-bg-2)] p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-[var(--color-mute)]">
        {label}
      </div>
      <div className="mt-1 break-words font-semibold">{value}</div>
    </div>
  );
}

function AccessHistory({
  title,
  rows,
  reasonReady,
  onRevoke,
}: {
  title: string;
  rows: Array<{
    id: string;
    label: string;
    detail: string;
    revokedAt: string | null;
    expiresAt: string | null;
  }>;
  reasonReady: boolean;
  onRevoke: (id: string) => void;
}) {
  return (
    <div className="min-w-0">
      <div className="text-sm font-semibold">{title}</div>
      <div className="mt-2 flex min-w-0 flex-col gap-2">
        {rows.length === 0 ? (
          <p className="text-sm text-[var(--color-mute)]">No history yet.</p>
        ) : (
          rows.map((row) => (
            <div
              key={row.id}
              className="flex min-w-0 flex-col gap-2 rounded-md border border-[var(--color-line)] p-3 sm:flex-row sm:flex-wrap sm:items-start sm:justify-between"
            >
              <div className="min-w-0 flex-1">
                <div className="break-words text-sm font-semibold">{row.label}</div>
                <div className="mt-1 break-words text-xs text-[var(--color-mute)]">
                  {row.detail}
                  {row.expiresAt ? ` · expires ${new Date(row.expiresAt).toLocaleString()}` : ""}
                </div>
              </div>
              {row.revokedAt ? (
                <span className="text-xs font-semibold text-[var(--color-mute)]">Revoked</span>
              ) : (
                <Button
                  className="w-full sm:w-auto"
                  size="sm"
                  variant="secondary"
                  onClick={() => onRevoke(row.id)}
                  disabled={!reasonReady}
                  aria-label={`Preview revoke access for ${row.label}`}
                >
                  Preview revoke
                </Button>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
