"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, FileText, LockKeyhole, Pencil, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { IpDocumentWorkspace } from "@/components/ip/IpDocumentWorkspace";
import { PatentFamilyLifecycle } from "@/components/ip/PatentFamilyLifecycle";
import { PatentFamilyApplications } from "@/components/ip/PatentApplicationWorkspace";
import { PatentSourceDownload } from "@/components/ip/PatentSourceDownload";
import { PatentParties } from "@/components/ip/PatentParties";
import { PatentFamilyGraph } from "@/components/ip/PatentPriorities";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { apiErrorMessage } from "@/lib/api/config";
import { fetchIpDocumentsForDocket, listClients } from "@/lib/api/endpoints";
import {
  correctPatentFamily, createPatentFamily, fetchPatentFamilies, fetchPatentFamily,
  type PatentFamily, type PatentFamilyFacts, type PatentFamilyStatusScope,
} from "@/lib/api/ip-patents";
import { useCapability } from "@/lib/capabilities";

const selectClass = "h-10 w-full min-w-0 rounded-sm border border-line bg-surface px-3 text-sm";
const key = (id: string) => ["ip", "patent-family", id];

export function PatentFamilyIndex() {
  const canRead = useCapability("ip:read");
  const canWrite = useCapability("ip:write");
  const router = useRouter();
  const [creating, setCreating] = useState(false);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState<string>();
  const [statusScope, setStatusScope] = useState<PatentFamilyStatusScope>("active");
  const families = useQuery({
    queryKey: ["ip", "patent-families", query, cursor, statusScope],
    queryFn: ({ signal }) => fetchPatentFamilies(query, cursor, signal, statusScope), enabled: canRead,
  });
  if (!canRead) return <p role="alert">Patent records are not available with your current permissions.</p>;
  return <div className="flex min-w-0 flex-col gap-5">
    <Link href="/app/ip" className="inline-flex w-fit items-center gap-2 text-sm"><ArrowLeft size={16} />IP workspace</Link>
    <PageHeader title="Patent families" actions={canWrite && !creating
      ? <Button onClick={() => setCreating(true)}><Plus size={16} />New disclosure</Button> : null} />
    {creating && <FamilyForm onCancel={() => setCreating(false)} onSaved={(family) => {
      router.push(`/app/ip/patents/${family.id}`);
    }} />}
    <form className="flex min-w-0 flex-wrap items-end gap-2" onSubmit={(event) => {
      event.preventDefault(); setQuery(search.trim()); setCursor(undefined);
    }}>
      <div className="min-w-0 flex-1 basis-48"><Label htmlFor="patent-search">Family title</Label>
        <Input id="patent-search" value={search} maxLength={200} onChange={(event) => setSearch(event.target.value)} /></div>
      <Button type="submit" variant="secondary" aria-label="Search patent families" title="Search patent families"><Search size={16} /></Button>
      <div className="min-w-0 basis-40"><Label htmlFor="patent-lifecycle-filter">Lifecycle</Label>
        <select id="patent-lifecycle-filter" className={selectClass} value={statusScope} onChange={(event) => {
          setStatusScope(event.target.value as PatentFamilyStatusScope); setCursor(undefined);
        }}><option value="active">Active records</option><option value="terminal">Closed records</option><option value="all">All records</option></select>
      </div>
    </form>
    {families.isPending ? <Skeleton className="h-40 w-full" /> : families.isError
      ? <QueryErrorState title="Could not load patent families" error={families.error} onRetry={families.refetch} />
      : <>
        <ul className="divide-y divide-line border-y border-line" aria-label="Patent families">
          {families.data.families.map((family) => <li key={family.id} className="flex min-w-0 flex-wrap items-center justify-between gap-3 py-3">
            <div className="min-w-0 flex-1 basis-48"><Link href={`/app/ip/patents/${family.id}`} className="break-words font-medium text-brand-700 hover:underline">{family.facts.title}</Link>
              <p className="text-sm text-mute">{family.facts.disclosure_date} · Version {family.version} · {family.lifecycle_status}</p></div>
            <Badge tone="neutral"><LockKeyhole size={12} />Restricted</Badge>
          </li>)}
        </ul>
        {families.data.families.length === 0 && <p className="text-sm text-mute">No accessible patent families on this page.</p>}
        <div className="flex flex-wrap justify-between gap-3">
          <Button variant="ghost" disabled={!cursor} onClick={() => setCursor(undefined)}><ArrowLeft size={16} />First page</Button>
          <Button variant="ghost" disabled={!families.data.next_cursor} onClick={() => setCursor(families.data.next_cursor ?? undefined)}>Next page<ArrowRight size={16} /></Button>
        </div>
      </>}
  </div>;
}

export function PatentFamilyDetail({ familyId }: { familyId: string }) {
  const canRead = useCapability("ip:read");
  const canWrite = useCapability("ip:write");
  const canUpload = useCapability("documents:upload");
  const canManage = useCapability("documents:manage");
  const canReview = useCapability("ip:approve");
  const canConfigure = useCapability("ip:taxonomy_admin");
  const [editing, setEditing] = useState(false);
  const [area, setArea] = useState("disclosure");
  const [versionInput, setVersionInput] = useState("");
  const [version, setVersion] = useState<number>();
  const family = useQuery({ queryKey: key(familyId), queryFn: ({ signal }) => fetchPatentFamily(familyId, undefined, signal), enabled: canRead });
  const historical = useQuery({
    queryKey: [...key(familyId), "version", version],
    queryFn: ({ signal }) => fetchPatentFamily(familyId, version, signal),
    enabled: canRead && !!family.data && version !== undefined && version !== family.data.version,
  });
  if (!canRead) return <p role="alert">Patent records are not available with your current permissions.</p>;
  if (family.isPending) return <Skeleton className="h-64 w-full" />;
  if (family.isError) return <QueryErrorState title="Could not open patent family" error={family.error} onRetry={family.refetch} />;
  const current = family.data;
  const isHistory = version !== undefined && version !== current.version;
  const shown = isHistory ? historical.data : current;
  return <div className="flex min-w-0 flex-col gap-5">
    <Link href="/app/ip/patents" className="inline-flex w-fit items-center gap-2 text-sm"><ArrowLeft size={16} />Patent families</Link>
    <PageHeader title={current.facts.title} className="[&>div:first-child]:min-w-0 [&>div:first-child]:flex-1 [&_h1]:[overflow-wrap:anywhere] [&_h1]:tracking-normal" actions={<Badge tone="neutral"><LockKeyhole size={12} />Restricted</Badge>} />
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <Tabs className="min-w-0 max-w-full" value={area} onValueChange={(value) => {
        setArea(value); setEditing(false);
      }}>
        <TabsList aria-label="Patent family areas" className="h-auto max-w-full flex-wrap justify-start">
          <TabsTrigger value="disclosure">Disclosure</TabsTrigger>
          <TabsTrigger value="applications">Applications</TabsTrigger>
          <TabsTrigger value="relationships">Relationships</TabsTrigger>
          <TabsTrigger value="parties">Parties</TabsTrigger>
          <TabsTrigger value="documents"><FileText size={16} />Documents</TabsTrigger>
          <TabsTrigger value="lifecycle">Lifecycle</TabsTrigger>
        </TabsList>
      </Tabs>
      {area === "disclosure" && !editing && !isHistory && canWrite && current.is_active && <Button variant="ghost" onClick={() => setEditing(true)}><Pencil size={16} />Edit disclosure</Button>}
    </div>
    {!current.is_active && <p role="status" className="text-sm capitalize">{current.lifecycle_status}. Disclosure history and source documents are read-only.</p>}
    {area === "applications" ? <PatentFamilyApplications family={current} canWrite={canWrite} onOpenDocuments={() => setArea("documents")} />
      : area === "relationships" ? <PatentFamilyGraph familyId={current.id} />
      : area === "parties" ? <PatentParties record={current} canWrite={canWrite} onOpenDocuments={() => setArea("documents")} />
      : area === "lifecycle" ? <PatentFamilyLifecycle family={current} canReview={canReview} />
      : area === "documents" ? <IpDocumentWorkspace dockets={[{ id: current.docket_id, title: current.facts.title }]}
      assetType="Patent" scopeDocketId={current.docket_id} canUpload={current.is_active && canWrite && canUpload} canManage={current.is_active && canWrite && canManage}
      canReview={current.is_active && canReview} canConfigure={current.is_active && canConfigure} />
      : editing && current.is_active ? <FamilyForm initial={current} onCancel={() => setEditing(false)} onSaved={() => { setEditing(false); setVersion(undefined); }} />
      : <>
        <form className="flex min-w-0 flex-wrap items-end gap-2" onSubmit={(event) => {
          event.preventDefault(); setVersion(Number(versionInput));
        }}><div className="w-32"><Label htmlFor="patent-history-version">Version</Label>
          <Input id="patent-history-version" type="number" min={1} max={current.version} required value={versionInput} placeholder={String(current.version)} onChange={(event) => setVersionInput(event.target.value)} /></div>
          <Button type="submit" variant="secondary">Open version</Button>
          {isHistory && <Button variant="ghost" onClick={() => setVersion(undefined)}>Current version</Button>}
        </form>
        {isHistory && historical.isPending ? <Skeleton className="h-32 w-full" /> : isHistory && historical.isError
          ? <QueryErrorState title="Could not load disclosure history" error={historical.error} onRetry={historical.refetch} />
          : shown && <section className="min-w-0 border-t border-line pt-4" aria-label="Disclosure facts">
            <div className="mb-4 flex flex-wrap gap-4 text-sm text-mute"><span>Version {shown.version}</span><span>Disclosed {shown.facts.disclosure_date}</span></div>
            <h2 className="mb-3 break-words text-lg font-semibold">{shown.facts.title}</h2>
            <p className="max-w-prose whitespace-pre-wrap break-words">{shown.facts.disclosure_narrative}</p>
            {shown.facts.source?.kind === "document_version" && <PatentSourceDownload source={shown.facts.source} />}
          </section>}
      </>}
  </div>;
}

function FamilyForm({ initial, onSaved, onCancel }: {
  initial?: PatentFamily; onSaved: (family: PatentFamily) => void; onCancel: () => void;
}) {
  const queryClient = useQueryClient();
  const base = useRef(initial);
  const creationKey = useRef<string | null>(null);
  const [title, setTitle] = useState(initial?.facts.title ?? "");
  const [clientId, setClientId] = useState(initial?.facts.client_id ?? "");
  const [date, setDate] = useState(initial?.facts.disclosure_date ?? "");
  const [narrative, setNarrative] = useState(initial?.facts.disclosure_narrative ?? "");
  const [reason, setReason] = useState("");
  const [sourceId, setSourceId] = useState(initial?.facts.source?.kind === "document_version" ? initial.facts.source.document_version_id : "");
  const clients = useQuery({ queryKey: ["clients", "list"], queryFn: listClients, enabled: !initial });
  const sources = useQuery({
    queryKey: ["ip", "documents", initial?.docket_id],
    queryFn: () => fetchIpDocumentsForDocket(initial!.docket_id), enabled: !!initial,
  });
  const options = sources.data?.items.flatMap((document) => document.versions.map((version) => ({ document, version }))) ?? [];
  const save = useMutation({
    mutationFn: async () => {
      const selected = options.find((option) => option.version.id === sourceId);
      const retained = base.current?.facts.source;
      const source = !sourceId ? null : selected ? {
        kind: "document_version" as const, document_id: selected.document.id,
        document_version_id: selected.version.id, content_sha256: selected.version.sha256_hex,
      } : retained?.kind === "document_version" && retained.document_version_id === sourceId ? retained : null;
      if (sourceId && !source) throw new Error("Select an available source document.");
      const facts: PatentFamilyFacts = { title, client_id: clientId, disclosure_date: date,
        disclosure_narrative: narrative, confidentiality: "restricted", source };
      creationKey.current ??= crypto.randomUUID();
      return base.current ? correctPatentFamily(base.current, facts, reason) : createPatentFamily(facts, creationKey.current);
    },
    onSuccess: async (family) => {
      await queryClient.cancelQueries({ queryKey: key(family.id), exact: true });
      queryClient.setQueryData(key(family.id), family);
      await queryClient.invalidateQueries({ queryKey: ["ip", "patent-families"] });
      onSaved(family);
    },
  });
  return <form className="min-w-0 space-y-4 border-y border-line py-5" aria-label={initial ? "Edit patent disclosure" : "New patent disclosure"} onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
    <h2 className="text-lg font-semibold">{initial ? "Disclosure correction" : "New disclosure"}</h2>
    <div><Label htmlFor="patent-title">Invention title</Label><Input id="patent-title" required maxLength={255} value={title} onChange={(event) => setTitle(event.target.value)} /></div>
    {!initial && <div><Label htmlFor="patent-client">Client</Label>
      {clients.isError ? <QueryErrorState title="Could not load clients" error={clients.error} onRetry={clients.refetch} />
        : <select id="patent-client" className={selectClass} required disabled={clients.isPending} value={clientId} onChange={(event) => setClientId(event.target.value)}>
          <option value="">{clients.isPending ? "Loading clients..." : "Select client"}</option>
          {clients.data?.clients.filter((client) => client.is_active).map((client) => <option key={client.id} value={client.id}>{client.name}</option>)}
        </select>}
      {!clients.isPending && !clients.isError && !clients.data?.clients.some((client) => client.is_active) && <Link href="/app/clients" className="text-sm text-brand-700 underline">Open clients</Link>}
    </div>}
    <div className="max-w-xs"><Label htmlFor="patent-disclosure-date">Disclosure date</Label><Input id="patent-disclosure-date" type="date" required value={date} onChange={(event) => setDate(event.target.value)} /></div>
    <div><Label htmlFor="patent-narrative">Invention disclosure</Label><Textarea id="patent-narrative" required rows={8} maxLength={30_000} value={narrative} onChange={(event) => setNarrative(event.target.value)} /></div>
    {initial && <>
      <div><Label htmlFor="patent-source">Source document version</Label>
        <select id="patent-source" className={selectClass} value={sourceId} disabled={sources.isPending} onChange={(event) => setSourceId(event.target.value)}>
          <option value="">No linked source</option>
          {sourceId && !options.some((option) => option.version.id === sourceId) && <option value={sourceId}>Retained source version</option>}
          {options.map(({ document, version }) => <option key={version.id} value={version.id}>{document.title} - version {version.version}</option>)}
        </select>
        {sources.isError && <QueryErrorState title="Could not load source documents" error={sources.error} onRetry={sources.refetch} />}
      </div>
      <div><Label htmlFor="patent-reason">Correction reason</Label><Textarea id="patent-reason" required minLength={8} maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} /></div>
    </>}
    {save.isError && <p role="alert" className="break-words text-sm text-danger-500">{apiErrorMessage(save.error, "Disclosure could not be saved.")}</p>}
    <div className="flex flex-wrap gap-2"><Button type="submit" disabled={save.isPending || (!initial && (!clientId || clients.isPending || clients.isError))}>{save.isPending ? "Saving..." : initial ? "Save correction" : "Create disclosure"}</Button>
      <Button type="button" variant="ghost" disabled={save.isPending} onClick={onCancel}>Cancel</Button></div>
  </form>;
}
