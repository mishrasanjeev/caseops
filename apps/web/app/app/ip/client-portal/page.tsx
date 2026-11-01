"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileCheck2, MailPlus, RefreshCw, ShieldX } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { toast } from "sonner";

import { IpDocketPicker } from "@/components/ip/IpDocketPicker";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { RecordSelect } from "@/components/ui/RecordSelect";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import { fetchIpDocumentTaxonomy } from "@/lib/api/endpoints";
import {
  acknowledgePortalInstruction,
  fetchAdminPortalIpGrants,
  fetchFirmPortalInstructions,
  fetchPortalGrantShareableDocuments,
  invitePortalUser,
  publishIpDocumentToPortal,
  revokePortalIpGrant,
} from "@/lib/api/portal";
import { useCapability } from "@/lib/capabilities";

const SELECT = "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm disabled:cursor-not-allowed disabled:opacity-60";
const DEFAULT_CATEGORIES = ["evidence", "correspondence", "registry_extract"];
const LINK = "font-semibold text-[var(--color-brand-700)]";

type GrantRow = Awaited<ReturnType<typeof fetchAdminPortalIpGrants>>["grants"][number];

/** The grant's state as publishing sees it; the API computes publishable with the publish rule. */
function grantStatus(grant: GrantRow): { label: string; tone: "success" | "warning" | "neutral" } {
  if (grant.publishable) return { label: "Active", tone: "success" };
  switch (grant.publication_blocked_reason) {
    case "revoked": return { label: "Revoked", tone: "neutral" };
    case "expired": return { label: "Expired", tone: "neutral" };
    case "docket_closed": return { label: "Docket closed", tone: "warning" };
    case "client_inactive": return { label: "Client deactivated", tone: "warning" };
    case "docket_not_visible": return { label: "Docket restricted for you", tone: "warning" };
    default: return grant.active ? { label: "Active", tone: "success" } : { label: "Revoked", tone: "neutral" };
  }
}

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
  const [categories, setCategories] = useState<string[] | null>(null);
  const [documentChoice, setDocumentChoice] = useState("");
  const [documentGrantId, setDocumentGrantId] = useState("");
  const [documentTitle, setDocumentTitle] = useState("");
  const [scheduledFor, setScheduledFor] = useState("");
  const [reasonById, setReasonById] = useState<Record<string, string>>({});
  const [shareNoDocuments, setShareNoDocuments] = useState(false);

  const grants = useQuery({ queryKey: ["ip", "portal", "grants"], queryFn: fetchAdminPortalIpGrants, enabled: canManage });
  const taxonomy = useQuery({ queryKey: ["ip", "document-taxonomy"], queryFn: fetchIpDocumentTaxonomy, enabled: canInvite });
  const shareable = useQuery({
    queryKey: ["ip", "portal", "shareable-documents", documentGrantId],
    queryFn: () => fetchPortalGrantShareableDocuments(documentGrantId),
    enabled: canApprove && Boolean(documentGrantId),
  });
  const instructions = useQuery({ queryKey: ["ip", "portal", "instructions"], queryFn: fetchFirmPortalInstructions, enabled: canWrite });
  const activeGrants = grants.data?.grants.filter((grant) => grant.active) ?? [];
  // Publishing accepts only these: the grant is live, the client is active, the
  // docket is open and visible to you. Anything else is shown with its reason.
  const publishableGrants = grants.data?.grants.filter((grant) => grant.publishable) ?? [];
  const blockedActiveGrants = activeGrants.length - activeGrants.filter((grant) => grant.publishable).length;
  const categoryEntries = (taxonomy.data?.entries ?? []).filter((entry) => entry.is_active);
  // Until the person changes them, grant the usual client-facing categories that exist here.
  const chosenCategories = categories ?? categoryEntries.map((entry) => entry.key).filter((key) => DEFAULT_CATEGORIES.includes(key));
  useEffect(() => { setDocumentChoice(""); }, [documentGrantId]);

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["ip", "portal"] }),
      queryClient.invalidateQueries({ queryKey: ["ip", "dockets"] }),
    ]);
  };
  const invite = useMutation({
    mutationFn: () => invitePortalUser({
      email: email.trim().toLowerCase(), fullName: name.trim(), role: "client",
      ipDocketIds: [docketId], eventKinds: ["registry_snapshot_accepted", "client_instruction"],
      deadlineKinds: ["opposition_evidence", "renewal"],
      documentCategories: chosenCategories,
      canSubmitInstructions: true,
      expiresAt: expiresAt ? new Date(expiresAt).toISOString() : null,
    }),
    onSuccess: async () => { setName(""); setEmail(""); setDocketId(""); setExpiresAt(""); setShareNoDocuments(false); toast.success("IP portal access granted."); await refresh(); },
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
      const grant = publishableGrants.find((row) => row.id === documentGrantId);
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

  const selectedGrant = publishableGrants.find((grant) => grant.id === documentGrantId);
  const shareableDocuments = shareable.data?.documents ?? [];
  let versionPlaceholder = "Select approved version";
  let versionHint: ReactNode = null;
  if (!documentGrantId) {
    versionPlaceholder = "Choose a client grant first";
  } else if (shareable.isPending) {
    versionPlaceholder = "Loading approved versions…";
  } else if (shareable.isError) {
    versionPlaceholder = "Approved versions could not be loaded";
    versionHint = <span role="alert" className="flex flex-wrap items-center gap-2 text-[var(--color-danger-500)]">{apiErrorMessage(shareable.error, "Approved versions could not be loaded.")}<Button type="button" size="sm" variant="outline" onClick={() => shareable.refetch()}>Retry</Button></span>;
  } else if (!shareableDocuments.length) {
    const granted = shareable.data?.document_categories ?? [];
    versionPlaceholder = "No shareable version on this docket";
    versionHint = <>No approved, non-privileged document version on {shareable.data?.docket_title ?? "this docket"} is in a category this grant shares ({granted.length ? granted.join(", ") : "none granted"}). <Link className={LINK} href={`/app/ip?docket=${encodeURIComponent(selectedGrant?.ip_docket_record_id ?? "")}&tab=documents`}>Approve a version in the IP workspace Documents tab</Link>, or grant its category to this client.</>;
  }

  let grantPlaceholder = "Select a client and docket";
  let grantHint: ReactNode = null;
  if (!canManage) {
    grantPlaceholder = "Grant management access required";
    grantHint = "Publishing needs portal grant management access. Ask an owner or admin.";
  } else if (grants.isPending) {
    grantPlaceholder = "Loading grants…";
  } else if (grants.isError) {
    grantPlaceholder = "Grants could not be loaded";
    grantHint = <span role="alert" className="flex flex-wrap items-center gap-2 text-[var(--color-danger-500)]">{apiErrorMessage(grants.error, "Client grants could not be loaded.")}<Button type="button" size="sm" variant="outline" onClick={() => grants.refetch()}>Retry</Button></span>;
  } else if (!publishableGrants.length) {
    grantPlaceholder = "No client grant can receive documents";
    const reason = blockedActiveGrants
      ? `${blockedActiveGrants === 1 ? "The only active grant is" : `All ${blockedActiveGrants} active grants are`} on a closed or restricted docket or for a deactivated client (see the grant list).`
      : "No client has active access.";
    grantHint = `${reason} ${canInvite ? "Grant a client access to an open docket above, then publish to that grant." : "Ask an owner or admin to grant portal access."}`;
  }

  if (!canManage && !canWrite) return <EmptyState title="Portal management access required" description="Ask an owner or admin for portal grant access." />;
  return <div className="flex min-w-0 flex-col gap-6">
    <PageHeader eyebrow="IP operations" title="Client portal" description="Control explicit client grants, approved publications, delivery, and acknowledged instructions." actions={<Button variant="outline" size="sm" onClick={refresh}><RefreshCw className="h-4 w-4" />Refresh</Button>} />

    {canInvite ? <Card><CardHeader><CardTitle as="h2">Grant IP access</CardTitle><CardDescription>Only the selected docket, event/date categories, and approved document categories become visible.</CardDescription></CardHeader><CardContent><form className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-4" onSubmit={(event) => { event.preventDefault(); invite.mutate(); }}>
      <Field label="Client name" htmlFor="ip-client-name"><Input id="ip-client-name" value={name} onChange={(event) => setName(event.target.value)} /></Field>
      <Field label="Work email" htmlFor="ip-client-email"><Input id="ip-client-email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></Field>
      <IpDocketPicker id="ip-client-docket" className="md:col-span-2" label="IP docket" searchLabel="Find the client's docket" value={docketId} onChange={(id) => setDocketId(id)} required />
      <Field label="Access expires" htmlFor="ip-client-expiry"><Input id="ip-client-expiry" type="datetime-local" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} /></Field>
      <fieldset className="min-w-0 space-y-2 md:col-span-2 xl:col-span-3">
        <legend className="text-sm font-medium">Approved document categories</legend>
        {taxonomy.isPending ? <p role="status" className="text-sm text-[var(--color-mute)]">Loading document categories…</p>
          : taxonomy.isError ? <p role="alert" className="flex flex-wrap items-center gap-2 text-sm text-[var(--color-danger-500)]">{apiErrorMessage(taxonomy.error, "Document categories could not be loaded.")}<Button type="button" size="sm" variant="outline" onClick={() => taxonomy.refetch()}>Retry</Button></p>
          : !categoryEntries.length ? <p className="text-sm text-[var(--color-mute)]">No IP document categories are set up for this workspace, so the client will see no documents. An IP administrator can load the standard categories in the <Link className={LINK} href="/app/ip">IP workspace Documents tab</Link>.</p>
          : <div className="flex min-w-0 flex-wrap gap-x-4 gap-y-2">{categoryEntries.map((entry) => <label key={entry.key} className="flex min-w-0 items-center gap-2 text-sm"><input type="checkbox" checked={chosenCategories.includes(entry.key)} onChange={(event) => setCategories(event.target.checked ? [...chosenCategories, entry.key] : chosenCategories.filter((key) => key !== entry.key))} /><span className="break-words">{entry.label}</span></label>)}</div>}
      </fieldset>
      {!taxonomy.isPending && !chosenCategories.length ? <label className="flex min-w-0 items-start gap-2 text-sm md:col-span-2 xl:col-span-4"><input type="checkbox" className="mt-1" checked={shareNoDocuments} onChange={(event) => setShareNoDocuments(event.target.checked)} /><span className="min-w-0 break-words">No document category is chosen, so this client will see no documents on the docket. Confirm to grant access to dates and events only.</span></label> : null}
      <div className="flex items-end"><Button className="w-full" type="submit" disabled={invite.isPending || !name.trim() || !email.includes("@") || !docketId || (!chosenCategories.length && !shareNoDocuments) || taxonomy.isPending}><MailPlus className="h-4 w-4" />Grant access</Button></div>
    </form></CardContent></Card> : null}

    <Card><CardHeader><CardTitle as="h2">Active and historical grants</CardTitle></CardHeader><CardContent>{grants.isError ? <QueryErrorState error={grants.error} title="Could not load grants" onRetry={() => grants.refetch()} /> : grants.isPending && canManage ? <p role="status" className="text-sm text-[var(--color-mute)]">Loading grants…</p> : !grants.data?.grants.length ? <EmptyState title="No IP portal grants" description={canInvite ? "Grant a client access to one docket above." : undefined} /> : <div className="space-y-3">{grants.data.grants.map((grant) => <div key={grant.id} className="grid min-w-0 gap-3 border-b border-[var(--color-line)] pb-3 lg:grid-cols-[1fr_1fr_auto]"><div className="min-w-0"><p className="break-words text-sm font-semibold">{grant.portal_user_name} · {grant.docket_title}</p><p className="break-words text-xs text-[var(--color-mute)]">{grant.portal_user_email}{grant.expires_at ? ` · expires ${new Date(grant.expires_at).toLocaleString("en-IN")}` : " · no expiry"}</p></div><Input aria-label={`Revocation reason for ${grant.portal_user_name}`} value={reasonById[grant.id] ?? ""} onChange={(event) => setReasonById((current) => ({ ...current, [grant.id]: event.target.value }))} placeholder="Reason for revocation" disabled={!grant.active} /><div className="flex items-center gap-2"><Badge tone={grantStatus(grant).tone}>{grantStatus(grant).label}</Badge>{grant.active ? <Button variant="outline" size="sm" onClick={() => revoke.mutate(grant.id)}><ShieldX className="h-4 w-4" />Revoke</Button> : null}</div></div>)}</div>}</CardContent></Card>

    {canApprove ? <Card><CardHeader><CardTitle as="h2">Publish approved document</CardTitle><CardDescription>Only versions this client&apos;s grant may receive are listed: approved, non-privileged, on the granted docket and in a granted category.</CardDescription></CardHeader><CardContent><form className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-4" onSubmit={(event) => { event.preventDefault(); publishDocument.mutate(); }}>
      <div className="min-w-0 space-y-1.5">
        <RecordSelect id="publication-grant" label="Client grant" className={SELECT} value={documentGrantId} onChange={(event) => setDocumentGrantId(event.target.value)} disabled={!publishableGrants.length} aria-describedby={grantHint ? "publication-grant-empty" : undefined}
          options={[{ value: "", label: grantPlaceholder }, ...publishableGrants.map((grant) => ({ value: grant.id, label: `${grant.portal_user_name} · ${grant.docket_title}` }))]} />
        {grantHint ? <p id="publication-grant-empty" className="min-w-0 break-words text-sm text-[var(--color-mute)]">{grantHint}</p> : null}
      </div>
      <div className="min-w-0 space-y-1.5">
        <RecordSelect id="publication-document" label="Approved version" className={SELECT} value={documentChoice} onChange={(event) => setDocumentChoice(event.target.value)} disabled={!shareableDocuments.length} aria-describedby={versionHint ? "publication-document-hint" : undefined}
          options={[{ value: "", label: versionPlaceholder }, ...shareableDocuments.map((row) => ({ value: `${row.document_id}:${row.version_number}`, label: `${row.document_title} · v${row.version_number} · ${row.taxonomy_label}` }))]} />
        {versionHint ? <p id="publication-document-hint" className="min-w-0 break-words text-sm text-[var(--color-mute)]">{versionHint}</p> : null}
      </div>
      <Field label="Client title" htmlFor="publication-title"><Input id="publication-title" value={documentTitle} onChange={(event) => setDocumentTitle(event.target.value)} /></Field>
      <Field label="Publish at" htmlFor="publication-schedule"><Input id="publication-schedule" type="datetime-local" value={scheduledFor} onChange={(event) => setScheduledFor(event.target.value)} /></Field>
      <div className="md:col-span-2 xl:col-span-4"><Button type="submit" disabled={publishDocument.isPending || !documentGrantId || !documentChoice || documentTitle.trim().length < 2}><FileCheck2 className="h-4 w-4" />Publish approved version</Button></div>
    </form></CardContent></Card> : null}

    {canWrite ? <Card><CardHeader><CardTitle as="h2">Client instructions</CardTitle><CardDescription>Instructions stay pending until the firm acknowledges them; they never change legal state by themselves.</CardDescription></CardHeader><CardContent>{instructions.isError ? <QueryErrorState error={instructions.error} title="Could not load client instructions" onRetry={() => instructions.refetch()} /> : instructions.isPending ? <p role="status" className="text-sm text-[var(--color-mute)]">Loading client instructions…</p> : !instructions.data.instructions.length ? <EmptyState title="No client instructions" /> : <div className="space-y-4">{instructions.data.instructions.map((instruction) => <div key={instruction.id} className="grid min-w-0 gap-3 border-b border-[var(--color-line)] pb-4 lg:grid-cols-[1fr_1fr_auto]"><div className="min-w-0"><p className="break-words text-sm font-semibold">{instruction.docket_title} · {instruction.decision.replaceAll("_", " ")}</p><p className="break-words text-sm text-[var(--color-ink-2)]">{instruction.note}</p><Badge tone={instruction.status === "pending" ? "warning" : "neutral"}>{instruction.status.replaceAll("_", " ")}</Badge></div><Textarea aria-label={`Acknowledgement reason for ${instruction.docket_title}`} value={reasonById[instruction.id] ?? ""} onChange={(event) => setReasonById((current) => ({ ...current, [instruction.id]: event.target.value }))} disabled={instruction.status !== "pending"} />{instruction.status === "pending" ? <div className="flex flex-wrap items-start gap-2"><Button size="sm" onClick={() => acknowledge.mutate({ id: instruction.id, status: "accepted" })}>Accept</Button><Button size="sm" variant="outline" onClick={() => acknowledge.mutate({ id: instruction.id, status: "clarification_required" })}>Clarify</Button><Button size="sm" variant="outline" onClick={() => acknowledge.mutate({ id: instruction.id, status: "rejected" })}>Reject</Button></div> : null}</div>)}</div>}</CardContent></Card> : null}
  </div>;
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: ReactNode }) {
  return <div className="min-w-0 space-y-1.5"><Label htmlFor={htmlFor}>{label}</Label>{children}</div>;
}
