"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowUpRight,
  Check,
  FileText,
  Globe2,
  Landmark,
  Link2,
  Plus,
  RefreshCw,
  Scale,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  createMadridRecord,
  fetchIpCoreRecords,
  fetchIpDockets,
  fetchMadridRecords,
  fetchMadridWorkspace,
  recordMadridAction,
  type MadridActionKind,
  type MadridRecord,
  type MadridWorkspace,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import { useSession } from "@/lib/use-session";

const SELECT_CLASS =
  "h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm";

const ACTIONS: Array<{ value: MadridActionKind; label: string }> = [
  { value: "form_prepared", label: "MM2 or form prepared" },
  { value: "fee_recorded", label: "Fee recorded" },
  { value: "office_of_origin_certified", label: "Office of Origin certified" },
  { value: "wipo_irregularity", label: "WIPO irregularity" },
  { value: "international_registration_recorded", label: "IR number recorded" },
  { value: "wipo_notification_recorded", label: "WIPO notification" },
  { value: "national_examination_recorded", label: "National examination" },
  { value: "provisional_refusal_recorded", label: "Provisional refusal" },
  { value: "response_filed", label: "Response filed" },
  { value: "publication_recorded", label: "Publication" },
  { value: "opposition_recorded", label: "Opposition" },
  { value: "grant_statement_recorded", label: "Statement of grant" },
  { value: "refusal_statement_recorded", label: "Statement of refusal" },
  { value: "dependency_impact_review", label: "Basic-mark dependency review" },
  { value: "central_attack_impact_review", label: "Central-attack impact review" },
  { value: "source_snapshot", label: "WIPO or national source snapshot" },
  { value: "local_agent_instruction", label: "Local-agent instruction" },
  { value: "subsequent_designation_recorded", label: "Subsequent designation" },
  { value: "change_recorded", label: "WIPO change transaction" },
  { value: "renewal_transaction", label: "Renewal transaction" },
];

const DATE = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

function displayDate(value: string | null) {
  return value ? DATE.format(new Date(value)) : "Not recorded";
}

function readable(value: string) {
  return value.replaceAll("_", " ");
}

function parseClasses(value: string) {
  const classes = value
    .split(",")
    .map((row) => Number(row.trim()))
    .filter((row) => Number.isInteger(row));
  if (!classes.length || classes.some((row) => row < 1 || row > 45)) {
    throw new Error("Classes must be comma-separated Nice class numbers from 1 to 45.");
  }
  if (new Set(classes).size !== classes.length) throw new Error("Classes must be unique.");
  return classes;
}

function parseGoods(value: string, classes: number[]) {
  const goods: Record<string, string> = {};
  for (const line of value.split("\n")) {
    const [key, ...rest] = line.split(":");
    if (key?.trim() && rest.join(":").trim()) goods[key.trim()] = rest.join(":").trim();
  }
  if (classes.some((row) => !goods[String(row)])) {
    throw new Error("Goods/services requires one 'class: specification' line per class.");
  }
  return Object.fromEntries(classes.map((row) => [String(row), goods[String(row)]]));
}

function authorityFor(action: MadridActionKind) {
  if (action === "source_snapshot") return "wipo" as const;
  if (["office_of_origin_certified"].includes(action)) return "office_of_origin" as const;
  if (["wipo_irregularity", "wipo_notification_recorded"].includes(action)) {
    return "wipo" as const;
  }
  if (
    [
      "national_examination_recorded",
      "provisional_refusal_recorded",
      "publication_recorded",
      "opposition_recorded",
      "grant_statement_recorded",
      "refusal_statement_recorded",
    ].includes(action)
  ) {
    return "national_office" as const;
  }
  if (action === "local_agent_instruction") return "local_agent" as const;
  return "internal" as const;
}

export default function MadridPage() {
  const canRead = useCapability("ip:read");
  const canWrite = useCapability("ip:write");
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState("");
  const records = useQuery({
    queryKey: ["ip", "madrid", "records"],
    queryFn: () => fetchMadridRecords(),
    enabled: canRead,
  });
  const workspace = useQuery({
    queryKey: ["ip", "madrid", "workspace", selectedId],
    queryFn: () => fetchMadridWorkspace(selectedId),
    enabled: canRead && Boolean(selectedId),
  });

  useEffect(() => {
    if (!selectedId && records.data?.items[0]) setSelectedId(records.data.items[0].id);
  }, [records.data, selectedId]);

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["ip", "madrid"] });
  }

  if (!canRead) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title="Madrid portfolio" />
        <EmptyState title="IP access required" description="Ask an owner for IP read access." />
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        eyebrow="International trademarks"
        title="Madrid portfolio"
        actions={
          <Button variant="outline" size="sm" onClick={refresh} disabled={records.isFetching}>
            <RefreshCw className={records.isFetching ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
            Refresh
          </Button>
        }
      />

      {records.isPending ? (
        <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
        </div>
      ) : records.isError ? (
        <QueryErrorState error={records.error} onRetry={refresh} />
      ) : (
        <>
          {canWrite ? <CreateMadridRecord records={records.data.items} onCreated={async (id) => { await refresh(); setSelectedId(id); }} /> : null}
          <div className="grid min-w-0 gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
            <RecordList records={records.data.items} selectedId={selectedId} onSelect={setSelectedId} />
            {workspace.isPending ? (
              <Skeleton className="h-[520px]" />
            ) : workspace.isError ? (
              <QueryErrorState error={workspace.error} onRetry={() => workspace.refetch()} />
            ) : workspace.data ? (
              <MadridDetail workspace={workspace.data} canWrite={canWrite} onChanged={refresh} />
            ) : (
              <Card><CardContent className="py-12"><EmptyState title="Select a Madrid record" description="Choose an international registration or designation." /></CardContent></Card>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function RecordList({ records, selectedId, onSelect }: { records: MadridRecord[]; selectedId: string; onSelect: (id: string) => void }) {
  return (
    <Card className="min-w-0 self-start">
      <CardHeader><CardTitle as="h2">Registrations and designations</CardTitle></CardHeader>
      <CardContent className="p-0">
        {records.length ? (
          <div className="divide-y divide-[var(--color-line)]">
            {records.map((record) => (
              <button key={record.id} type="button" className={record.id === selectedId ? "w-full bg-[var(--color-brand-50)] px-5 py-4 text-left" : "w-full px-5 py-4 text-left hover:bg-[var(--color-bg-2)]"} onClick={() => onSelect(record.id)}>
                <span className="block break-words font-semibold">{record.mark_name}</span>
                <span className="mt-1 block break-words text-sm text-[var(--color-mute)]">{record.record_kind === "international_registration" ? record.ir_number ?? record.wipo_reference : `${record.designated_member_code} · ${record.jurisdiction}`}</span>
                <span className="mt-2 flex flex-wrap gap-2"><Badge tone="neutral">{record.direction}</Badge><Badge tone={record.record_kind === "international_designation" ? "warning" : "success"}>{record.record_kind === "international_designation" ? "designation" : "IR"}</Badge></span>
              </button>
            ))}
          </div>
        ) : <div className="p-6"><EmptyState title="No Madrid records" description="Create the first international registration." /></div>}
      </CardContent>
    </Card>
  );
}

function CreateMadridRecord({ records, onCreated }: { records: MadridRecord[]; onCreated: (id: string) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<MadridRecord["record_kind"]>("international_registration");
  const [direction, setDirection] = useState<MadridRecord["direction"]>("outbound");
  const [parentId, setParentId] = useState("");
  const [basicDocketId, setBasicDocketId] = useState("");
  const [basicApplicationId, setBasicApplicationId] = useState("");
  const [title, setTitle] = useState("");
  const [mark, setMark] = useState("");
  const [holder, setHolder] = useState("");
  const [wipoReference, setWipoReference] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [sourceReference, setSourceReference] = useState("");
  const [member, setMember] = useState("");
  const [office, setOffice] = useState("");
  const [classes, setClasses] = useState("9");
  const [goods, setGoods] = useState("9: ");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [designationKind, setDesignationKind] = useState<"original" | "subsequent">("original");
  const [restricted, setRestricted] = useState(false);
  const dockets = useQuery({ queryKey: ["ip", "dockets"], queryFn: fetchIpDockets, enabled: open && kind === "international_registration" && direction === "outbound" });
  const core = useQuery({ queryKey: ["ip", "core-records", basicDocketId], queryFn: () => fetchIpCoreRecords(basicDocketId), enabled: Boolean(basicDocketId) });
  const registrations = records.filter((row) => row.record_kind === "international_registration");
  const mutation = useMutation({
    mutationFn: async () => {
      const parsedClasses = parseClasses(classes);
      const parent = registrations.find((row) => row.id === parentId);
      return createMadridRecord({
        recordKind: kind,
        direction: kind === "international_designation" ? parent?.direction ?? direction : direction,
        parentRegistrationId: kind === "international_designation" ? parentId : null,
        basicApplicationId: kind === "international_registration" && direction === "outbound" ? basicApplicationId : null,
        docketTitle: title,
        restricted,
        wipoReference,
        holderName: holder,
        markName: mark,
        officeOfOrigin: kind === "international_registration" && direction === "outbound" ? "IP India" : null,
        designatedMemberCode: kind === "international_designation" ? member.toUpperCase() : null,
        designatedOffice: kind === "international_designation" ? office : null,
        jurisdiction: kind === "international_designation" ? member.toUpperCase() : null,
        designationKind: kind === "international_designation" ? designationKind : null,
        classes: parsedClasses,
        goodsServices: parseGoods(goods, parsedClasses),
        formKind: kind === "international_registration" && direction === "outbound" ? "MM2" : null,
        sourceUrl,
        sourceReference,
        sourceRetrievedAt: new Date().toISOString(),
        designationEffectiveDate: kind === "international_designation" ? effectiveDate : null,
      });
    },
    onSuccess: async (record) => { toast.success("Madrid record created."); setOpen(false); await onCreated(record.id); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not create Madrid record.")),
  });
  function submit(event: FormEvent) { event.preventDefault(); mutation.mutate(); }
  return (
    <Card>
      <CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between"><CardTitle as="h2">Madrid intake</CardTitle><Button size="sm" variant={open ? "ghost" : "outline"} onClick={() => setOpen((value) => !value)}><Plus className="h-4 w-4" />{open ? "Close" : "New record"}</Button></CardHeader>
      {open ? <CardContent><form className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-4" onSubmit={submit}>
        <Field label="Record type"><select className={SELECT_CLASS} value={kind} onChange={(event) => setKind(event.target.value as MadridRecord["record_kind"])}><option value="international_registration">International registration</option><option value="international_designation">Designation</option></select></Field>
        {kind === "international_registration" ? <Field label="Direction"><select className={SELECT_CLASS} value={direction} onChange={(event) => setDirection(event.target.value as MadridRecord["direction"])}><option value="outbound">Outbound from India</option><option value="inbound">Inbound foundation</option></select></Field> : <Field label="Parent IR"><select className={SELECT_CLASS} value={parentId} onChange={(event) => setParentId(event.target.value)} required><option value="">Select IR</option>{registrations.map((row) => <option key={row.id} value={row.id}>{row.mark_name} · {row.ir_number ?? row.wipo_reference}</option>)}</select></Field>}
        {kind === "international_registration" && direction === "outbound" ? <><Field label="Basic mark docket"><select className={SELECT_CLASS} value={basicDocketId} onChange={(event) => { setBasicDocketId(event.target.value); setBasicApplicationId(""); }} required><option value="">Select docket</option>{(dockets.data?.dockets ?? []).filter((row) => row.record_type === "trademark").map((row) => <option key={row.id} value={row.id}>{row.title}</option>)}</select></Field><Field label="Basic Indian application"><select className={SELECT_CLASS} value={basicApplicationId} onChange={(event) => setBasicApplicationId(event.target.value)} required><option value="">Select application</option>{(core.data?.applications ?? []).filter((row) => row.jurisdiction === "IN").map((row) => <option key={row.id} value={row.id}>{row.office} · {row.filing_phase}</option>)}</select></Field></> : null}
        <Field label="Docket title"><Input value={title} onChange={(event) => setTitle(event.target.value)} required /></Field><Field label="Mark"><Input value={mark} onChange={(event) => setMark(event.target.value)} required /></Field><Field label="Holder"><Input value={holder} onChange={(event) => setHolder(event.target.value)} required /></Field><Field label="WIPO reference"><Input value={wipoReference} onChange={(event) => setWipoReference(event.target.value)} required /></Field>
        {kind === "international_designation" ? <><Field label="Designation type"><select className={SELECT_CLASS} value={designationKind} onChange={(event) => setDesignationKind(event.target.value as "original" | "subsequent")}><option value="original">Original designation</option><option value="subsequent">Subsequent designation</option></select></Field><Field label="Member code"><Input value={member} onChange={(event) => setMember(event.target.value)} required /></Field><Field label="Designated office"><Input value={office} onChange={(event) => setOffice(event.target.value)} required /></Field><Field label="Designation date"><Input type="date" value={effectiveDate} onChange={(event) => setEffectiveDate(event.target.value)} required /></Field></> : null}
        <Field label="Nice classes"><Input value={classes} onChange={(event) => setClasses(event.target.value)} required /></Field><Field label="Goods/services" wide><Textarea value={goods} onChange={(event) => setGoods(event.target.value)} rows={3} required /></Field><Field label="Source URL"><Input type="url" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} required /></Field><Field label="Source reference"><Input value={sourceReference} onChange={(event) => setSourceReference(event.target.value)} required /></Field>
        <label className="flex items-center gap-2 text-sm md:col-span-2 xl:col-span-4"><input type="checkbox" checked={restricted} onChange={(event) => setRestricted(event.target.checked)} />Restrict this docket to explicitly granted members</label>
        <div className="flex items-end md:col-span-2 xl:col-span-4"><Button type="submit" disabled={mutation.isPending}><Plus className="h-4 w-4" />Create record</Button></div>
      </form></CardContent> : null}
    </Card>
  );
}

function MadridDetail({ workspace, canWrite, onChanged }: { workspace: MadridWorkspace; canWrite: boolean; onChanged: () => Promise<void> }) {
  const record = workspace.record;
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <Card><CardHeader className="gap-3 sm:flex-row sm:items-start sm:justify-between"><div className="min-w-0"><CardTitle as="h2">{record.mark_name}</CardTitle><p className="mt-1 break-words text-sm text-[var(--color-mute)]">{record.ir_number ?? record.wipo_reference}</p></div><div className="flex flex-wrap gap-2"><Badge tone={record.wipo_status ? "success" : "warning"}>WIPO: {record.wipo_status ?? "unconfirmed"}</Badge>{record.record_kind === "international_designation" ? <Badge tone={record.national_status ? "success" : "warning"}>National: {record.national_status ?? "unconfirmed"}</Badge> : null}<Badge tone={workspace.provider_mode === "contracted_sync" ? "success" : "warning"}>{readable(workspace.provider_mode)}</Badge></div></CardHeader><CardContent><div className="grid gap-4 text-sm sm:grid-cols-2 xl:grid-cols-4"><Datum label="Direction" value={record.direction} /><Datum label="Jurisdiction" value={record.jurisdiction ?? "International"} /><Datum label="Classes" value={record.classes_json.join(", ")} /><Datum label="Local agent" value={record.local_agent_name ?? "Not instructed"} /><Datum label="IR date" value={displayDate(record.international_registration_date)} /><Datum label="Notification" value={displayDate(record.notification_date)} /><Datum label="Publication" value={displayDate(record.publication_date)} /><Datum label="Renewal due" value={displayDate(record.renewal_due_date)} /></div><div className="mt-4 flex flex-wrap gap-2"><Button href={record.source_url} target="_blank" rel="noreferrer" size="sm" variant="outline"><ArrowUpRight className="h-4 w-4" />Open source</Button><Button href="/app/ip" size="sm" variant="ghost"><Link2 className="h-4 w-4" />Open docket</Button></div></CardContent></Card>
      {workspace.data_quality_gaps.length ? <div className="flex min-w-0 items-start gap-3 rounded-md border border-amber-300 bg-amber-50 p-4 text-sm"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" /><div className="min-w-0"><strong>Open controls</strong><div className="mt-2 flex flex-wrap gap-2">{workspace.data_quality_gaps.map((gap) => <Badge key={gap} tone="warning">{readable(gap)}</Badge>)}</div></div></div> : null}
      <Tabs defaultValue="status" className="min-w-0"><TabsList className="h-auto w-full flex-wrap justify-start"><TabsTrigger className="min-w-[140px] flex-1 sm:flex-none" value="status">Status and sources</TabsTrigger><TabsTrigger className="min-w-[140px] flex-1 sm:flex-none" value="designations">Designations</TabsTrigger><TabsTrigger className="min-w-[140px] flex-1 sm:flex-none" value="evidence">Deadlines and evidence</TabsTrigger><TabsTrigger className="min-w-[140px] flex-1 sm:flex-none" value="history">History</TabsTrigger></TabsList>
        <TabsContent value="status"><SourcePanel workspace={workspace} canWrite={canWrite} onChanged={onChanged} /></TabsContent>
        <TabsContent value="designations"><DesignationPanel workspace={workspace} /></TabsContent>
        <TabsContent value="evidence"><EvidencePanel workspace={workspace} /></TabsContent>
        <TabsContent value="history"><HistoryPanel events={workspace.events} /></TabsContent>
      </Tabs>
      {canWrite ? <MadridActionForm workspace={workspace} onChanged={onChanged} /> : null}
    </div>
  );
}

function SourcePanel({ workspace, canWrite, onChanged }: { workspace: MadridWorkspace; canWrite: boolean; onChanged: () => Promise<void> }) {
  const session = useSession();
  const mutation = useMutation({ mutationFn: (input: { eventId: string; decision: "same_fact" | "keep_separate" | "reject_candidate" }) => recordMadridAction({ recordId: workspace.record.id, expectedVersion: workspace.record.version, expectedLifecycleVersion: workspace.docket.lifecycle_version, actionKind: "source_reconciliation", authority: "internal", effectiveAt: new Date().toISOString(), responsibleMembershipId: session.context?.membership.id ?? "", reason: `Counsel reconciled source candidate as ${input.decision.replaceAll("_", " ")}.`, sourceReference: `madrid-review:${input.eventId}`, sourceRetrievedAt: new Date().toISOString(), reconcilesEventId: input.eventId, reconciliationDecision: input.decision }), onSuccess: async () => { toast.success("Source candidate reconciled."); await onChanged(); }, onError: (error) => toast.error(apiErrorMessage(error, "Could not reconcile source.")) });
  return <Card><CardHeader><CardTitle as="h3">Source reconciliation</CardTitle></CardHeader><CardContent className="space-y-3">{workspace.unresolved_source_candidates.length ? workspace.unresolved_source_candidates.map((event) => <div key={event.id} className="grid min-w-0 gap-3 rounded-md border border-[var(--color-line)] p-4 md:grid-cols-[minmax(0,1fr)_auto]"><div className="min-w-0"><div className="flex flex-wrap gap-2"><Badge tone="warning">candidate</Badge><Badge tone="neutral">{String(event.payload_json.authority ?? event.source)}</Badge></div><strong className="mt-2 block break-words">{String(event.payload_json.wipo_status ?? event.payload_json.national_status ?? "Status observation")}</strong><a href={String(event.payload_json.source_url ?? "#")} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 break-all text-sm underline">{event.source_reference}<ArrowUpRight className="h-3 w-3" /></a></div>{canWrite ? <div className="flex flex-wrap items-center gap-2"><Button size="sm" onClick={() => mutation.mutate({ eventId: event.id, decision: "same_fact" })} disabled={mutation.isPending}><Check className="h-4 w-4" />Accept</Button><Button size="sm" variant="outline" onClick={() => mutation.mutate({ eventId: event.id, decision: "keep_separate" })} disabled={mutation.isPending}>Keep separate</Button><Button size="sm" variant="ghost" onClick={() => mutation.mutate({ eventId: event.id, decision: "reject_candidate" })} disabled={mutation.isPending}>Reject</Button></div> : null}</div>) : <EmptyState title="No source conflicts" description="All WIPO and national-office snapshots are reconciled." />}</CardContent></Card>;
}

function DesignationPanel({ workspace }: { workspace: MadridWorkspace }) {
  const rows = workspace.record.record_kind === "international_registration" ? workspace.designations : workspace.parent ? [workspace.parent, workspace.record] : [workspace.record];
  return <Card><CardHeader><CardTitle as="h3">International family</CardTitle></CardHeader><CardContent className="p-0"><div className="overflow-x-auto"><table className="w-full min-w-[720px] text-left text-sm"><thead className="bg-[var(--color-bg-2)] text-xs text-[var(--color-mute)]"><tr><th className="px-4 py-3">Member</th><th className="px-4 py-3">WIPO status</th><th className="px-4 py-3">National status</th><th className="px-4 py-3">Agent</th><th className="px-4 py-3">Source</th></tr></thead><tbody className="divide-y divide-[var(--color-line)]">{rows.map((row) => <tr key={row.id}><td className="px-4 py-3 font-medium">{row.record_kind === "international_registration" ? "International registration" : row.designated_member_code}</td><td className="px-4 py-3">{row.wipo_status ?? "Unconfirmed"}</td><td className="px-4 py-3">{row.national_status ?? "Not applicable"}</td><td className="px-4 py-3">{row.local_agent_name ?? "Not instructed"}</td><td className="px-4 py-3"><a className="inline-flex items-center gap-1 underline" href={row.source_url} target="_blank" rel="noreferrer">Open<ArrowUpRight className="h-3 w-3" /></a></td></tr>)}</tbody></table></div></CardContent></Card>;
}

function EvidencePanel({ workspace }: { workspace: MadridWorkspace }) {
  return <div className="grid min-w-0 gap-4 lg:grid-cols-3"><Card><CardHeader><CardTitle as="h3"><Scale className="mr-2 inline h-4 w-4" />Deadlines</CardTitle></CardHeader><CardContent className="space-y-3">{workspace.deadlines.length ? workspace.deadlines.map((row) => <div key={row.id}><strong className="block">{row.title}</strong><span className="text-sm text-[var(--color-mute)]">{displayDate(row.result_on)} · {row.state}</span><span className="mt-1 block break-words text-xs text-[var(--color-mute)]">{row.rule_citation} · {row.source_version}</span></div>) : <EmptyState title="No Madrid deadlines" description="No versioned deadline is linked." />}</CardContent></Card><Card><CardHeader><CardTitle as="h3"><FileText className="mr-2 inline h-4 w-4" />Documents</CardTitle></CardHeader><CardContent className="space-y-3">{workspace.documents.length ? workspace.documents.map((row) => <div key={row.id}><strong className="block break-words">{row.title}</strong><span className="text-sm text-[var(--color-mute)]">{row.taxonomy_label} · v{row.current_version}</span></div>) : <EmptyState title="No linked documents" description="No document evidence is linked." />}</CardContent></Card><Card><CardHeader><CardTitle as="h3"><Landmark className="mr-2 inline h-4 w-4" />Fees and costs</CardTitle></CardHeader><CardContent className="space-y-3">{workspace.costs.length ? workspace.costs.map((row) => <div key={row.id}><strong className="block break-words">{row.description}</strong><span className="text-sm text-[var(--color-mute)]">{row.amount_withheld ? "Amount restricted" : `${row.amount_minor ?? 0} ${row.currency}`} · {row.reconciliation_status}</span></div>) : <EmptyState title="No linked costs" description="No fee or cost evidence is linked." />}</CardContent></Card></div>;
}

function HistoryPanel({ events }: { events: MadridWorkspace["events"] }) {
  return <Card><CardHeader><CardTitle as="h3">Versioned transactions</CardTitle></CardHeader><CardContent className="space-y-3">{events.length ? [...events].reverse().map((event) => { const sourceUrl = String(event.payload_json.source_url ?? event.payload_json.candidate_source_url ?? ""); return <div key={event.id} className="grid min-w-0 gap-2 border-b border-[var(--color-line)] pb-3 last:border-0 md:grid-cols-[160px_minmax(0,1fr)_auto]"><span className="text-sm tabular-nums text-[var(--color-mute)]">{displayDate(event.effective_at)}</span><div className="min-w-0"><strong className="block break-words">{readable(String(event.payload_json.action_kind ?? event.event_kind))}</strong><span className="block text-sm text-[var(--color-mute)]">{event.reason ?? event.source_reference}</span>{sourceUrl.startsWith("http") ? <a href={sourceUrl} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 break-all text-sm underline">{event.source_reference}<ArrowUpRight className="h-3 w-3" /></a> : null}</div><Badge tone={event.candidate_status === "candidate" ? "warning" : "success"}>{event.candidate_status}</Badge></div>; }) : <EmptyState title="No Madrid transactions" description="No workflow transaction is recorded." />}</CardContent></Card>;
}

function MadridActionForm({ workspace, onChanged }: { workspace: MadridWorkspace; onChanged: () => Promise<void> }) {
  const session = useSession();
  const [action, setAction] = useState<MadridActionKind>("source_snapshot");
  const [authority, setAuthority] = useState<ReturnType<typeof authorityFor>>("wipo");
  const [sourceReference, setSourceReference] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [reason, setReason] = useState("");
  const [status, setStatus] = useState("");
  const [localAgent, setLocalAgent] = useState("");
  const [eventDate, setEventDate] = useState(new Date().toISOString().slice(0, 10));
  const [irNumber, setIrNumber] = useState("");
  const [costId, setCostId] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [deadlineId, setDeadlineId] = useState("");
  const [impactScope, setImpactScope] = useState("");
  const [recommendedAction, setRecommendedAction] = useState("");
  useEffect(() => { setAuthority(authorityFor(action)); }, [action]);
  const mutation = useMutation({ mutationFn: () => recordMadridAction({ recordId: workspace.record.id, expectedVersion: workspace.record.version, expectedLifecycleVersion: workspace.docket.lifecycle_version, actionKind: action, authority, effectiveAt: new Date(`${eventDate}T12:00:00Z`).toISOString(), responsibleMembershipId: session.context?.membership.id ?? "", reason, sourceUrl: sourceUrl || null, sourceReference, sourceRetrievedAt: new Date().toISOString(), evidenceRefs: [sourceReference], documentRefs: documentId ? [documentId] : [], deadlineRefs: deadlineId ? [deadlineId] : [], costItemRefs: action === "fee_recorded" && costId ? [costId] : [], wipoStatus: action === "source_snapshot" && authority === "wipo" ? status : null, nationalStatus: action === "source_snapshot" && authority === "national_office" ? status : null, localAgentName: action === "local_agent_instruction" ? localAgent : null, irNumber: action === "international_registration_recorded" ? irNumber : null, internationalRegistrationDate: action === "international_registration_recorded" ? eventDate : null, notificationDate: action === "wipo_notification_recorded" ? eventDate : null, publicationDate: action === "publication_recorded" ? eventDate : null, statementDate: ["grant_statement_recorded", "refusal_statement_recorded"].includes(action) ? eventDate : null, renewalDueDate: action === "renewal_transaction" ? eventDate : null, details: ["dependency_impact_review", "central_attack_impact_review"].includes(action) ? { impact_scope: impactScope.split(",").map((row) => row.trim()).filter(Boolean), recommended_action: recommendedAction } : {} }), onSuccess: async (result) => { toast.success(result.impact_review_only ? "Impact review recorded without changing legal status." : "Madrid transaction recorded."); setSourceReference(""); setReason(""); await onChanged(); }, onError: (error) => toast.error(apiErrorMessage(error, "Could not record Madrid transaction.")) });
  function submit(event: FormEvent) { event.preventDefault(); mutation.mutate(); }
  const external = ["wipo", "office_of_origin", "national_office"].includes(authority);
  return <Card><CardHeader><CardTitle as="h3"><Globe2 className="mr-2 inline h-4 w-4" />Record transaction</CardTitle></CardHeader><CardContent><form className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-4" onSubmit={submit}><Field label="Action"><select className={SELECT_CLASS} value={action} onChange={(event) => setAction(event.target.value as MadridActionKind)}>{ACTIONS.filter((row) => workspace.record.record_kind === "international_registration" ? ![..._NATIONAL_UI_ACTIONS, "local_agent_instruction", "wipo_notification_recorded"].includes(row.value) : ![..._OUTBOUND_UI_ACTIONS].includes(row.value)).map((row) => <option key={row.value} value={row.value}>{row.label}</option>)}</select></Field><Field label="Authority"><select className={SELECT_CLASS} value={authority} onChange={(event) => setAuthority(event.target.value as ReturnType<typeof authorityFor>)} disabled={action !== "source_snapshot"}><option value="internal">Internal</option><option value="wipo">WIPO</option><option value="office_of_origin">Office of Origin</option><option value="national_office">National office</option><option value="local_agent">Local agent</option></select></Field><Field label="Effective date"><Input type="date" value={eventDate} onChange={(event) => setEventDate(event.target.value)} required /></Field><Field label="Source reference"><Input value={sourceReference} onChange={(event) => setSourceReference(event.target.value)} required /></Field>{external ? <Field label="Source URL"><Input type="url" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} required /></Field> : null}{action === "source_snapshot" ? <Field label={authority === "wipo" ? "WIPO status" : "National status"}><Input value={status} onChange={(event) => setStatus(event.target.value)} required /></Field> : null}{action === "local_agent_instruction" ? <Field label="Local agent"><Input value={localAgent} onChange={(event) => setLocalAgent(event.target.value)} required /></Field> : null}{action === "international_registration_recorded" ? <Field label="IR number"><Input value={irNumber} onChange={(event) => setIrNumber(event.target.value)} required /></Field> : null}{action === "fee_recorded" ? <Field label="Canonical cost item"><select className={SELECT_CLASS} value={costId} onChange={(event) => setCostId(event.target.value)} required><option value="">Select cost</option>{workspace.costs.map((row) => <option key={row.id} value={row.id}>{row.description}</option>)}</select></Field> : null}<Field label="Linked document"><select className={SELECT_CLASS} value={documentId} onChange={(event) => setDocumentId(event.target.value)}><option value="">No document</option>{workspace.documents.map((row) => <option key={row.id} value={row.id}>{row.title}</option>)}</select></Field><Field label="Linked deadline"><select className={SELECT_CLASS} value={deadlineId} onChange={(event) => setDeadlineId(event.target.value)}><option value="">No deadline</option>{workspace.deadlines.map((row) => <option key={row.id} value={row.id}>{row.title}</option>)}</select></Field>{["dependency_impact_review", "central_attack_impact_review"].includes(action) ? <><Field label="Impact scope"><Input value={impactScope} onChange={(event) => setImpactScope(event.target.value)} required /></Field><Field label="Recommended action"><Input value={recommendedAction} onChange={(event) => setRecommendedAction(event.target.value)} required /></Field></> : null}<Field label="Reason" wide><Textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={3} required /></Field><div className="flex items-end md:col-span-2 xl:col-span-4"><Button type="submit" disabled={mutation.isPending || !session.context?.membership.id}><Check className="h-4 w-4" />Record transaction</Button></div></form></CardContent></Card>;
}

const _NATIONAL_UI_ACTIONS: MadridActionKind[] = ["national_examination_recorded", "provisional_refusal_recorded", "response_filed", "publication_recorded", "opposition_recorded", "grant_statement_recorded", "refusal_statement_recorded"];
const _OUTBOUND_UI_ACTIONS: MadridActionKind[] = ["form_prepared", "office_of_origin_certified", "international_registration_recorded", "dependency_impact_review", "central_attack_impact_review", "subsequent_designation_recorded"];

function Field({ label, children, wide = false }: { label: string; children: ReactNode; wide?: boolean }) {
  return <Label className={wide ? "min-w-0 md:col-span-2" : "min-w-0"}><span className="mb-1.5 block">{label}</span>{children}</Label>;
}

function Datum({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><span className="text-[var(--color-mute)]">{label}</span><strong className="mt-1 block break-words font-medium capitalize">{value.replaceAll("_", " ")}</strong></div>;
}
