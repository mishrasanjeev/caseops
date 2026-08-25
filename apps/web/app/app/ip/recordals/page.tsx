"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Download,
  FileText,
  GitBranch,
  Link2,
  LoaderCircle,
  Plus,
  RefreshCw,
  Scale,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  createIpRecordal,
  fetchIpDeadlineWorkspace,
  fetchIpDocket,
  fetchIpDockets,
  fetchIpDocuments,
  fetchIpDocumentsForDocket,
  fetchIpRecordals,
  fetchIpRecordalWorkspace,
  fetchIpRegistryWorkspaces,
  recordIpRecordalTransaction,
  type IpDocket,
  type IpDocument,
  type IpLegalDeadline,
  type IpRecordal,
  type IpRecordalParty,
  type IpRecordalPartyRole,
  type IpRecordalTransactionKind,
  type IpRecordalType,
  type IpRecordalWorkspace,
  type IpRegistryWorkspace,
  type IpTitleInterest,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import { useSession } from "@/lib/use-session";

const SELECT_CLASS =
  "h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm";

const TYPE_OPTIONS: Array<{ value: IpRecordalType; label: string }> = [
  { value: "assignment", label: "Assignment" },
  { value: "transmission", label: "Transmission" },
  { value: "registered_user", label: "Registered user" },
  { value: "licence", label: "Licence" },
  { value: "name_change", label: "Name change" },
  { value: "address_change", label: "Address change" },
  { value: "address_for_service_change", label: "Address for service" },
  { value: "association", label: "Associated mark" },
  { value: "division", label: "Divisional mark" },
  { value: "limitation", label: "Limitation" },
  { value: "disclaimer", label: "Disclaimer" },
  { value: "certified_copy", label: "Certified copy" },
  { value: "well_known_mark", label: "Well-known mark request" },
];

const PARTY_ROLES: Array<{ value: IpRecordalPartyRole; label: string }> = [
  { value: "registered_proprietor", label: "Registered proprietor" },
  { value: "assignor", label: "Assignor" },
  { value: "assignee", label: "Assignee" },
  { value: "transmitter", label: "Transmitter" },
  { value: "transmittee", label: "Transmittee" },
  { value: "licensor", label: "Licensor" },
  { value: "licensee", label: "Licensee" },
  { value: "registered_user", label: "Registered user" },
  { value: "applicant", label: "Applicant" },
  { value: "subject", label: "Subject" },
  { value: "authorized_signatory", label: "Authorized signatory" },
];

const TRANSITIONS: Record<IpRecordal["status"], IpRecordalTransactionKind[]> = {
  draft: ["review_approved", "withdrawn"],
  ready: ["filed", "withdrawn"],
  filed: ["acknowledgement_received", "defect_noted", "accepted", "rejected", "withdrawn"],
  defective: ["corrected", "rejected", "withdrawn"],
  accepted: [],
  rejected: [],
  withdrawn: [],
};

const DATE = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

function readable(value: string) {
  return value.replaceAll("_", " ");
}

function displayDate(value: string | null) {
  return value ? DATE.format(new Date(`${value.slice(0, 10)}T00:00:00`)) : "Not recorded";
}

function todayInput() {
  return new Date().toISOString().slice(0, 10);
}

function localDateTimeInput() {
  const date = new Date(Date.now() - new Date().getTimezoneOffset() * 60_000);
  return date.toISOString().slice(0, 16);
}

function parseList(value: string) {
  return [...new Set(value.split(/[\n,]/).map((row) => row.trim()).filter(Boolean))];
}

function parseClasses(value: string) {
  const rows = parseList(value).map(Number);
  if (rows.some((row) => !Number.isInteger(row) || row < 1 || row > 45)) {
    throw new Error("Affected classes must be unique Nice classes from 1 to 45.");
  }
  return [...new Set(rows)];
}

function documentsForDocket(documents: IpDocument[], docketId: string) {
  return documents.filter((document) =>
    document.links.some((link) => link.target_type === "docket" && link.target_id === docketId),
  );
}

function defaultParties(type: IpRecordalType, evidence = ""): IpRecordalParty[] {
  const roles: IpRecordalPartyRole[] =
    type === "assignment"
      ? ["assignor", "assignee"]
      : type === "transmission"
        ? ["transmitter", "transmittee"]
        : type === "licence"
          ? ["licensor", "licensee"]
          : type === "registered_user"
            ? ["registered_proprietor", "registered_user"]
            : ["registered_proprietor"];
  return roles.map((role) => ({
    role,
    name: "",
    identifier: null,
    address: null,
    evidence_reference: evidence,
  }));
}

function isTitleBearing(type: IpRecordalType) {
  return ["assignment", "transmission", "registered_user", "licence"].includes(type);
}

export default function RecordalsPage() {
  const canRead = useCapability("ip:read");
  const canWrite = useCapability("ip:write");
  const canApprove = useCapability("ip:approve");
  const session = useSession();
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [docketCatalogRequested, setDocketCatalogRequested] = useState(false);
  const [documentCatalogRequested, setDocumentCatalogRequested] = useState(false);

  const recordals = useQuery({
    queryKey: ["ip", "recordals", statusFilter, typeFilter],
    queryFn: () =>
      fetchIpRecordals({
        status: (statusFilter || null) as IpRecordal["status"] | null,
        recordalType: (typeFilter || null) as IpRecordalType | null,
      }),
    enabled: canRead,
  });
  const selectedRecordal = recordals.data?.items.find((row) => row.id === selectedId) ?? null;
  const selectedDocket = useQuery({
    queryKey: ["ip", "dockets", selectedRecordal?.docket_id],
    queryFn: () => fetchIpDocket(selectedRecordal!.docket_id),
    enabled: canRead && Boolean(selectedRecordal),
  });
  const dockets = useQuery({
    queryKey: ["ip", "dockets", "catalog"],
    queryFn: fetchIpDockets,
    enabled: canRead && docketCatalogRequested,
  });
  const documents = useQuery({
    queryKey: ["ip", "documents", selectedRecordal?.docket_id],
    queryFn: () => fetchIpDocumentsForDocket(selectedRecordal!.docket_id),
    enabled: canRead && Boolean(selectedRecordal),
  });
  const catalogDocuments = useQuery({
    queryKey: ["ip", "documents", "catalog"],
    queryFn: () => fetchIpDocuments(),
    enabled: canRead && documentCatalogRequested,
  });
  const workspace = useQuery({
    queryKey: ["ip", "recordals", selectedId, "workspace"],
    queryFn: () => fetchIpRecordalWorkspace(selectedId),
    enabled: canRead && Boolean(selectedId),
  });
  const registry = useQuery({
    queryKey: ["ip", "registry-links", selectedDocket.data?.id],
    queryFn: () => fetchIpRegistryWorkspaces(selectedDocket.data?.id),
    enabled: canRead && Boolean(selectedDocket.data),
  });
  const deadlines = useQuery({
    queryKey: ["ip", "deadline-workspace", selectedDocket.data?.id],
    queryFn: () => fetchIpDeadlineWorkspace(selectedDocket.data!.id),
    enabled: canRead && Boolean(selectedDocket.data),
  });

  useEffect(() => {
    if (!recordals.data?.items.some((row) => row.id === selectedId)) {
      setSelectedId(recordals.data?.items[0]?.id ?? "");
    }
  }, [recordals.data, selectedId]);

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["ip"] });
  }

  if (!canRead) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title="Post-registration" />
        <EmptyState title="IP access required" description="Ask an owner for IP read access." />
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        eyebrow="Trademark recordals"
        title="Post-registration"
        actions={
          <Button variant="outline" size="sm" onClick={refresh} disabled={recordals.isFetching}>
            <RefreshCw className={recordals.isFetching ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
            Refresh
          </Button>
        }
      />

      <nav className="flex min-w-0 flex-wrap gap-x-5 gap-y-2 border-b border-[var(--color-line)] pb-4 text-sm font-medium">
        <Link className="inline-flex items-center gap-1 underline" href="/app/ip/renewals">
          Trademark renewals <ArrowUpRight className="h-3.5 w-3.5" />
        </Link>
        <Link className="inline-flex items-center gap-1 underline" href="/app/ip">
          Cancellation, rectification and non-use <ArrowUpRight className="h-3.5 w-3.5" />
        </Link>
      </nav>

      {canWrite ? (
        <CreateRecordal
          dockets={dockets.data?.dockets ?? []}
          documents={catalogDocuments.data?.items ?? []}
          catalogPending={
            (docketCatalogRequested && dockets.isPending)
            || (documentCatalogRequested && catalogDocuments.isPending)
          }
          onCatalogRequested={() => {
            setDocketCatalogRequested(true);
            setDocumentCatalogRequested(true);
          }}
          membershipId={session.context?.membership.id ?? null}
          onCreated={async (id) => {
            await refresh();
            setSelectedId(id);
          }}
        />
      ) : null}

      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-end">
        <Field label="Recordal type">
          <select className={SELECT_CLASS} value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
            <option value="">All types</option>
            {TYPE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </Field>
        <Field label="Status">
          <select className={SELECT_CLASS} value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="">All statuses</option>
            {Object.keys(TRANSITIONS).map((status) => <option key={status} value={status}>{readable(status)}</option>)}
          </select>
        </Field>
      </div>

      {recordals.isPending ? (
        <div className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
          <Skeleton className="h-80" />
          <Skeleton className="h-[560px]" />
        </div>
      ) : recordals.isError ? (
        <QueryErrorState error={recordals.error} onRetry={refresh} />
      ) : (
        <div className="grid min-w-0 gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
          <RecordalList
            rows={recordals.data.items}
            dockets={dockets.data?.dockets ?? (selectedDocket.data ? [selectedDocket.data] : [])}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
          {workspace.isPending || selectedDocket.isPending ? (
            <Skeleton className="h-[560px]" />
          ) : workspace.isError ? (
            <QueryErrorState error={workspace.error} onRetry={() => workspace.refetch()} />
          ) : workspace.data && selectedDocket.data ? (
            <RecordalDetail
              workspace={workspace.data}
              docket={selectedDocket.data}
              allDockets={dockets.data?.dockets ?? [selectedDocket.data]}
              documents={documents.data?.items ?? []}
              registry={registry.data?.items ?? []}
              deadlines={deadlines.data?.deadlines ?? []}
              membershipId={session.context?.membership.id ?? null}
              canWrite={canWrite}
              canApprove={canApprove}
              onFamilyCatalogRequested={() => setDocketCatalogRequested(true)}
              onChanged={refresh}
            />
          ) : (
            <section className="border border-[var(--color-line)] bg-white p-8">
              <EmptyState title="Select a recordal" description="Choose a post-registration transaction." />
            </section>
          )}
        </div>
      )}
    </div>
  );
}

function CreateRecordal({
  dockets,
  documents,
  catalogPending,
  onCatalogRequested,
  membershipId,
  onCreated,
}: {
  dockets: IpDocket[];
  documents: IpDocument[];
  catalogPending: boolean;
  onCatalogRequested: () => void;
  membershipId: string | null;
  onCreated: (id: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [docketId, setDocketId] = useState("");
  const [type, setType] = useState<IpRecordalType>("assignment");
  const [legalBasis, setLegalBasis] = useState("");
  const [formCode, setFormCode] = useState("");
  const [executedOn, setExecutedOn] = useState("");
  const [effectiveOn, setEffectiveOn] = useState("");
  const [affectedRefs, setAffectedRefs] = useState("");
  const [affectedClasses, setAffectedClasses] = useState("");
  const [scopeKind, setScopeKind] = useState<"whole_right" | "partial">("whole_right");
  const [scopeDetails, setScopeDetails] = useState("");
  const [instrumentRefs, setInstrumentRefs] = useState<string[]>([]);
  const [costRefs, setCostRefs] = useState<string[]>([]);
  const [deadlineRuleKey, setDeadlineRuleKey] = useState("");
  const [reason, setReason] = useState("");
  const [parties, setParties] = useState<IpRecordalParty[]>(defaultParties("assignment"));
  const docket = dockets.find((row) => row.id === docketId) ?? null;
  const linkedDocuments = documentsForDocket(documents, docketId);

  useEffect(() => {
    const evidence = instrumentRefs[0] ?? "";
    setParties(defaultParties(type, evidence));
  }, [type]);

  const mutation = useMutation({
    mutationFn: async () => {
      if (!docket || !membershipId) throw new Error("Select a docket and signed-in actor.");
      const classes = parseClasses(affectedClasses);
      const refs = parseList(affectedRefs);
      if (!refs.length) throw new Error("At least one affected application or registration is required.");
      if (!instrumentRefs.length) throw new Error("Select at least one docket-linked instrument.");
      if (scopeKind === "partial" && !classes.length) throw new Error("Partial scope requires affected classes.");
      if (parties.some((party) => party.name.trim().length < 2 || !party.evidence_reference)) {
        throw new Error("Every party needs a name and selected supporting instrument.");
      }
      return createIpRecordal({
        docketId,
        expectedLifecycleVersion: docket.lifecycle_version,
        responsibleMembershipId: membershipId,
        reason: reason.trim(),
        recordalType: type,
        legalBasis: legalBasis.trim(),
        formCode: formCode.trim(),
        parties: parties.map((party) => ({
          ...party,
          name: party.name.trim(),
          identifier: party.identifier?.trim() || null,
          address: party.address?.trim() || null,
        })),
        executedOn: executedOn || null,
        effectiveOn: effectiveOn || null,
        affectedRegistrationRefs: refs,
        affectedClasses: classes,
        scopeKind,
        scopeDetails: scopeDetails.trim() ? { description: scopeDetails.trim() } : {},
        supportingInstrumentRefs: instrumentRefs,
        feeCostItemRefs: costRefs,
        deadlineRuleKey: deadlineRuleKey.trim() || null,
      });
    },
    onSuccess: async (row) => {
      toast.success("Post-registration recordal created.");
      setOpen(false);
      await onCreated(row.id);
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not create recordal.")),
  });

  function selectDocket(nextId: string) {
    setDocketId(nextId);
    const next = dockets.find((row) => row.id === nextId);
    setAffectedRefs(next?.primary_identifier ?? "");
    setInstrumentRefs([]);
    setCostRefs([]);
  }

  function selectInstrument(id: string, checked: boolean) {
    const next = checked
      ? [...new Set([...instrumentRefs, id])]
      : instrumentRefs.filter((value) => value !== id);
    setInstrumentRefs(next);
    setParties((rows) => rows.map((party) => ({
      ...party,
      evidence_reference: next.includes(party.evidence_reference)
        ? party.evidence_reference
        : next[0] ?? "",
    })));
  }

  return (
    <Card className="min-w-0">
      <CardHeader className="flex-row items-center justify-between gap-3">
        <CardTitle as="h2">New recordal</CardTitle>
        <Button
          size="sm"
          variant={open ? "ghost" : "outline"}
          onClick={() => {
            if (!open) onCatalogRequested();
            setOpen((value) => !value);
          }}
        >
          <Plus className="h-4 w-4" />
          {open ? "Close" : "Create"}
        </Button>
      </CardHeader>
      {open && catalogPending ? (
        <CardContent><Skeleton className="h-44" /></CardContent>
      ) : open ? (
        <CardContent>
          <form className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-3" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
            <Field label="IP docket">
              <select className={SELECT_CLASS} value={docketId} onChange={(event) => selectDocket(event.target.value)} required>
                <option value="">Select docket</option>
                {dockets.map((row) => <option key={row.id} value={row.id}>{row.title}</option>)}
              </select>
            </Field>
            <Field label="Recordal type">
              <select className={SELECT_CLASS} value={type} onChange={(event) => setType(event.target.value as IpRecordalType)}>
                {TYPE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </Field>
            <Field label="Form code"><Input value={formCode} onChange={(event) => setFormCode(event.target.value)} required /></Field>
            <div className="md:col-span-2 xl:col-span-3"><Field label="Legal basis"><Textarea value={legalBasis} onChange={(event) => setLegalBasis(event.target.value)} required /></Field></div>
            <Field label="Execution date"><Input type="date" value={executedOn} onChange={(event) => setExecutedOn(event.target.value)} required={isTitleBearing(type)} /></Field>
            <Field label="Effective date"><Input type="date" value={effectiveOn} onChange={(event) => setEffectiveOn(event.target.value)} required={isTitleBearing(type)} /></Field>
            <Field label="Deadline rule key"><Input value={deadlineRuleKey} onChange={(event) => setDeadlineRuleKey(event.target.value)} /></Field>
            <div className="md:col-span-2"><Field label="Affected application or registration references"><Textarea value={affectedRefs} onChange={(event) => setAffectedRefs(event.target.value)} required /></Field></div>
            <Field label="Affected classes"><Input value={affectedClasses} onChange={(event) => setAffectedClasses(event.target.value)} placeholder="9, 35, 42" /></Field>
            <fieldset className="min-w-0">
              <legend className="mb-1 text-sm font-medium">Scope</legend>
              <div className="flex min-w-0 gap-2">
                <Button type="button" size="sm" variant={scopeKind === "whole_right" ? "primary" : "outline"} onClick={() => setScopeKind("whole_right")}>Whole right</Button>
                <Button type="button" size="sm" variant={scopeKind === "partial" ? "primary" : "outline"} onClick={() => setScopeKind("partial")}>Partial</Button>
              </div>
            </fieldset>
            <div className="md:col-span-2"><Field label="Scope details"><Textarea value={scopeDetails} onChange={(event) => setScopeDetails(event.target.value)} /></Field></div>

            <fieldset className="min-w-0 md:col-span-2 xl:col-span-3">
              <legend className="mb-2 text-sm font-medium">Supporting instruments</legend>
              {docketId && !linkedDocuments.length ? (
                <p className="text-sm text-amber-800">No canonical document is linked to this docket.</p>
              ) : (
                <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                  {linkedDocuments.map((document) => (
                    <label key={document.id} className="flex min-w-0 items-start gap-2 border border-[var(--color-line)] p-3 text-sm">
                      <input type="checkbox" checked={instrumentRefs.includes(document.id)} onChange={(event) => selectInstrument(document.id, event.target.checked)} />
                      <span className="min-w-0 break-words">{document.title}<span className="block text-xs text-[var(--color-mute)]">{document.taxonomy_label}</span></span>
                    </label>
                  ))}
                </div>
              )}
            </fieldset>

            <fieldset className="min-w-0 md:col-span-2 xl:col-span-3">
              <div className="mb-2 flex items-center justify-between gap-3">
                <legend className="text-sm font-medium">Parties</legend>
                <Button type="button" size="sm" variant="ghost" onClick={() => setParties((rows) => [...rows, { role: "subject", name: "", identifier: null, address: null, evidence_reference: instrumentRefs[0] ?? "" }])}>
                  <Plus className="h-4 w-4" /> Add party
                </Button>
              </div>
              <div className="flex flex-col gap-3">
                {parties.map((party, index) => (
                  <div key={`${index}-${party.role}`} className="grid min-w-0 gap-3 border-t border-[var(--color-line)] pt-3 md:grid-cols-[180px_minmax(0,1fr)_minmax(0,1fr)_40px]">
                    <Field label="Role"><select className={SELECT_CLASS} value={party.role} onChange={(event) => setParties((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, role: event.target.value as IpRecordalPartyRole } : row))}>{PARTY_ROLES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></Field>
                    <Field label="Party name"><Input value={party.name} onChange={(event) => setParties((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, name: event.target.value } : row))} required /></Field>
                    <Field label="Instrument"><select className={SELECT_CLASS} value={party.evidence_reference} onChange={(event) => setParties((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, evidence_reference: event.target.value } : row))} required><option value="">Select</option>{instrumentRefs.map((id) => <option key={id} value={id}>{linkedDocuments.find((document) => document.id === id)?.title ?? id}</option>)}</select></Field>
                    <Button className="mt-6 w-8 px-0" type="button" size="sm" variant="ghost" aria-label="Remove party" title="Remove party" disabled={parties.length === 1} onClick={() => setParties((rows) => rows.filter((_, rowIndex) => rowIndex !== index))}><Trash2 className="h-4 w-4" /></Button>
                  </div>
                ))}
              </div>
            </fieldset>

            {docket?.cost_items.length ? (
              <fieldset className="min-w-0 md:col-span-2 xl:col-span-3">
                <legend className="mb-2 text-sm font-medium">Fee and cost items</legend>
                <div className="flex flex-wrap gap-3">
                  {docket.cost_items.map((cost) => <label key={cost.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={costRefs.includes(cost.id)} onChange={(event) => setCostRefs((rows) => event.target.checked ? [...new Set([...rows, cost.id])] : rows.filter((id) => id !== cost.id))} />{cost.description}</label>)}
                </div>
              </fieldset>
            ) : null}
            <div className="md:col-span-2 xl:col-span-3"><Field label="Creation reason"><Textarea value={reason} onChange={(event) => setReason(event.target.value)} required minLength={5} /></Field></div>
            <div className="md:col-span-2 xl:col-span-3"><Button type="submit" disabled={mutation.isPending || !membershipId}>{mutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}Create recordal</Button></div>
          </form>
        </CardContent>
      ) : null}
    </Card>
  );
}

function RecordalList({ rows, dockets, selectedId, onSelect }: { rows: IpRecordal[]; dockets: IpDocket[]; selectedId: string; onSelect: (id: string) => void }) {
  return (
    <Card className="min-w-0 self-start">
      <CardHeader><CardTitle as="h2">Recordals</CardTitle></CardHeader>
      <CardContent className="p-0">
        {rows.length ? <div className="divide-y divide-[var(--color-line)]">{rows.map((row) => {
          const docket = dockets.find((item) => item.id === row.docket_id);
          return <button key={row.id} type="button" className={row.id === selectedId ? "w-full bg-[var(--color-brand-50)] px-5 py-4 text-left" : "w-full px-5 py-4 text-left hover:bg-[var(--color-bg-2)]"} onClick={() => onSelect(row.id)}>
            <span className="block break-words font-semibold">{readable(row.recordal_type)}</span>
            <span className="mt-1 block break-words text-sm text-[var(--color-mute)]">{docket?.title ?? row.docket_id}</span>
            <span className="mt-2 flex flex-wrap gap-2"><Badge tone={row.status === "accepted" ? "success" : row.status === "defective" || row.status === "rejected" ? "warning" : "neutral"}>{readable(row.status)}</Badge><Badge tone="neutral">v{row.version}</Badge></span>
          </button>;
        })}</div> : <div className="p-6"><EmptyState title="No recordals" description="No post-registration transactions match the filters." /></div>}
      </CardContent>
    </Card>
  );
}

function RecordalDetail({ workspace, docket, allDockets, documents, registry, deadlines, membershipId, canWrite, canApprove, onFamilyCatalogRequested, onChanged }: {
  workspace: IpRecordalWorkspace;
  docket: IpDocket;
  allDockets: IpDocket[];
  documents: IpDocument[];
  registry: IpRegistryWorkspace[];
  deadlines: IpLegalDeadline[];
  membershipId: string | null;
  canWrite: boolean;
  canApprove: boolean;
  onFamilyCatalogRequested: () => void;
  onChanged: () => Promise<unknown>;
}) {
  const recordal = workspace.recordal;
  const linkedDocuments = documentsForDocket(documents, docket.id);
  return (
    <section className="min-w-0 border border-[var(--color-line)] bg-white">
      <header className="flex min-w-0 flex-col gap-3 border-b border-[var(--color-line)] p-5 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0"><p className="text-sm text-[var(--color-mute)]">{docket.title}</p><h2 className="break-words text-xl font-semibold">{TYPE_OPTIONS.find((option) => option.value === recordal.recordal_type)?.label ?? readable(recordal.recordal_type)}</h2><div className="mt-2 flex flex-wrap gap-2"><Badge tone={recordal.status === "accepted" ? "success" : recordal.status === "defective" || recordal.status === "rejected" ? "warning" : "neutral"}>{readable(recordal.status)}</Badge><Badge tone="neutral">Version {recordal.version}</Badge></div></div>
        <Link className="inline-flex items-center gap-1 text-sm font-medium underline" href="/app/ip">Open IP docket <ArrowUpRight className="h-3.5 w-3.5" /></Link>
      </header>
      <Tabs
        defaultValue="recordal"
        className="min-w-0"
        onValueChange={(value) => {
          if (value === "title") onFamilyCatalogRequested();
        }}
      >
        <TabsList className="flex h-auto min-w-0 flex-wrap justify-start gap-1 border-b border-[var(--color-line)] p-3">
          <TabsTrigger value="recordal">Recordal</TabsTrigger>
          <TabsTrigger value="title">Title at date</TabsTrigger>
          <TabsTrigger value="evidence">Evidence and controls</TabsTrigger>
          <TabsTrigger value="history">History</TabsTrigger>
        </TabsList>
        <TabsContent value="recordal" className="m-0 min-w-0 p-5">
          <RecordalOverview recordal={recordal} documents={linkedDocuments} />
          <div className="mt-6 border-t border-[var(--color-line)] pt-5">
            <TransactionPanel workspace={workspace} docket={docket} documents={linkedDocuments} registry={registry} deadlines={deadlines} membershipId={membershipId} canWrite={canWrite} canApprove={canApprove} onChanged={onChanged} />
          </div>
        </TabsContent>
        <TabsContent value="title" className="m-0 min-w-0 p-5"><TitleAssessment docket={docket} allDockets={allDockets} documents={documents} /></TabsContent>
        <TabsContent value="evidence" className="m-0 min-w-0 p-5"><EvidencePanel recordal={recordal} docket={docket} documents={linkedDocuments} registry={registry} deadlines={deadlines} /></TabsContent>
        <TabsContent value="history" className="m-0 min-w-0 p-5"><HistoryPanel events={workspace.transactions} /></TabsContent>
      </Tabs>
    </section>
  );
}

function RecordalOverview({ recordal, documents }: { recordal: IpRecordal; documents: IpDocument[] }) {
  return <div className="grid min-w-0 gap-6 lg:grid-cols-2">
    <section><h3 className="font-semibold">Legal particulars</h3><dl className="mt-3 grid gap-3 sm:grid-cols-2"><Datum label="Legal basis" value={recordal.legal_basis} wide /><Datum label="Form" value={recordal.form_code} /><Datum label="Execution" value={displayDate(recordal.executed_on)} /><Datum label="Effective" value={displayDate(recordal.effective_on)} /><Datum label="Scope" value={readable(String(recordal.scope_json.scope_kind ?? "whole_right"))} /><Datum label="Classes" value={recordal.affected_classes_json.join(", ") || "All affected classes"} /><Datum label="Affected rights" value={recordal.affected_registration_refs_json.join(", ")} wide /></dl></section>
    <section><h3 className="font-semibold">Parties</h3><div className="mt-3 divide-y divide-[var(--color-line)]">{recordal.parties_json.map((party, index) => <div key={`${party.role}-${index}`} className="py-3 first:pt-0"><p className="font-medium">{party.name}</p><p className="text-sm text-[var(--color-mute)]">{readable(party.role)} · {documents.find((document) => document.id === party.evidence_reference)?.title ?? party.evidence_reference}</p></div>)}</div></section>
  </div>;
}

function TransactionPanel({ workspace, docket, documents, registry, deadlines, membershipId, canWrite, canApprove, onChanged }: {
  workspace: IpRecordalWorkspace;
  docket: IpDocket;
  documents: IpDocument[];
  registry: IpRegistryWorkspace[];
  deadlines: IpLegalDeadline[];
  membershipId: string | null;
  canWrite: boolean;
  canApprove: boolean;
  onChanged: () => Promise<unknown>;
}) {
  const options = TRANSITIONS[workspace.recordal.status];
  const [kind, setKind] = useState<IpRecordalTransactionKind>(options[0] ?? "acknowledgement_received");
  const [effectiveAt, setEffectiveAt] = useState(localDateTimeInput());
  const [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState("");
  const [documentRefs, setDocumentRefs] = useState<string[]>([]);
  const [deadlineRefs, setDeadlineRefs] = useState<string[]>([]);
  const [costRefs, setCostRefs] = useState<string[]>([]);
  const [snapshotId, setSnapshotId] = useState("");
  const [registryRecordedOn, setRegistryRecordedOn] = useState("");
  const [conflictReviewed, setConflictReviewed] = useState(false);
  const snapshots = registry.flatMap((item) => item.link.match_status === "confirmed" ? item.snapshots.map((snapshot) => ({ link: item, snapshot })) : []);
  const selectedSnapshot = snapshots.find((row) => row.snapshot.id === snapshotId) ?? null;
  const requiresApproval = ["review_approved", "accepted", "rejected"].includes(kind);
  const requiresEvidence = ["filed", "defect_noted", "rejected", "accepted", "corrected"].includes(kind);

  useEffect(() => { if (options.length) setKind(options[0]); }, [workspace.recordal.id, workspace.recordal.status]);

  const mutation = useMutation({
    mutationFn: () => {
      if (!membershipId) throw new Error("Signed-in membership is unavailable.");
      const evidenceRefs = parseList(evidence);
      if (requiresEvidence && !evidenceRefs.length) throw new Error(`${readable(kind)} requires evidence.`);
      if (kind === "corrected" && !documentRefs.length) throw new Error("A corrective transaction requires a docket-linked corrected instrument.");
      if (kind === "accepted" && (!selectedSnapshot || !registryRecordedOn || !conflictReviewed)) throw new Error("Registry acceptance requires a confirmed snapshot, recorded date, and conflict review.");
      return recordIpRecordalTransaction({
        recordalId: workspace.recordal.id,
        expectedVersion: workspace.recordal.version,
        expectedLifecycleVersion: docket.lifecycle_version,
        transactionKind: kind,
        effectiveAt: new Date(effectiveAt).toISOString(),
        responsibleMembershipId: membershipId,
        reason: reason.trim(),
        sourceUrl: selectedSnapshot?.snapshot.source_url ?? null,
        sourceReference: selectedSnapshot ? `${selectedSnapshot.link.link.provider_key}:${selectedSnapshot.link.link.normalized_identifier}:${selectedSnapshot.snapshot.source_retrieved_at}` : null,
        evidenceRefs,
        documentRefs,
        deadlineRefs,
        costItemRefs: costRefs,
        registrySnapshotId: snapshotId || null,
        registryRecordedOn: registryRecordedOn || null,
        details: { client_registry_conflict_reviewed: conflictReviewed, affected_scope_confirmed: true },
      });
    },
    onSuccess: async (result) => {
      toast.success(`Recordal moved to ${readable(result.recordal.status)}.`);
      setReason(""); setEvidence(""); setDocumentRefs([]); setDeadlineRefs([]); setCostRefs([]); setSnapshotId(""); setRegistryRecordedOn(""); setConflictReviewed(false);
      await onChanged();
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not record transaction.")),
  });

  if (!options.length) return <div className="flex items-center gap-2 text-sm"><CheckCircle2 className="h-4 w-4 text-green-700" />This recordal is closed.</div>;
  if ((!canWrite && !canApprove) || (requiresApproval && !canApprove)) return <p className="text-sm text-[var(--color-mute)]">Current status: {readable(workspace.recordal.status)}</p>;

  return <form className="grid min-w-0 gap-4 md:grid-cols-2" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
    <h3 className="font-semibold md:col-span-2">Record transaction</h3>
    <Field label="Transaction"><select className={SELECT_CLASS} value={kind} onChange={(event) => setKind(event.target.value as IpRecordalTransactionKind)}>{options.filter((option) => !["review_approved", "accepted", "rejected"].includes(option) || canApprove).map((option) => <option key={option} value={option}>{readable(option)}</option>)}</select></Field>
    <Field label="Effective time"><Input type="datetime-local" value={effectiveAt} onChange={(event) => setEffectiveAt(event.target.value)} required /></Field>
    <div className="md:col-span-2"><Field label="Reason"><Textarea value={reason} onChange={(event) => setReason(event.target.value)} required minLength={5} /></Field></div>
    {requiresEvidence ? <div className="md:col-span-2"><Field label="Evidence references"><Textarea value={evidence} onChange={(event) => setEvidence(event.target.value)} required /></Field></div> : null}
    {documents.length ? <CheckGroup legend={kind === "corrected" ? "Corrected instrument" : "Linked documents"} rows={documents.map((document) => ({ id: document.id, label: document.title }))} selected={documentRefs} onChange={setDocumentRefs} /> : null}
    {deadlines.length ? <CheckGroup legend="Resulting deadlines" rows={deadlines.map((deadline) => ({ id: deadline.id, label: deadline.title }))} selected={deadlineRefs} onChange={setDeadlineRefs} /> : null}
    {docket.cost_items.length ? <CheckGroup legend="Cost items" rows={docket.cost_items.map((cost) => ({ id: cost.id, label: cost.description }))} selected={costRefs} onChange={setCostRefs} /> : null}
    {kind === "accepted" ? <><Field label="Confirmed Registry snapshot"><select className={SELECT_CLASS} value={snapshotId} onChange={(event) => setSnapshotId(event.target.value)} required><option value="">Select snapshot</option>{snapshots.map(({ link, snapshot }) => <option key={snapshot.id} value={snapshot.id}>{link.link.normalized_identifier} · {displayDate(snapshot.source_retrieved_at)}</option>)}</select></Field><Field label="Registry-recorded date"><Input type="date" value={registryRecordedOn} onChange={(event) => setRegistryRecordedOn(event.target.value)} required /></Field><label className="flex min-w-0 items-start gap-2 text-sm md:col-span-2"><input type="checkbox" checked={conflictReviewed} onChange={(event) => setConflictReviewed(event.target.checked)} /><span>Client instruction, instrument, affected scope, and Registry evidence reviewed</span></label></> : null}
    <div className="md:col-span-2"><Button type="submit" disabled={mutation.isPending || (requiresApproval && !canApprove)}>{mutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}Record {readable(kind)}</Button></div>
  </form>;
}

function TitleAssessment({ docket, allDockets, documents }: { docket: IpDocket; allDockets: IpDocket[]; documents: IpDocument[] }) {
  const [asOf, setAsOf] = useState(todayInput());
  const cutoff = new Date(`${asOf}T23:59:59`);
  const active = docket.title_interests.filter((interest) => new Date(`${interest.effective_from}T00:00:00`) <= cutoff && (!interest.effective_until || new Date(`${interest.effective_until}T23:59:59`) >= cutoff) && !["rejected", "withdrawn"].includes(interest.recordal_status));
  const registered = active.filter((interest) => interest.recordal_status === "recorded" && ["ownership", "assignment"].includes(interest.interest_type));
  const beneficial = active.filter((interest) => ["ownership", "assignment", "licence"].includes(interest.interest_type));
  const issues = assessTitle(docket, allDockets, documents, asOf);

  function downloadReport() {
    const lines = [
      `CaseOps title report`, `Right: ${docket.title}`, `As of: ${asOf}`, `Identifier: ${docket.primary_identifier ?? "Not recorded"}`, "",
      "Registry-recorded position:", ...(registered.length ? registered.map(reportInterest) : ["- No recorded interest at this date"]), "",
      "Beneficial/effective position:", ...(beneficial.length ? beneficial.map(reportInterest) : ["- No supported interest at this date"]), "",
      "Unresolved issues:", ...(issues.length ? issues.map((issue) => `- ${issue}`) : ["- None detected from accessible records"]),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `title-report-${docket.id}-${asOf}.txt`; anchor.click(); URL.revokeObjectURL(url);
  }

  return <div className="flex min-w-0 flex-col gap-6">
    <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-end sm:justify-between"><Field label="Position as of"><Input type="date" value={asOf} onChange={(event) => setAsOf(event.target.value)} /></Field><Button size="sm" variant="outline" onClick={downloadReport}><Download className="h-4 w-4" />Download dated report</Button></div>
    <section><h3 className="flex items-center gap-2 font-semibold"><Scale className="h-4 w-4" />Registry-recorded position</h3><InterestTable rows={registered} documents={documents} empty="No Registry-recorded ownership interest at this date." /></section>
    <section><h3 className="flex items-center gap-2 font-semibold"><GitBranch className="h-4 w-4" />Beneficial and effective position</h3><InterestTable rows={beneficial} documents={documents} empty="No supported beneficial or effective interest at this date." /></section>
    <section><h3 className="flex items-center gap-2 font-semibold"><AlertTriangle className="h-4 w-4" />Unresolved chain issues</h3>{issues.length ? <ul className="mt-3 space-y-2">{issues.map((issue) => <li key={issue} className="border-l-2 border-amber-500 bg-amber-50 p-3 text-sm text-amber-950">{issue}</li>)}</ul> : <p className="mt-3 flex items-center gap-2 text-sm"><CheckCircle2 className="h-4 w-4 text-green-700" />No issue detected from accessible title records at this date.</p>}</section>
  </div>;
}

function assessTitle(docket: IpDocket, allDockets: IpDocket[], documents: IpDocument[], asOf: string) {
  const issues: string[] = [];
  const cutoff = new Date(`${asOf}T23:59:59`);
  const relevant = docket.title_interests.filter((interest) => new Date(`${interest.effective_from}T00:00:00`) <= cutoff);
  for (const interest of relevant) {
    if (["pending", "filed"].includes(interest.recordal_status)) issues.push(`${interest.party_name}: effective but not Registry-recorded (${interest.recordal_status}).`);
    if (interest.conflict_flags_json.length) issues.push(`${interest.party_name}: ${interest.conflict_flags_json.map(readable).join(", ")}.`);
    const classes = Array.isArray(interest.scope_json.affected_classes) ? interest.scope_json.affected_classes : [];
    if (interest.scope_json.scope_kind === "partial" || classes.length) issues.push(`${interest.party_name}: partial scope${classes.length ? ` in classes ${classes.join(", ")}` : ""}.`);
    const source = documents.find((document) => document.id === interest.evidence_reference);
    if (!source) issues.push(`${interest.party_name}: canonical source document is unavailable; reference ${interest.evidence_reference}.`);
    else if (source.confidentiality !== "internal" || source.is_privileged) issues.push(`${interest.party_name}: source access is restricted (${source.confidentiality}${source.is_privileged ? ", privileged" : ""}).`);
  }
  for (const interest of docket.title_interests) {
    if (interest.executed_on && interest.executed_on <= asOf && interest.effective_from > asOf) issues.push(`${interest.party_name}: executed but not effective at the report date.`);
  }
  const ownership = docket.title_interests.filter((interest) => ["ownership", "assignment"].includes(interest.interest_type) && !["rejected", "withdrawn"].includes(interest.recordal_status)).sort((left, right) => left.effective_from.localeCompare(right.effective_from));
  for (let index = 1; index < ownership.length; index += 1) {
    const previous = ownership[index - 1]; const current = ownership[index];
    if (previous.effective_until) {
      const nextDay = new Date(`${previous.effective_until}T00:00:00`); nextDay.setUTCDate(nextDay.getUTCDate() + 1);
      if (nextDay.toISOString().slice(0, 10) < current.effective_from) issues.push(`Title gap from ${nextDay.toISOString().slice(0, 10)} to ${current.effective_from}.`);
    }
  }
  if (relationshipCycle(docket.id, allDockets)) issues.push("Related-right relationship cycle detected; legal interpretation remains unresolved.");
  return [...new Set(issues)];
}

function relationshipCycle(startId: string, dockets: IpDocket[]) {
  const graph = new Map(dockets.map((docket) => [docket.id, docket.title_interests.map((interest) => interest.related_docket_id).filter((id): id is string => Boolean(id))]));
  function visit(id: string, path: Set<string>): boolean { if (path.has(id)) return id === startId; const next = new Set(path); next.add(id); return (graph.get(id) ?? []).some((child) => visit(child, next)); }
  return (graph.get(startId) ?? []).some((id) => visit(id, new Set([startId])));
}

function reportInterest(interest: IpTitleInterest) { return `- ${interest.party_name}; ${interest.interest_type}; effective ${interest.effective_from}${interest.effective_until ? ` to ${interest.effective_until}` : " onward"}; recordal ${interest.recordal_status}; source ${interest.evidence_reference}`; }

function InterestTable({ rows, documents, empty }: { rows: IpTitleInterest[]; documents: IpDocument[]; empty: string }) {
  if (!rows.length) return <p className="mt-3 text-sm text-[var(--color-mute)]">{empty}</p>;
  return <div className="mt-3 overflow-x-auto"><table className="w-full min-w-[680px] text-left text-sm"><thead><tr className="border-b border-[var(--color-line)]"><th className="p-2">Party</th><th className="p-2">Interest</th><th className="p-2">Effective</th><th className="p-2">Recordal</th><th className="p-2">Scope</th><th className="p-2">Source</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id} className="border-b border-[var(--color-line)]"><td className="p-2 font-medium">{row.party_name}</td><td className="p-2">{readable(row.interest_type)}</td><td className="p-2">{displayDate(row.effective_from)}{row.effective_until ? ` to ${displayDate(row.effective_until)}` : " onward"}</td><td className="p-2"><Badge tone={row.recordal_status === "recorded" ? "success" : "warning"}>{readable(row.recordal_status)}</Badge></td><td className="p-2">{String(row.scope_json.scope_kind ?? "whole right").replaceAll("_", " ")}</td><td className="p-2 break-all">{documents.find((document) => document.id === row.evidence_reference)?.title ?? row.evidence_reference}</td></tr>)}</tbody></table></div>;
}

function EvidencePanel({ recordal, docket, documents, registry, deadlines }: { recordal: IpRecordal; docket: IpDocket; documents: IpDocument[]; registry: IpRegistryWorkspace[]; deadlines: IpLegalDeadline[] }) {
  return <div className="grid min-w-0 gap-6 lg:grid-cols-2">
    <EvidenceSection icon={<FileText className="h-4 w-4" />} title="Documents">{documents.filter((document) => recordal.supporting_instrument_refs_json.includes(document.id) || recordal.filing_evidence_refs_json.includes(document.id) || recordal.acceptance_evidence_refs_json.includes(document.id)).map((document) => <EvidenceRow key={document.id} title={document.title} detail={`${document.taxonomy_label} · ${document.confidentiality}${document.is_privileged ? " · privileged" : ""}`} />)}</EvidenceSection>
    <EvidenceSection icon={<Scale className="h-4 w-4" />} title="Fees and costs">{docket.cost_items.filter((cost) => recordal.fee_cost_item_refs_json.includes(cost.id)).map((cost) => <EvidenceRow key={cost.id} title={cost.description} detail={`${cost.currency} ${cost.amount_withheld ? "withheld" : ((cost.amount_minor ?? 0) / 100).toFixed(2)} · ${cost.reconciliation_status}`} />)}</EvidenceSection>
    <EvidenceSection icon={<ShieldCheck className="h-4 w-4" />} title="Deadlines">{deadlines.map((deadline) => <EvidenceRow key={deadline.id} title={deadline.title} detail={`${readable(deadline.state)} · ${deadline.result_on ? displayDate(deadline.result_on) : "date unconfirmed"}`} />)}</EvidenceSection>
    <EvidenceSection icon={<Link2 className="h-4 w-4" />} title="Registry sources">{registry.flatMap((item) => item.snapshots.map((snapshot) => <EvidenceRow key={snapshot.id} title={item.link.normalized_identifier} detail={`${item.link.match_status} · retrieved ${displayDate(snapshot.source_retrieved_at)}`} href={snapshot.source_url} />))}</EvidenceSection>
  </div>;
}

function EvidenceSection({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) { const rows = Array.isArray(children) ? children : [children]; return <section className="min-w-0"><h3 className="flex items-center gap-2 font-semibold">{icon}{title}</h3><div className="mt-3 divide-y divide-[var(--color-line)]">{rows.some(Boolean) ? children : <p className="py-3 text-sm text-[var(--color-mute)]">None linked</p>}</div></section>; }
function EvidenceRow({ title, detail, href }: { title: string; detail: string; href?: string }) { return <div className="min-w-0 py-3"><p className="break-words font-medium">{href ? <a className="inline-flex items-center gap-1 underline" href={href} target="_blank" rel="noreferrer">{title}<ArrowUpRight className="h-3.5 w-3.5" /></a> : title}</p><p className="break-words text-sm text-[var(--color-mute)]">{detail}</p></div>; }

function HistoryPanel({ events }: { events: IpRecordalWorkspace["transactions"] }) {
  return <div className="min-w-0 overflow-x-auto"><table className="w-full min-w-[720px] text-left text-sm"><thead><tr className="border-b border-[var(--color-line)]"><th className="p-2">Sequence</th><th className="p-2">Transaction</th><th className="p-2">Effective</th><th className="p-2">Reason</th><th className="p-2">Source</th></tr></thead><tbody>{events.map((event) => { const sourceUrl = typeof event.payload_json.source_url === "string" ? event.payload_json.source_url : null; return <tr key={event.id} className="border-b border-[var(--color-line)] align-top"><td className="p-2">{event.sequence}</td><td className="p-2 font-medium">{readable(String(event.payload_json.transaction_kind ?? event.event_kind))}</td><td className="p-2">{displayDate(event.effective_at)}</td><td className="p-2">{event.reason ?? "Not recorded"}</td><td className="p-2">{sourceUrl ? <a className="inline-flex items-center gap-1 underline" href={sourceUrl} target="_blank" rel="noreferrer">{event.source_reference ?? "Open source"}<ArrowUpRight className="h-3.5 w-3.5" /></a> : event.source_reference ?? "Internal"}</td></tr>; })}</tbody></table></div>;
}

function CheckGroup({ legend, rows, selected, onChange }: { legend: string; rows: Array<{ id: string; label: string }>; selected: string[]; onChange: (ids: string[]) => void }) {
  return <fieldset className="min-w-0"><legend className="mb-2 text-sm font-medium">{legend}</legend><div className="flex max-h-36 flex-col gap-2 overflow-y-auto border border-[var(--color-line)] p-3">{rows.map((row) => <label key={row.id} className="flex min-w-0 items-start gap-2 text-sm"><input type="checkbox" checked={selected.includes(row.id)} onChange={(event) => onChange(event.target.checked ? [...new Set([...selected, row.id])] : selected.filter((id) => id !== row.id))} /><span className="break-words">{row.label}</span></label>)}</div></fieldset>;
}

function Datum({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) { return <div className={wide ? "min-w-0 sm:col-span-2" : "min-w-0"}><dt className="text-xs font-semibold uppercase text-[var(--color-mute)]">{label}</dt><dd className="mt-1 break-words text-sm">{value}</dd></div>; }
function Field({ label, children }: { label: string; children: ReactNode }) { return <label className="flex min-w-0 flex-col gap-1 text-sm font-medium"><span>{label}</span>{children}</label>; }
