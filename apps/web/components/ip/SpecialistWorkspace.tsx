"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, Download, Eye, FileText, LockKeyhole, Pencil, Plus, Upload } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import { downloadApiFile, fetchIpDocument, fetchIpDocumentsForDocket, fetchIpDocumentTaxonomy,
  listClients, previewIpDocketLifecycle, transitionIpDocketLifecycle, type IpLifecycleInput } from "@/lib/api/endpoints";
import { fetchSpecialistContracts, fetchSpecialistObservations, fetchSpecialistRecord, fetchSpecialistRecords,
  saveSpecialistFacts, saveSpecialistObservation, specialistFactsSchema, specialistKey, uploadSpecialistSource,
  type SpecialistContract, type SpecialistObservation, type SpecialistRecord } from "@/lib/api/ip-specialist";
import { useCapability } from "@/lib/capabilities";
import { SpecialistWorkflows } from "@/components/ip/SpecialistWorkflows";

const selectClass = "h-10 w-full min-w-0 rounded-sm border border-line bg-surface px-3 text-sm";
const label = (value: string) => value.replaceAll("_", " ");
const errors = (error: unknown) => apiErrorMessage(error, "The record could not be saved.");

export function SpecialistIndex() {
  const canRead = useCapability("ip:read");
  const canWrite = useCapability("ip:write");
  const router = useRouter();
  const [domain, setDomain] = useState("design");
  const [closed, setClosed] = useState(false);
  const [cursor, setCursor] = useState<string>();
  const [creating, setCreating] = useState(false);
  const contracts = useQuery({ queryKey: ["ip", "specialist-contracts"], queryFn: ({ signal }) => fetchSpecialistContracts(signal), enabled: canRead });
  const records = useQuery({ queryKey: ["ip", "specialist-list", domain, closed, cursor],
    queryFn: ({ signal }) => fetchSpecialistRecords(domain, closed, cursor, signal), enabled: canRead && contracts.isSuccess });
  if (!canRead) return <p role="alert">Specialist records are not available with your current permissions.</p>;
  const contract = contracts.data?.find((row) => row.domain === domain);
  return <div className="flex min-w-0 flex-col gap-5">
    <Link href="/app/ip" className="inline-flex w-fit items-center gap-2 text-sm"><ArrowLeft size={16} />IP workspace</Link>
    <PageHeader title="Specialist IP" actions={canWrite && !creating ? <Button disabled={!contract?.intake_available} onClick={() => setCreating(true)}><Plus size={16} />New intake</Button> : null} />
    <div className="flex min-w-0 flex-wrap items-end gap-4">
      <div className="min-w-0 flex-1 basis-64"><Label htmlFor="specialist-domain">Domain</Label><select id="specialist-domain" className={selectClass} value={domain} disabled={!contracts.isSuccess || creating}
        onChange={(event) => { setDomain(event.target.value); setCursor(undefined); }}>{contracts.data?.map((row) => <option key={row.domain} value={row.domain}>{row.label}</option>)}</select></div>
      <label className="flex min-h-10 items-center gap-2 text-sm"><input type="checkbox" checked={closed} onChange={(event) => { setClosed(event.target.checked); setCursor(undefined); }} />Include closed records</label>
    </div>
    {contracts.isError && <QueryErrorState title="Could not load specialist domains" error={contracts.error} onRetry={contracts.refetch} />}
    {contract && <Badge tone="neutral">{contract.intake_available ? "Intake only" : "Intake unavailable"}</Badge>}
    {creating && contract && <SpecialistForm contract={contract} onCancel={() => setCreating(false)} onSaved={(record) => router.push(`/app/ip/specialist/${record.id}`)} />}
    {records.isError ? <QueryErrorState title="Could not load specialist records" error={records.error} onRetry={records.refetch} /> : records.isPending ? <p role="status">Loading records...</p> : <>
      <ul aria-label="Specialist records" className="divide-y divide-line border-y border-line">{records.data.records.map((row) => <li key={row.id} className="flex min-w-0 flex-wrap items-center justify-between gap-3 py-3">
        <Link href={`/app/ip/specialist/${row.id}`} className="min-w-0 flex-1 basis-64 break-words font-medium text-brand-700 hover:underline">{row.title}</Link>
        <span className="text-sm capitalize">{row.lifecycle_status} / Version {row.version}</span></li>)}</ul>
      {records.data.records.length === 0 && <p className="text-sm text-mute">No accessible specialist records on this page.</p>}
      <div className="flex min-w-0 flex-wrap justify-between gap-3"><Button variant="ghost" disabled={!cursor} onClick={() => setCursor(undefined)}><ArrowLeft size={16} />First page</Button>
        <Button variant="ghost" disabled={!records.data.next_cursor} onClick={() => setCursor(records.data.next_cursor ?? undefined)}>Next page<ArrowRight size={16} /></Button></div>
    </>}
  </div>;
}

export function SpecialistForm({ contract, initial: serverInitial, onSaved, onCancel }: {
  contract: SpecialistContract; initial?: SpecialistRecord; onSaved: (record: SpecialistRecord) => void; onCancel: () => void;
}) {
  const [initial] = useState(serverInitial);
  const key = useRef(crypto.randomUUID());
  const form = useRef<HTMLFormElement>(null);
  const clients = useQuery({ queryKey: ["clients"], queryFn: listClients });
  const save = useMutation({ mutationFn: async () => {
    const values = new FormData(form.current!);
    const details: Record<string, unknown> = { domain: contract.domain };
    for (const field of contract.fields) {
      const raw = values.get(field.key);
      details[field.key] = field.kind === "boolean" ? raw === "on" : raw || null;
    }
    const facts = specialistFactsSchema.parse({ title: values.get("title"), client_id: initial?.facts.client_id ?? values.get("client_id"),
      jurisdiction_as_supplied: values.get("jurisdiction_as_supplied"), details });
    return saveSpecialistFacts(facts, key.current, initial, String(values.get("reason") ?? ""));
  }, onSuccess: onSaved });
  const initialDetails = initial?.facts.details as Record<string, unknown> | undefined;
  return <form ref={form} aria-label={initial ? "Correct specialist intake" : "New specialist intake"} className="min-w-0 space-y-4 border-y border-line py-5" onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
    <fieldset disabled={save.isPending || !clients.isSuccess || !contract.intake_available} className="min-w-0 space-y-4">
      <div><Label htmlFor="specialist-title">Title</Label><Input id="specialist-title" name="title" required maxLength={255} defaultValue={initial?.facts.title} /></div>
      <div className="grid min-w-0 gap-4 sm:grid-cols-2"><div className="min-w-0"><Label htmlFor="specialist-client">Client</Label><select className={selectClass} id="specialist-client" name="client_id" required disabled={!!initial} defaultValue={initial?.facts.client_id ?? ""}>
        <option value="" disabled>Select a client</option>{clients.data?.clients.map((client) => <option key={client.id} value={client.id}>{client.name}</option>)}</select></div>
        <div className="min-w-0"><Label htmlFor="specialist-jurisdiction">Jurisdiction as supplied</Label><Input id="specialist-jurisdiction" name="jurisdiction_as_supplied" required maxLength={500} defaultValue={initial?.facts.jurisdiction_as_supplied} /></div></div>
      <div className="grid min-w-0 gap-4 sm:grid-cols-2">{contract.fields.map((field) => <div key={field.key} className={`min-w-0 ${field.kind === "textarea" ? "sm:col-span-2" : ""}`}>
        {field.kind === "boolean" ? <label className="flex min-w-0 items-center gap-2 text-sm">
          <input id={`specialist-${field.key}`} name={field.key} type="checkbox" className="h-4 w-4 shrink-0" defaultChecked={Boolean(initialDetails?.[field.key])} />
          <span className="min-w-0 break-words">{field.label}</span>
        </label> : <>
          <Label htmlFor={`specialist-${field.key}`}>{field.label}</Label>
          {field.kind === "select" ? <select className={selectClass} id={`specialist-${field.key}`} name={field.key} defaultValue={String(initialDetails?.[field.key] ?? field.options[0])}>{field.options.map((value) => <option key={value} value={value}>{label(value)}</option>)}</select>
            : field.kind === "textarea" ? <Textarea id={`specialist-${field.key}`} name={field.key} required={field.required} maxLength={field.max_length ?? undefined} defaultValue={String(initialDetails?.[field.key] ?? "")} />
              : <Input id={`specialist-${field.key}`} name={field.key} type={field.kind === "date" ? "date" : "text"} required={field.required} maxLength={field.max_length ?? undefined} defaultValue={String(initialDetails?.[field.key] ?? "")} />}
        </>}
      </div>)}</div>
      {initial && <div><Label htmlFor="specialist-reason">Correction reason</Label><Input id="specialist-reason" name="reason" required maxLength={500} /></div>}
      <div className="flex flex-wrap gap-3"><Button type="submit"><Check size={16} />{save.isPending ? "Saving..." : "Save intake"}</Button><Button variant="ghost" type="button" onClick={onCancel}>Cancel</Button></div>
    </fieldset>
    {clients.isError && <QueryErrorState title="Could not load clients" error={clients.error} onRetry={clients.refetch} />}
    {save.isError && <p role="alert" className="break-words text-sm text-danger-500">{errors(save.error)}</p>}
  </form>;
}

export function SpecialistDetail({ recordId }: { recordId: string }) {
  const canRead = useCapability("ip:read");
  const canWrite = useCapability("ip:write");
  const canUpload = useCapability("documents:upload");
  const canReview = useCapability("ip:approve");
  const queryClient = useQueryClient();
  const [area, setArea] = useState("intake");
  const [editing, setEditing] = useState(false);
  const [version, setVersion] = useState<number>();
  const record = useQuery({ queryKey: specialistKey(recordId), queryFn: ({ signal }) => fetchSpecialistRecord(recordId, undefined, signal), enabled: canRead });
  const historical = useQuery({ queryKey: [...specialistKey(recordId), "version", version],
    queryFn: ({ signal }) => fetchSpecialistRecord(recordId, version, signal), enabled: canRead && !!version });
  const contracts = useQuery({ queryKey: ["ip", "specialist-contracts"], queryFn: ({ signal }) => fetchSpecialistContracts(signal), enabled: canRead });
  async function saved(next: SpecialistRecord) {
    await queryClient.cancelQueries({ queryKey: specialistKey(recordId), exact: true });
    queryClient.setQueryData(specialistKey(recordId), next);
    setEditing(false); setVersion(undefined);
    await queryClient.invalidateQueries({ queryKey: specialistKey(recordId) });
    await queryClient.invalidateQueries({ queryKey: ["ip", "specialist-list"] });
  }
  if (!canRead) return <p role="alert">Specialist records are not available with your current permissions.</p>;
  if (record.isPending) return <p role="status">Loading specialist record...</p>;
  if (record.isError) return <QueryErrorState title="Could not open specialist record" error={record.error} onRetry={record.refetch} />;
  const current = record.data;
  const contract = contracts.data?.find((row) => row.domain === current.facts.details.domain);
  const shown = version ? historical.data : current;
  return <div className="flex min-w-0 flex-col gap-5">
    <Link href="/app/ip/specialist" className="inline-flex w-fit items-center gap-2 text-sm"><ArrowLeft size={16} />Specialist IP</Link>
    <PageHeader title={current.facts.title} className="[&>div:first-child]:min-w-0 [&_h1]:[overflow-wrap:anywhere]" actions={<Badge tone="neutral"><LockKeyhole size={12} />Restricted</Badge>} />
    <p className="text-sm capitalize">{label(current.facts.details.domain)} / {current.lifecycle_status} / Version {current.version}</p>
    <div role="tablist" aria-label="Specialist work areas" className="flex min-w-0 flex-wrap gap-2 border-b border-line pb-3">{["intake", ...(["design", "copyright", "licensing"].includes(current.facts.details.domain) ? ["workflows"] : []), "evidence", "lifecycle"].map((tab) => <Button key={tab} role="tab" aria-selected={area === tab} variant={area === tab ? "secondary" : "ghost"} onClick={() => { setArea(tab); setEditing(false); }}><FileText size={16} />{label(tab)}</Button>)}</div>
    {contracts.isError && <QueryErrorState title="Could not load domain contract" error={contracts.error} onRetry={contracts.refetch} />}
    {area === "intake" && <section className="min-w-0 space-y-4">
      {editing && contract ? <SpecialistForm contract={contract} initial={current} onSaved={saved} onCancel={() => setEditing(false)} /> : <>
        <div className="flex min-w-0 flex-wrap items-end gap-3"><div className="min-w-0 flex-1 basis-48"><Label htmlFor="specialist-version">Intake version</Label><Input id="specialist-version" type="number" min={1} max={current.version} value={version ?? current.version} onChange={(event) => {
          const selected = Number(event.target.value); if (selected >= 1 && selected <= current.version) setVersion(selected === current.version ? undefined : selected);
        }} /></div>{canWrite && current.is_active && !version && <Button variant="secondary" disabled={!contract?.intake_available} onClick={() => setEditing(true)}><Pencil size={16} />Correct intake</Button>}</div>
        {version && historical.isError && <QueryErrorState title="Could not load intake history" error={historical.error} onRetry={historical.refetch} />}
        {shown ? <dl aria-label="Saved intake facts" className="grid min-w-0 gap-4 border-y border-line py-4 sm:grid-cols-2">{Object.entries({ title: shown.facts.title, jurisdiction_as_supplied: shown.facts.jurisdiction_as_supplied, ...shown.facts.details }).map(([name, value]) => <div key={name} className="min-w-0"><dt className="text-sm capitalize text-mute">{label(name)}</dt><dd className="whitespace-pre-wrap break-words">{value === null || value === undefined ? "Not recorded" : typeof value === "boolean" ? value ? "Yes" : "No" : String(value)}</dd></div>)}</dl> : <p role="status">Loading intake history...</p>}
      </>}
    </section>}
    {area === "evidence" && <SpecialistEvidence record={current} contract={contract} canWrite={canWrite && current.is_active} canUpload={canUpload && current.is_active && !!contract?.intake_available} />}
    {area === "workflows" && <SpecialistWorkflows record={current} canWrite={canWrite && current.is_active && !!contract?.intake_available} onEvidence={() => setArea("evidence")} />}
    {area === "lifecycle" && <SpecialistLifecycle record={current} canReview={canReview} onSaved={saved} />}
  </div>;
}

function SourceDownload({ source }: { source: SpecialistObservation["source"] }) {
  const download = useMutation({ mutationFn: async () => {
    const document = await fetchIpDocument(source.document_id);
    const version = document.versions.find((row) => row.id === source.document_version_id && row.sha256_hex === source.content_sha256);
    if (!version) throw new Error("The exact source version is no longer available.");
    return downloadApiFile(`/api/ip/documents/${document.id}/versions/${version.version}/download`, version.display_name);
  } });
  return <div><Button variant="ghost" disabled={download.isPending} onClick={() => download.mutate()}><Download size={16} />Source version</Button>
    {download.isError && <p role="alert">{errors(download.error)}</p>}</div>;
}

function SpecialistEvidence({ record, contract, canWrite, canUpload }: { record: SpecialistRecord; contract?: SpecialistContract; canWrite: boolean; canUpload: boolean }) {
  const queryClient = useQueryClient();
  const [cursor, setCursor] = useState<number>();
  const [file, setFile] = useState<File | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [taxonomy, setTaxonomy] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [kind, setKind] = useState("");
  const [day, setDay] = useState("");
  const [account, setAccount] = useState("");
  const [locator, setLocator] = useState("");
  const [supersedes, setSupersedes] = useState<string | null>(null);
  const intentKey = useRef(crypto.randomUUID());
  const documentKey = ["ip", "documents", record.docket_id];
  const documents = useQuery({ queryKey: documentKey, queryFn: () => fetchIpDocumentsForDocket(record.docket_id) });
  const types = useQuery({ queryKey: ["ip", "document-taxonomy"], queryFn: fetchIpDocumentTaxonomy, enabled: canUpload });
  const history = useQuery({ queryKey: [...specialistKey(record.id), "observations", cursor], queryFn: ({ signal }) => fetchSpecialistObservations(record.id, cursor, signal) });
  const versions = documents.data?.items.flatMap((document) => document.versions.map((version) => ({ document, version }))) ?? [];
  const selected = versions.find((row) => row.version.id === sourceId);
  const upload = useMutation({ mutationFn: async () => {
    if (!file) throw new Error("Select an evidence file.");
    const result = await uploadSpecialistSource(record, file, taxonomy);
    if (result.outcome !== "created") throw new Error("Duplicate evidence was detected. Select its retained version instead.");
    return result;
  }, onSuccess: async () => { setFile(null); if (fileInput.current) fileInput.current.value = ""; await queryClient.invalidateQueries({ queryKey: documentKey }); } });
  const save = useMutation({ mutationFn: async () => {
    if (!selected) throw new Error("Select an accessible source version.");
    return saveSpecialistObservation(record, { kind, occurred_on: day, account, supersedes_id: supersedes,
      source: { document_id: selected.document.id, document_version_id: selected.version.id, content_sha256: selected.version.sha256_hex, locator } }, intentKey.current);
  }, onSuccess: async () => {
    setAccount(""); setLocator(""); setSupersedes(null); intentKey.current = crypto.randomUUID(); setCursor(undefined);
    await queryClient.invalidateQueries({ queryKey: [...specialistKey(record.id), "observations"] });
  } });
  return <section className="min-w-0 space-y-5">
    {canUpload && <form aria-label="Upload specialist evidence" className="flex min-w-0 flex-wrap items-end gap-3 border-y border-line py-4" onSubmit={(event) => { event.preventDefault(); upload.mutate(); }}>
      <div className="min-w-0 flex-1 basis-64"><Label htmlFor="specialist-upload">Evidence file</Label><Input ref={fileInput} id="specialist-upload" type="file" required disabled={upload.isPending} onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></div>
      <div className="min-w-0 flex-1 basis-48"><Label htmlFor="specialist-taxonomy">Document type</Label><select id="specialist-taxonomy" className={selectClass} required value={taxonomy} onChange={(event) => setTaxonomy(event.target.value)}><option value="">Select document type</option>{types.data?.entries.filter((row) => row.is_active).map((row) => <option key={row.key} value={row.key}>{row.label}</option>)}</select></div>
      <Button type="submit" disabled={upload.isPending || !file || !taxonomy}><Upload size={16} />Upload evidence</Button>
    </form>}
    {types.isError && <QueryErrorState title="Could not load document types" error={types.error} onRetry={types.refetch} />}
    {upload.isError && <p role="alert">{errors(upload.error)}</p>}
    {documents.isError && <QueryErrorState title="Could not load source evidence" error={documents.error} onRetry={documents.refetch} />}
    {canWrite && contract?.intake_available && <form aria-label="Record source observation" className="min-w-0 space-y-4" onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
      <fieldset disabled={save.isPending || !documents.isSuccess} className="min-w-0 space-y-4"><div className="grid min-w-0 gap-4 sm:grid-cols-2">
        <div className="min-w-0"><Label htmlFor="specialist-kind">Observation type</Label><select id="specialist-kind" required className={selectClass} value={kind} onChange={(event) => setKind(event.target.value)}><option value="">Select observation type</option>{contract.observation_kinds.map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></div>
        <div className="min-w-0"><Label htmlFor="specialist-day">Event date as recorded</Label><Input id="specialist-day" type="date" required value={day} onChange={(event) => setDay(event.target.value)} /></div></div>
        <div><Label htmlFor="specialist-source">Source version</Label><select id="specialist-source" required className={selectClass} value={sourceId} onChange={(event) => setSourceId(event.target.value)}><option value="">Select source version</option>{versions.filter((row) => !["rejected", "superseded"].includes(row.version.state)).map(({ document, version }) => <option key={version.id} value={version.id}>{document.title} / Version {version.version}</option>)}</select></div>
        <div><Label htmlFor="specialist-locator">Source page or locator</Label><Input id="specialist-locator" required maxLength={500} value={locator} onChange={(event) => setLocator(event.target.value)} /></div>
        <div><Label htmlFor="specialist-account">Source account</Label><Textarea id="specialist-account" required maxLength={4000} value={account} onChange={(event) => setAccount(event.target.value)} /></div>
        {supersedes && <p role="status">Correction of a retained observation <Button type="button" variant="ghost" onClick={() => setSupersedes(null)}>Cancel correction</Button></p>}
        <Button type="submit" disabled={!selected}><Check size={16} />Record observation</Button>
      </fieldset>{save.isError && <p role="alert">{errors(save.error)}</p>}
    </form>}
    <h2 className="text-lg font-semibold">Source history</h2>
    {history.isError ? <QueryErrorState title="Could not load source history" error={history.error} onRetry={history.refetch} /> : history.isPending ? <p role="status">Loading source history...</p> : <>
      <ol aria-label="Specialist source history" className="divide-y divide-line">{history.data.observations.map((row) => <li key={row.id} className="min-w-0 space-y-2 py-4"><p className="font-medium capitalize">{label(row.kind)} / {row.occurred_on}</p>
        <p className="whitespace-pre-wrap break-words">{row.account}</p><p className="break-words text-sm text-mute">{row.source.locator} / Legal effect not determined{row.supersedes_id ? " / Corrected observation" : ""}</p>
        <div className="flex flex-wrap gap-2"><SourceDownload source={row.source} />{canWrite && <Button variant="ghost" onClick={() => { setSupersedes(row.id); setKind(row.kind); setDay(row.occurred_on); setAccount(row.account); setSourceId(row.source.document_version_id); setLocator(row.source.locator); intentKey.current = crypto.randomUUID(); }}><Pencil size={16} />Correct observation</Button>}</div>
      </li>)}</ol>{history.data.observations.length === 0 && <p className="text-sm text-mute">No source observations recorded.</p>}
      <div className="flex flex-wrap justify-between gap-3"><Button variant="ghost" disabled={!cursor} onClick={() => setCursor(undefined)}><ArrowLeft size={16} />Newest</Button><Button variant="ghost" disabled={!history.data.next_cursor} onClick={() => setCursor(history.data.next_cursor ?? undefined)}>Earlier<ArrowRight size={16} /></Button></div>
    </>}
  </section>;
}

function SpecialistLifecycle({ record, canReview, onSaved }: { record: SpecialistRecord; canReview: boolean; onSaved: (record: SpecialistRecord) => Promise<void> }) {
  const [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState("");
  const [effective, setEffective] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [acknowledged, setAcknowledged] = useState<string[]>([]);
  const date = new Date(effective);
  const input: IpLifecycleInput = { lifecycleVersion: record.lifecycle_version, toStatus: record.is_active ? "closed" : "ready",
    effectiveAt: Number.isNaN(date.getTime()) ? "" : date.toISOString(), reason, outcome: record.is_active ? "closed" : "reopened",
    evidenceRef: evidence, linkedMatterHandling: "reviewed" };
  const preview = useMutation({ mutationFn: async () => ({ input, result: await previewIpDocketLifecycle(record.docket_id, input) }),
    onMutate: () => { setConfirmed(false); setAcknowledged([]); } });
  const reviewed = preview.data && JSON.stringify(preview.data.input) === JSON.stringify(input) ? preview.data : undefined;
  const apply = useMutation({ mutationFn: () => transitionIpDocketLifecycle(record.docket_id, { ...input, acknowledgedExceptionCodes: acknowledged }),
    onSuccess: async (result) => { await onSaved({ ...record, lifecycle_version: result.lifecycle_version, lifecycle_status: result.status, is_active: result.is_active });
      preview.reset(); setConfirmed(false); setAcknowledged([]); } });
  return <section className="min-w-0 space-y-4"><h2 className="text-lg font-semibold">Record lifecycle</h2>
    <p className="capitalize">{record.lifecycle_status} / Lifecycle version {record.lifecycle_version}</p>
    {canReview && <form className="min-w-0 space-y-4" onSubmit={(event) => { event.preventDefault(); preview.mutate(); }}>
      <fieldset disabled={preview.isPending || apply.isPending} className="min-w-0 space-y-4">
        <div><Label htmlFor="specialist-effective">Effective date and time</Label><Input id="specialist-effective" type="datetime-local" required value={effective} onChange={(event) => setEffective(event.target.value)} /></div>
        <div><Label htmlFor="specialist-lifecycle-reason">Lifecycle reason</Label><Textarea id="specialist-lifecycle-reason" required minLength={5} maxLength={2000} value={reason} onChange={(event) => setReason(event.target.value)} /></div>
        <div><Label htmlFor="specialist-lifecycle-evidence">Instruction or evidence reference</Label><Input id="specialist-lifecycle-evidence" required minLength={2} maxLength={512} value={evidence} onChange={(event) => setEvidence(event.target.value)} /></div>
        <Button type="submit" variant="secondary"><Eye size={16} />{record.is_active ? "Preview closure" : "Preview reopening"}</Button>
      </fieldset></form>}
    {preview.isError && <p role="alert">{errors(preview.error)}</p>}
    {reviewed && canReview && <div className="min-w-0 space-y-3 border-y border-line py-4"><p className="capitalize">{reviewed.result.from_status} to {reviewed.result.to_status}</p>
      <ul>{reviewed.result.impacts.map((row, index) => <li key={`${row.record_id}:${index}`} className="break-words">{label(row.impact_kind)}: {label(row.current_state)} to {label(row.proposed_outcome)}</li>)}</ul>
      {reviewed.result.blocker_codes.map((code) => <label className="flex items-start gap-2" key={code}><input type="checkbox" checked={acknowledged.includes(code)} onChange={(event) => { setConfirmed(false); setAcknowledged((old) => event.target.checked ? [...old, code] : old.filter((value) => value !== code)); }} />Reviewed exception: {label(code)}</label>)}
      <label className="flex items-start gap-2"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />I confirm this lifecycle change and its recorded impacts.</label>
      <Button disabled={!confirmed || apply.isPending || reviewed.result.blocker_codes.some((code) => !acknowledged.includes(code))} onClick={() => apply.mutate()}><Check size={16} />Confirm lifecycle change</Button>
    </div>}{apply.isError && <p role="alert">{errors(apply.error)}</p>}
  </section>;
}
