"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarCheck,
  Download,
  HardDrive,
  MailPlus,
  MessageSquareWarning,
  PlugZap,
  ServerCog,
  Shield,
  ShieldCheck,
  UserPlus,
  Users as UsersIcon,
  Wrench,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { RoadmapStub } from "@/components/app/RoadmapStub";
import { TenantAIPolicyCard } from "@/components/app/TenantAIPolicyCard";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { API_BASE_URL, apiErrorMessage } from "@/lib/api/config";
import {
  fetchTenantEnterpriseReadiness,
  getStorageGovernance,
  listMatters,
  updateStorageGovernance,
  type FirmStorageUsageSummary,
} from "@/lib/api/endpoints";
import { fetchWithTimeout } from "@/lib/api/client";
import {
  invitePortalUser,
  type PortalUserRole,
} from "@/lib/api/portal";
import type { TenantEnterpriseReadinessResponse } from "@/lib/api/schemas";
import { useCapability } from "@/lib/capabilities";

function sinceIsoOrNull(local: string): string | null {
  if (!local) return null;
  // "Since" is inclusive from the start of that calendar day.
  return `${local}T00:00:00Z`;
}

function untilIsoOrNull(local: string): string | null {
  if (!local) return null;
  // "Until" from <input type="date"> is a day, and users mean "to the
  // end of that day" — not "to the start". Snapping to 00:00:00Z
  // truncated the whole day the user selected, silently dropping
  // rows. Snap to 23:59:59Z of the picked day instead so the export
  // actually includes events on the until-date.
  return `${local}T23:59:59Z`;
}

const GIB = 1024 ** 3;

function humanSize(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "Unlimited";
  if (bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = bytes;
  let i = 0;
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024;
    i += 1;
  }
  return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function quotaGbInput(summary: FirmStorageUsageSummary | undefined): string {
  if (!summary || summary.quota_bytes === null) return "";
  const value = summary.quota_bytes / GIB;
  return value.toFixed(2).replace(/\.?0+$/, "");
}

function quotaBytesFromInput(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) {
    throw new Error("Quota must be a non-negative number of GiB.");
  }
  return Math.round(parsed * GIB);
}

function storageStateLabel(state: string): string {
  if (state === "hard_limit") return "Hard limit";
  if (state === "warning") return "Warning";
  if (state === "unlimited") return "Unlimited";
  return "OK";
}

function EnterpriseReadinessCard({
  readiness,
}: {
  readiness: TenantEnterpriseReadinessResponse | undefined;
}) {
  const identity = readiness?.enterprise_identity;
  const agents = readiness?.agent_trust_plane;
  const ai = readiness?.ai_governance;
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2">Enterprise readiness</CardTitle>
        <CardDescription>
          SSO/SCIM, agent trust, and AI governance status without implying unavailable features are live.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 md:grid-cols-3">
          <div className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-semibold text-[var(--color-ink)]">SSO / SCIM</div>
              <Badge tone="neutral">{identity?.readiness_classification ?? "planned"}</Badge>
            </div>
            <p className="mt-2 text-sm leading-relaxed text-[var(--color-mute)]">
              {identity?.not_enabled_reason ??
                "OIDC, SAML, and SCIM are not enabled until IdP UAT evidence is recorded."}
            </p>
            <dl className="mt-3 grid grid-cols-2 gap-2 text-xs text-[var(--color-ink-2)]">
              <div>OIDC: {identity?.oidc_status ?? "disabled"}</div>
              <div>SAML: {identity?.saml_status ?? "planned"}</div>
              <div>SCIM: {identity?.scim_status ?? "planned"}</div>
              <div>Enforce: {identity?.sso_enforcement_status ?? "disabled"}</div>
            </dl>
          </div>
          <div className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-semibold text-[var(--color-ink)]">Agent trust</div>
              <Badge tone="warning">{agents?.readiness_classification ?? "planned"}</Badge>
            </div>
            <p className="mt-2 text-sm leading-relaxed text-[var(--color-mute)]">
              {agents?.not_enabled_reason ??
                "Autonomous scoped-agent execution is not live."}
            </p>
            <div className="mt-3 text-xs text-[var(--color-ink-2)]">
              Grants {agents?.grant_count ?? 0} / active {agents?.active_grant_count ?? 0};
              executions {agents?.execution_count ?? 0}
            </div>
          </div>
          <div className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-semibold text-[var(--color-ink)]">AI governance</div>
              <Badge tone="brand">{ai?.readiness_classification ?? "review-first"}</Badge>
            </div>
            <p className="mt-2 text-sm leading-relaxed text-[var(--color-mute)]">
              Prompt/model approvals, regression evidence, legal disclaimers, and audit gates remain required for AI workflows.
            </p>
            <div className="mt-3 text-xs text-[var(--color-ink-2)]">
              Approved {ai?.approved_policy_count ?? 0}; pending {ai?.pending_policy_count ?? 0};
              blocked {ai?.blocked_policy_count ?? 0}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function AdminPage() {
  const queryClient = useQueryClient();
  const canAdmin = useCapability("workspace:admin");
  const canAudit = useCapability("audit:export");
  const canManageUsers = useCapability("company:manage_users");
  const canTeamsManage = useCapability("teams:manage");
  const canPortalInvite = useCapability("portal:invite");
  const canManageNotifications = useCapability("notifications:manage");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [action, setAction] = useState("");
  const [format, setFormat] = useState<"jsonl" | "csv">("jsonl");
  const [busy, setBusy] = useState(false);
  const [portalEmail, setPortalEmail] = useState("");
  const [portalFullName, setPortalFullName] = useState("");
  const [portalRole, setPortalRole] = useState<PortalUserRole>("client");
  const [portalMatterId, setPortalMatterId] = useState("");
  const [portalCanReply, setPortalCanReply] = useState(true);
  const [portalCanUpload, setPortalCanUpload] = useState(false);
  const [portalCanInvoice, setPortalCanInvoice] = useState(false);
  const [storageQuotaGb, setStorageQuotaGb] = useState("");

  const storageQuery = useQuery({
    queryKey: ["admin", "storage-governance"],
    queryFn: getStorageGovernance,
    enabled: canAdmin,
  });
  const enterpriseReadinessQuery = useQuery({
    queryKey: ["admin", "enterprise-readiness"],
    queryFn: fetchTenantEnterpriseReadiness,
    enabled: canAdmin,
  });

  useEffect(() => {
    setStorageQuotaGb(quotaGbInput(storageQuery.data));
  }, [storageQuery.data?.quota_bytes]);

  const storageMutation = useMutation({
    mutationFn: () =>
      updateStorageGovernance({
        quotaBytes: quotaBytesFromInput(storageQuotaGb),
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["admin", "storage-governance"], data);
      toast.success("Storage quota updated.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not update storage quota."));
    },
  });

  const portalMattersQuery = useQuery({
    queryKey: ["admin", "portal-invite", "matters"],
    queryFn: () => listMatters({ limit: 100 }),
    enabled: canPortalInvite,
  });
  const portalMatterOptions = portalMattersQuery.data?.matters ?? [];

  const portalInviteMutation = useMutation({
    mutationFn: () =>
      invitePortalUser({
        email: portalEmail.trim().toLowerCase(),
        fullName: portalFullName.trim(),
        role: portalRole,
        matterIds: [portalMatterId],
        canReply: portalCanReply,
        canUpload: portalRole === "outside_counsel" && portalCanUpload,
        canInvoice: portalRole === "outside_counsel" && portalCanInvoice,
      }),
    onSuccess: (result) => {
      toast.success(
        `${result.portal_user.full_name} invited to the ${portalRole === "outside_counsel" ? "outside-counsel" : "client"} portal.`,
      );
      setPortalEmail("");
      setPortalFullName("");
      setPortalMatterId("");
      setPortalRole("client");
      setPortalCanReply(true);
      setPortalCanUpload(false);
      setPortalCanInvoice(false);
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not invite portal user."));
    },
  });

  const portalInviteReady =
    portalEmail.includes("@") &&
    portalFullName.trim().length > 0 &&
    portalMatterId.trim().length > 0 &&
    !portalInviteMutation.isPending;

  async function handleDownload() {
    // P0-001 (2026-04-24): EG-001 cookie migration removed the
    // localStorage token, but this page still bearer-fetched and
    // threw "Your session expired" even when the cookie session was
    // perfectly valid. Use credentials: "include" so the browser
    // sends the HttpOnly session cookie. GET so no CSRF header
    // needed (CSRF middleware exempts GET/HEAD/OPTIONS).
    setBusy(true);
    try {
      const params = new URLSearchParams();
      const sinceIso = sinceIsoOrNull(since);
      const untilIso = untilIsoOrNull(until);
      if (sinceIso) params.set("since", sinceIso);
      if (untilIso) params.set("until", untilIso);
      if (action.trim()) params.set("action", action.trim());
      if (format !== "jsonl") params.set("format", format);
      const url =
        `${API_BASE_URL}/api/admin/audit/export` +
        (params.toString() ? `?${params.toString()}` : "");
      const resp = await fetchWithTimeout(url, {
        credentials: "include",
        headers: { Accept: "*/*" },
      });
      if (resp.status === 401) {
        throw new Error("Sign in again to export the audit trail.");
      }
      if (resp.status === 403) {
        throw new Error(
          "Your role does not include audit:export — ask the workspace owner.",
        );
      }
      if (!resp.ok) {
        let detail = "Could not export the audit trail.";
        try {
          const body = await resp.json();
          if (body?.detail) detail = body.detail;
        } catch {
          /* ignore */
        }
        throw new Error(detail);
      }
      const blob = await resp.blob();
      const downloadName =
        resp.headers
          .get("content-disposition")
          ?.match(/filename="([^"]+)"/)?.[1] ?? `audit-export.${format}`;
      const href = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = href;
      a.download = downloadName;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(href);
      toast.success("Audit trail downloaded.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Download failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Workspace"
        title="Admin & governance"
        description="Audit trail export, storage governance, security policy, AI policy, and enterprise-readiness status for this workspace."
        actions={
          <div className="flex min-w-0 w-full flex-wrap items-center gap-2 md:w-auto">
            {canManageNotifications ? (
              <Link
                href="/app/admin/notifications"
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-line)] bg-white px-3 py-1.5 text-sm font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
              >
                Notifications
              </Link>
            ) : null}
            {canAdmin ? (
              <Link
                href="/app/admin/ai-feedback"
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-line)] bg-white px-3 py-1.5 text-sm font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
              >
                <MessageSquareWarning className="h-4 w-4" aria-hidden /> AI feedback
              </Link>
            ) : null}
            {canAdmin ? (
              <Link
                href="/app/admin/integrations"
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-line)] bg-white px-3 py-1.5 text-sm font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
              >
                <PlugZap className="h-4 w-4" aria-hidden /> Integrations
              </Link>
            ) : null}
            {canAdmin ? (
              <Link
                href="/app/admin/provider-operations"
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-line)] bg-white px-3 py-1.5 text-sm font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
              >
                <ServerCog className="h-4 w-4" aria-hidden /> Provider ops
              </Link>
            ) : null}
            {canAdmin ? (
              <Link
                href="/app/admin/outlook"
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-line)] bg-white px-3 py-1.5 text-sm font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
              >
                <CalendarCheck className="h-4 w-4" aria-hidden /> Outlook
              </Link>
            ) : null}
            {canAudit ? (
              <Link
                href="/app/admin/data-governance"
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-line)] bg-white px-3 py-1.5 text-sm font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
              >
                <Shield className="h-4 w-4" aria-hidden /> Data governance
              </Link>
            ) : null}
            {canManageUsers ? (
              <Link
                href="/app/admin/employees"
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-line)] bg-white px-3 py-1.5 text-sm font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
              >
                <UserPlus className="h-4 w-4" aria-hidden /> Employees
              </Link>
            ) : null}
            {canManageUsers ? (
              <Link
                href="/app/admin/roles"
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-line)] bg-white px-3 py-1.5 text-sm font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
              >
                <ShieldCheck className="h-4 w-4" aria-hidden /> Roles
              </Link>
            ) : null}
            {canTeamsManage ? (
              <Link
                href="/app/admin/teams"
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-line)] bg-white px-3 py-1.5 text-sm font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
              >
                <UsersIcon className="h-4 w-4" aria-hidden /> Manage teams
              </Link>
            ) : null}
            <Link
              href="/app/admin/judge-aliases"
              className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-line)] bg-white px-3 py-1.5 text-sm font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
            >
              Judge aliases
            </Link>
          </div>
        }
      />

      {canAdmin ? <EnterpriseReadinessCard readiness={enterpriseReadinessQuery.data} /> : null}

      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div>
            <CardTitle as="h2">Audit trail export</CardTitle>
            <CardDescription>
              Streams every recorded action on this tenant — matter
              creation, draft state transitions, hearing-pack review,
              access denials, and the export itself. Choose JSONL for
              machine analysis or CSV for spreadsheets. Defaults to the
              last 30 days. Workspace owner only.
            </CardDescription>
          </div>
          <Shield className="h-5 w-5 text-[var(--color-brand-700)]" aria-hidden />
        </CardHeader>
        <CardContent>
          {!canAudit ? (
            <p className="text-sm text-[var(--color-mute)]">
              Your role does not include <code>audit:export</code>. Ask
              your workspace owner to export on your behalf.
            </p>
          ) : (
            <form
              className="grid gap-4 md:grid-cols-4"
              onSubmit={(event) => {
                event.preventDefault();
                handleDownload();
              }}
            >
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="audit-since">Since</Label>
                <Input
                  id="audit-since"
                  type="date"
                  value={since}
                  onChange={(e) => setSince(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="audit-until">Until</Label>
                <Input
                  id="audit-until"
                  type="date"
                  value={until}
                  onChange={(e) => setUntil(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="audit-action">Action filter (optional)</Label>
                <Input
                  id="audit-action"
                  placeholder="e.g. draft.approve"
                  value={action}
                  onChange={(e) => setAction(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="audit-format">Format</Label>
                <select
                  id="audit-format"
                  className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm"
                  value={format}
                  onChange={(e) => setFormat(e.target.value as "jsonl" | "csv")}
                >
                  <option value="jsonl">JSONL (structured)</option>
                  <option value="csv">CSV (spreadsheet)</option>
                </select>
              </div>
              <div className="md:col-span-4">
                <Button
                  type="submit"
                  disabled={busy}
                  data-testid="download-audit-export"
                >
                  <Download className="h-4 w-4" aria-hidden />
                  {busy
                    ? "Downloading…"
                    : `Download audit trail (${format.toUpperCase()})`}
                </Button>
              </div>
            </form>
          )}
        </CardContent>
      </Card>

      {canAdmin ? (
        <Card data-testid="storage-governance-card">
          <CardHeader className="flex-row items-start justify-between gap-4">
            <div>
              <CardTitle as="h2">Storage governance</CardTitle>
              <CardDescription>
                Firm-level usage, quota, and largest matter files.
              </CardDescription>
            </div>
            <HardDrive className="h-5 w-5 text-[var(--color-brand-700)]" aria-hidden />
          </CardHeader>
          <CardContent>
            {storageQuery.isPending ? (
              <p className="text-sm text-[var(--color-mute)]">
                Loading storage usage...
              </p>
            ) : storageQuery.data ? (
              <div className="flex flex-col gap-4">
                <div className="grid gap-3 md:grid-cols-4">
                  <div className="rounded-md border border-[var(--color-line)] px-3 py-2">
                    <div className="text-xs text-[var(--color-mute)]">Used</div>
                    <div className="text-lg font-semibold text-[var(--color-ink)]">
                      {humanSize(storageQuery.data.used_bytes)}
                    </div>
                  </div>
                  <div className="rounded-md border border-[var(--color-line)] px-3 py-2">
                    <div className="text-xs text-[var(--color-mute)]">Quota</div>
                    <div className="text-lg font-semibold text-[var(--color-ink)]">
                      {humanSize(storageQuery.data.quota_bytes)}
                    </div>
                  </div>
                  <div className="rounded-md border border-[var(--color-line)] px-3 py-2">
                    <div className="text-xs text-[var(--color-mute)]">Remaining</div>
                    <div className="text-lg font-semibold text-[var(--color-ink)]">
                      {humanSize(storageQuery.data.remaining_bytes)}
                    </div>
                  </div>
                  <div className="rounded-md border border-[var(--color-line)] px-3 py-2">
                    <div className="text-xs text-[var(--color-mute)]">State</div>
                    <div className="text-lg font-semibold text-[var(--color-ink)]">
                      {storageStateLabel(storageQuery.data.state)}
                    </div>
                  </div>
                </div>

                <form
                  className="flex flex-wrap items-end gap-3"
                  onSubmit={(event) => {
                    event.preventDefault();
                    storageMutation.mutate();
                  }}
                >
                  <div className="flex min-w-48 flex-col gap-1.5">
                    <Label htmlFor="storage-quota-gb">
                      Firm quota in GiB
                    </Label>
                    <Input
                      id="storage-quota-gb"
                      type="number"
                      min={0}
                      step="0.01"
                      value={storageQuotaGb}
                      onChange={(event) => setStorageQuotaGb(event.target.value)}
                      placeholder="Blank for unlimited"
                      data-testid="storage-quota-input"
                    />
                  </div>
                  <Button
                    type="submit"
                    disabled={storageMutation.isPending}
                    data-testid="storage-quota-save"
                  >
                    {storageMutation.isPending ? "Saving..." : "Save quota"}
                  </Button>
                </form>

                <div className="grid gap-4 lg:grid-cols-2">
                  <div>
                    <h3 className="text-sm font-semibold text-[var(--color-ink)]">
                      Usage by matter
                    </h3>
                    <div className="mt-2 overflow-hidden rounded-md border border-[var(--color-line)]">
                      {(storageQuery.data.usage_by_matter.slice(0, 5)).map((matter) => (
                        <div
                          key={matter.matter_id}
                          className="flex items-center justify-between gap-3 border-b border-[var(--color-line-2)] px-3 py-2 text-sm last:border-0"
                        >
                          <span className="min-w-0 truncate">
                            {matter.matter_code} - {matter.matter_title}
                          </span>
                          <span className="shrink-0 text-[var(--color-mute)]">
                            {humanSize(matter.used_bytes)}
                          </span>
                        </div>
                      ))}
                      {storageQuery.data.usage_by_matter.length === 0 ? (
                        <div className="px-3 py-2 text-sm text-[var(--color-mute)]">
                          No stored matter files yet.
                        </div>
                      ) : null}
                    </div>
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-[var(--color-ink)]">
                      Largest files
                    </h3>
                    <div className="mt-2 overflow-hidden rounded-md border border-[var(--color-line)]">
                      {(storageQuery.data.largest_files.slice(0, 5)).map((file) => (
                        <div
                          key={file.attachment_id}
                          className="flex items-center justify-between gap-3 border-b border-[var(--color-line-2)] px-3 py-2 text-sm last:border-0"
                        >
                          <span className="min-w-0 truncate">
                            {file.original_filename}
                          </span>
                          <span className="shrink-0 text-[var(--color-mute)]">
                            {humanSize(file.size_bytes)}
                          </span>
                        </div>
                      ))}
                      {storageQuery.data.largest_files.length === 0 ? (
                        <div className="px-3 py-2 text-sm text-[var(--color-mute)]">
                          No files to report.
                        </div>
                      ) : null}
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <p className="text-sm text-[var(--color-mute)]">
                Storage usage could not be loaded.
              </p>
            )}
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div>
            <CardTitle as="h2">External portal access</CardTitle>
            <CardDescription>
              Invite a client or outside counsel and grant access to one
              matter. Clients land in the read-only matter portal; outside
              counsel land in the assigned-matters portal.
            </CardDescription>
          </div>
          <MailPlus className="h-5 w-5 text-[var(--color-brand-700)]" aria-hidden />
        </CardHeader>
        <CardContent>
          {!canPortalInvite ? (
            <p className="text-sm text-[var(--color-mute)]">
              Your role does not include <code>portal:invite</code>. Ask
              the workspace owner or admin to invite external users.
            </p>
          ) : (
            <form
              className="grid gap-4 md:grid-cols-2"
              onSubmit={(event) => {
                event.preventDefault();
                if (!portalInviteReady) {
                  toast.error("Name, email, and matter are required.");
                  return;
                }
                portalInviteMutation.mutate();
              }}
            >
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="portal-invite-name">Full name</Label>
                <Input
                  id="portal-invite-name"
                  value={portalFullName}
                  onChange={(e) => setPortalFullName(e.target.value)}
                  placeholder="Asha Rao"
                  data-testid="portal-invite-name"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="portal-invite-email">Email</Label>
                <Input
                  id="portal-invite-email"
                  type="email"
                  value={portalEmail}
                  onChange={(e) => setPortalEmail(e.target.value)}
                  placeholder="asha@example.com"
                  data-testid="portal-invite-email"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="portal-invite-role">Portal role</Label>
                <select
                  id="portal-invite-role"
                  className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm"
                  value={portalRole}
                  onChange={(e) => {
                    const next = e.target.value as PortalUserRole;
                    setPortalRole(next);
                    setPortalCanReply(next === "client");
                    setPortalCanUpload(next === "outside_counsel");
                    setPortalCanInvoice(next === "outside_counsel");
                  }}
                  data-testid="portal-invite-role"
                >
                  <option value="client">Client portal</option>
                  <option value="outside_counsel">Outside counsel portal</option>
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="portal-invite-matter">Matter grant</Label>
                <select
                  id="portal-invite-matter"
                  className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm"
                  value={portalMatterId}
                  onChange={(e) => setPortalMatterId(e.target.value)}
                  disabled={portalMattersQuery.isPending}
                  data-testid="portal-invite-matter"
                >
                  <option value="">
                    {portalMattersQuery.isPending
                      ? "Loading matters..."
                      : "Select a matter"}
                  </option>
                  {portalMatterOptions.map((matter) => (
                    <option key={matter.id} value={matter.id}>
                      {[matter.matter_code, matter.title]
                        .filter(Boolean)
                        .join(" - ")}
                    </option>
                  ))}
                </select>
              </div>
              <div className="md:col-span-2">
                <fieldset className="grid gap-2 rounded-md border border-[var(--color-line)] px-3 py-2 text-sm sm:grid-cols-3">
                  <legend className="px-1 text-xs font-medium text-[var(--color-mute)]">
                    Grant options
                  </legend>
                  <label className="inline-flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={portalCanReply}
                      onChange={(e) => setPortalCanReply(e.target.checked)}
                      data-testid="portal-invite-can-reply"
                    />
                    Can reply
                  </label>
                  <label className="inline-flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={portalCanUpload}
                      disabled={portalRole !== "outside_counsel"}
                      onChange={(e) => setPortalCanUpload(e.target.checked)}
                      data-testid="portal-invite-can-upload"
                    />
                    Can upload
                  </label>
                  <label className="inline-flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={portalCanInvoice}
                      disabled={portalRole !== "outside_counsel"}
                      onChange={(e) => setPortalCanInvoice(e.target.checked)}
                      data-testid="portal-invite-can-invoice"
                    />
                    Can invoice
                  </label>
                </fieldset>
              </div>
              <div className="md:col-span-2">
                <Button
                  type="submit"
                  disabled={!portalInviteReady}
                  data-testid="portal-invite-submit"
                >
                  <MailPlus className="h-4 w-4" aria-hidden />
                  {portalInviteMutation.isPending ? "Sending..." : "Send portal invite"}
                </Button>
              </div>
            </form>
          )}
        </CardContent>
      </Card>

      <TenantAIPolicyCard />

      {canAdmin ? null : (
        <Card>
          <CardHeader>
            <CardTitle as="h2">Read-only</CardTitle>
            <CardDescription>
              You are viewing the Admin page as a member. Management
              actions stay hidden unless your role is owner or admin.
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      <RoadmapStub
        icon={Wrench}
        eyebrow="Coming soon"
        title="More admin controls on the way"
        description="Ethical walls UI, enterprise identity readiness, tenant AI policy, and plan management continue behind explicit status gates."
        prdSection="§10.9"
        bullets={[
          "Ethical walls are wired on the API today and will surface here next.",
          "OIDC / SAML with JIT provisioning and role mapping is planned until IdP UAT evidence exists.",
          "Tenant AI policy — allowed models, prompt audit, external-share approvals.",
          "Plan entitlements — seat limits, matter limits, feature flags.",
        ]}
      />
    </div>
  );
}
