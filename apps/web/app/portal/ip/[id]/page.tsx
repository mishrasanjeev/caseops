"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CalendarDays, Download, Send } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Textarea } from "@/components/ui/Textarea";
import { API_BASE_URL, apiErrorMessage } from "@/lib/api/config";
import {
  fetchPortalIpRecord,
  fetchPortalPublications,
  submitPortalInstruction,
} from "@/lib/api/portal";

const SELECT = "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm";

export default function PortalIpRecordPage() {
  const params = useParams<{ id: string }>();
  const docketId = String(params.id);
  const queryClient = useQueryClient();
  const [publicationId, setPublicationId] = useState("");
  const [instructionKind, setInstructionKind] = useState<"renewal" | "proceeding" | "filing" | "watch" | "general">("general");
  const [decision, setDecision] = useState<"renew" | "do_not_renew" | "proceed" | "do_not_proceed" | "defer" | "clarification_required">("proceed");
  const [note, setNote] = useState("");
  const record = useQuery({ queryKey: ["portal", "ip-records", docketId], queryFn: () => fetchPortalIpRecord(docketId) });
  const publications = useQuery({ queryKey: ["portal", "publications"], queryFn: fetchPortalPublications });
  const scopedPublications = useMemo(() => (publications.data?.publications ?? []).filter((publication) => publication.targets.some((target) => target.ip_docket_record_id === docketId)), [docketId, publications.data]);
  const instruction = useMutation({
    mutationFn: () => submitPortalInstruction({ publicationId, decision, instructionKind, docketId, note }),
    onSuccess: async () => { setNote(""); toast.success("Instruction sent to your firm for acknowledgement."); await queryClient.invalidateQueries({ queryKey: ["portal", "publications"] }); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not send the instruction.")),
  });

  if (record.isError) return <main className="mx-auto min-h-screen max-w-5xl px-6 py-10"><QueryErrorState error={record.error} title="IP record is unavailable" onRetry={() => record.refetch()} /></main>;
  const item = record.data;
  return <main className="mx-auto flex min-h-screen max-w-5xl min-w-0 flex-col gap-6 px-6 py-10">
    <PageHeader eyebrow="Client IP record" title={item?.title ?? "Loading IP record"} description={item ? [item.primary_identifier ?? item.identifiers[0], item.status].filter(Boolean).join(" · ") : ""} actions={<Link href="/portal"><Button variant="outline" size="sm"><ArrowLeft className="h-4 w-4" />Portal</Button></Link>} />
    {item ? <>
      <Card><CardHeader><CardTitle as="h2">Registry identifiers and status</CardTitle></CardHeader><CardContent className="space-y-3"><div className="flex flex-wrap gap-2">{item.status ? <Badge tone="brand">{item.status}</Badge> : null}{item.identifiers.map((identifier) => <Badge key={identifier}>{identifier}</Badge>)}</div>{item.grant_expires_at ? <p className="text-xs text-[var(--color-mute)]">Access expires {new Date(item.grant_expires_at).toLocaleString("en-IN")}</p> : null}</CardContent></Card>
      <div className="grid gap-6 lg:grid-cols-2"><Card><CardHeader><CardTitle as="h2">Shared events</CardTitle></CardHeader><CardContent>{!item.events.length ? <EmptyState title="No shared events" /> : <ol className="space-y-3">{item.events.map((event) => <li key={event.id} className="border-b border-[var(--color-line)] pb-2"><p className="text-sm font-semibold">{event.event_kind.replaceAll("_", " ")}</p><p className="text-xs text-[var(--color-mute)]">{new Date(event.effective_at).toLocaleString("en-IN")} · {event.source}</p></li>)}</ol>}</CardContent></Card><Card><CardHeader><CardTitle as="h2">Shared dates</CardTitle></CardHeader><CardContent>{!item.upcoming_dates.length ? <EmptyState icon={CalendarDays} title="No shared dates" /> : <ol className="space-y-3">{item.upcoming_dates.map((date) => <li key={date.id} className="border-b border-[var(--color-line)] pb-2"><p className="text-sm font-semibold">{date.title}</p><p className="text-xs text-[var(--color-mute)]">{date.due_on ?? date.due_at ?? "Date under review"} · {date.certainty}</p></li>)}</ol>}</CardContent></Card></div>
      <Card><CardHeader><CardTitle as="h2">Approved publications</CardTitle></CardHeader><CardContent>{!scopedPublications.length ? <EmptyState title="No approved publications" /> : <div className="space-y-5">{scopedPublications.map((publication) => <section key={publication.id} className="border-b border-[var(--color-line)] pb-4"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold">{publication.title}</h3><Badge tone={publication.access_state === "available" ? "success" : "warning"}>{publication.access_state.replaceAll("_", " ")}</Badge></div>{publication.summary ? <dl className="mt-3 grid gap-2 sm:grid-cols-3">{Object.entries(publication.summary).map(([key, value]) => <div key={key}><dt className="text-xs text-[var(--color-mute)]">{key.replaceAll("_", " ")}</dt><dd className="text-sm font-medium">{String(value)}</dd></div>)}</dl> : null}{publication.rows ? <div className="mt-3 max-h-64 overflow-auto rounded-md border border-[var(--color-line)]"><pre className="whitespace-pre-wrap p-3 text-xs">{JSON.stringify(publication.rows, null, 2)}</pre></div> : null}{publication.document_filename && publication.access_state === "available" ? <a className="mt-3 inline-flex items-center gap-2 text-sm font-semibold text-[var(--color-brand-700)]" href={`${API_BASE_URL}/api/portal/publications/${publication.id}/document`}><Download className="h-4 w-4" />{publication.document_filename}</a> : null}</section>)}</div>}</CardContent></Card>
      <Card><CardHeader><CardTitle as="h2">Send instruction</CardTitle></CardHeader><CardContent><form className="grid gap-4 md:grid-cols-3" onSubmit={(event) => { event.preventDefault(); instruction.mutate(); }}><div className="space-y-1.5"><Label htmlFor="instruction-publication">Approved publication</Label><select id="instruction-publication" className={SELECT} value={publicationId} onChange={(event) => setPublicationId(event.target.value)}><option value="">Select publication</option>{scopedPublications.filter((publication) => publication.access_state === "available").map((publication) => <option key={publication.id} value={publication.id}>{publication.title}</option>)}</select></div><div className="space-y-1.5"><Label htmlFor="instruction-kind">Instruction type</Label><select id="instruction-kind" className={SELECT} value={instructionKind} onChange={(event) => { const nextKind = event.target.value as typeof instructionKind; setInstructionKind(nextKind); setDecision(nextKind === "renewal" ? "renew" : "proceed"); }}><option value="general">General</option><option value="proceeding">Proceeding</option><option value="filing">Filing</option><option value="renewal">Renewal</option><option value="watch">Watch</option></select></div><div className="space-y-1.5"><Label htmlFor="instruction-decision">Decision</Label><select id="instruction-decision" className={SELECT} value={decision} onChange={(event) => setDecision(event.target.value as typeof decision)}>{instructionKind === "renewal" ? <><option value="renew">Renew</option><option value="do_not_renew">Do not renew</option></> : <><option value="proceed">Proceed</option><option value="do_not_proceed">Do not proceed</option><option value="defer">Defer</option><option value="clarification_required">Request clarification</option></>}</select></div><div className="space-y-1.5 md:col-span-3"><Label htmlFor="instruction-note">Instruction details</Label><Textarea id="instruction-note" value={note} onChange={(event) => setNote(event.target.value)} /></div><div className="md:col-span-3"><Button type="submit" disabled={instruction.isPending || !publicationId || note.trim().length < 2}><Send className="h-4 w-4" />Send for firm acknowledgement</Button></div></form></CardContent></Card>
    </> : null}
  </main>;
}
