"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, FileText, Pencil, Plus, RefreshCw } from "lucide-react";
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
import { fetchIpDocumentsForDocket, listClients } from "@/lib/api/endpoints";
import {
  createPatentParty, fetchPatentParties, patentPartyRoles,
  type PatentApplication, type PatentFamily, type PatentParty, type PatentPartyFact, type PatentPartyPage,
} from "@/lib/api/ip-patents";

const selectClass = "h-10 w-full min-w-0 rounded-sm border border-line bg-surface px-3 text-sm";
const rootKey = (id: string) => ["ip", "patent-parties", id];
const pageKey = (id: string, history: boolean, cursor?: number, sequence?: number) =>
  [...rootKey(id), history, cursor ?? null, sequence ?? null];
type Anchor = PatentFamily | PatentApplication;

export function PatentParties({ record, canWrite, onOpenDocuments }: {
  record: Anchor; canWrite: boolean; onOpenDocuments: () => void;
}) {
  const queryClient = useQueryClient();
  const [history, setHistory] = useState(false);
  const [continuation, setContinuation] = useState<{ cursor: number; sequence: number }>();
  const [editor, setEditor] = useState<{ sequence: number; record: Anchor; party?: PatentParty }>();
  const [confirmed, setConfirmed] = useState<PatentParty>();
  const parties = useQuery({
    queryKey: pageKey(record.docket_id, history, continuation?.cursor, continuation?.sequence),
    queryFn: ({ signal }) => fetchPatentParties(record.docket_id, history, continuation, signal),
  });
  const busy = parties.isPending || parties.isError || parties.isFetching || !!editor;
  const editable = canWrite && record.is_active;
  const onSaved = async (party: PatentParty) => {
    await queryClient.cancelQueries({ queryKey: rootKey(record.docket_id) });
    setConfirmed(party);
    setContinuation(undefined);
    setHistory(false);
    queryClient.setQueryData<PatentPartyPage>(pageKey(record.docket_id, false), (old) => ({
      docket_id: record.docket_id, collection_sequence: party.sequence,
      parties: [party, ...(old?.parties ?? []).filter((row) => row.id !== party.id && row.id !== party.supersedes_party_id)].slice(0, 25),
      next_cursor: old?.next_cursor ?? null,
    }));
    setEditor(undefined);
    await queryClient.invalidateQueries({ queryKey: rootKey(record.docket_id) });
  };
  const showConfirmed = confirmed && (!parties.data || parties.data.collection_sequence < confirmed.sequence || parties.isError);
  return <section className="min-w-0 space-y-4 border-t border-line pt-4" aria-label="Patent parties">
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-3">
      <h2 className="text-lg font-semibold">Parties</h2>
      <div className="flex min-w-0 flex-wrap items-center gap-3">
        <label className="inline-flex items-center gap-2 text-sm"><input type="checkbox" checked={history} disabled={!!editor}
          onChange={(event) => { setHistory(event.target.checked); setContinuation(undefined); }} />Include superseded facts</label>
        {editable && <Button disabled={busy} onClick={() => setEditor({ sequence: parties.data!.collection_sequence, record })}><Plus size={16} />Add party</Button>}
      </div>
    </div>
    {editor && editable && <PartyForm key={editor.party?.id ?? "new"} record={editor.record} sequence={editor.sequence}
      initial={editor.party} onCancel={() => setEditor(undefined)} onSaved={onSaved} onOpenDocuments={onOpenDocuments}
      onReload={() => {
        setEditor(undefined); setContinuation(undefined);
        void queryClient.invalidateQueries({ queryKey: rootKey(record.docket_id) });
        void queryClient.invalidateQueries({ queryKey: ["ip", record.record_kind === "patent_family" ? "patent-family" : "patent-application", record.id], exact: true });
      }} />}
    {showConfirmed && <p role="status" className="break-words text-sm">Saved: {confirmed.fact.name}. Refreshing party records.</p>}
    {parties.isPending ? <Skeleton className="h-32 w-full" /> : parties.isError
      ? <QueryErrorState title="Could not load patent parties" error={parties.error} onRetry={() => {
        if (continuation) setContinuation(undefined); else void parties.refetch();
      }} /> : <>
        {!parties.data.parties.length && <p className="text-sm text-mute">No party facts recorded.</p>}
        <ul className="min-w-0 divide-y divide-line" aria-label="Recorded patent parties">
          {parties.data.parties.map((party) => <li key={party.id} className="min-w-0 space-y-2 py-4">
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 basis-64 grow"><h3 className="break-words font-semibold">{party.fact.name}</h3>
                <p className="text-sm capitalize">{party.fact.role}</p></div>
              {!party.is_current && <Badge tone="neutral">Superseded</Badge>}
              {editable && party.is_current && <Button variant="ghost" disabled={busy} onClick={() =>
                setEditor({ party, sequence: parties.data.collection_sequence, record })}><Pencil size={16} />Replace facts</Button>}
            </div>
            <address className="min-w-0 break-words text-sm not-italic">{party.fact.address.address_lines.map((line, index) => <div key={index}>{line}</div>)}
              <div>{[party.fact.address.city, party.fact.address.region, party.fact.address.postal_code, party.fact.address.country_code].filter(Boolean).join(", ")}</div></address>
            <p className="text-sm">Effective {party.fact.effective_from}{party.fact.effective_until ? ` to ${party.fact.effective_until}` : " onwards"}</p>
            <p className="break-words text-sm text-mute">{party.reason}</p>
            {party.fact.source.kind === "document_version" && <PatentSourceDownload source={party.fact.source} />}
          </li>)}
        </ul>
        <nav className="flex min-w-0 flex-wrap justify-between gap-2" aria-label="Party pages">
          <Button variant="ghost" disabled={!continuation || parties.isFetching || !!editor} onClick={() => setContinuation(undefined)}><ArrowLeft size={16} />Latest parties</Button>
          <Button variant="ghost" disabled={!parties.data.next_cursor || parties.isFetching || !!editor} onClick={() =>
            setContinuation({ cursor: parties.data.next_cursor!, sequence: parties.data.collection_sequence })}>Older parties<ArrowRight size={16} /></Button>
        </nav>
      </>}
  </section>;
}

function PartyForm({ record, sequence, initial, onCancel, onSaved, onOpenDocuments, onReload }: {
  record: Anchor; sequence: number; initial?: PatentParty; onCancel: () => void;
  onSaved: (party: PatentParty) => Promise<void>; onOpenDocuments: () => void; onReload: () => void;
}) {
  const base = useRef({ record, sequence, initial });
  const key = useRef<string | null>(null);
  const [role, setRole] = useState<PatentPartyFact["role"]>(initial?.fact.role ?? "inventor");
  const [name, setName] = useState(initial?.fact.name ?? "");
  const [clientId, setClientId] = useState(initial?.fact.client_id ?? "");
  const [lines, setLines] = useState(initial?.fact.address.address_lines.join("\n") ?? "");
  const [city, setCity] = useState(initial?.fact.address.city ?? "");
  const [region, setRegion] = useState(initial?.fact.address.region ?? "");
  const [postal, setPostal] = useState(initial?.fact.address.postal_code ?? "");
  const [country, setCountry] = useState(initial?.fact.address.country_code ?? "");
  const [from, setFrom] = useState(initial?.fact.effective_from ?? "");
  const [until, setUntil] = useState(initial?.fact.effective_until ?? "");
  const [reason, setReason] = useState("");
  const [sourceId, setSourceId] = useState(initial?.fact.source.kind === "document_version" ? initial.fact.source.document_version_id : "");
  const clients = useQuery({ queryKey: ["clients", "list"], queryFn: listClients });
  const sources = useQuery({ queryKey: ["ip", "documents", record.docket_id], queryFn: () => fetchIpDocumentsForDocket(record.docket_id) });
  const unavailableClient = Boolean(clientId) && clients.isSuccess && !clients.data.clients.some((client) => client.id === clientId && client.is_active);
  const options = sources.data?.items.flatMap((document) => document.versions.map((version) => ({
    label: `${document.title} - version ${version.version}`, source: {
      kind: "document_version" as const, document_id: document.id, document_version_id: version.id, content_sha256: version.sha256_hex,
    },
  }))) ?? [];
  const retained = initial?.fact.source;
  if (retained?.kind === "document_version" && !options.some((option) => option.source.document_version_id === retained.document_version_id)) {
    options.push({ label: "Retained source version", source: retained });
  }
  const save = useMutation({
    mutationFn: async () => {
      const source = options.find((option) => option.source.document_version_id === sourceId)?.source;
      if (!source) throw new Error("Select an available source document version.");
      const fact: PatentPartyFact = { role, name, client_id: clientId || null,
        address: { address_lines: lines.split(/\r?\n/), city, region: region || null,
          postal_code: postal || null, country_code: country },
        effective_from: from, effective_until: until || null, source,
      };
      key.current ??= crypto.randomUUID();
      return createPatentParty(base.current.record, base.current.sequence, fact, reason, base.current.initial?.id ?? null, key.current);
    },
    onSuccess: onSaved,
  });
  const input = (id: string, label: string, value: string, onChange: (value: string) => void,
    maxLength: number, required = false, type = "text") => <div className="min-w-0">
      <Label htmlFor={id}>{label}</Label><Input id={id} value={value} type={type} maxLength={maxLength} required={required}
        onChange={(event) => onChange(event.target.value)} /></div>;
  return <form className="min-w-0 space-y-4 border-y border-line py-4" aria-label={initial ? "Replace patent party" : "Add patent party"}
    onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
    <h3 className="font-semibold">{initial ? "Replacement party facts" : "New party facts"}</h3>
    <fieldset disabled={save.isPending} className="min-w-0 space-y-4">
      <div className="grid min-w-0 gap-4 sm:grid-cols-2">
        <div className="min-w-0"><Label htmlFor="patent-party-role">Party role</Label><select id="patent-party-role" className={selectClass} value={role} onChange={(event) => setRole(event.target.value as PatentPartyFact["role"])}>
          {patentPartyRoles.map((value) => <option key={value} value={value}>{value[0].toUpperCase() + value.slice(1)}</option>)}
        </select></div>
        {input("patent-party-name", "Party name", name, setName, 255, true)}
      </div>
      <div className="min-w-0"><Label htmlFor="patent-party-client">Linked client</Label><select id="patent-party-client" className={selectClass} value={clientId} disabled={clients.isPending || clients.isError} onChange={(event) => setClientId(event.target.value)}>
        <option value="">No linked client</option>
        {clients.data?.clients.filter((client) => client.is_active || client.id === clientId).map((client) => <option key={client.id} value={client.id} disabled={!client.is_active}>{client.name}{!client.is_active ? " (inactive)" : ""}</option>)}
        {clientId && clients.data && !clients.data.clients.some((client) => client.id === clientId) && <option value={clientId} disabled>Retained client unavailable</option>}
      </select></div>
      {clients.isError && <QueryErrorState title="Could not load clients" error={clients.error} onRetry={clients.refetch} />}
      <div className="min-w-0"><Label htmlFor="patent-party-address">Address lines</Label><Textarea id="patent-party-address" required rows={3} maxLength={1279} value={lines} onChange={(event) => setLines(event.target.value)} /></div>
      <div className="grid min-w-0 gap-4 sm:grid-cols-2">
        {input("patent-party-city", "City", city, setCity, 120, true)}
        {input("patent-party-region", "State or region", region, setRegion, 120)}
        {input("patent-party-postal", "Postal code", postal, setPostal, 40)}
        {input("patent-party-country", "Country code", country, setCountry, 2, true)}
        {input("patent-party-from", "Effective from", from, setFrom, 10, true, "date")}
        {input("patent-party-until", "Effective until", until, setUntil, 10, false, "date")}
      </div>
      <div className="min-w-0"><Label htmlFor="patent-party-source">Party source version</Label><select id="patent-party-source" className={selectClass} required value={sourceId} disabled={sources.isPending || sources.isError} onChange={(event) => setSourceId(event.target.value)}>
        <option value="">{sources.isPending ? "Loading source documents..." : "Select source version"}</option>
        {options.map((option) => <option key={option.source.document_version_id} value={option.source.document_version_id}>{option.label}</option>)}
      </select></div>
      {sources.isError && <QueryErrorState title="Could not load party sources" error={sources.error} onRetry={sources.refetch} />}
      {!sources.isPending && !sources.isError && !options.length && <Button type="button" variant="secondary" onClick={onOpenDocuments}><FileText size={16} />Open documents</Button>}
      <div className="min-w-0"><Label htmlFor="patent-party-reason">Party change reason</Label><Textarea id="patent-party-reason" required minLength={8} maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} /></div>
    </fieldset>
    {save.isError && <div className="min-w-0 space-y-2">
      <p role="alert" className="break-words text-sm text-danger-500">{apiErrorMessage(save.error, "Party facts could not be saved.")}</p>
      <Button type="button" variant="secondary" onClick={onReload}><RefreshCw size={16} />Reload record</Button>
    </div>}
    <div className="flex min-w-0 flex-wrap gap-2">
      <Button type="submit" disabled={save.isPending || sources.isPending || sources.isError || !sourceId || unavailableClient || (Boolean(clientId) && (clients.isError || clients.isPending))}>{save.isPending ? "Saving..." : "Save party facts"}</Button>
      <Button type="button" variant="ghost" disabled={save.isPending} onClick={onCancel}>Cancel</Button>
    </div>
  </form>;
}
