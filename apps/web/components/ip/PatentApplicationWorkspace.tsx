"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, FileText, LockKeyhole, Pencil, Plus, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { IpDocumentWorkspace } from "@/components/ip/IpDocumentWorkspace";
import { PatentRecordLifecycle } from "@/components/ip/PatentFamilyLifecycle";
import { PatentSourceDownload } from "@/components/ip/PatentSourceDownload";
import { PatentParties } from "@/components/ip/PatentParties";
import { PatentPriorities } from "@/components/ip/PatentPriorities";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import { fetchIpDocumentsForDocket } from "@/lib/api/endpoints";
import {
  correctPatentApplication, createPatentApplication, fetchPatentApplication, fetchPatentApplications,
  patentApplicationKinds, type PatentApplication, type PatentApplicationFacts,
  type PatentFamily, type PatentFamilyStatusScope, type PatentSource,
} from "@/lib/api/ip-patents";
import { useCapability } from "@/lib/capabilities";

const selectClass = "h-10 w-full min-w-0 rounded-sm border border-line bg-surface px-3 text-sm";
const key = (id: string) => ["ip", "patent-application", id];
const label = (value: string) => value.replaceAll("_", " ");

export function PatentFamilyApplications({ family, canWrite, onOpenDocuments }: {
  family: PatentFamily; canWrite: boolean; onOpenDocuments: () => void;
}) {
  const router = useRouter();
  const [creating, setCreating] = useState(false);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState<string>();
  const [scope, setScope] = useState<PatentFamilyStatusScope>("active");
  const applications = useQuery({
    queryKey: ["ip", "patent-applications", family.id, cursor, scope, query],
    queryFn: ({ signal }) => fetchPatentApplications(family.id, cursor, signal, scope, query),
  });
  return <section className="min-w-0 space-y-4 border-t border-line pt-4" aria-label="Family applications">
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
      <h2 className="text-lg font-semibold">Applications</h2>
      {canWrite && family.is_active && !creating && <Button onClick={() => setCreating(true)}><Plus size={16} />New application</Button>}
    </div>
    {creating && family.is_active && <ApplicationForm family={family} onOpenDocuments={onOpenDocuments}
      onCancel={() => setCreating(false)} onSaved={(application) => router.push(`/app/ip/patents/applications/${application.id}`)} />}
    <form className="flex min-w-0 flex-wrap items-end gap-2" onSubmit={(event) => {
      event.preventDefault(); setQuery(search.trim()); setCursor(undefined);
    }}>
      <div className="min-w-0 flex-1 basis-48"><Label htmlFor="patent-application-search">Title or exact identifier</Label>
        <Input id="patent-application-search" value={search} maxLength={200} onChange={(event) => setSearch(event.target.value)} /></div>
      <Button type="submit" variant="secondary" aria-label="Search patent applications" title="Search patent applications"><Search size={16} /></Button>
      <div className="min-w-0 basis-40"><Label htmlFor="patent-application-scope">Lifecycle</Label>
        <select id="patent-application-scope" className={selectClass} value={scope} onChange={(event) => {
          setScope(event.target.value as PatentFamilyStatusScope); setCursor(undefined);
        }}><option value="active">Active records</option><option value="terminal">Closed records</option><option value="all">All records</option></select>
      </div>
    </form>
    {applications.isPending ? <Skeleton className="h-32 w-full" /> : applications.isError
      ? <QueryErrorState title="Could not load applications" error={applications.error} onRetry={applications.refetch} />
      : <>
        <ul aria-label="Patent applications" className="divide-y divide-line border-y border-line">
          {applications.data.applications.map((application) => <li key={application.id} className="min-w-0 space-y-1 py-3">
            <Link className="break-words font-medium text-brand-700 hover:underline" href={`/app/ip/patents/applications/${application.id}`}>{application.facts.title}</Link>
            <p className="break-words text-sm capitalize text-mute">{label(application.facts.application_kind)} · {application.facts.jurisdiction} · {application.facts.office} · {label(application.lifecycle_status)}</p>
            <p className="break-words text-sm">{application.facts.identifiers.filter((row) => row.identifier_kind === "application").map((row) => row.raw_value).join(", ")
              || (application.facts.source_pending_identifier_allocation ? "Application number pending allocation" : "Application number not recorded")}</p>
          </li>)}
        </ul>
        {!applications.data.applications.length && <p className="text-sm text-mute">No accessible applications on this page.</p>}
        <div className="flex flex-wrap justify-between gap-2">
          <Button variant="ghost" disabled={!cursor} onClick={() => setCursor(undefined)}><ArrowLeft size={16} />First page</Button>
          <Button variant="ghost" disabled={!applications.data.next_cursor} onClick={() => setCursor(applications.data.next_cursor ?? undefined)}>Next page<ArrowRight size={16} /></Button>
        </div>
      </>}
  </section>;
}

export function PatentApplicationDetail({ applicationId }: { applicationId: string }) {
  const canRead = useCapability("ip:read");
  const canWrite = useCapability("ip:write");
  const canUpload = useCapability("documents:upload");
  const canManage = useCapability("documents:manage");
  const canReview = useCapability("ip:approve");
  const canConfigure = useCapability("ip:taxonomy_admin");
  const [area, setArea] = useState("application");
  const [editing, setEditing] = useState(false);
  const [versionInput, setVersionInput] = useState("");
  const [version, setVersion] = useState<number>();
  const application = useQuery({ queryKey: key(applicationId),
    queryFn: ({ signal }) => fetchPatentApplication(applicationId, undefined, signal), enabled: canRead });
  const historical = useQuery({ queryKey: [...key(applicationId), "version", version],
    queryFn: ({ signal }) => fetchPatentApplication(applicationId, version, signal),
    enabled: canRead && !!application.data && version !== undefined && version !== application.data.version });
  if (!canRead) return <p role="alert">Patent records are not available with your current permissions.</p>;
  if (application.isPending) return <Skeleton className="h-64 w-full" />;
  if (application.isError) return <QueryErrorState title="Could not open patent application" error={application.error} onRetry={application.refetch} />;
  const current = application.data;
  const isHistory = version !== undefined && version !== current.version;
  const shown = isHistory ? historical.data : current;
  return <div className="flex min-w-0 flex-col gap-5">
    <Link className="inline-flex w-fit items-center gap-2 text-sm" href={`/app/ip/patents/${current.family_id}`}><ArrowLeft size={16} />Patent family</Link>
    <PageHeader title={current.facts.title} className="[&>div:first-child]:min-w-0 [&>div:first-child]:flex-1 [&_h1]:[overflow-wrap:anywhere] [&_h1]:tracking-normal"
      actions={<Badge tone="neutral"><LockKeyhole size={12} />Restricted</Badge>} />
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <Tabs className="min-w-0 max-w-full" value={area} onValueChange={(value) => { setArea(value); setEditing(false); }}>
        <TabsList className="h-auto max-w-full flex-wrap justify-start" aria-label="Patent application areas">
          <TabsTrigger value="application">Application</TabsTrigger>
          <TabsTrigger value="parties">Parties</TabsTrigger>
          <TabsTrigger value="priorities">Priorities</TabsTrigger>
          <TabsTrigger value="documents"><FileText size={16} />Documents</TabsTrigger>
          <TabsTrigger value="lifecycle">Lifecycle</TabsTrigger>
        </TabsList>
      </Tabs>
      {area === "application" && !editing && !isHistory && canWrite && current.is_active
        && <Button variant="ghost" onClick={() => setEditing(true)}><Pencil size={16} />Edit application</Button>}
    </div>
    {!current.is_active && <p role="status" className="text-sm capitalize">{current.lifecycle_status}. Application history and source documents are read-only.</p>}
    {area === "lifecycle" ? <PatentRecordLifecycle record={current} canReview={canReview} />
      : area === "parties" ? <PatentParties record={current} canWrite={canWrite} onOpenDocuments={() => setArea("documents")} />
      : area === "priorities" ? <PatentPriorities record={current} canWrite={canWrite} onOpenDocuments={() => setArea("documents")} />
      : area === "documents" ? <IpDocumentWorkspace assetType="Patent" scopeDocketId={current.docket_id}
        dockets={[{ id: current.docket_id, title: current.facts.title }]}
        canUpload={current.is_active && canWrite && canUpload} canManage={current.is_active && canWrite && canManage}
        canReview={current.is_active && canReview} canConfigure={current.is_active && canConfigure} />
        : editing && current.is_active ? <ApplicationForm initial={current} onOpenDocuments={() => setArea("documents")}
          onCancel={() => setEditing(false)} onSaved={() => { setEditing(false); setVersion(undefined); }} />
          : <>
            <form className="flex min-w-0 flex-wrap items-end gap-2" onSubmit={(event) => { event.preventDefault(); setVersion(Number(versionInput)); }}>
              <div className="w-32"><Label htmlFor="patent-application-version">Version</Label>
                <Input id="patent-application-version" type="number" min={1} max={current.version} required value={versionInput} placeholder={String(current.version)} onChange={(event) => setVersionInput(event.target.value)} /></div>
              <Button type="submit" variant="secondary">Open version</Button>
              {isHistory && <Button variant="ghost" onClick={() => setVersion(undefined)}>Current version</Button>}
            </form>
            {isHistory && historical.isPending ? <Skeleton className="h-32 w-full" /> : isHistory && historical.isError
              ? <QueryErrorState title="Could not load application history" error={historical.error} onRetry={historical.refetch} />
              : shown && <section className="min-w-0 space-y-4 border-t border-line pt-4" aria-label="Application facts">
                <h2 className="break-words text-lg font-semibold">{shown.facts.title}</h2>
                <dl className="grid min-w-0 gap-4 text-sm sm:grid-cols-2">
                  {[ ["Version", shown.version], ["Application kind", label(shown.facts.application_kind)],
                    ["Jurisdiction", shown.facts.jurisdiction], ["Office", shown.facts.office],
                    ["Recorded filing date", shown.facts.filing_date ?? "Not recorded"],
                    ["Recorded publication date", shown.facts.publication_date ?? "Not recorded"],
                  ].map(([name, value]) => <div key={String(name)} className="min-w-0"><dt className="text-mute">{name}</dt><dd className="break-words capitalize">{value}</dd></div>)}
                </dl>
                {shown.facts.source_pending_identifier_allocation && <p className="text-sm">Application number pending allocation</p>}
                {shown.facts.source.kind === "document_version" && <PatentSourceDownload source={shown.facts.source} />}
                <h3 className="font-semibold">Recorded identifiers</h3>
                <ul className="divide-y divide-line" aria-label="Application identifiers">
                  {shown.facts.identifiers.map((identifier, index) => <li key={`${identifier.identifier_kind}:${index}`} className="min-w-0 space-y-1 py-3">
                    <p className="text-sm capitalize text-mute">{identifier.identifier_kind}</p><p className="whitespace-pre-wrap break-words">{identifier.raw_value}</p>
                    {identifier.source.kind === "document_version" && <PatentSourceDownload source={identifier.source} />}
                  </li>)}
                </ul>
                {!shown.facts.identifiers.length && <p className="text-sm text-mute">No identifiers recorded in this version.</p>}
              </section>}
          </>}
  </div>;
}

type IdentifierInput = { key: string; kind: "application" | "publication" | "grant"; value: string; sourceId: string };

function ApplicationForm({ family, initial, onSaved, onCancel, onOpenDocuments }: {
  family?: PatentFamily; initial?: PatentApplication; onSaved: (application: PatentApplication) => void;
  onCancel: () => void; onOpenDocuments: () => void;
}) {
  const queryClient = useQueryClient();
  const base = useRef({ family, initial });
  const creationKey = useRef<string | null>(null);
  const [title, setTitle] = useState(initial?.facts.title ?? family?.facts.title ?? "");
  const [kind, setKind] = useState<PatentApplicationFacts["application_kind"]>(initial?.facts.application_kind ?? "complete");
  const [jurisdiction, setJurisdiction] = useState(initial?.facts.jurisdiction ?? "");
  const [office, setOffice] = useState(initial?.facts.office ?? "");
  const [filingDate, setFilingDate] = useState(initial?.facts.filing_date ?? "");
  const [publicationDate, setPublicationDate] = useState(initial?.facts.publication_date ?? "");
  const [pending, setPending] = useState(initial?.facts.source_pending_identifier_allocation ?? true);
  const [reason, setReason] = useState("");
  const [sourceId, setSourceId] = useState(initial?.facts.source.kind === "document_version" ? initial.facts.source.document_version_id : "");
  const [identifiers, setIdentifiers] = useState<IdentifierInput[]>(() => initial?.facts.identifiers.map((row, index) => ({
    key: `saved-${index}`, kind: row.identifier_kind, value: row.raw_value,
    sourceId: row.source.kind === "document_version" ? row.source.document_version_id : "",
  })) ?? []);
  const docketId = initial?.docket_id ?? family!.docket_id;
  const sources = useQuery({ queryKey: ["ip", "documents", docketId], queryFn: () => fetchIpDocumentsForDocket(docketId) });
  const options = sources.data?.items.flatMap((document) => document.versions.map((version) => ({
    label: `${document.title} - version ${version.version}`, pin: {
      kind: "document_version" as const, document_id: document.id, document_version_id: version.id, content_sha256: version.sha256_hex,
    },
  }))) ?? [];
  const retained = initial ? [initial.facts.source, ...initial.facts.identifiers.map((row) => row.source)] : [];
  for (const source of retained) {
    if (source.kind === "document_version" && !options.some((option) => option.pin.document_version_id === source.document_version_id)) {
      options.push({ label: "Retained source version", pin: source });
    }
  }
  const sourcePin = (id: string): PatentSource => {
    const chosen = options.find((option) => option.pin.document_version_id === id);
    if (!chosen) throw new Error("Select an available source document version.");
    return chosen.pin;
  };
  const save = useMutation({
    mutationFn: async () => {
      const facts: PatentApplicationFacts = { title, application_kind: kind, jurisdiction, office,
        filing_date: filingDate || null, publication_date: publicationDate || null,
        source_pending_identifier_allocation: pending, source: sourcePin(sourceId),
        identifiers: identifiers.map((row) => ({ identifier_kind: row.kind, raw_value: row.value, source: sourcePin(row.sourceId) })),
      };
      creationKey.current ??= crypto.randomUUID();
      if (base.current.initial) return correctPatentApplication(base.current.initial, facts, reason);
      if (!base.current.family) throw new Error("Reload the application family before saving.");
      return createPatentApplication(base.current.family, facts, creationKey.current);
    },
    onSuccess: async (application) => {
      await queryClient.cancelQueries({ queryKey: key(application.id), exact: true });
      queryClient.setQueryData(key(application.id), application);
      await queryClient.invalidateQueries({ queryKey: ["ip", "patent-applications"] });
      onSaved(application);
    },
  });
  const selectSource = (id: string, name: string, value: string, onChange: (value: string) => void) => <div className="min-w-0">
    <Label htmlFor={id}>{name}</Label><select id={id} className={selectClass} required value={value}
      disabled={sources.isPending || sources.isError} onChange={(event) => onChange(event.target.value)}>
      <option value="">{sources.isPending ? "Loading source documents..." : "Select source version"}</option>
      {options.map((option) => <option key={option.pin.document_version_id} value={option.pin.document_version_id}>{option.label}</option>)}
    </select>
  </div>;
  const updateIdentifier = (key: string, changes: Partial<IdentifierInput>) => setIdentifiers((rows) => rows.map((row) => row.key === key ? { ...row, ...changes } : row));
  return <form className="min-w-0 space-y-4 border-y border-line py-5" aria-label={initial ? "Edit patent application" : "New patent application"}
    onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
    <h2 className="text-lg font-semibold">{initial ? "Application correction" : "New application"}</h2>
    <fieldset className="min-w-0 space-y-4" disabled={save.isPending}>
      <div><Label htmlFor="patent-app-title">Application title</Label><Input id="patent-app-title" required maxLength={255} value={title} onChange={(event) => setTitle(event.target.value)} /></div>
      <div className="grid min-w-0 gap-4 sm:grid-cols-2">
        <div className="min-w-0"><Label htmlFor="patent-app-kind">Application kind</Label><select id="patent-app-kind" className={selectClass} value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}>
          {patentApplicationKinds.map((value) => <option key={value} value={value}>{label(value)}</option>)}
        </select></div>
        <div className="min-w-0"><Label htmlFor="patent-app-jurisdiction">Jurisdiction code</Label><Input id="patent-app-jurisdiction" required pattern="[A-Z]{2}" minLength={2} maxLength={2} value={jurisdiction} onChange={(event) => setJurisdiction(event.target.value)} /></div>
        <div className="min-w-0 sm:col-span-2"><Label htmlFor="patent-app-office">Office</Label><Input id="patent-app-office" required maxLength={80} value={office} onChange={(event) => setOffice(event.target.value)} /></div>
        <div className="min-w-0"><Label htmlFor="patent-app-filing">Recorded filing date</Label><Input id="patent-app-filing" type="date" value={filingDate} onChange={(event) => setFilingDate(event.target.value)} /></div>
        <div className="min-w-0"><Label htmlFor="patent-app-publication">Recorded publication date</Label><Input id="patent-app-publication" type="date" value={publicationDate} onChange={(event) => setPublicationDate(event.target.value)} /></div>
      </div>
      {selectSource("patent-app-source", "Application source version", sourceId, setSourceId)}
      {sources.isError && <QueryErrorState title="Could not load application sources" error={sources.error} onRetry={sources.refetch} />}
      {!sources.isPending && !sources.isError && !options.length && <div className="space-y-2"><p className="text-sm">No source documents are available.</p>
        <Button type="button" variant="secondary" onClick={onOpenDocuments}><FileText size={16} />Open documents</Button></div>}
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={pending}
        disabled={identifiers.some((row) => row.kind === "application")} onChange={(event) => setPending(event.target.checked)} />
        <span className="min-w-0">Application number pending allocation</span></label>
      <section className="min-w-0 space-y-3" aria-label="Identifier editor">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">Identifiers</h3>
          <Button type="button" variant="secondary" disabled={identifiers.length >= 20} onClick={() => {
            setPending(false); setIdentifiers((rows) => [...rows, { key: crypto.randomUUID(), kind: "application", value: "", sourceId }]);
          }}><Plus size={16} />Add identifier</Button></div>
        {identifiers.map((row, index) => <div key={row.key} className="min-w-0 space-y-3 border-t border-line py-3">
          <div className="flex min-w-0 flex-wrap items-center justify-between gap-2"><h4 className="text-sm font-medium">Identifier {index + 1}</h4>
            <Button type="button" variant="ghost" aria-label={`Remove identifier ${index + 1}`} title={`Remove identifier ${index + 1}`} onClick={() => setIdentifiers((rows) => rows.filter((item) => item.key !== row.key))}><Trash2 size={16} /></Button></div>
          <div className="grid min-w-0 gap-3 sm:grid-cols-2"><div className="min-w-0"><Label htmlFor={`patent-id-kind-${index}`}>Identifier {index + 1} kind</Label>
            <select id={`patent-id-kind-${index}`} className={selectClass} value={row.kind} onChange={(event) => { if (event.target.value === "application") setPending(false); updateIdentifier(row.key, { kind: event.target.value as IdentifierInput["kind"] }); }}>
              <option value="application">Application</option><option value="publication">Publication</option><option value="grant">Grant</option>
            </select></div><div className="min-w-0"><Label htmlFor={`patent-id-value-${index}`}>Identifier {index + 1} value</Label><Input id={`patent-id-value-${index}`} required maxLength={120} value={row.value} onChange={(event) => updateIdentifier(row.key, { value: event.target.value })} /></div></div>
          {selectSource(`patent-id-source-${index}`, `Identifier ${index + 1} source version`, row.sourceId, (value) => updateIdentifier(row.key, { sourceId: value }))}
        </div>)}
      </section>
      {initial && <div><Label htmlFor="patent-app-reason">Correction reason</Label><Textarea id="patent-app-reason" required minLength={8} maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} /></div>}
    </fieldset>
    {save.isError && <p role="alert" className="break-words text-sm text-danger-500">{apiErrorMessage(save.error, "Application could not be saved.")}</p>}
    <div className="flex flex-wrap gap-2"><Button type="submit" disabled={save.isPending || sources.isPending || sources.isError || !sourceId}>{save.isPending ? "Saving..." : initial ? "Save application correction" : "Create application"}</Button>
      <Button type="button" variant="ghost" disabled={save.isPending} onClick={onCancel}>Cancel</Button></div>
  </form>;
}
