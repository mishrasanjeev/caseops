"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, MailPlus, Shield, Users as UsersIcon, Wrench } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { RoadmapStub } from "@/components/app/RoadmapStub";
import { TenantAIPolicyCard } from "@/components/app/TenantAIPolicyCard";
import { Button } from "@/components/ui/Button";
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
import { listMatters } from "@/lib/api/endpoints";
import {
  invitePortalUser,
  type PortalUserRole,
} from "@/lib/api/portal";
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

export default function AdminPage() {
  const canAdmin = useCapability("workspace:admin");
  const canAudit = useCapability("audit:export");
  const canTeamsManage = useCapability("teams:manage");
  const canPortalInvite = useCapability("portal:invite");
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
      const resp = await fetch(url, {
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
        description="Audit trail export is live. Tenant profile, SSO, AI policy, and plan management follow in §10.1–§10.3."
        actions={
          <div className="flex items-center gap-2">
            <Link
              href="/app/admin/notifications"
              className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-line)] bg-white px-3 py-1.5 text-sm font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]"
            >
              Notifications
            </Link>
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
        description="User directory + ethical walls UI, SSO, tenant AI policy, and plan management are next."
        prdSection="§10.9"
        bullets={[
          "User directory with team-based scoping; ethical walls are wired on the API today and will surface here next.",
          "OIDC / SAML with JIT provisioning and role mapping.",
          "Tenant AI policy — allowed models, prompt audit, external-share approvals.",
          "Plan entitlements — seat limits, matter limits, feature flags.",
        ]}
      />
    </div>
  );
}
