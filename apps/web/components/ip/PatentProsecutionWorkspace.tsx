"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, FilePlus2, Plus, Save, Trash2 } from "lucide-react";
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
import {
  createPatentEvidence, createPatentProsecution, fetchPatentEvidence, fetchPatentProsecution,
  patentDocumentKinds, patentEventKinds, previewPatentProsecution,
  type PatentEvidence, type PatentEvidenceInput, type PatentEventInput, type PatentProsecution, type PatentProsecutionPreview,
} from "@/lib/api/ip-patent-prosecution";
import { type PatentApplication } from "@/lib/api/ip-patents";

const selectClass = "h-10 w-full min-w-0 rounded-sm border border-line bg-surface px-3 text-sm";
const label = (value: string) => value.replaceAll("_", " ");
const workKey = (id: string) => ["ip", "patent-work", id];

export function PatentProsecutionWorkspace({ application, canWrite, area, onOpenDocuments }: {
  application: PatentApplication; canWrite: boolean; area: "evidence" | "prosecution"; onOpenDocuments: () => void;
}) {
  const cache = useQueryClient();
  const [page, setPage] = useState<{ cursor?: number; snapshot?: number }>({});
  const [creating, setCreating] = useState(false);
  const [predecessor, setPredecessor] = useState<PatentEvidence>();
  const [success, setSuccess] = useState("");
  const evidence = useQuery({ queryKey: [...workKey(application.id), "evidence", page],
    queryFn: ({ signal }) => fetchPatentEvidence(application.id, page.cursor, page.snapshot, signal), enabled: area === "evidence" });
  const prosecution = useQuery({ queryKey: [...workKey(application.id), "prosecution", page],
    queryFn: ({ signal }) => fetchPatentProsecution(application.id, page.cursor, page.snapshot, signal), enabled: area === "prosecution" });
  const query = area === "evidence" ? evidence : prosecution;
  const sequence = query.data?.work_sequence;
  const editable = canWrite && application.is_active && sequence !== undefined && !query.isError;
  async function saved(record: PatentEvidence | PatentProsecution) {
    await cache.cancelQueries({ queryKey: workKey(application.id) });
    if ("edition" in record) {
      cache.setQueryData([...workKey(application.id), "evidence", {}], (old: Awaited<ReturnType<typeof fetchPatentEvidence>> | undefined) => ({
        application_id: application.id, work_sequence: record.sequence, next_cursor: old?.next_cursor ?? null,
        records: [record, ...(old?.records ?? []).filter((row) => row.id !== record.id).slice(0, 24)],
      }));
    } else {
      cache.setQueryData([...workKey(application.id), "prosecution", {}], (old: Awaited<ReturnType<typeof fetchPatentProsecution>> | undefined) => ({
        application_id: application.id, work_sequence: record.sequence, next_cursor: old?.next_cursor ?? null,
        records: [record, ...(old?.records ?? []).filter((row) => row.id !== record.id).slice(0, 24)],
      }));
    }
    setPage({}); setCreating(false); setPredecessor(undefined); setSuccess("Patent evidence saved.");
    await cache.invalidateQueries({ queryKey: workKey(application.id) });
    await cache.invalidateQueries({ queryKey: ["ip", "patent-application", application.id] });
  }
  return <section aria-label={area === "evidence" ? "Patent work product" : "Patent prosecution"} className="min-w-0 space-y-4 border-t border-line pt-4">
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
      <h2 className="text-lg font-semibold">{area === "evidence" ? "Work product" : "Prosecution"}</h2>
      {editable && !creating && <Button onClick={() => { setCreating(true); setSuccess(""); }}><Plus size={16} />{area === "evidence" ? "Prepare edition" : "Record event"}</Button>}
    </div>
    {success && <p role="status" className="text-sm">{success}</p>}
    {area === "prosecution" && <p className="text-sm capitalize">Current phase: {label(application.prosecution_phase)}</p>}
    {creating && canWrite && application.is_active && sequence !== undefined && <PatentWorkForm application={application} area={area} sequence={sequence} predecessor={predecessor}
      onSaved={saved} onCancel={() => { setCreating(false); setPredecessor(undefined); }} onOpenDocuments={onOpenDocuments} />}
    {query.isPending ? <Skeleton className="h-32 w-full" /> : query.isError
      ? <QueryErrorState title="Could not load patent work" error={query.error} onRetry={query.refetch} />
      : <>
        {area === "evidence" && <ul className="divide-y divide-line border-y border-line" aria-label="Patent document editions">
          {evidence.data?.records.map((row) => <li key={row.id} className="min-w-0 space-y-3 py-4">
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1 basis-60"><h3 className="break-words font-semibold">{row.title}</h3>
                <p className="text-sm capitalize text-mute">{label(row.document_kind)} · Edition {row.edition} · Application version {row.anchor_version}</p></div>
              {editable && !creating && row.is_current && row.lifecycle_version === application.lifecycle_version && <Button variant="ghost" onClick={() => {
                setPredecessor(row); setCreating(true); setSuccess("");
              }}><FilePlus2 size={16} />New edition</Button>}
            </div>
            <ul className="min-w-0 space-y-2" aria-label={`${row.title} manifest`}>
              {row.documents.map((item) => <li key={item.source.document_version_id} className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                <span className="text-sm capitalize">{label(item.document_kind)}</span><PatentSourceDownload source={item.source} />
              </li>)}
            </ul>
            <p className="break-words text-sm">{row.reason}</p>
          </li>)}
        </ul>}
        {area === "prosecution" && <ol className="divide-y divide-line border-y border-line" aria-label="Patent prosecution history">
          {prosecution.data?.records.map((row) => <li key={row.id} className="min-w-0 space-y-2 py-4">
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
              <h3 className="min-w-0 flex-1 basis-48 break-words font-semibold capitalize">{label(row.event_kind)}</h3>
              <time className="text-sm" dateTime={row.effective_on}>{row.effective_on}</time>
            </div>
            <p className="text-sm capitalize">{label(row.before_phase)} to {label(row.after_phase)}</p>
            <p className="break-words text-sm">{row.reason}</p>
            {row.impact.backdated && <p className="text-sm">Backdated impact acknowledged. Existing deadlines retained.</p>}
            <PatentSourceDownload source={row.source} />
          </li>)}
        </ol>}
        {!query.data?.records.length && <p className="text-sm text-mute">{area === "evidence" ? "No prepared editions recorded." : "No prosecution events recorded."}</p>}
        <div className="flex min-w-0 flex-wrap justify-between gap-2">
          <Button variant="ghost" disabled={!page.cursor} onClick={() => setPage({})}><ArrowLeft size={16} />First page</Button>
          <Button variant="ghost" disabled={!query.data?.next_cursor} onClick={() => setPage({ cursor: query.data?.next_cursor ?? undefined, snapshot: sequence })}>Next page<ArrowRight size={16} /></Button>
        </div>
      </>}
  </section>;
}

function PatentWorkForm({ application, area, sequence, predecessor, onSaved, onCancel, onOpenDocuments }: {
  application: PatentApplication; area: "evidence" | "prosecution"; sequence: number; predecessor?: PatentEvidence;
  onSaved: (record: PatentEvidence | PatentProsecution) => Promise<void>; onCancel: () => void; onOpenDocuments: () => void;
}) {
  const observed = useRef({ application, sequence });
  const commandKey = useRef<string | null>(null);
  const [title, setTitle] = useState(predecessor?.title ?? "");
  const [kind, setKind] = useState<PatentEvidenceInput["document_kind"]>(predecessor?.document_kind ?? "filing_package");
  const [eventKind, setEventKind] = useState<PatentEventInput["event_kind"]>("filing_preparation");
  const [sourceId, setSourceId] = useState(predecessor?.source.document_version_id ?? "");
  const [documents, setDocuments] = useState<{ kind: PatentEvidenceInput["document_kind"]; version: string }[]>(
    predecessor?.documents.map((item) => ({ kind: item.document_kind, version: item.source.document_version_id })) ?? [{ kind: "claims", version: "" }]);
  const [reason, setReason] = useState("");
  const [exceptionReason, setExceptionReason] = useState("");
  const [effective, setEffective] = useState("");
  const [received, setReceived] = useState("");
  const [packageId, setPackageId] = useState("");
  const [review, setReview] = useState<{ payload: PatentEventInput; impact: PatentProsecutionPreview }>();
  const [acknowledged, setAcknowledged] = useState(false);
  const [error, setError] = useState("");
  const [packagePage, setPackagePage] = useState<{ cursor?: number; snapshot?: number }>({});
  const sources = useQuery({ queryKey: ["ip", "documents", application.docket_id], queryFn: () => fetchIpDocumentsForDocket(application.docket_id) });
  const packages = useQuery({ queryKey: [...workKey(application.id), "choices", packagePage],
    queryFn: ({ signal }) => fetchPatentEvidence(application.id, packagePage.cursor, packagePage.snapshot, signal), enabled: area === "prosecution" });
  const options = sources.data?.items.flatMap((document) => document.versions.map((version) => ({
    label: `${document.title} - version ${version.version}`, pin: { kind: "document_version" as const,
      document_id: document.id, document_version_id: version.id, content_sha256: version.sha256_hex },
  }))) ?? [];
  const selectedSource = options.find((item) => item.pin.document_version_id === sourceId)?.pin;
  const preconditions = () => ({ expected_version: observed.current.application.version,
    expected_lifecycle_version: observed.current.application.lifecycle_version,
    expected_work_sequence: observed.current.sequence, reason });
  const mutation = useMutation({ mutationFn: async () => {
    setError("");
    if (!selectedSource) throw new Error("Select an accessible exact source version.");
    if (area === "evidence") {
      const manifest = documents.map((item) => {
        const source = options.find((option) => option.pin.document_version_id === item.version)?.pin;
        if (!source) throw new Error("Select every manifest document version.");
        return { document_kind: item.kind, source };
      });
      commandKey.current ??= crypto.randomUUID();
      const record = await createPatentEvidence(application.id, { ...preconditions(), title, document_kind: kind,
        predecessor_id: predecessor?.id ?? null, source: selectedSource, documents: manifest }, commandKey.current);
      await onSaved(record);
    } else {
      const payload: PatentEventInput = { ...preconditions(), event_kind: eventKind, received_on: received, effective_on: effective,
        source: selectedSource, evidence_id: packageId || null, expected_phase: observed.current.application.prosecution_phase,
        exceptional_transition_reason: exceptionReason || null };
      const impact = await previewPatentProsecution(application.id, payload);
      setReview({ payload, impact }); setAcknowledged(false);
    }
  }, onError: (failure) => setError(apiErrorMessage(failure, "Patent evidence could not be saved.")) });
  const commit = useMutation({ mutationFn: async () => {
    if (!review) return;
    commandKey.current ??= crypto.randomUUID();
    const record = await createPatentProsecution(application.id, { ...review.payload, preview_sha256: review.impact.preview_sha256,
      acknowledged_exception_codes: review.impact.required_acknowledgements }, commandKey.current);
    await onSaved(record);
  }, onError: (failure) => setError(apiErrorMessage(failure, "The prosecution event could not be saved.")) });
  const busy = mutation.isPending || commit.isPending;
  function invalidateReview() { setReview(undefined); setAcknowledged(false); commandKey.current = null; setError(""); }
  const sourceOptions = <><option value="">Select document version</option>{options.map((option) => <option key={option.pin.document_version_id} value={option.pin.document_version_id}>{option.label}</option>)}</>;
  return <form aria-label={area === "evidence" ? "Prepare patent edition" : "Record patent event"} className="min-w-0 space-y-4 border-y border-line py-4"
    onChange={invalidateReview} onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
    <fieldset disabled={busy} className="min-w-0 space-y-4">
      {sources.isPending ? <Skeleton className="h-10 w-full" /> : sources.isError
        ? <QueryErrorState title="Could not load source documents" error={sources.error} onRetry={sources.refetch} />
        : <div className="grid min-w-0 gap-4 sm:grid-cols-2">
          <div className="min-w-0"><Label htmlFor="patent-work-source">Source evidence</Label><select id="patent-work-source" className={selectClass} value={sourceId} required onChange={(event) => setSourceId(event.target.value)}>{sourceOptions}</select></div>
          <div className="flex min-w-0 items-end"><Button type="button" variant="ghost" onClick={onOpenDocuments}><Plus size={16} />Upload source</Button></div>
        </div>}
      {area === "evidence" ? <>
        <div className="grid min-w-0 gap-4 sm:grid-cols-2">
          <div className="min-w-0"><Label htmlFor="patent-work-title">Edition title</Label><Input id="patent-work-title" value={title} onChange={(event) => setTitle(event.target.value)} maxLength={255} required /></div>
          <div className="min-w-0"><Label htmlFor="patent-work-kind">Work product</Label><select id="patent-work-kind" className={selectClass} value={kind} disabled={!!predecessor} onChange={(event) => {
            const next = event.target.value as typeof kind; setKind(next);
            if (next !== "filing_package") setDocuments([{ kind: next, version: documents[0]?.version ?? "" }]);
          }}>{patentDocumentKinds.map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></div>
        </div>
        {documents.map((item, index) => <div key={index} className="flex min-w-0 flex-wrap items-end gap-2">
          <div className="min-w-0 flex-1 basis-48"><Label htmlFor={`manifest-kind-${index}`}>Document kind {index + 1}</Label><select id={`manifest-kind-${index}`} className={selectClass} value={item.kind} disabled={kind !== "filing_package"} onChange={(event) => setDocuments(documents.map((row, ordinal) => ordinal === index ? { ...row, kind: event.target.value as typeof kind } : row))}>
            {patentDocumentKinds.filter((value) => value !== "filing_package").map((value) => <option key={value} value={value}>{label(value)}</option>)}
          </select></div>
          <div className="min-w-0 flex-1 basis-64"><Label htmlFor={`manifest-source-${index}`}>Exact version {index + 1}</Label><select id={`manifest-source-${index}`} className={selectClass} value={item.version} required onChange={(event) => setDocuments(documents.map((row, ordinal) => ordinal === index ? { ...row, version: event.target.value } : row))}>{sourceOptions}</select></div>
          {documents.length > 1 && <Button type="button" variant="ghost" aria-label={`Remove document ${index + 1}`} title={`Remove document ${index + 1}`} onClick={() => { setDocuments(documents.filter((_, ordinal) => ordinal !== index)); invalidateReview(); }}><Trash2 size={16} /></Button>}
        </div>)}
        {kind === "filing_package" && documents.length < 20 && <Button type="button" variant="ghost" onClick={() => { setDocuments([...documents, { kind: "claims", version: "" }]); invalidateReview(); }}><Plus size={16} />Add document</Button>}
      </> : <>
        <div className="grid min-w-0 gap-4 sm:grid-cols-2">
          <div className="min-w-0"><Label htmlFor="patent-event-kind">Event</Label><select id="patent-event-kind" className={selectClass} value={eventKind} onChange={(event) => setEventKind(event.target.value as typeof eventKind)}>{patentEventKinds.map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></div>
          <div className="min-w-0"><Label htmlFor="patent-event-package">Exact work product</Label><select id="patent-event-package" className={selectClass} value={packageId} onChange={(event) => setPackageId(event.target.value)} required={["filing", "response", "amendment", "grant"].includes(eventKind)}>
            <option value="">Select work product</option>{packages.data?.records.filter((row) => row.is_current && row.anchor_version === application.version && row.lifecycle_version === application.lifecycle_version).map((row) => <option key={row.id} value={row.id}>{row.title} - edition {row.edition}</option>)}
          </select></div>
          <div className="min-w-0"><Label htmlFor="patent-event-received">Received date</Label><Input id="patent-event-received" type="date" value={received} onChange={(event) => setReceived(event.target.value)} required /></div>
          <div className="min-w-0"><Label htmlFor="patent-event-effective">Effective date</Label><Input id="patent-event-effective" type="date" value={effective} onChange={(event) => setEffective(event.target.value)} required /></div>
        </div>
        {packages.isError && <QueryErrorState title="Could not load filing manifests" error={packages.error} onRetry={packages.refetch} />}
        <div className="flex min-w-0 flex-wrap gap-2">
          <Button type="button" variant="ghost" disabled={!packagePage.cursor} onClick={() => { setPackageId(""); setPackagePage({}); invalidateReview(); }}><ArrowLeft size={16} />First manifests</Button>
          <Button type="button" variant="ghost" disabled={!packages.data?.next_cursor} onClick={() => { setPackageId(""); setPackagePage({ cursor: packages.data?.next_cursor ?? undefined, snapshot: packages.data?.work_sequence }); invalidateReview(); }}>More manifests<ArrowRight size={16} /></Button>
        </div>
        <div><Label htmlFor="patent-event-exception">Exceptional transition reason</Label><Textarea id="patent-event-exception" value={exceptionReason} maxLength={1000} onChange={(event) => setExceptionReason(event.target.value)} /></div>
      </>}
      <div><Label htmlFor="patent-work-reason">Reason</Label><Textarea id="patent-work-reason" value={reason} onChange={(event) => setReason(event.target.value)} minLength={5} maxLength={1000} required /></div>
    </fieldset>
    {error && <p role="alert" className="break-words text-sm text-danger-700">{error}</p>}
    {review && <section aria-label="Prosecution impact" className="min-w-0 space-y-3 border-y border-line py-3">
      <h3 className="font-semibold">Prosecution impact</h3><p className="text-sm capitalize">{label(review.impact.current_phase)} to {label(review.impact.proposed_phase)}</p>
      {review.impact.required_acknowledgements.length > 0 && <label className="flex min-w-0 items-start gap-3 py-2 text-sm">
        <input type="checkbox" className="mt-1 size-4 shrink-0" checked={acknowledged} onChange={(event) => { event.stopPropagation(); setAcknowledged(event.target.checked); }} />
        <span className="min-w-0 break-words">I reviewed {review.impact.required_acknowledgements.map((code) => code === "backdated_recalculation_review_required" ? "the backdated event" : "the exceptional transition").join(" and ")} and {review.impact.affected_deadline_ids.length} affected deadlines. No deadline will change automatically.</span>
      </label>}
      <Button type="button" disabled={busy || (!!review.impact.required_acknowledgements.length && !acknowledged)} onClick={() => commit.mutate()}><Save size={16} />Record reviewed event</Button>
    </section>}
    <div className="flex min-w-0 flex-wrap gap-2"><Button type="submit" disabled={busy || sources.isPending || sources.isError}><Save size={16} />{area === "evidence" ? "Save edition" : "Preview event"}</Button>
      <Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>Cancel</Button></div>
  </form>;
}
