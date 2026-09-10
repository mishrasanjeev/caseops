"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Plus, Save } from "lucide-react";
import { useRef, useState } from "react";

import { PatentSourceDownload } from "@/components/ip/PatentSourceDownload";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import { fetchIpDocumentsForDocket } from "@/lib/api/endpoints";
import { fetchPatentEvidence } from "@/lib/api/ip-patent-prosecution";
import {
  createPatentProceeding, fetchPatentProceedingHistory, fetchPatentProceedings, patentProceedingStages,
  previewPatentProceeding, transitionPatentProceeding,
  type PatentProceeding, type PatentProceedingPreview, type PatentProceedingTransitionInput,
} from "@/lib/api/ip-patent-proceedings";
import { type PatentApplication } from "@/lib/api/ip-patents";

const label = (value: string) => value.replaceAll("_", " ");
const key = (id: string) => ["ip", "patent-proceedings", id];
const selectClass = "h-10 w-full min-w-0 rounded-sm border border-line bg-surface px-3 text-sm";

export function PatentProceedingsWorkspace({ application, canWrite, onOpenDocuments }: {
  application: PatentApplication; canWrite: boolean; onOpenDocuments: () => void;
}) {
  const cache = useQueryClient();
  const [page, setPage] = useState<{ cursor?: string; snapshot?: number }>({});
  const [selected, setSelected] = useState<string>();
  const [editing, setEditing] = useState(false);
  const [success, setSuccess] = useState("");
  const query = useQuery({ queryKey: [...key(application.id), "list", page],
    queryFn: ({ signal }) => fetchPatentProceedings(application.id, page.cursor, page.snapshot, signal) });
  const history = useQuery({ queryKey: [...key(application.id), "history", selected], enabled: !!selected,
    queryFn: ({ signal }) => fetchPatentProceedingHistory(application.id, selected!, signal) });
  const record = history.data?.proceeding;
  const editable = canWrite && application.is_active;
  const ready = editable && query.data !== undefined && !query.isError && (!selected || (!!record && !history.isError));
  async function saved(result: PatentProceeding) {
    await cache.cancelQueries({ queryKey: key(application.id) });
    cache.setQueryData([...key(application.id), "history", result.id], (old: Awaited<ReturnType<typeof fetchPatentProceedingHistory>> | undefined) => ({
      proceeding: result, events: [...(old?.events ?? []).filter((event) => event.id !== result.latest.id), result.latest],
    }));
    cache.setQueryData([...key(application.id), "list", {}], (old: Awaited<ReturnType<typeof fetchPatentProceedings>> | undefined) => ({
      application_id: application.id, work_sequence: result.latest.sequence, next_cursor: old?.next_cursor ?? null,
      records: [result, ...(old?.records ?? []).filter((row) => row.id !== result.id)].slice(0, 25),
    }));
    setEditing(false); setSelected(result.id); setPage({}); setSuccess("Patent proceeding saved.");
    await cache.invalidateQueries({ queryKey: key(application.id) });
    await cache.invalidateQueries({ queryKey: ["ip", "patent-work", application.id] });
    await cache.invalidateQueries({ queryKey: ["ip", "patent-application", application.id] });
  }
  return <section aria-label="Patent proceedings" className="min-w-0 space-y-4 border-t border-line pt-4">
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-semibold">Proceedings</h2>
      {ready && !editing && !selected && application.prosecution_phase !== "granted" && application.facts.jurisdiction === "IN" && application.facts.office === "IP India" && <Button onClick={() => { setEditing(true); setSuccess(""); }}><Plus size={16} />New pre-grant opposition</Button>}
      {selected && <Button variant="ghost" onClick={() => { setSelected(undefined); setEditing(false); setSuccess(""); }}><ArrowLeft size={16} />All proceedings</Button>}
    </div>
    {success && <p role="status" className="text-sm">{success}</p>}
    {query.isError && <QueryErrorState title="Could not load proceedings" error={query.error} onRetry={query.refetch} />}
    {selected && history.isError && <QueryErrorState title="Could not load proceeding history" error={history.error} onRetry={history.refetch} />}
    {editing && editable && query.data && (!selected || record?.operational) && <ProceedingForm key={selected ?? "intake"}
      application={application} sequence={query.data.work_sequence} record={record} onSaved={saved}
      onCancel={() => setEditing(false)} onOpenDocuments={onOpenDocuments} />}
    {selected ? history.isPending ? <Skeleton className="h-32 w-full" /> : record && <>
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 basis-64"><h3 className="break-words font-semibold">{record.title}</h3>
          <p className="break-words text-sm">{record.counterparty} | {record.office} | {record.jurisdiction}</p>
          <p className="text-sm capitalize">Representing {record.side} | {label(record.stage)}</p>
          <p className="break-words text-sm">{record.latest.proceeding_number ?? "Number allocation pending"}</p>
          {!record.operational && <p className="text-sm text-mute">Read-only proceeding</p>}
        </div>
        {ready && record.operational && !editing && <Button onClick={() => { setEditing(true); setSuccess(""); }}><Plus size={16} />Update proceeding</Button>}
      </div>
      <ol aria-label="Proceeding stage history" className="min-w-0 divide-y divide-line border-y border-line">
        {history.data?.events.map((event) => <li key={event.id} className="min-w-0 space-y-2 py-4">
          <div className="flex min-w-0 flex-wrap justify-between gap-2"><h4 className="min-w-0 flex-1 basis-48 font-semibold capitalize">{label(event.after_stage)}</h4><time dateTime={event.effective_on} className="text-sm">{event.effective_on}</time></div>
          <p className="break-words text-sm">{event.reason}</p>
          {event.outcome && <p className="break-words text-sm">{event.outcome}</p>}
          {event.impact?.required_acknowledgements.length ? <p className="text-sm">Source review acknowledged: {event.impact.required_acknowledgements.map(label).join(", ")}</p> : null}
          <PatentSourceDownload source={event.source} />
        </li>)}
      </ol>
    </> : query.isPending ? <Skeleton className="h-32 w-full" /> : <>
      <ul aria-label="Patent proceeding list" className="min-w-0 divide-y divide-line border-y border-line">
        {query.data?.records.map((row) => <li key={row.id} className="min-w-0 py-4"><button type="button" className="w-full min-w-0 space-y-1 text-left" onClick={() => { setSelected(row.id); setEditing(false); setSuccess(""); }}>
          <span className="block break-words font-semibold underline underline-offset-4">{row.title}</span>
          <span className="block break-words text-sm">{row.latest.proceeding_number ?? "Number allocation pending"} | {row.counterparty}</span>
          <span className="block text-sm capitalize text-mute">{label(row.stage)}{!row.operational ? " | Read-only" : ""}</span>
        </button></li>)}
      </ul>
      {!query.data?.records.length && !query.isError && <p className="text-sm text-mute">No patent proceedings recorded.</p>}
      <div className="flex min-w-0 flex-wrap justify-between gap-2"><Button variant="ghost" disabled={!page.cursor || editing} onClick={() => setPage({})}><ArrowLeft size={16} />First page</Button>
        <Button variant="ghost" disabled={!query.data?.next_cursor || editing} onClick={() => setPage({ cursor: query.data?.next_cursor ?? undefined, snapshot: query.data?.work_sequence })}>Next page<ArrowRight size={16} /></Button></div>
    </>}
  </section>;
}

function ProceedingForm({ application, sequence, record, onSaved, onCancel, onOpenDocuments }: {
  application: PatentApplication; sequence: number; record?: PatentProceeding;
  onSaved: (record: PatentProceeding) => Promise<void>; onCancel: () => void; onOpenDocuments: () => void;
}) {
  const observed = useRef({ application, sequence, record });
  const commandKey = useRef<string | null>(null);
  const [title, setTitle] = useState(""); const [counterparty, setCounterparty] = useState("");
  const [side, setSide] = useState<"applicant" | "opponent">("applicant");
  const [number, setNumber] = useState(record?.latest.proceeding_number ?? "");
  const [pending, setPending] = useState(true);
  const [sourceId, setSourceId] = useState(""); const [reason, setReason] = useState("");
  const [received, setReceived] = useState(""); const [effective, setEffective] = useState("");
  const [stage, setStage] = useState<PatentProceeding["stage"]>(record?.allowed_stages[0] ?? "response_preparation");
  const [manifestId, setManifestId] = useState(""); const [outcome, setOutcome] = useState("");
  const [exception, setException] = useState(""); const [error, setError] = useState("");
  const [review, setReview] = useState<{ payload: PatentProceedingTransitionInput; impact: PatentProceedingPreview }>();
  const [ack, setAck] = useState(false);
  const [manifestPage, setManifestPage] = useState<{ cursor?: number; snapshot?: number }>({});
  const sources = useQuery({ queryKey: ["ip", "documents", application.docket_id], queryFn: () => fetchIpDocumentsForDocket(application.docket_id) });
  const manifests = useQuery({ queryKey: ["ip", "patent-work", application.id, "choices", manifestPage],
    queryFn: ({ signal }) => fetchPatentEvidence(application.id, manifestPage.cursor, manifestPage.snapshot, signal), enabled: !!record });
  const options = sources.data?.items.flatMap((document) => document.versions.map((version) => ({
    title: `${document.title} - version ${version.version}`, pin: { kind: "document_version" as const,
      document_id: document.id, document_version_id: version.id, content_sha256: version.sha256_hex },
  }))) ?? [];
  function invalidate() { setReview(undefined); setAck(false); setError(""); commandKey.current = null; }
  const prepare = useMutation({ mutationFn: async () => {
    setError("");
    const source = options.find((option) => option.pin.document_version_id === sourceId)?.pin;
    if (!source) throw new Error("Select an accessible source version.");
    const base = { expected_version: observed.current.application.version,
      expected_lifecycle_version: observed.current.application.lifecycle_version,
      expected_work_sequence: observed.current.sequence, source, reason, received_on: received,
      effective_on: effective, proceeding_number: number || null };
    if (!record) {
      commandKey.current ??= crypto.randomUUID();
      await onSaved(await createPatentProceeding(application.id, { ...base, title, counterparty, side,
        proceeding_kind: "patent_pre_grant_opposition", source_pending_identifier_allocation: pending }, commandKey.current));
    } else {
      const payload: PatentProceedingTransitionInput = { ...base,
        expected_proceeding_version: observed.current.record!.version, to_stage: stage,
        evidence_id: manifestId || null, outcome: ["decided", "withdrawn"].includes(stage) ? outcome || null : null,
        exceptional_transition_reason: exception || null };
      const impact = await previewPatentProceeding(application.id, record.id, payload);
      setReview({ payload, impact }); setAck(false);
    }
  }, onError: (failure) => setError(apiErrorMessage(failure, "The proceeding could not be saved.")) });
  const commit = useMutation({ mutationFn: async () => {
    if (!review || !record) return;
    commandKey.current ??= crypto.randomUUID();
    await onSaved(await transitionPatentProceeding(application.id, record.id, { ...review.payload,
      preview_sha256: review.impact.preview_sha256, acknowledged_exception_codes: review.impact.required_acknowledgements }, commandKey.current));
  }, onError: (failure) => setError(apiErrorMessage(failure, "The proceeding stage could not be saved.")) });
  const busy = prepare.isPending || commit.isPending;
  return <form aria-label={record ? "Update patent proceeding" : "New patent proceeding"} className="min-w-0 space-y-4 border-y border-line py-4"
    onChange={invalidate} onSubmit={(event) => { event.preventDefault(); prepare.mutate(); }}>
    <fieldset disabled={busy} className="min-w-0 space-y-4">
      {!record && <div className="grid min-w-0 gap-4 sm:grid-cols-2">
        <div className="min-w-0"><Label htmlFor="pg-title">Proceeding title</Label><Input id="pg-title" value={title} onChange={(e) => setTitle(e.target.value)} minLength={2} maxLength={255} required /></div>
        <div className="min-w-0"><Label htmlFor="pg-counterparty">Counterparty</Label><Input id="pg-counterparty" value={counterparty} onChange={(e) => setCounterparty(e.target.value)} minLength={2} maxLength={255} required /></div>
        <div className="min-w-0"><Label htmlFor="pg-side">Representing</Label><select id="pg-side" className={selectClass} value={side} onChange={(e) => setSide(e.target.value as typeof side)}><option value="applicant">Applicant</option><option value="opponent">Opponent</option></select></div>
      </div>}
      <div className="grid min-w-0 gap-4 sm:grid-cols-2">
        <div className="min-w-0"><Label htmlFor="pg-number">Proceeding number</Label><Input id="pg-number" value={number} onChange={(e) => setNumber(e.target.value)} maxLength={160} disabled={!!record?.latest.proceeding_number || (!record && pending)} required={!record && !pending} /></div>
        {!record && <label className="flex min-w-0 items-center gap-3 text-sm"><input type="checkbox" className="size-4 shrink-0" checked={pending} onChange={(e) => { setPending(e.target.checked); setNumber(""); }} /><span className="min-w-0">Source confirms number allocation pending</span></label>}
        <div className="min-w-0"><Label htmlFor="pg-source">Proceeding source</Label><select id="pg-source" className={selectClass} value={sourceId} onChange={(e) => setSourceId(e.target.value)} required><option value="">Select document version</option>{options.map((option) => <option key={option.pin.document_version_id} value={option.pin.document_version_id}>{option.title}</option>)}</select></div>
        <div className="flex min-w-0 items-end"><Button type="button" variant="ghost" onClick={onOpenDocuments}><Plus size={16} />Upload source</Button></div>
        <div className="min-w-0"><Label htmlFor="pg-received">Received date</Label><Input id="pg-received" type="date" value={received} onChange={(e) => setReceived(e.target.value)} required /></div>
        <div className="min-w-0"><Label htmlFor="pg-effective">Effective date</Label><Input id="pg-effective" type="date" value={effective} onChange={(e) => setEffective(e.target.value)} required /></div>
      </div>
      {sources.isError && <QueryErrorState title="Could not load source documents" error={sources.error} onRetry={sources.refetch} />}
      {record && <>
        <div className="grid min-w-0 gap-4 sm:grid-cols-2">
          <div className="min-w-0"><Label htmlFor="pg-stage">Proceeding stage</Label><select id="pg-stage" className={selectClass} value={stage} onChange={(e) => setStage(e.target.value as typeof stage)}>{patentProceedingStages.filter((value) => value !== "notice_recorded").map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></div>
          <div className="min-w-0"><Label htmlFor="pg-manifest">Exact response manifest</Label><select id="pg-manifest" className={selectClass} value={manifestId} required={stage === "response_filed"} onChange={(e) => setManifestId(e.target.value)}><option value="">Select response manifest</option>{manifests.data?.records.filter((row) => row.is_current && row.anchor_version === application.version && row.lifecycle_version === application.lifecycle_version && ["response", "filing_package"].includes(row.document_kind)).map((row) => <option key={row.id} value={row.id}>{row.title} - edition {row.edition}</option>)}</select></div>
        </div>
        {manifests.isError && <QueryErrorState title="Could not load response manifests" error={manifests.error} onRetry={manifests.refetch} />}
        <div className="flex min-w-0 flex-wrap gap-2"><Button type="button" variant="ghost" disabled={!manifestPage.cursor} onClick={() => { setManifestPage({}); setManifestId(""); invalidate(); }}><ArrowLeft size={16} />First manifests</Button><Button type="button" variant="ghost" disabled={!manifests.data?.next_cursor} onClick={() => { setManifestPage({ cursor: manifests.data?.next_cursor ?? undefined, snapshot: manifests.data?.work_sequence }); setManifestId(""); invalidate(); }}>More manifests<ArrowRight size={16} /></Button></div>
        {["decided", "withdrawn"].includes(stage) && <div><Label htmlFor="pg-outcome">Outcome</Label><Textarea id="pg-outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)} minLength={5} maxLength={1000} required /></div>}
        <div><Label htmlFor="pg-exception">Exceptional stage reason</Label><Textarea id="pg-exception" value={exception} onChange={(e) => setException(e.target.value)} maxLength={1000} /></div>
      </>}
      <div><Label htmlFor="pg-reason">Reason</Label><Textarea id="pg-reason" value={reason} onChange={(e) => setReason(e.target.value)} minLength={5} maxLength={1000} required /></div>
    </fieldset>
    {error && <p role="alert" className="break-words text-sm text-danger-700">{error}</p>}
    {review && <section aria-label="Proceeding impact" className="min-w-0 space-y-3 border-y border-line py-3">
      <p className="text-sm capitalize">{label(review.impact.current_stage)} to {label(review.impact.proposed_stage)}</p>
      {!!review.impact.required_acknowledgements.length && <label className="flex min-w-0 items-start gap-3 text-sm"><input type="checkbox" className="mt-1 size-4 shrink-0" checked={ack} onChange={(e) => { e.stopPropagation(); setAck(e.target.checked); }} /><span className="min-w-0 break-words">I reviewed {review.impact.required_acknowledgements.map((code) => code === "backdated_source_review" ? "the backdated source" : "the exceptional stage") .join(" and ")}. Application phase and deadlines remain unchanged.</span></label>}
      <Button type="button" disabled={busy || (!!review.impact.required_acknowledgements.length && !ack)} onClick={() => commit.mutate()}><Save size={16} />Record reviewed stage</Button>
    </section>}
    <div className="flex min-w-0 flex-wrap gap-2"><Button type="submit" disabled={busy || sources.isPending || sources.isError}><Save size={16} />{record ? "Preview stage" : "Save proceeding"}</Button><Button type="button" variant="ghost" disabled={busy} onClick={onCancel}>Cancel</Button></div>
  </form>;
}
