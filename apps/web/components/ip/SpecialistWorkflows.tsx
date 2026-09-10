"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, Eye, FileText, Plus, Trash2 } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import { fetchIpDocumentsForDocket } from "@/lib/api/endpoints";
import type { SpecialistRecord } from "@/lib/api/ip-specialist";
import { fetchWorkflow, fetchWorkflows, fetchContractObligations, fetchContractPerformance, fetchContractCostOptions, saveContractPerformance,
  obligationKey, recordContractCost, voidContractCost, saveContractObligation, saveWorkflow, workflowFactsSchema, workflowKey,
  type ContractObligation, type ContractPerformance, type WorkflowFacts, type WorkflowIssue, type WorkflowRecord, type WorkflowSource } from "@/lib/api/ip-specialist-workflows";
import { useCapability } from "@/lib/capabilities";

const selectClass = "h-10 w-full min-w-0 rounded-sm border border-line bg-surface px-3 text-sm";
const human = (value: string) => value.replaceAll("_", " ");
const errorMessage = (error: unknown) => apiErrorMessage(error, "The workflow could not be saved.");
type Kind = WorkflowFacts["kind"];
type Field = { key: string; title?: string; kind?: "date" | "note" | "number"; options?: string[]; optional?: boolean };
const applicationFields: Field[] = [{ key: "registry" }, { key: "jurisdiction" }, { key: "identifier_as_supplied", optional: true },
  { key: "registration_identifier", optional: true }, { key: "registration_on", kind: "date", optional: true }];
const fields: Record<Exclude<Kind, "source_set">, Field[]> = {
  design_application: [...applicationFields,
    { key: "stage", options: ["prepared", "filed", "examination", "objection", "response", "hearing", "accepted", "registered", "refused", "withdrawn"] },
    { key: "publication", options: ["not_recorded", "deferred", "published"] }, { key: "publication_on", kind: "date", optional: true },
    { key: "period_action", options: ["none", "renewal", "extension"] }, { key: "protection_from", kind: "date", optional: true }, { key: "protection_until", kind: "date", optional: true }],
  copyright_registration: [...applicationFields,
    { key: "stage", options: ["prepared", "filed", "deficiency", "objection", "response", "hearing", "registered", "correction", "expunged", "refused", "withdrawn"] }],
  layout_application: [...applicationFields,
    { key: "stage", options: ["prepared", "filed", "examination", "objection", "response", "hearing", "registered", "refused", "withdrawn"] },
    { key: "first_exploitation_on_as_supplied", kind: "date", optional: true }, { key: "exploitation_territory_as_supplied", optional: true },
    { key: "publication", options: ["not_recorded", "reported_published"] }, { key: "publication_on", kind: "date", optional: true }],
  rights_claim: [{ key: "claimant" }, { key: "interest", options: ["authorship", "ownership", "assignment", "licence", "permission"] },
    { key: "rights", kind: "note" }, { key: "territory" }, { key: "effective_from", kind: "date" }, { key: "effective_until", kind: "date", optional: true },
    { key: "review", options: ["unreviewed", "unresolved", "supported", "rejected"] }, { key: "review_reason", kind: "note", optional: true }],
  licence: [{ key: "grantor" }, { key: "grantee" }, { key: "transaction", options: ["licence", "assignment", "permission", "security_interest"] },
    { key: "exclusivity", options: ["not_stated", "exclusive", "nonexclusive", "sole"] }, { key: "rights", kind: "note" }, { key: "territory" },
    ...["field_of_use", "sublicensing", "quality_control", "prosecution_control", "enforcement_control", "renewal_terms", "termination_terms", "notice_terms"].map((key): Field => ({ key, kind: "note" })),
    { key: "effective_from", kind: "date" }, { key: "effective_until", kind: "date", optional: true },
    { key: "extracted_by", options: ["manual", "document_extraction"] }, { key: "interpretation", options: ["unreviewed", "issues_open", "reviewed"] },
    { key: "review_reason", kind: "note", optional: true }, { key: "status", options: ["draft", "active", "terminated"] },
    { key: "recordal", options: ["not_determined", "not_required_as_reviewed", "required", "filed", "deficiency", "accepted", "rejected", "withdrawn"] },
    { key: "recordal_identifier", optional: true }, { key: "recordal_on", kind: "date", optional: true }, { key: "termination_on", kind: "date", optional: true }],
  proceeding: [{ key: "channel", options: ["design_cancellation", "copyright_registry", "platform_takedown", "court", "settlement"] }, { key: "authority" }, { key: "jurisdiction" },
    { key: "identifier_as_supplied" }, { key: "stage", options: ["opened", "notice", "response", "hearing", "decision", "appeal", "closed"] },
    { key: "disposition", options: ["pending", "platform_removed", "platform_declined", "allowed", "dismissed", "settled", "withdrawn"] }],
};
const domainKinds: Record<string, Kind[]> = { design: ["source_set", "design_application", "rights_claim", "proceeding"],
  copyright: ["source_set", "copyright_registration", "rights_claim", "proceeding"], licensing: ["source_set", "licence", "proceeding"],
  semiconductor_layout: ["source_set", "layout_application", "rights_claim", "licence", "proceeding"] };
type SourceOption = { label: string; source: Omit<WorkflowSource, "locator"> };

function FieldInput({ field, value, set, prefix = "workflow" }: { field: Field; value: unknown; set: (value: unknown) => void; prefix?: string }) {
  const id = `${prefix}-${field.key}`;
  const text = value == null ? "" : String(value);
  return <div className={`min-w-0 ${field.kind === "note" ? "sm:col-span-2" : ""}`}><Label htmlFor={id}>{field.title ?? human(field.key)}</Label>
    {field.options ? <select id={id} className={selectClass} value={text || field.options[0]} onChange={(event) => set(event.target.value)}>{field.options.map((option) => <option key={option} value={option}>{human(option)}</option>)}</select>
      : field.kind === "note" ? <Textarea id={id} required={!field.optional} maxLength={4000} value={text} onChange={(event) => set(event.target.value || null)} />
        : <Input id={id} required={!field.optional} type={field.kind === "date" ? "date" : field.kind === "number" ? "number" : "text"} min={field.kind === "number" ? 0 : undefined} maxLength={255} value={text}
          onChange={(event) => set(event.target.value ? field.kind === "number" ? Number(event.target.value) : event.target.value : null)} />}</div>;
}

function SourcePicker({ options, value, onChange, prefix }: { options: SourceOption[]; value?: WorkflowSource; onChange: (source: WorkflowSource) => void; prefix: string }) {
  return <div className="grid min-w-0 gap-3 sm:grid-cols-2"><div className="min-w-0"><Label htmlFor={`${prefix}-version`}>Source document version</Label>
    <select id={`${prefix}-version`} required className={selectClass} value={value?.document_version_id ?? ""} onChange={(event) => {
      const selected = options.find((row) => row.source.document_version_id === event.target.value);
      if (selected) onChange({ ...selected.source, locator: value?.locator ?? "" });
    }}><option value="">Select retained source</option>{options.map((row) => <option key={row.source.document_version_id} value={row.source.document_version_id}>{row.label}</option>)}</select></div>
    <div className="min-w-0"><Label htmlFor={`${prefix}-locator`}>Page or locator</Label><Input id={`${prefix}-locator`} required maxLength={500} value={value?.locator ?? ""} onChange={(event) => { if (value) onChange({ ...value, locator: event.target.value }); }} /></div></div>;
}

export function SpecialistWorkflows({ record, canWrite, onEvidence }: { record: SpecialistRecord; canWrite: boolean; onEvidence: () => void }) {
  const queryClient = useQueryClient();
  const canFinance = useCapability("ip:fees_manage");
  const [cursor, setCursor] = useState<string>();
  const [selected, setSelected] = useState<WorkflowRecord>();
  const [kind, setKind] = useState<Kind>("source_set");
  const [creating, setCreating] = useState(false);
  const [historicalVersion, setHistoricalVersion] = useState<number>();
  const domain = record.facts.details.domain;
  const list = useQuery({ queryKey: [...workflowKey(record.id), "list", cursor], queryFn: ({ signal }) => fetchWorkflows(record.id, cursor, signal) });
  const documents = useQuery({ queryKey: ["ip", "documents", record.docket_id], queryFn: () => fetchIpDocumentsForDocket(record.docket_id) });
  const history = useQuery({ queryKey: [...workflowKey(record.id), selected?.id, historicalVersion],
    queryFn: ({ signal }) => fetchWorkflow(record.id, selected!.id, historicalVersion, signal), enabled: !!selected && !!historicalVersion });
  const options: SourceOption[] = documents.data?.items.flatMap((document) => document.versions.filter((version) => !["rejected", "superseded"].includes(version.state)).map((version) => ({
    label: `${document.title} / Version ${version.version}`, source: { document_id: document.id, document_version_id: version.id, content_sha256: version.sha256_hex },
  }))) ?? [];
  async function saved(next: WorkflowRecord) {
    await queryClient.cancelQueries({ queryKey: workflowKey(record.id) });
    setSelected(next); setCreating(false); setHistoricalVersion(undefined);
    await queryClient.invalidateQueries({ queryKey: workflowKey(record.id) });
  }
  if (!domainKinds[domain]) return null;
  return <section className="min-w-0 space-y-4" aria-label="Domain workflows">
    <div className="flex min-w-0 flex-wrap items-end gap-3"><div className="min-w-0 flex-1 basis-64"><Label htmlFor="workflow-kind">Workflow</Label><select id="workflow-kind" className={selectClass} value={kind} disabled={creating} onChange={(event) => setKind(event.target.value as Kind)}>
      {domainKinds[domain].filter((item) => item !== "licence" || canFinance).map((item) => <option key={item} value={item}>{human(item)}</option>)}</select></div>
      {canWrite && <Button disabled={!list.isSuccess || !documents.isSuccess} onClick={() => { setCreating(true); setSelected(undefined); setHistoricalVersion(undefined); }}><Plus size={16} />New workflow</Button>}
      <Button variant="ghost" onClick={onEvidence}><FileText size={16} />Evidence</Button></div>
    {list.isError && <QueryErrorState title="Could not load workflows" error={list.error} onRetry={list.refetch} />}
    {documents.isError && <QueryErrorState title="Could not load retained evidence" error={documents.error} onRetry={documents.refetch} />}
    {creating && list.data && <WorkflowForm key={`new-${kind}`} record={record} kind={kind} options={options} initialCursor={cursor} onSaved={saved} onCancel={() => setCreating(false)} />}
    {!creating && selected && <div className="min-w-0 space-y-4 border-y border-line py-4">
      <div className="flex min-w-0 flex-wrap items-end justify-between gap-3"><h2 className="min-w-0 flex-1 basis-64 break-words text-lg font-semibold">{selected.facts.title}</h2>
        <div className="w-36"><Label htmlFor="workflow-history-version">Version</Label><Input id="workflow-history-version" type="number" min={1} max={selected.version} value={historicalVersion ?? selected.version} onChange={(event) => {
          const next = Number(event.target.value); if (next >= 1 && next <= selected.version) setHistoricalVersion(next === selected.version ? undefined : next);
        }} /></div></div>
      {historicalVersion ? history.isError ? <QueryErrorState title="Could not load workflow history" error={history.error} onRetry={history.refetch} /> : history.data ? <WorkflowFactsView facts={history.data.facts} /> : <p role="status">Loading history...</p>
        : canWrite && !(selected.facts.kind === "licence" && (!canFinance || selected.facts.status === "terminated")) && !(selected.facts.kind === "proceeding" && selected.facts.stage === "closed") && !(selected.facts.kind === "layout_application" && ["refused", "withdrawn"].includes(selected.facts.stage)) ?
          <WorkflowForm key={`${selected.id}:${selected.version}`} initial={selected} kind={selected.facts.kind} record={record} options={options} initialCursor={cursor} onSaved={saved} onCancel={() => setSelected(undefined)} /> : <WorkflowFactsView facts={selected.facts} />}
      {!historicalVersion && ["licence", "layout_application"].includes(selected.facts.kind) && <ContractWork key={selected.id} record={record} workflow={selected} options={options} canWrite={canWrite && documents.isSuccess && !(selected.facts.kind === "layout_application" && ["refused", "withdrawn"].includes(selected.facts.stage))} />}
    </div>}
    <ul aria-label="Saved domain workflows" className="divide-y divide-line border-y border-line">{list.data?.records.map((row) => <li key={row.id} className="flex min-w-0 flex-wrap items-center justify-between gap-3 py-3">
      <div className="min-w-0 flex-1 basis-64"><p className="break-words font-medium">{row.facts.title}</p><p className="text-sm capitalize text-mute">{human(row.facts.kind)} / Version {row.version}{"stage" in row.facts ? ` / ${row.facts.stage}` : "status" in row.facts ? ` / ${row.facts.status}` : ""}</p></div>
      <Button variant="ghost" onClick={() => { setSelected(row); setCreating(false); setHistoricalVersion(undefined); }}><Eye size={16} />Open</Button></li>)}</ul>
    {list.data?.records.length === 0 && <p className="text-sm text-mute">No domain workflows recorded.</p>}
    <div className="flex flex-wrap justify-between gap-3"><Button variant="ghost" disabled={!cursor} onClick={() => setCursor(undefined)}><ArrowLeft size={16} />First page</Button><Button variant="ghost" disabled={!list.data?.next_cursor} onClick={() => { setCursor(list.data!.next_cursor!); setSelected(undefined); }}>Next page<ArrowRight size={16} /></Button></div>
  </section>;
}

function WorkflowFactsView({ facts }: { facts: WorkflowFacts }) {
  const render = (value: unknown): string => value === null ? "Not recorded" : typeof value === "object" ? Object.entries(value as Record<string, unknown>).map(([k, v]) => `${human(k)}: ${render(v)}`).join("\n") : String(value);
  return <dl className="grid min-w-0 gap-4 sm:grid-cols-2">{Object.entries(facts).filter(([key]) => key !== "kind").map(([key, value]) => <div key={key} className="min-w-0"><dt className="text-sm capitalize text-mute">{human(key)}</dt><dd className="whitespace-pre-wrap [overflow-wrap:anywhere]">{render(value)}</dd></div>)}</dl>;
}

export function WorkflowForm({ record: currentRecord, kind, initial: serverInitial, initialCursor, options, onSaved, onCancel }: {
  record: SpecialistRecord; kind: Kind; initial?: WorkflowRecord; initialCursor?: string; options: SourceOption[];
  onSaved: (record: WorkflowRecord) => Promise<void>; onCancel: () => void;
}) {
  const [record] = useState(currentRecord);
  const [initial] = useState(serverInitial);
  const [referenceCursor, setReferenceCursor] = useState(initialCursor);
  const references = useQuery({ queryKey: [...workflowKey(record.id), "list", referenceCursor],
    queryFn: ({ signal }) => fetchWorkflows(record.id, referenceCursor, signal), enabled: kind !== "source_set", staleTime: 30_000 });
  const records = references.data?.records ?? [];
  const [values, setValues] = useState<Record<string, unknown>>(() => initial ? structuredClone(initial.facts) : { kind });
  const [members, setMembers] = useState<{ role: string; source?: WorkflowSource }[]>(initial?.facts.kind === "source_set" ? initial.facts.members : [{ role: "" }]);
  const [issues, setIssues] = useState<Partial<WorkflowIssue>[]>(initial?.facts.kind === "licence" ? initial.facts.issues : []);
  const [reason, setReason] = useState("");
  const key = useRef(crypto.randomUUID());
  const set = (name: string, value: unknown) => setValues((old) => ({ ...old, [name]: value }));
  const definitions = kind === "source_set" ? [] : fields[kind].map((field) => kind === "proceeding" && field.key === "channel" ? {
    ...field, options: record.facts.details.domain === "semiconductor_layout" ? ["layout_opposition", "layout_cancellation", "layout_infringement", "court", "settlement"]
      : record.facts.details.domain === "design" ? ["design_cancellation", "court", "settlement"]
        : record.facts.details.domain === "copyright" ? ["copyright_registry", "platform_takedown", "court", "settlement"] : ["court", "settlement"],
  } : field);
  const save = useMutation({ mutationFn: async () => {
    const candidate = { ...values };
    for (const field of definitions) if (!(field.key in candidate) && field.options) candidate[field.key] = field.options[0];
    if (kind === "source_set") { candidate.members = members; candidate.purpose ??= record.facts.details.domain === "design" ? "representations" : record.facts.details.domain === "copyright" ? "deposit" : record.facts.details.domain === "semiconductor_layout" ? "layout_deposit" : "instrument"; }
    if (kind === "licence") candidate.issues = issues;
    return saveWorkflow(record, workflowFactsSchema.parse(candidate), reason, key.current, initial);
  }, onSuccess: onSaved });
  const refPurpose = { design_application: "representations", copyright_registration: "deposit", layout_application: "layout_deposit", rights_claim: "instrument", licence: "instrument", proceeding: "proceeding_evidence" };
  const sources = records.filter((row) => row.facts.kind === "source_set" && kind !== "source_set" && row.facts.purpose === refPurpose[kind]);
  const sourceReference = values.source_set as { id: string; version: number } | undefined;
  const hasRetainedSource = sourceReference && !sources.some((row) => row.id === sourceReference.id && row.version === sourceReference.version);
  const finance = (values.financial_terms ?? {}) as Record<string, unknown>;
  const canSubmit = !save.isPending && (kind === "source_set" || references.isSuccess);
  return <form aria-label={initial ? "Revise domain workflow" : "New domain workflow"} className="min-w-0 space-y-4 border-y border-line py-4" onSubmit={(event) => { event.preventDefault(); if (canSubmit) save.mutate(); }}>
    {kind !== "source_set" && <div className="flex min-w-0 flex-wrap items-center justify-between gap-3" aria-label="Workflow reference pages">
      <h3 className="text-sm font-medium">Reference choices</h3><div className="flex shrink-0 gap-2">
        <Button type="button" variant="ghost" title="First reference page" aria-label="First reference page" disabled={!referenceCursor || references.isFetching || save.isPending} onClick={() => setReferenceCursor(undefined)}><ArrowLeft size={16} /></Button>
        <Button type="button" variant="ghost" title="Next reference page" aria-label="Next reference page" disabled={!references.data?.next_cursor || references.isFetching || save.isPending} onClick={() => setReferenceCursor(references.data!.next_cursor!)}><ArrowRight size={16} /></Button>
      </div></div>}
    {kind !== "source_set" && references.isPending && <p role="status">Loading reference choices...</p>}
    {kind !== "source_set" && references.isError && <QueryErrorState title="Could not load reference choices" error={references.error} onRetry={references.refetch} />}
    <fieldset disabled={save.isPending || (kind !== "source_set" && !references.isSuccess)} className="min-w-0 space-y-4">
      <FieldInput field={{ key: "title" }} value={values.title} set={(v) => set("title", v)} />
      {kind === "source_set" ? <>
        <FieldInput field={{ key: "purpose", options: [...(record.facts.details.domain === "design" ? ["representations"] : record.facts.details.domain === "copyright" ? ["deposit"] : record.facts.details.domain === "semiconductor_layout" ? ["layout_deposit"] : []), "instrument", "proceeding_evidence"] }} value={values.purpose} set={(v) => { set("purpose", v); if (v === "layout_deposit") set("confidentiality", "restricted"); }} />
        {members.map((member, index) => <div className="min-w-0 space-y-3 border-b border-line py-3" key={index}>
          <FieldInput prefix={`member-${index}`} field={{ key: "role" }} value={member.role} set={(role) => setMembers((old) => old.map((m, i) => i === index ? { ...m, role: String(role ?? "") } : m))} />
          <SourcePicker prefix={`member-${index}`} options={options} value={member.source} onChange={(source) => setMembers((old) => old.map((m, i) => i === index ? { ...m, source } : m))} />
          <Button variant="ghost" type="button" title="Remove source member" aria-label={`Remove member ${index + 1}`} disabled={members.length === 1} onClick={() => setMembers((old) => old.filter((_, i) => i !== index))}><Trash2 size={16} /></Button></div>)}
        <Button type="button" variant="ghost" disabled={members.length >= 25} onClick={() => setMembers((old) => [...old, { role: "" }])}><Plus size={16} />Add source member</Button>
        <FieldInput field={{ key: "confidentiality", options: (values.purpose === "layout_deposit" || (!values.purpose && record.facts.details.domain === "semiconductor_layout")) ? ["restricted"] : ["restricted", "publication_authorized"] }} value={values.confidentiality} set={(v) => set("confidentiality", v)} />
        <FieldInput field={{ key: "publication_instruction", kind: "note", optional: values.confidentiality !== "publication_authorized" }} value={values.publication_instruction} set={(v) => set("publication_instruction", v)} />
        <FieldInput field={{ key: "publication_on_as_supplied", kind: "date", optional: true }} value={values.publication_on_as_supplied} set={(v) => set("publication_on_as_supplied", v)} />
      </> : <>
        <div><Label htmlFor="workflow-source-set">Source set</Label><select id="workflow-source-set" required className={selectClass} value={sourceReference ? `${sourceReference.id}:${sourceReference.version}` : ""} onChange={(event) => {
          const source = sources.find((row) => `${row.id}:${row.version}` === event.target.value); if (source) set("source_set", { id: source.id, version: source.version });
        }}><option value="">Select current source set</option>{hasRetainedSource && <option value={`${sourceReference.id}:${sourceReference.version}`}>Retained source set / Version {sourceReference.version}</option>}{sources.map((row) => <option key={row.id} value={`${row.id}:${row.version}`}>{row.facts.title} / Version {row.version}</option>)}</select></div>
        <div className="grid min-w-0 gap-4 sm:grid-cols-2"><FieldInput field={{ key: "occurred_on", title: "Source event date", kind: "date" }} value={values.occurred_on} set={(v) => set("occurred_on", v)} />
          {definitions.map((field) => <FieldInput key={field.key} field={field} value={values[field.key]} set={(v) => {
            if (kind === "layout_application" && field.key === "publication" && v === "not_recorded") {
              setValues((old) => ({ ...old, publication: v, publication_on: null, registry_source: null }));
            } else set(field.key, v);
          }} />)}</div>
        <FieldInput field={{ key: "account", title: "Source account", kind: "note" }} value={values.account} set={(v) => set("account", v)} />
        {kind === "layout_application" && <>
          {values.publication === "reported_published" && <div className="space-y-2"><h3 className="text-sm font-medium">Registry publication evidence</h3><SourcePicker prefix="layout-registry" options={options} value={values.registry_source as WorkflowSource | undefined} onChange={(v) => set("registry_source", v)} /></div>}
          {initial && <CostPicker record={record} workflow={initial} prefix="layout-application" value={(values.cost_item_id as string | null) ?? null} set={(v) => set("cost_item_id", v)} />}
        </>}
        {kind === "design_application" && <><WorkflowReference title="Variant parent" name="variant_of" records={records.filter((r) => r.facts.kind === "design_application" && r.id !== initial?.id)} value={values.variant_of} set={(v) => { set("variant_of", v); if (!v) set("variant_basis", null); }} />
          {!!values.variant_of && <SourcePicker prefix="variant-basis" options={options} value={values.variant_basis as WorkflowSource | undefined} onChange={(v) => set("variant_basis", v)} />}</>}
        {kind === "rights_claim" && <><WorkflowReference title="Predecessor claim" name="predecessor" records={records.filter((r) => r.facts.kind === "rights_claim" && r.id !== initial?.id)} value={values.predecessor} set={(v) => set("predecessor", v)} />
          <fieldset className="min-w-0 space-y-2"><legend className="text-sm">Competing claims</legend>{records.filter((r) => r.facts.kind === "rights_claim" && r.id !== initial?.id).map((row) => <label key={row.id} className="flex items-start gap-2 break-words"><input type="checkbox" checked={(values.competing_claims as string[] | undefined)?.includes(row.id) ?? false} onChange={(event) => {
            const current = (values.competing_claims as string[] | undefined) ?? []; set("competing_claims", event.target.checked ? [...current, row.id] : current.filter((id) => id !== row.id));
          }} />{row.facts.title}</label>)}</fieldset></>}
        {kind === "proceeding" && <WorkflowReference title="Related application or proceeding" name="related_workflow" records={records.filter((r) => r.facts.kind !== "source_set" && r.id !== initial?.id)} value={values.related_workflow} set={(v) => set("related_workflow", v)} />}
        {kind === "licence" && <>
          <h3 className="text-base font-semibold">Term review issues</h3>{issues.map((issue, index) => <div key={index} className="min-w-0 space-y-3 border-y border-line py-3">
            {(["clause", "question", "resolution"] as const).map((name) => <FieldInput key={name} prefix={`issue-${index}`} field={{ key: name, kind: name === "clause" ? undefined : "note", optional: name === "resolution" }} value={issue[name]} set={(v) => setIssues((old) => old.map((row, i) => i === index ? { ...row, [name]: v } : row))} />)}
            <SourcePicker prefix={`issue-${index}`} options={options} value={issue.source} onChange={(source) => setIssues((old) => old.map((row, i) => i === index ? { ...row, source } : row))} />
            <Button type="button" variant="ghost" title="Remove draft issue" aria-label={`Remove issue ${index + 1}`} onClick={() => setIssues((old) => old.filter((_, i) => i !== index))}><Trash2 size={16} /></Button></div>)}
          <Button type="button" variant="ghost" disabled={issues.length >= 25} onClick={() => setIssues((old) => [...old, {}])}><Plus size={16} />Add review issue</Button>
          <h3 className="text-base font-semibold">Confidential financial terms</h3>
          <div className="grid min-w-0 gap-4 sm:grid-cols-2">{([{ key: "currency", optional: true }, { key: "royalty", kind: "note", optional: true },
            { key: "fee_minor", title: "Fee in minor currency units", kind: "number", optional: true }, { key: "minimum_minor", title: "Minimum in minor currency units", kind: "number", optional: true },
            { key: "reporting", kind: "note", optional: true }, { key: "audit", kind: "note", optional: true }] as Field[]).map((field) => <FieldInput key={field.key} prefix="finance" field={field} value={finance[field.key]} set={(v) => set("financial_terms", { ...finance, [field.key]: v })} />)}</div>
        </>}
      </>}
      <FieldInput field={{ key: "reason", title: "Revision reason" }} value={reason} set={(v) => setReason(String(v ?? ""))} />
    </fieldset>
    <div className="flex flex-wrap gap-3"><Button type="submit" disabled={!canSubmit}><Check size={16} />{save.isPending ? "Saving..." : initial ? "Save revision" : "Create workflow"}</Button><Button variant="ghost" type="button" disabled={save.isPending} onClick={onCancel}>Cancel</Button></div>
    {save.isError && <p role="alert" className="break-words text-sm text-danger-500">{errorMessage(save.error)}</p>}
  </form>;
}

function WorkflowReference({ name, title, records, value, set }: { name: string; title: string; records: WorkflowRecord[]; value: unknown; set: (value: string | null) => void }) {
  const selected = typeof value === "string" ? value : "";
  return <div><Label htmlFor={`workflow-${name}`}>{title}</Label><select id={`workflow-${name}`} className={selectClass} value={selected} onChange={(event) => set(event.target.value || null)}><option value="">Not linked</option>
    {selected && !records.some((r) => r.id === selected) && <option value={selected}>Retained linked workflow</option>}{records.map((row) => <option key={row.id} value={row.id}>{row.facts.title}</option>)}</select></div>;
}

export function ContractWork({ record, workflow, options, canWrite }: { record: SpecialistRecord; workflow: WorkflowRecord; options: SourceOption[]; canWrite: boolean }) {
  const queryClient = useQueryClient();
  const canFinance = useCapability("ip:fees_manage");
  const layout = workflow.facts.kind === "layout_application";
  const workLabel = layout ? "Layout application work" : "Contract obligations";
  const [cursor, setCursor] = useState<string>();
  const [selected, setSelected] = useState<ContractObligation>();
  const list = useQuery({ queryKey: [...obligationKey(record.id, workflow.id), "list", cursor],
    queryFn: ({ signal }) => fetchContractObligations(record.id, workflow.id, cursor, signal) });
  const current = list.data?.records.find((row) => row.id === selected?.id) ?? selected;
  async function refresh() {
    await queryClient.cancelQueries({ queryKey: obligationKey(record.id, workflow.id) });
    await queryClient.invalidateQueries({ queryKey: obligationKey(record.id, workflow.id) });
  }
  return <section aria-label={workLabel} className="min-w-0 space-y-4 border-y border-line py-4">
    <h3 className="text-base font-semibold">{workLabel}</h3>
    {list.isError && <QueryErrorState title="Could not load obligations" error={list.error} onRetry={list.refetch} />}
    {list.isPending && <p role="status">Loading obligations...</p>}
    <ul aria-label="Saved obligations" className="divide-y divide-line">{list.data?.records.map((row) => <li key={row.id} className="flex min-w-0 flex-wrap items-center gap-3 py-3">
      <div className="min-w-0 flex-1 basis-64"><p className="break-words font-medium">{row.title}</p><p className="text-sm">{row.due_on} / {human(row.status)}</p></div>
      <Button variant="ghost" onClick={() => setSelected(row)}><Eye size={16} />Performance history</Button></li>)}</ul>
    {list.data?.records.length === 0 && <p className="text-sm text-mute">{layout ? "No layout application work recorded." : "No contractual obligations recorded."}</p>}
    <div className="flex flex-wrap justify-between gap-3"><Button variant="ghost" disabled={!cursor} onClick={() => { setCursor(undefined); setSelected(undefined); }}><ArrowLeft size={16} />First obligations</Button>
      <Button variant="ghost" disabled={!list.data?.next_cursor} onClick={() => { setCursor(list.data!.next_cursor!); setSelected(undefined); }}>Next obligations<ArrowRight size={16} /></Button></div>
    {current && <PerformancePanel key={current.id} record={record} workflow={workflow} obligation={current} options={options} canWrite={canWrite && list.isSuccess} onSaved={refresh} />}
    {canWrite && canFinance && list.isSuccess && <CostEvidencePanel record={record} workflow={workflow} options={options} />}
    {canWrite && list.isSuccess && ((workflow.facts.kind === "licence" && workflow.facts.status === "active") || (workflow.facts.kind === "layout_application" && !["refused", "withdrawn"].includes(workflow.facts.stage))) && <ObligationForm record={record} workflow={workflow} options={options} onSaved={refresh} />}
  </section>;
}

function PerformancePanel({ record, workflow, obligation, options, canWrite, onSaved }: {
  record: SpecialistRecord; workflow: WorkflowRecord; obligation: ContractObligation; options: SourceOption[]; canWrite: boolean; onSaved: () => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const [cursor, setCursor] = useState<string>();
  const [action, setAction] = useState<ContractPerformance["action"]>("complete");
  const [occurredOn, setOccurredOn] = useState("");
  const [account, setAccount] = useState("");
  const [source, setSource] = useState<WorkflowSource>();
  const [replacementCost, setReplacementCost] = useState<string | null>(null);
  const key = useRef(crypto.randomUUID());
  const [editRecord] = useState(record);
  const historyKey = [...obligationKey(record.id, workflow.id), obligation.id, "performance", cursor];
  const history = useQuery({ queryKey: historyKey, queryFn: ({ signal }) => fetchContractPerformance(record.id, workflow.id, obligation.id, cursor, signal) });
  const save = useMutation({ mutationFn: () => {
    if (!source) throw new Error("Select the performance evidence and locator.");
    return saveContractPerformance(editRecord, workflow.id, obligation.id, { action, occurred_on: occurredOn, account, source, replacement_cost_item_id: replacementCost }, key.current);
  }, onSuccess: async (saved) => {
    await queryClient.cancelQueries({ queryKey: obligationKey(record.id, workflow.id) });
    queryClient.setQueryData(historyKey, (old: { records: ContractPerformance[]; next_cursor: string | null } | undefined) => ({
      records: [saved, ...(old?.records ?? []).filter((row) => row.id !== saved.id)].slice(0, 10), next_cursor: old?.next_cursor ?? null,
    }));
    key.current = crypto.randomUUID(); setAccount("");
    await onSaved();
  } });
  return <div className="min-w-0 space-y-4 border-y border-line py-4">
    <h4 className="break-words text-base font-semibold">{obligation.title}</h4>
    {history.isError && <QueryErrorState title="Could not load performance history" error={history.error} onRetry={history.refetch} />}
    <ol aria-label="Performance evidence" className="space-y-3">{history.data?.records.map((row) => <li key={row.id} className="min-w-0 break-words text-sm">
      <p>{human(row.action)} / {row.occurred_on}</p><p>{row.account}</p><p>{row.source.locator}</p></li>)}</ol>
    {history.data?.records.length === 0 && <p className="text-sm text-mute">No performance evidence recorded.</p>}
    <div className="flex flex-wrap justify-between gap-3"><Button variant="ghost" disabled={!cursor} onClick={() => setCursor(undefined)}><ArrowLeft size={16} />First evidence</Button>
      <Button variant="ghost" disabled={!history.data?.next_cursor} onClick={() => setCursor(history.data!.next_cursor!)}>Next evidence<ArrowRight size={16} /></Button></div>
    {canWrite && obligation.status === "open" && history.isSuccess && <form aria-label={workflow.facts.kind === "layout_application" ? "Record layout performance" : "Record contract performance"} className="min-w-0 space-y-3" onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
      <fieldset disabled={save.isPending} className="min-w-0 space-y-3">
        <FieldInput prefix="performance" field={{ key: "action", options: obligation.kind === "notice" ? ["complete", "cancel", "notice_recorded"] : ["complete", "cancel"] }} value={action} set={(v) => setAction(v as ContractPerformance["action"])} />
        <FieldInput prefix="performance" field={{ key: "occurred_on", title: "Performance date", kind: "date" }} value={occurredOn} set={(v) => setOccurredOn(String(v ?? ""))} />
        <FieldInput prefix="performance" field={{ key: "account", title: "Performance evidence account", kind: "note" }} value={account} set={(v) => setAccount(String(v ?? ""))} />
        <SourcePicker prefix="performance" options={options} value={source} onChange={setSource} />
        <CostPicker record={record} workflow={workflow} prefix="performance" value={replacementCost} set={setReplacementCost} />
        <Button type="submit"><Check size={16} />{save.isPending ? "Saving..." : "Record performance"}</Button>
      </fieldset>
    </form>}
    {save.isError && <p role="alert" className="break-words text-sm text-danger-500">{errorMessage(save.error)}</p>}
    {save.isSuccess && <p role="status">Performance evidence retained.</p>}
  </div>;
}

function ObligationForm({ record: currentRecord, workflow: currentWorkflow, options, onSaved }: { record: SpecialistRecord; workflow: WorkflowRecord; options: SourceOption[]; onSaved: () => Promise<void> }) {
  const [record] = useState(currentRecord);
  const [workflow] = useState(currentWorkflow);
  const layout = workflow.facts.kind === "layout_application";
  const workLabel = layout ? "Layout application work" : "Contractual obligation";
  const [kind, setKind] = useState("notice");
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [source, setSource] = useState<WorkflowSource>();
  const [cost, setCost] = useState<string | null>(null);
  const key = useRef(crypto.randomUUID());
  const save = useMutation({ mutationFn: () => {
    if (!source) throw new Error("Select the source evidence and locator.");
    return saveContractObligation(record, workflow, { kind, title, due_on_as_supplied: due, source, cost_item_id: cost }, key.current);
  }, onSuccess: async () => { key.current = crypto.randomUUID(); setTitle(""); await onSaved(); } });
  return <form aria-label={workLabel} className="min-w-0 space-y-4 border-y border-line py-4" onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
    <h3 className="text-base font-semibold">{workLabel}</h3><fieldset disabled={save.isPending} className="min-w-0 space-y-4">
      <FieldInput prefix="obligation" field={{ key: "kind", options: layout ? ["notice", "filing", "office_response", "hearing", "renewal"] : ["notice", "royalty", "reporting", "audit", "quality_control", "recordal", "renewal", "termination"] }} value={kind} set={(v) => setKind(String(v))} />
      <FieldInput prefix="obligation" field={{ key: "title" }} value={title} set={(v) => setTitle(String(v ?? ""))} />
      <FieldInput prefix="obligation" field={{ key: "due", title: layout ? "Layout work due date as supplied" : "Contractual due date as supplied", kind: "date" }} value={due} set={(v) => setDue(String(v ?? ""))} />
      <SourcePicker prefix="obligation" options={options} value={source} onChange={setSource} />
      <CostPicker record={record} workflow={workflow} prefix="obligation" value={cost} set={setCost} /><Button type="submit"><Plus size={16} />Create obligation</Button></fieldset>
    {save.isError && <p role="alert">{errorMessage(save.error)}</p>}{save.data && <p role="status">{layout ? "Layout task and calendar obligation" : "Contractual task and calendar obligation"} saved for {save.data.due_on}.</p>}
  </form>;
}

function CostPicker({ record, workflow, prefix, value, set }: { record: SpecialistRecord; workflow: WorkflowRecord; prefix: string; value: string | null; set: (value: string | null) => void }) {
  const [cursor, setCursor] = useState<string>();
  const options = useQuery({ queryKey: [...workflowKey(record.id), workflow.id, "cost-options", cursor],
    queryFn: ({ signal }) => fetchContractCostOptions(record.id, workflow.id, cursor, signal) });
  return <div className="min-w-0 space-y-2"><Label htmlFor={`${prefix}-cost`}>{prefix === "performance" ? "Replacement cost evidence" : "Cost evidence"}</Label>
    <select id={`${prefix}-cost`} className={selectClass} value={value ?? ""} disabled={!options.isSuccess} onChange={(event) => set(event.target.value || null)}>
      <option value="">{prefix === "performance" ? "Keep original cost reference" : "No cost reference"}</option>
      {value && !options.data?.records.some((row) => row.id === value) && <option value={value}>Selected cost evidence</option>}
      {options.data?.records.map((row) => <option key={row.id} value={row.id}>{row.description}</option>)}
    </select>
    {options.isError && <QueryErrorState title="Could not load cost evidence" error={options.error} onRetry={options.refetch} />}
    <div className="flex flex-wrap justify-between gap-3"><Button type="button" variant="ghost" title="First cost options" aria-label={`${prefix}: first cost options`} disabled={!cursor} onClick={() => setCursor(undefined)}><ArrowLeft size={16} /></Button>
      <Button type="button" variant="ghost" title="Next cost options" aria-label={`${prefix}: next cost options`} disabled={!options.data?.next_cursor} onClick={() => setCursor(options.data!.next_cursor!)}><ArrowRight size={16} /></Button></div>
  </div>;
}

function CostEvidencePanel({ record: currentRecord, workflow, options }: { record: SpecialistRecord; workflow: WorkflowRecord; options: SourceOption[] }) {
  const queryClient = useQueryClient();
  const [record] = useState(currentRecord);
  const [mode, setMode] = useState<"create" | "void">("create");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("");
  const [cost, setCost] = useState<string | null>(null);
  const [source, setSource] = useState<WorkflowSource>();
  const key = useRef(crypto.randomUUID());
  const save = useMutation({ mutationFn: () => {
    if (!source) throw new Error("Select the cost evidence and locator.");
    if (mode === "void") {
      if (!cost) throw new Error("Select the cost evidence to void.");
      return voidContractCost(record, workflow.id, cost, description, source, key.current);
    }
    if (!amount.trim() || !Number.isSafeInteger(Number(amount)) || Number(amount) < 0) throw new Error("Enter a nonnegative amount in minor currency units.");
    return recordContractCost(record, workflow.id, { description, amount_minor: Number(amount), currency, cost_nature: "actual", source }, key.current);
  }, onSuccess: async () => {
    await queryClient.cancelQueries({ queryKey: [...workflowKey(record.id), workflow.id, "cost-options"] });
    await queryClient.invalidateQueries({ queryKey: [...workflowKey(record.id), workflow.id, "cost-options"] });
    key.current = crypto.randomUUID(); setDescription(""); setCost(null);
  } });
  return <details className="min-w-0 border-y border-line py-3"><summary className="cursor-pointer text-sm font-medium">Nonbillable cost evidence</summary>
    <form aria-label="Record cost evidence" className="min-w-0 space-y-3 pt-3" onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
      <fieldset disabled={save.isPending} className="min-w-0 space-y-3">
        <FieldInput prefix="cost-evidence" field={{ key: "action", options: ["create", "void"] }} value={mode} set={(v) => { setMode(v as "create" | "void"); key.current = crypto.randomUUID(); save.reset(); }} />
        {mode === "void" ? <CostPicker record={record} workflow={workflow} prefix="void" value={cost} set={setCost} /> : <div className="grid min-w-0 gap-3 sm:grid-cols-2">
          <FieldInput prefix="cost-evidence" field={{ key: "amount", title: "Amount in minor currency units", kind: "number" }} value={amount} set={(v) => setAmount(String(v ?? ""))} />
          <FieldInput prefix="cost-evidence" field={{ key: "currency", title: "Currency code" }} value={currency} set={(v) => setCurrency(String(v ?? "").toUpperCase())} />
        </div>}
        <FieldInput prefix="cost-evidence" field={{ key: "description", title: mode === "void" ? "Void reason" : "Cost description", kind: "note" }} value={description} set={(v) => setDescription(String(v ?? ""))} />
        <SourcePicker prefix="cost-evidence" options={options} value={source} onChange={setSource} />
        <Button type="submit"><Check size={16} />{mode === "void" ? "Void cost evidence" : "Record cost evidence"}</Button>
      </fieldset>
      {save.isError && <p role="alert" className="break-words text-sm text-danger-500">{errorMessage(save.error)}</p>}
      {save.isSuccess && <p role="status">Cost evidence retained.</p>}
    </form>
  </details>;
}
