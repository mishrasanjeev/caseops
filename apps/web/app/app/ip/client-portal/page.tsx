"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileCheck2, MailPlus, RefreshCw, ShieldX } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import { fetchIpDockets, fetchIpDocuments } from "@/lib/api/endpoints";
import {
  acknowledgePortalInstruction,
  fetchAdminPortalIpGrants,
  fetchFirmPortalInstructions,
  invitePortalUser,
  publishIpDocumentToPortal,
  revokePortalIpGrant,
} from "@/lib/api/portal";
import { useCapability } from "@/lib/capabilities";

const SELECT = "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm";

export default function IpClientPortalPage() {
  const queryClient = useQueryClient();
  const canManage = useCapability("portal:manage_grants");
  const canInvite = useCapability("portal:invite");
  const canApprove = useCapability("ip:approve");
  const canWrite = useCapability("ip:write");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [docketId, setDocketId] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [categories, setCategories] = useState("evidence, correspondence, registry_extract");
  const [documentChoice, setDocumentChoice] = useState("");
  const [documentGrantId, setDocumentGrantId] = useState("");
  const [documentTitle, setDocumentTitle] = useState("");
  const [scheduledFor, setScheduledFor] = useState("");
  const [reasonById, setReasonById] = useState<Record<string, string>>({});

  const dockets = useQuery({ queryKey: ["ip", "dockets"], queryFn: fetchIpDockets, enabled: canInvite });
  const grants = useQuery({ queryKey: ["ip", "portal", "grants"], queryFn: fetchAdminPortalIpGrants, enabled: canManage });
  const documents = useQuery({ queryKey: ["ip", "documents"], queryFn: fetchIpDocuments, enabled: canApprove });
  const instructions = useQuery({ queryKey: ["ip", "portal", "instructions"], queryFn: fetchFirmPortalInstructions, enabled: canWrite });
  const activeGrants = grants.data?.grants.filter((grant) => grant.active) ?? [];
  const shareableDocuments = useMemo(
    () => (documents.data?.items ?? []).flatMap((document) =>
      document.confidentiality === "internal" && !document.is_privileged
        ? document.versions
            .filter((version) => ["approved", "filed", "served", "accepted"].includes(version.state))
            .map((version) => ({ document, version }))
        : [],
    ),
    [documents.data],
  );

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["ip", "portal"] }),
      queryClient.invalidateQueries({ queryKey: ["ip", "documents"] }),
    ]);
  };
  const invite = useMutation({
    mutationFn: () => invitePortalUser({
      email: email.trim().toLowerCase(), fullName: name.trim(), role: "client",
      ipDocketIds: [docketId], eventKinds: ["registry_snapshot_accepted", "client_instruction"],
      deadlineKinds: ["opposition_evidence", "renewal"],
      documentCategories: categories.split(",").map((value) => value.trim()).filter(Boolean),
      canSubmitInstructions: true,
      expiresAt: expiresAt ? new Date(expiresAt).toISOString() : null,
    }),
    onSuccess: async () => { setName(""); setEmail(""); setDocketId(""); setExpiresAt(""); toast.success("IP portal access granted."); await refresh(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not grant portal access.")),
  });
  const revoke = useMutation({
    mutationFn: (grantId: string) => {
      const grant = activeGrants.find((row) => row.id === grantId);
      if (!grant) throw new Error("Refresh the grant before revoking it.");
      return revokePortalIpGrant({ grantId, rowVersion: grant.row_version, reason: reasonById[grantId] ?? "Client access removed by the firm." });
    },
    onSuccess: async () => { toast.success("Grant revoked and active portal sessions invalidated."); await refresh(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not revoke the grant.")),
  });
  const publishDocument = useMutation({
    mutationFn: () => {
      const [documentId, versionText] = documentChoice.split(":");
      const grant = activeGrants.find((row) => row.id === documentGrantId);
      if (!grant || !documentId || !versionText) throw new Error("Choose an approved document and client grant.");
      return publishIpDocumentToPortal({ portalUserId: grant.portal_user_id, grantId: grant.id, documentId, versionNumber: Number(versionText), title: documentTitle.trim(), scheduledFor: scheduledFor ? new Date(scheduledFor).toISOString() : null });
    },
    onSuccess: () => { setDocumentChoice(""); setDocumentTitle(""); setScheduledFor(""); toast.success("Approved document published to the client portal."); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not publish the document.")),
  });
  const acknowledge = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "accepted" | "rejected" | "clarification_required" }) => {
      const instruction = instructions.data?.instructions.find((row) => row.id === id);
      if (!instruction) throw new Error("Refresh the instruction before acknowledging it.");
      return acknowledgePortalInstruction({ instructionId: id, rowVersion: instruction.row_version, status, reason: reasonById[id] ?? "Reviewed by the IP team." });
    },
    onSuccess: async () => { toast.success("Client instruction acknowledged."); await refresh(); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not acknowledge the instruction.")),
  });

  if (!canManage && !canWrite) return <EmptyState title="Portal management access required" description="Ask an owner or admin for portal grant access." />;
  return <div className="flex min-w-0 flex-col gap-6">
    <PageHeader eyebrow="IP operations" title="Client portal" description="Control explicit client grants, approved publications, delivery, and acknowledged instructions." actions={<Button variant="outline" size="sm" onClick={refresh}><RefreshCw className="h-4 w-4" />Refresh</Button>} />

    {canInvite ? <Card><CardHeader><CardTitle as="h2">Grant IP access</CardTitle><CardDescription>Only the selected docket, event/date categories, and approved document categories become visible.</CardDescription></CardHeader><CardContent><form className="grid gap-4 md:grid-cols-2 xl:grid-cols-4" onSubmit={(event) => { event.preventDefault(); invite.mutate(); }}>
      <Field label="Client name" htmlFor="ip-client-name"><Input id="ip-client-name" value={name} onChange={(event) => setName(event.target.value)} /></Field>
      <Field label="Work email" htmlFor="ip-client-email"><Input id="ip-client-email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></Field>
      <Field label="IP docket" htmlFor="ip-client-docket"><select id="ip-client-docket" className={SELECT} value={docketId} onChange={(event) => setDocketId(event.target.value)}><option value="">Select a docket</option>{dockets.data?.dockets.map((docket) => <option key={docket.id} value={docket.id}>{docket.title}</option>)}</select></Field>
      <Field label="Access expires" htmlFor="ip-client-expiry"><Input id="ip-client-expiry" type="datetime-local" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} /></Field>
      <div className="md:col-span-2 xl:col-span-3"><Field label="Approved document categories" htmlFor="ip-client-categories"><Input id="ip-client-categories" value={categories} onChange={(event) => setCategories(event.target.value)} /></Field></div>
      <div className="flex items-end"><Button className="w-full" type="submit" disabled={invite.isPending || !name.trim() || !email.includes("@") || !docketId}><MailPlus className="h-4 w-4" />Grant access</Button></div>
    </form></CardContent></Card> : null}

    <Card><CardHeader><CardTitle as="h2">Active and historical grants</CardTitle></CardHeader><CardContent>{grants.isError ? <QueryErrorState error={grants.error} title="Could not load grants" onRetry={() => grants.refetch()} /> : !grants.data?.grants.length ? <EmptyState title="No IP portal grants" /> : <div className="space-y-3">{grants.data.grants.map((grant) => <div key={grant.id} className="grid min-w-0 gap-3 border-b border-[var(--color-line)] pb-3 lg:grid-cols-[1fr_1fr_auto]"><div className="min-w-0"><p className="truncate text-sm font-semibold">{grant.portal_user_name} · {grant.docket_title}</p><p className="truncate text-xs text-[var(--color-mute)]">{grant.portal_user_email}{grant.expires_at ? ` · expires ${new Date(grant.expires_at).toLocaleString("en-IN")}` : " · no expiry"}</p></div><Input aria-label={`Revocation reason for ${grant.portal_user_name}`} value={reasonById[grant.id] ?? ""} onChange={(event) => setReasonById((current) => ({ ...current, [grant.id]: event.target.value }))} placeholder="Reason for revocation" disabled={!grant.active} /><div className="flex items-center gap-2"><Badge tone={grant.active ? "success" : "neutral"}>{grant.active ? "Active" : "Revoked"}</Badge>{grant.active ? <Button variant="outline" size="sm" onClick={() => revoke.mutate(grant.id)}><ShieldX className="h-4 w-4" />Revoke</Button> : null}</div></div>)}</div>}</CardContent></Card>

    {canApprove ? <Card><CardHeader><CardTitle as="h2">Publish approved document</CardTitle><CardDescription>Privileged, confidential, restricted, draft, and ungranted categories are excluded by the API.</CardDescription></CardHeader><CardContent><form className="grid gap-4 md:grid-cols-2 xl:grid-cols-4" onSubmit={(event) => { event.preventDefault(); publishDocument.mutate(); }}>
      <Field label="Client grant" htmlFor="publication-grant"><select id="publication-grant" className={SELECT} value={documentGrantId} onChange={(event) => setDocumentGrantId(event.target.value)}><option value="">Select a client and docket</option>{activeGrants.map((grant) => <option key={grant.id} value={grant.id}>{grant.portal_user_name} · {grant.docket_title}</option>)}</select></Field>
      <Field label="Approved version" htmlFor="publication-document"><select id="publication-document" className={SELECT} value={documentChoice} onChange={(event) => setDocumentChoice(event.target.value)}><option value="">Select approved document</option>{shareableDocuments.map(({ document, version }) => <option key={version.id} value={`${document.id}:${version.version}`}>{document.title} · v{version.version} · {document.taxonomy_label}</option>)}</select></Field>
      <Field label="Client title" htmlFor="publication-title"><Input id="publication-title" value={documentTitle} onChange={(event) => setDocumentTitle(event.target.value)} /></Field>
      <Field label="Publish at" htmlFor="publication-schedule"><Input id="publication-schedule" type="datetime-local" value={scheduledFor} onChange={(event) => setScheduledFor(event.target.value)} /></Field>
      <div className="md:col-span-2 xl:col-span-4"><Button type="submit" disabled={publishDocument.isPending || !documentGrantId || !documentChoice || documentTitle.trim().length < 2}><FileCheck2 className="h-4 w-4" />Publish approved version</Button></div>
    </form></CardContent></Card> : null}

    {canWrite ? <Card><CardHeader><CardTitle as="h2">Client instructions</CardTitle><CardDescription>Instructions stay pending until the firm acknowledges them; they never change legal state by themselves.</CardDescription></CardHeader><CardContent>{!instructions.data?.instructions.length ? <EmptyState title="No client instructions" /> : <div className="space-y-4">{instructions.data.instructions.map((instruction) => <div key={instruction.id} className="grid gap-3 border-b border-[var(--color-line)] pb-4 lg:grid-cols-[1fr_1fr_auto]"><div><p className="text-sm font-semibold">{instruction.docket_title} · {instruction.decision.replaceAll("_", " ")}</p><p className="text-sm text-[var(--color-ink-2)]">{instruction.note}</p><Badge tone={instruction.status === "pending" ? "warning" : "neutral"}>{instruction.status.replaceAll("_", " ")}</Badge></div><Textarea aria-label={`Acknowledgement reason for ${instruction.docket_title}`} value={reasonById[instruction.id] ?? ""} onChange={(event) => setReasonById((current) => ({ ...current, [instruction.id]: event.target.value }))} disabled={instruction.status !== "pending"} />{instruction.status === "pending" ? <div className="flex flex-wrap items-start gap-2"><Button size="sm" onClick={() => acknowledge.mutate({ id: instruction.id, status: "accepted" })}>Accept</Button><Button size="sm" variant="outline" onClick={() => acknowledge.mutate({ id: instruction.id, status: "clarification_required" })}>Clarify</Button><Button size="sm" variant="outline" onClick={() => acknowledge.mutate({ id: instruction.id, status: "rejected" })}>Reject</Button></div> : null}</div>)}</div>}</CardContent></Card> : null}
  </div>;
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) {
  return <div className="min-w-0 space-y-1.5"><Label htmlFor={htmlFor}>{label}</Label>{children}</div>;
}
