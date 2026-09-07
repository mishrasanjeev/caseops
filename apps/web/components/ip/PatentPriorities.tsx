"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, FileText, Pencil, Plus, RefreshCw, Search, X } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";

import { PatentSourceDownload } from "@/components/ip/PatentSourceDownload";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import { fetchIpDocumentsForDocket } from "@/lib/api/endpoints";
import {
  createPatentPriority, fetchPatentApplication, fetchPatentApplications, fetchPatentFamilyGraph,
  fetchPatentPriorities, patentPriorityKinds,
  type PatentApplication, type PatentPriority, type PatentPriorityCommand, type PatentPriorityPage,
} from "@/lib/api/ip-patents";

const selectClass = "h-10 w-full min-w-0 rounded-sm border border-line bg-surface px-3 text-sm";
const rootKey = (id: string) => ["ip", "patent-priorities", id];
const pageKey = (id: string, history: boolean, cursor?: number, sequence?: number) =>
  [...rootKey(id), history, cursor ?? null, sequence ?? null];
const kindLabels = { priority: "Priority claim", divisional_parent: "Divisional parent",
  addition_parent: "Patent of addition parent", national_phase_parent: "National phase parent" };
const reviewLabels = {
  office_names_differ: "Recorded office names differ",
  jurisdictions_differ: "Recorded jurisdictions differ",
  filing_dates_incomplete: "Filing dates are incomplete",
  priority_date_precedes_parent_filing: "Priority date precedes the recorded parent filing",
};

function PriorityEvidence({ priority }: { priority: PatentPriority }) {
  return <div className="min-w-0 space-y-2">
    <p className="text-sm">{kindLabels[priority.relation_kind]} - {priority.priority_date}</p>
    <p className="break-words text-sm text-mute">{priority.reason}</p>
    {!!priority.review_flags.length && <ul className="space-y-1 text-sm" aria-label="Recorded review notes">
      {priority.review_flags.map((flag) => <li key={flag}>{reviewLabels[flag]}</li>)}
    </ul>}
    {priority.source.kind === "document_version" && <PatentSourceDownload source={priority.source} />}
  </div>;
}

export function PatentPriorities({ record, canWrite, onOpenDocuments }: {
  record: PatentApplication; canWrite: boolean; onOpenDocuments: () => void;
}) {
  const queryClient = useQueryClient();
  const [history, setHistory] = useState(false);
  const [continuation, setContinuation] = useState<{ cursor: number; sequence: number }>();
  const [editor, setEditor] = useState<{ record: PatentApplication; sequence: number; priority?: PatentPriority; withdrawn?: boolean }>();
  const [confirmed, setConfirmed] = useState<PatentPriority>();
  const priorities = useQuery({
    queryKey: pageKey(record.id, history, continuation?.cursor, continuation?.sequence),
    queryFn: ({ signal }) => fetchPatentPriorities(record.id, history, continuation, signal),
  });
  const busy = priorities.isPending || priorities.isError || priorities.isFetching || !!editor;
  const editable = canWrite && record.is_active;
  const reload = () => {
    setEditor(undefined); setContinuation(undefined);
    void queryClient.invalidateQueries({ queryKey: rootKey(record.id) });
    void queryClient.invalidateQueries({ queryKey: ["ip", "patent-application", record.id], exact: true });
    void queryClient.invalidateQueries({ queryKey: ["ip", "priority-parent"] });
  };
  const onSaved = async (priority: PatentPriority) => {
    await queryClient.cancelQueries({ queryKey: rootKey(record.id) });
    setConfirmed(priority); setContinuation(undefined); setHistory(false); setEditor(undefined);
    queryClient.setQueryData<PatentPriorityPage>(pageKey(record.id, false), (old) => ({
      application_id: record.id, collection_sequence: priority.sequence,
      priorities: [...(priority.is_current ? [priority] : []), ...(old?.priorities ?? [])
        .filter((row) => row.id !== priority.id && row.id !== priority.supersedes_priority_id)].slice(0, 25),
      next_cursor: old?.next_cursor ?? null,
    }));
    await queryClient.invalidateQueries({ queryKey: rootKey(record.id) });
    await queryClient.invalidateQueries({ queryKey: ["ip", "patent-family-graph"] });
  };
  return <section className="min-w-0 space-y-4 border-t border-line pt-4" aria-label="Patent priorities">
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
      <h2 className="text-lg font-semibold">Priorities and parents</h2>
      <div className="flex min-w-0 flex-wrap items-center gap-3">
        <label className="inline-flex items-center gap-2 text-sm"><input type="checkbox" checked={history} disabled={!!editor}
          onChange={(event) => { setHistory(event.target.checked); setContinuation(undefined); }} />Include relationship history</label>
        {editable && <Button disabled={busy} onClick={() => setEditor({ record, sequence: priorities.data!.collection_sequence })}><Plus size={16} />Add relationship</Button>}
      </div>
    </div>
    {editor && editable && <PriorityForm key={`${editor.priority?.id ?? "new"}:${editor.withdrawn ?? false}`}
      {...editor} initial={editor.priority} onCancel={() => setEditor(undefined)} onSaved={onSaved}
      onOpenDocuments={onOpenDocuments} onReload={reload} />}
    {confirmed && (priorities.isError || !priorities.data || priorities.data.collection_sequence < confirmed.sequence)
      && <p role="status" className="break-words text-sm">Saved relationship record for {confirmed.current_parent_title}. Refreshing records.</p>}
    {priorities.isPending ? <Skeleton className="h-32 w-full" /> : priorities.isError
      ? <QueryErrorState title="Could not load priority records" error={priorities.error} onRetry={() => {
        if (continuation) setContinuation(undefined); else void priorities.refetch();
      }} /> : <>
        {!priorities.data.priorities.length && <p className="text-sm text-mute">No recorded relationships on this page.</p>}
        <ul className="min-w-0 divide-y divide-line" aria-label="Recorded patent relationships">
          {priorities.data.priorities.map((priority) => <li key={priority.id} className="min-w-0 space-y-2 py-4">
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
              <Link className="min-w-0 basis-64 grow break-words font-semibold text-brand-700 hover:underline"
                href={`/app/ip/patents/applications/${priority.parent_application_id}`}>{priority.current_parent_title}</Link>
              {!priority.is_current && <Badge tone="neutral">{priority.withdrawn ? "Withdrawn record" : "Superseded"}</Badge>}
              {editable && priority.is_current && <div className="flex min-w-0 max-w-full flex-wrap gap-2" role="group" aria-label="Relationship actions">
                <Button variant="ghost" disabled={busy} onClick={() => setEditor({ record, sequence: priorities.data.collection_sequence, priority })}><Pencil size={16} />Correct relationship</Button>
                <Button variant="ghost" disabled={busy} onClick={() => setEditor({ record, sequence: priorities.data.collection_sequence, priority, withdrawn: true })}><X size={16} />Withdraw record</Button>
              </div>}
            </div>
            <PriorityEvidence priority={priority} />
          </li>)}
        </ul>
        <nav className="flex min-w-0 flex-wrap justify-between gap-2" aria-label="Relationship pages">
          <Button variant="ghost" disabled={!continuation || busy} onClick={() => setContinuation(undefined)}><ArrowLeft size={16} />Latest relationships</Button>
          <Button variant="ghost" disabled={!priorities.data.next_cursor || busy} onClick={() =>
            setContinuation({ cursor: priorities.data.next_cursor!, sequence: priorities.data.collection_sequence })}>Older relationships<ArrowRight size={16} /></Button>
        </nav>
      </>}
  </section>;
}

function PriorityForm({ record, sequence, initial, withdrawn = false, onCancel, onSaved, onOpenDocuments, onReload }: {
  record: PatentApplication; sequence: number; initial?: PatentPriority; withdrawn?: boolean;
  onCancel: () => void; onSaved: (priority: PatentPriority) => Promise<void>;
  onOpenDocuments: () => void; onReload: () => void;
}) {
  const base = useRef({ record, sequence, initial, withdrawn });
  const commandKey = useRef<{ body: string; key: string } | undefined>(undefined);
  const [parentId, setParentId] = useState(initial?.parent_application_id ?? "");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState<string>();
  const [kind, setKind] = useState<PatentPriorityCommand["relation_kind"]>(initial?.relation_kind ?? "priority");
  const [date, setDate] = useState(initial?.priority_date ?? "");
  const [reason, setReason] = useState("");
  const retained = initial?.source ?? record.facts.source;
  const [sourceId, setSourceId] = useState(retained.kind === "document_version" ? retained.document_version_id : "");
  const parents = useQuery({ queryKey: ["ip", "priority-parents", query, cursor], enabled: !withdrawn,
    queryFn: ({ signal }) => fetchPatentApplications("", cursor, signal, "active", query) });
  const selected = useQuery({ queryKey: ["ip", "priority-parent", parentId], enabled: !!parentId,
    queryFn: ({ signal }) => fetchPatentApplication(parentId, undefined, signal) });
  const sources = useQuery({ queryKey: ["ip", "documents", record.docket_id],
    queryFn: () => fetchIpDocumentsForDocket(record.docket_id) });
  const options = sources.data?.items.flatMap((document) => document.versions.map((version) => ({
    label: `${document.title} - version ${version.version}`, source: { kind: "document_version" as const,
      document_id: document.id, document_version_id: version.id, content_sha256: version.sha256_hex },
  }))) ?? [];
  if (retained.kind === "document_version" && !options.some((option) => option.source.document_version_id === retained.document_version_id)) {
    options.push({ label: "Retained source version", source: retained });
  }
  const candidates = parents.data?.applications.filter((candidate) => candidate.id !== record.id) ?? [];
  const save = useMutation({
    mutationFn: async () => {
      const parent = selected.data;
      const source = options.find((option) => option.source.document_version_id === sourceId)?.source;
      if (!parent || !source) throw new Error("Select an accessible parent and source version.");
      const command: PatentPriorityCommand = { parent_application_id: parent.id, relation_kind: kind,
        priority_date: date, source, reason, withdrawn: base.current.withdrawn,
        expected_application_version: base.current.record.version,
        expected_lifecycle_version: base.current.record.lifecycle_version,
        expected_parent_version: parent.version, expected_parent_lifecycle_version: parent.lifecycle_version,
        expected_priority_sequence: base.current.sequence, supersedes_priority_id: base.current.initial?.id ?? null };
      const body = JSON.stringify(command);
      if (commandKey.current?.body !== body) commandKey.current = { body, key: crypto.randomUUID() };
      return createPatentPriority(base.current.record.id, command, commandKey.current.key);
    }, onSuccess: onSaved,
  });
  return <form className="min-w-0 space-y-4 border-y border-line py-4"
    aria-label={withdrawn ? "Withdraw patent relationship" : initial ? "Correct patent relationship" : "Add patent relationship"}
    onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
    <h3 className="font-semibold">{withdrawn ? "Withdrawal evidence" : initial ? "Corrected relationship evidence" : "New relationship evidence"}</h3>
    <fieldset disabled={save.isPending} className="min-w-0 space-y-4">
      {!withdrawn && <div className="space-y-3">
        <div className="flex min-w-0 flex-wrap items-end gap-2">
          <div className="min-w-0 flex-1 basis-48"><Label htmlFor="priority-parent-search">Parent title or exact identifier</Label>
            <Input id="priority-parent-search" maxLength={200} value={search} onChange={(event) => setSearch(event.target.value)} /></div>
          <Button type="button" variant="secondary" title="Search parent applications" aria-label="Search parent applications"
            onClick={() => { setQuery(search.trim()); setCursor(undefined); }}><Search size={16} /></Button>
        </div>
        <div className="min-w-0"><Label htmlFor="priority-parent">Parent application</Label>
          <select id="priority-parent" className={selectClass} required value={parentId} disabled={parents.isPending || parents.isError}
            onChange={(event) => setParentId(event.target.value)}>
            <option value="">Select parent application</option>
            {candidates.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.facts.title} - {candidate.facts.jurisdiction} - {candidate.facts.identifiers.find((identifier) => identifier.identifier_kind === "application")?.raw_value ?? "Number not recorded"}</option>)}
            {parentId && !candidates.some((candidate) => candidate.id === parentId) && <option value={parentId}>
              {selected.data?.facts.title ?? initial?.current_parent_title ?? "Selected parent"}</option>}
          </select>
        </div>
        {parents.isError && <QueryErrorState title="Could not load parent applications" error={parents.error} onRetry={parents.refetch} />}
        {parents.isSuccess && !candidates.length && <p className="text-sm text-mute">No other accessible active applications on this page.</p>}
        <nav className="flex min-w-0 flex-wrap justify-between gap-2" aria-label="Parent application pages">
          <Button type="button" variant="ghost" disabled={!cursor || parents.isFetching} onClick={() => setCursor(undefined)}><ArrowLeft size={16} />First parents</Button>
          <Button type="button" variant="ghost" disabled={!parents.data?.next_cursor || parents.isFetching} onClick={() => setCursor(parents.data!.next_cursor!)}>Next parents<ArrowRight size={16} /></Button>
        </nav>
      </div>}
      {withdrawn && <p className="break-words font-medium">{initial?.current_parent_title}</p>}
      {parentId && selected.isPending && <p role="status" className="text-sm">Loading selected parent...</p>}
      {parentId && selected.isError && <QueryErrorState title="Selected parent is unavailable" error={selected.error} onRetry={selected.refetch} />}
      <div className="grid min-w-0 gap-4 sm:grid-cols-2">
        <div className="min-w-0"><Label htmlFor="priority-kind">Relationship type</Label><select id="priority-kind" className={selectClass} value={kind} disabled={withdrawn}
          onChange={(event) => setKind(event.target.value as PatentPriorityCommand["relation_kind"])}>
          {patentPriorityKinds.map((value) => <option key={value} value={value}>{kindLabels[value]}</option>)}
        </select></div>
        <div className="min-w-0"><Label htmlFor="priority-date">Recorded priority date</Label><Input id="priority-date" type="date" required value={date}
          disabled={withdrawn} onChange={(event) => setDate(event.target.value)} /></div>
      </div>
      <div className="min-w-0"><Label htmlFor="priority-source">Relationship source version</Label><select id="priority-source" className={selectClass} required value={sourceId}
        disabled={sources.isPending || sources.isError} onChange={(event) => setSourceId(event.target.value)}>
        <option value="">Select source version</option>
        {options.map((option) => <option key={option.source.document_version_id} value={option.source.document_version_id}>{option.label}</option>)}
      </select></div>
      {sources.isError && <QueryErrorState title="Could not load relationship sources" error={sources.error} onRetry={sources.refetch} />}
      {sources.isSuccess && !options.length && <Button type="button" variant="secondary" onClick={onOpenDocuments}><FileText size={16} />Open documents</Button>}
      <div className="min-w-0"><Label htmlFor="priority-reason">Relationship change reason</Label><Textarea id="priority-reason" required minLength={8} maxLength={1000}
        value={reason} onChange={(event) => setReason(event.target.value)} /></div>
    </fieldset>
    {save.isError && <div className="min-w-0 space-y-2"><p role="alert" className="break-words text-sm text-danger-500">{apiErrorMessage(save.error, "The relationship could not be saved.")}</p>
      <Button type="button" variant="secondary" onClick={onReload}><RefreshCw size={16} />Reload records</Button></div>}
    <div className="flex min-w-0 flex-wrap gap-2">
      <Button type="submit" disabled={save.isPending || !parentId || !selected.isSuccess || selected.isFetching || !sources.isSuccess || !sourceId}>
        {save.isPending ? "Saving..." : withdrawn ? "Save withdrawal record" : "Save relationship"}</Button>
      <Button type="button" variant="ghost" disabled={save.isPending} onClick={onCancel}>Cancel</Button>
    </div>
  </form>;
}

export function PatentFamilyGraph({ familyId }: { familyId: string }) {
  const [applicationCursor, setApplicationCursor] = useState<string>();
  const [priorityCursor, setPriorityCursor] = useState<string>();
  const graph = useQuery({ queryKey: ["ip", "patent-family-graph", familyId, applicationCursor, priorityCursor],
    queryFn: ({ signal }) => fetchPatentFamilyGraph(familyId, applicationCursor, priorityCursor, signal) });
  const reset = () => { setApplicationCursor(undefined); setPriorityCursor(undefined); };
  return <section className="min-w-0 space-y-4 border-t border-line pt-4" aria-label="Patent family relationships">
    <h2 className="text-lg font-semibold">Family relationships</h2>
    {graph.isPending ? <Skeleton className="h-32 w-full" /> : graph.isError
      ? <QueryErrorState title="Could not load family relationships" error={graph.error} onRetry={() => {
        if (applicationCursor || priorityCursor) reset(); else void graph.refetch();
      }} /> : <>
        <h3 className="font-semibold">Applications</h3>
        <ul className="min-w-0 divide-y divide-line" aria-label="Family graph applications">
          {graph.data.applications.map((application) => <li key={application.id} className="min-w-0 py-3">
            <Link className="break-words font-medium text-brand-700 hover:underline" href={`/app/ip/patents/applications/${application.id}`}>{application.facts.title}</Link>
            <p className="break-words text-sm capitalize">{application.facts.application_kind.replaceAll("_", " ")} - {application.facts.jurisdiction} - {application.lifecycle_status}</p>
          </li>)}
        </ul>
        {!graph.data.applications.length && <p className="text-sm text-mute">No accessible applications on this page.</p>}
        <nav className="flex min-w-0 flex-wrap justify-between gap-2" aria-label="Graph application pages">
          <Button variant="ghost" disabled={!applicationCursor || graph.isFetching} onClick={() => setApplicationCursor(undefined)}><ArrowLeft size={16} />First applications</Button>
          <Button variant="ghost" disabled={!graph.data.has_more_applications || graph.isFetching} onClick={() => setApplicationCursor(graph.data!.applications_next_cursor!)}>Next applications<ArrowRight size={16} /></Button>
        </nav>
        <h3 className="font-semibold">Priority and parent links</h3>
        <ul className="min-w-0 divide-y divide-line" aria-label="Family graph links">
          {graph.data.priorities.map((priority) => <li key={priority.id} className="min-w-0 space-y-2 py-4">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <Link className="min-w-0 break-words font-medium text-brand-700 hover:underline" href={`/app/ip/patents/applications/${priority.application_id}`}>{priority.current_application_title}</Link>
              <ArrowRight size={16} className="shrink-0" aria-label="has parent" />
              <Link className="min-w-0 break-words font-medium text-brand-700 hover:underline" href={`/app/ip/patents/applications/${priority.parent_application_id}`}>{priority.current_parent_title}</Link>
            </div>
            <PriorityEvidence priority={priority} />
          </li>)}
        </ul>
        {!graph.data.priorities.length && <p className="text-sm text-mute">No recorded links on this page.</p>}
        <nav className="flex min-w-0 flex-wrap justify-between gap-2" aria-label="Graph relationship pages">
          <Button variant="ghost" disabled={!priorityCursor || graph.isFetching} onClick={() => setPriorityCursor(undefined)}><ArrowLeft size={16} />Latest links</Button>
          <Button variant="ghost" disabled={!graph.data.has_more_relationships || graph.isFetching} onClick={() => setPriorityCursor(graph.data!.priorities_next_cursor!)}>Older links<ArrowRight size={16} /></Button>
        </nav>
      </>}
  </section>;
}
