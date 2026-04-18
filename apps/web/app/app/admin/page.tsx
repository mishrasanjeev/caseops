"use client";

import { Download, Shield, Wrench } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { RoadmapStub } from "@/components/app/RoadmapStub";
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
import { API_BASE_URL } from "@/lib/api/config";
import { getStoredToken } from "@/lib/session";
import { useCapability } from "@/lib/capabilities";

function toIsoOrNull(local: string): string | null {
  if (!local) return null;
  // <input type="date"> gives YYYY-MM-DD; expand to the start of that UTC day.
  return `${local}T00:00:00Z`;
}

export default function AdminPage() {
  const canAdmin = useCapability("workspace:admin");
  const canAudit = useCapability("audit:export");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [action, setAction] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleDownload() {
    const token = getStoredToken();
    if (!token) {
      toast.error("Your session expired. Sign in again.");
      return;
    }
    setBusy(true);
    try {
      const params = new URLSearchParams();
      const sinceIso = toIsoOrNull(since);
      const untilIso = toIsoOrNull(until);
      if (sinceIso) params.set("since", sinceIso);
      if (untilIso) params.set("until", untilIso);
      if (action.trim()) params.set("action", action.trim());
      const url =
        `${API_BASE_URL}/api/admin/audit/export` +
        (params.toString() ? `?${params.toString()}` : "");
      const resp = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
      });
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
          ?.match(/filename="([^"]+)"/)?.[1] ?? "audit-export.jsonl";
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
      />

      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div>
            <CardTitle as="h2">Audit trail export</CardTitle>
            <CardDescription>
              Streams every recorded action on this tenant as JSONL —
              matter creation, draft state transitions, hearing-pack
              review, access denials, and the export itself. Defaults to
              the last 30 days. Admin or owner only.
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
              <div className="flex flex-col gap-1.5 md:col-span-2">
                <Label htmlFor="audit-action">Action filter (optional)</Label>
                <Input
                  id="audit-action"
                  placeholder="e.g. draft.approve"
                  value={action}
                  onChange={(e) => setAction(e.target.value)}
                />
              </div>
              <div className="md:col-span-4">
                <Button
                  type="submit"
                  disabled={busy}
                  data-testid="download-audit-export"
                >
                  <Download className="h-4 w-4" aria-hidden />
                  {busy ? "Downloading…" : "Download audit trail (JSONL)"}
                </Button>
              </div>
            </form>
          )}
        </CardContent>
      </Card>

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
        description="User directory + ethical walls UI, SSO, tenant AI policy, and plan management — per the post-Sprint-H roadmap."
        prdSection="§10.9"
        workDocSection="§10.1 admin · §10.2 SSO · §10.3 AI policy · §10.5 plan entitlements"
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
