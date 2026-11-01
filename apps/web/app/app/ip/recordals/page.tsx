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
  Upload,
  X,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { toast } from "sonner";

import { IpDocketPicker } from "@/components/ip/IpDocketPicker";
import { RecordalInstrumentUpload } from "@/components/ip/RecordalInstrumentUpload";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { RecordSelect } from "@/components/ui/RecordSelect";
import { Skeleton } from "@/components/ui/Skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { Textarea } from "@/components/ui/Textarea";
import {
  API_FORM_ERROR_KEY,
  apiErrorMessage,
  apiFieldErrors,
  isApiErrorShape,
} from "@/lib/api/config";
import {
  createIpRecordal,
  fetchIpDocket,
  fetchIpDockets,
  fetchIpRecordalInstruments,
  fetchIpRecordals,
  fetchIpRecordalWorkspace,
  recordIpRecordalTransaction,
  type IpDocket,
  type IpDocument,
  type IpLegalDeadline,
  type IpRecordal,
  type IpRecordalListItem,
  type IpRecordalParty,
  type IpRecordalPartyRole,
  type IpRecordalTransactionKind,
  type IpRecordalType,
  type IpRecordalWorkspace,
  type IpRegistryWorkspace,
  type IpTitleInterest,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import { parseNiceClasses } from "@/lib/ip/nice-classes";
import { useSession } from "@/lib/use-session";

const SELECT_CLASS =
  "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm disabled:cursor-not-allowed disabled:opacity-60 aria-[invalid=true]:border-[var(--color-danger-500)]";

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

// The parties the API requires for each title-bearing recordal type.
const REQUIRED_ROLES: Partial<Record<IpRecordalType, { roles: IpRecordalPartyRole[]; need: string }>> = {
  assignment: { roles: ["assignor", "assignee"], need: "include an assignor and an assignee" },
  transmission: { roles: ["transmitter", "transmittee"], need: "include a transmitter and a transmittee" },
  licence: { roles: ["licensor", "licensee"], need: "include a licensor and a licensee" },
  registered_user: { roles: ["registered_user"], need: "include a registered user" },
};

// 422 field paths of POST /api/ip/recordals -> the control that shows the message.
const CREATE_FIELD_MAP: Readonly<Record<string, string>> = {
  docket_id: "recordal-docket",
  recordal_type: "recordal-type",
  form_code: "recordal-form-code",
  legal_basis: "recordal-legal-basis",
  executed_on: "recordal-executed-on",
  effective_on: "recordal-effective-on",
  affected_registration_refs: "recordal-affected-refs",
  affected_classes: "recordal-affected-classes",
  scope_details: "recordal-scope-details",
  supporting_instrument_refs: "recordal-instruments",
  parties: "recordal-parties",
  reason: "recordal-reason",
};
const PLACED_ERRORS = new Set(Object.values(CREATE_FIELD_MAP));

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

function formatList(items: string[]) {
  return items.length <= 1
    ? items.join("")
    : `${items.slice(0, -1).join("; ")}; and ${items[items.length - 1]}`;
}

function partyRoles(type: IpRecordalType): IpRecordalPartyRole[] {
  return type === "assignment"
    ? ["assignor", "assignee"]
    : type === "transmission"
      ? ["transmitter", "transmittee"]
      : type === "licence"
        ? ["licensor", "licensee"]
        : type === "registered_user"
          ? ["registered_proprietor", "registered_user"]
          : ["registered_proprietor"];
}

function blankParty(role: IpRecordalPartyRole): IpRecordalParty {
  return { role, name: "", identifier: null, address: null, evidence_reference: "" };
}

/** A new recordal type retargets the leading roles but keeps what was typed. */
function retargetParties(rows: IpRecordalParty[], type: IpRecordalType): IpRecordalParty[] {
  const roles = partyRoles(type);
  return [
    ...roles.map((role, index) => ({ ...(rows[index] ?? blankParty(role)), role })),
    ...rows.slice(roles.length),
  ];
}

function suggestedInstrumentClassification(type: IpRecordalType) {
  if (type === "assignment" || type === "transmission") return "assignment";
  if (type === "licence" || type === "registered_user") return "licence";
  return undefined;
}

function instrumentDetail(document: IpDocument) {
  return [
    document.taxonomy_label,
    `uploaded ${displayDate(document.created_at)}`,
    document.confidentiality === "internal" ? null : document.confidentiality,
    document.is_privileged ? "privileged" : null,
  ].filter(Boolean).join(" · ");
}

function instrumentCaption(document: IpDocument) {
  return `${document.title} · ${instrumentDetail(document)}`;
}

function isTitleBearing(type: IpRecordalType) {
  return ["assignment", "transmission", "registered_user", "licence"].includes(type);
}

function activeCostItems(docket: IpDocket) {
  // The API accepts only cost items that were never voided or superseded.
  return docket.cost_items.filter((cost) => cost.lineage_status === "active");
}

function controlProps(id: string, error?: string, hintId?: string) {
  const describedBy = [hintId, error ? `${id}-error` : null].filter(Boolean).join(" ");
  return {
    id,
    "aria-invalid": error ? (true as const) : undefined,
    "aria-describedby": describedBy || undefined,
  };
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
  const dockets = useQuery({
    queryKey: ["ip", "dockets", "catalog"],
    queryFn: fetchIpDockets,
    enabled: canRead && docketCatalogRequested,
  });
  const workspace = useQuery({
    queryKey: ["ip", "recordals", selectedId, "workspace"],
    queryFn: () => fetchIpRecordalWorkspace(selectedId),
    enabled: canRead && Boolean(selectedId),
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
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
          {selectedRecordal ? (
            <RecordalDetail
              recordal={workspace.data?.recordal ?? selectedRecordal}
              docketTitle={selectedRecordal.docket_title}
              workspace={workspace.data ?? null}
              allDockets={dockets.data?.dockets ?? (workspace.data ? [workspace.data.docket] : [])}
              workspacePending={workspace.isPending}
              workspaceError={workspace.isError ? workspace.error : null}
              onWorkspaceRetry={() => workspace.refetch()}
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

/**
 * Drafts a recordal on one docket (BUG-008). Every party cites an executed
 * instrument chosen from the docket's own documents, listed by the same
 * predicate the API validates; a docket with no instrument offers an upload
 * here instead of a dead end. Create stays disabled, with the reasons shown,
 * until the draft can pass the API contract.
 */
function CreateRecordal({
  membershipId,
  onCreated,
}: {
  membershipId: string | null;
  onCreated: (id: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [docketId, setDocketId] = useState("");
  const [docket, setDocket] = useState<IpDocket | null>(null);
  const [type, setType] = useState<IpRecordalType>("assignment");
  const [legalBasis, setLegalBasis] = useState("");
  const [formCode, setFormCode] = useState("");
  const [executedOn, setExecutedOn] = useState("");
  const [effectiveOn, setEffectiveOn] = useState("");
  const [affectedRefs, setAffectedRefs] = useState("");
  const [affectedClasses, setAffectedClasses] = useState("");
  const [scopeKind, setScopeKind] = useState<"whole_right" | "partial">("whole_right");
  const [scopeDetails, setScopeDetails] = useState("");
  const [extraRefs, setExtraRefs] = useState<string[]>([]);
  const [costRefs, setCostRefs] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [parties, setParties] = useState<IpRecordalParty[]>(() => partyRoles("assignment").map(blankParty));
  const [uploadOpen, setUploadOpen] = useState(false);
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});

  const instruments = useQuery({
    queryKey: ["ip", "recordals", "instruments", docketId],
    queryFn: ({ signal }) => fetchIpRecordalInstruments(docketId, signal),
    enabled: open && Boolean(docketId),
  });
  const instrumentRows = instruments.data?.items ?? [];
  const instrumentIds = new Set(instrumentRows.map((row) => row.id));
  const supportingRefs = [...new Set([
    ...parties.map((party) => party.evidence_reference),
    ...extraRefs,
  ])].filter((ref) => instrumentIds.has(ref));
  const classes = parseNiceClasses(affectedClasses);
  const refs = parseList(affectedRefs);
  const requiredRoles = REQUIRED_ROLES[type];
  const datesInverted = Boolean(executedOn && effectiveOn && effectiveOn < executedOn);
  const costs = docket ? activeCostItems(docket) : [];

  const blockers = [
    !docketId ? "choose the IP docket" : null,
    docketId && instruments.isPending ? "wait for this docket's instruments to load" : null,
    docketId && instruments.isError ? "reload this docket's instruments" : null,
    instruments.isSuccess && !instrumentRows.length ? "upload the executed instrument for this docket" : null,
    instrumentRows.length && parties.some((party) => !instrumentIds.has(party.evidence_reference))
      ? "choose an instrument for every party"
      : null,
    parties.some((party) => party.name.trim().length < 2) ? "name every party (at least 2 characters)" : null,
    requiredRoles && !requiredRoles.roles.every((role) => parties.some((party) => party.role === role))
      ? requiredRoles.need
      : null,
    !formCode.trim() ? "enter the form code" : null,
    legalBasis.trim().length < 3 ? "state the legal basis" : null,
    isTitleBearing(type) && (!executedOn || !effectiveOn) ? "enter the execution and effective dates" : null,
    datesInverted ? "make the effective date the execution date or later" : null,
    !refs.length ? "list at least one affected application or registration" : null,
    classes.errors.length ? "correct the affected classes" : null,
    scopeKind === "partial" && !classes.classes.length ? "list the affected classes of a partial recordal" : null,
    reason.trim().length < 5 ? "give a creation reason of at least 5 characters" : null,
    !membershipId ? "sign in again so the responsible lawyer is recorded" : null,
  ].filter((value): value is string => Boolean(value));

  function reset() {
    setDocketId(""); setDocket(null); setType("assignment"); setLegalBasis(""); setFormCode("");
    setExecutedOn(""); setEffectiveOn(""); setAffectedRefs(""); setAffectedClasses("");
    setScopeKind("whole_right"); setScopeDetails(""); setExtraRefs([]); setCostRefs([]); setReason("");
    setParties(partyRoles("assignment").map(blankParty)); setUploadOpen(false); setServerErrors({});
  }

  const mutation = useMutation({
    mutationFn: async () => {
      if (!docket || !membershipId || blockers.length) {
        throw new Error(`To create this recordal, ${formatList(blockers)}.`);
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
        affectedClasses: classes.classes,
        scopeKind,
        scopeDetails: scopeDetails.trim() ? { description: scopeDetails.trim() } : {},
        supportingInstrumentRefs: supportingRefs,
        feeCostItemRefs: costRefs.filter((id) => costs.some((cost) => cost.id === id)),
        deadlineRuleKey: null,
      });
    },
    onMutate: () => setServerErrors({}),
    onSuccess: async (row) => {
      toast.success("Draft recordal created.");
      reset();
      setOpen(false);
      await onCreated(row.id);
    },
    onError: async (error) => {
      const fields = apiFieldErrors(error, CREATE_FIELD_MAP);
      if (isApiErrorShape(error) && error.status === 409 && docketId) {
        // The docket changed meanwhile (for example a lifecycle transition).
        // Load its current state so the next attempt is made against it.
        const fresh = await fetchIpDocket(docketId).catch(() => null);
        if (fresh) setDocket(fresh);
      }
      setServerErrors(Object.keys(fields).length
        ? fields
        : { [API_FORM_ERROR_KEY]: apiErrorMessage(error, "Could not create the recordal.") });
    },
  });

  function selectDocket(nextId: string, next: IpDocket | null) {
    setDocketId(nextId);
    setDocket(next);
    setAffectedRefs(next?.primary_identifier ?? "");
    setExtraRefs([]);
    setCostRefs([]);
    setUploadOpen(false);
    setServerErrors({});
    setParties((rows) => rows.map((party) => ({ ...party, evidence_reference: "" })));
  }

  function updateParty(index: number, patch: Partial<IpRecordalParty>) {
    setParties((rows) => rows.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)));
  }

  const formError = [
    serverErrors[API_FORM_ERROR_KEY],
    ...Object.entries(serverErrors)
      .filter(([key]) => key !== API_FORM_ERROR_KEY && !PLACED_ERRORS.has(key))
      .map(([key, message]) => `${readable(key.replaceAll(".", " "))}: ${message}`),
  ].filter(Boolean).join(" ");
  const classError = [
    ...classes.errors.map((issue) => issue.message),
    scopeKind === "partial" && !classes.classes.length && !classes.errors.length
      ? "A partial recordal must list its affected classes."
      : null,
    serverErrors["recordal-affected-classes"],
  ].filter(Boolean).join(" ");
  const effectiveError = [
    datesInverted ? "The effective date cannot precede the execution date." : null,
    serverErrors["recordal-effective-on"],
  ].filter(Boolean).join(" ");
  const instrumentStatus = !docketId
    ? "Choose the IP docket first. Its executed instruments are listed here, and you can upload one if none is filed yet."
    : instruments.isPending
      ? "Loading this docket's instruments…"
      : instruments.isError
        ? "This docket's instruments could not be loaded."
        : instrumentRows.length
          ? `${instrumentRows.length} ${instrumentRows.length === 1 ? "instrument is" : "instruments are"} filed on this docket. Choose one for each party; tick any other instrument the recordal relies on.`
          : "No executed instrument is filed on this docket yet. Upload it here; it is linked to this docket and becomes selectable for every party.";
  const instrumentPlaceholder = !docketId
    ? "Choose a docket first"
    : instruments.isPending
      ? "Loading instruments…"
      : instruments.isError
        ? "Instruments could not be loaded"
        : instrumentRows.length
          ? "Select an instrument"
          : "Upload an instrument first";
  const instrumentOptions = [
    { value: "", label: instrumentPlaceholder, disabled: true },
    ...instrumentRows.map((row) => ({ value: row.id, label: instrumentCaption(row) })),
  ];
  const citedBy = (id: string) => parties
    .filter((party) => party.evidence_reference === id)
    .map((party) => PARTY_ROLES.find((option) => option.value === party.role)?.label ?? readable(party.role));
  const uploadPanel = docket ? (
    <RecordalInstrumentUpload
      docket={docket}
      suggestedTaxonomyKey={suggestedInstrumentClassification(type)}
      onUploaded={() => setUploadOpen(false)}
    />
  ) : null;

  return (
    <Card className="min-w-0">
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <CardTitle as="h2">Draft a recordal</CardTitle>
          <p className="mt-1 text-sm text-[var(--color-mute)]">
            Assignments, licences, name and address changes and other post-registration requests, each party cited to its executed instrument.
          </p>
        </div>
        <Button
          size="sm"
          variant={open ? "ghost" : "outline"}
          aria-expanded={open}
          aria-controls="new-recordal-form"
          onClick={() => setOpen((value) => !value)}
        >
          {open ? <X className="h-4 w-4" aria-hidden /> : <Plus className="h-4 w-4" aria-hidden />}
          {open ? "Close new recordal" : "New recordal"}
        </Button>
      </CardHeader>
      {open ? (
        <CardContent>
          <form
            id="new-recordal-form"
            aria-label="New recordal"
            className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-3"
            noValidate
            onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}
          >
            <div className="min-w-0 md:col-span-2 xl:col-span-3">
              <IpDocketPicker
                id="recordal-docket"
                label="IP docket"
                searchLabel="Find IP docket"
                value={docketId}
                onChange={selectDocket}
                error={serverErrors["recordal-docket"]}
                required
              />
            </div>
            <FormField id="recordal-type" label="Recordal type" error={serverErrors["recordal-type"]}>
              <select
                {...controlProps("recordal-type", serverErrors["recordal-type"])}
                className={SELECT_CLASS}
                value={type}
                onChange={(event) => {
                  const next = event.target.value as IpRecordalType;
                  setType(next);
                  setParties((rows) => retargetParties(rows, next));
                }}
              >
                {TYPE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </FormField>
            <FormField id="recordal-form-code" label="Form code" error={serverErrors["recordal-form-code"]}>
              <Input {...controlProps("recordal-form-code", serverErrors["recordal-form-code"])} value={formCode} onChange={(event) => setFormCode(event.target.value)} placeholder="TM-P" required />
            </FormField>
            <div className="min-w-0 md:col-span-2 xl:col-span-3">
              <FormField id="recordal-legal-basis" label="Legal basis" error={serverErrors["recordal-legal-basis"]}>
                <Textarea {...controlProps("recordal-legal-basis", serverErrors["recordal-legal-basis"])} value={legalBasis} onChange={(event) => setLegalBasis(event.target.value)} required />
              </FormField>
            </div>
            <FormField id="recordal-executed-on" label="Execution date" error={serverErrors["recordal-executed-on"]}>
              <Input {...controlProps("recordal-executed-on", serverErrors["recordal-executed-on"])} type="date" value={executedOn} onChange={(event) => setExecutedOn(event.target.value)} required={isTitleBearing(type)} />
            </FormField>
            <FormField id="recordal-effective-on" label="Effective date" error={effectiveError || undefined}>
              <Input {...controlProps("recordal-effective-on", effectiveError || undefined)} type="date" value={effectiveOn} onChange={(event) => setEffectiveOn(event.target.value)} required={isTitleBearing(type)} />
            </FormField>
            <div className="min-w-0 md:col-span-2">
              <FormField
                id="recordal-affected-refs"
                label="Affected application or registration references"
                hint="One per line or separated by commas."
                error={serverErrors["recordal-affected-refs"]}
              >
                <Textarea {...controlProps("recordal-affected-refs", serverErrors["recordal-affected-refs"], "recordal-affected-refs-hint")} value={affectedRefs} onChange={(event) => setAffectedRefs(event.target.value)} required />
              </FormField>
            </div>
            <FormField
              id="recordal-affected-classes"
              label="Affected classes"
              hint="Nice classes, for example 9, 35, 42. Leave blank when every class is affected."
              error={classError || undefined}
            >
              <Input {...controlProps("recordal-affected-classes", classError || undefined, "recordal-affected-classes-hint")} value={affectedClasses} onChange={(event) => setAffectedClasses(event.target.value)} />
            </FormField>
            <fieldset className="min-w-0">
              <legend className="mb-1 text-sm font-medium">Scope</legend>
              <div className="flex min-w-0 flex-wrap gap-2">
                <Button type="button" size="sm" aria-pressed={scopeKind === "whole_right"} variant={scopeKind === "whole_right" ? "primary" : "outline"} onClick={() => setScopeKind("whole_right")}>Whole right</Button>
                <Button type="button" size="sm" aria-pressed={scopeKind === "partial"} variant={scopeKind === "partial" ? "primary" : "outline"} onClick={() => setScopeKind("partial")}>Partial</Button>
              </div>
            </fieldset>
            <div className="min-w-0 md:col-span-2">
              <FormField id="recordal-scope-details" label="Scope details" error={serverErrors["recordal-scope-details"]}>
                <Textarea {...controlProps("recordal-scope-details", serverErrors["recordal-scope-details"])} value={scopeDetails} onChange={(event) => setScopeDetails(event.target.value)} />
              </FormField>
            </div>

            <fieldset
              id="recordal-instruments"
              className="min-w-0 md:col-span-2 xl:col-span-3"
              aria-describedby={["recordal-instruments-status", serverErrors["recordal-instruments"] ? "recordal-instruments-error" : null].filter(Boolean).join(" ")}
              data-testid="recordal-instruments"
            >
              <legend className="mb-2 text-sm font-medium">Supporting instruments</legend>
              <p
                id="recordal-instruments-status"
                role="status"
                className={instruments.isSuccess && !instrumentRows.length
                  ? "rounded-md border border-[var(--color-warn-border)] bg-[var(--color-warn-bg)] p-3 text-sm text-[var(--color-warn-text)]"
                  : "text-sm text-[var(--color-mute)]"}
              >
                {instrumentStatus}
              </p>
              {docketId && instruments.isPending ? <Skeleton className="mt-2 h-16" /> : null}
              {instruments.isError ? (
                <div className="mt-2">
                  <QueryErrorState error={instruments.error} title="Could not load this docket's instruments" onRetry={() => instruments.refetch()} />
                </div>
              ) : null}
              {instrumentRows.length ? (
                <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                  {instrumentRows.map((document) => {
                    const cited = citedBy(document.id);
                    return (
                      <label key={document.id} className="flex min-w-0 items-start gap-2 border border-[var(--color-line)] p-3 text-sm">
                        <input
                          type="checkbox"
                          className="mt-0.5"
                          checked={supportingRefs.includes(document.id)}
                          disabled={cited.length > 0}
                          onChange={(event) => setExtraRefs((rows) => event.target.checked ? [...new Set([...rows, document.id])] : rows.filter((id) => id !== document.id))}
                        />
                        <span className="min-w-0 break-words">
                          {document.title}
                          <span className="block text-xs text-[var(--color-mute)]">{instrumentDetail(document)}</span>
                          {cited.length ? <span className="block text-xs text-[var(--color-mute)]">Cited by {cited.join(", ")}</span> : null}
                        </span>
                      </label>
                    );
                  })}
                </div>
              ) : null}
              {instruments.data?.truncated ? (
                <p className="mt-2 text-xs text-[var(--color-mute)]">Showing the {instrumentRows.length} most recently updated instruments on this docket.</p>
              ) : null}
              {serverErrors["recordal-instruments"] ? (
                <p id="recordal-instruments-error" className="mt-2 text-sm text-[var(--color-danger-500)]">{serverErrors["recordal-instruments"]}</p>
              ) : null}
              {instruments.isSuccess && !instrumentRows.length ? <div className="mt-3">{uploadPanel}</div> : null}
              {instrumentRows.length ? (
                <div className="mt-3 flex min-w-0 flex-col gap-3">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="w-full sm:w-fit"
                    aria-expanded={uploadOpen}
                    aria-controls="recordal-instrument-upload"
                    onClick={() => setUploadOpen((value) => !value)}
                  >
                    <Upload className="h-4 w-4" aria-hidden />
                    {uploadOpen ? "Hide instrument upload" : "Upload another instrument"}
                  </Button>
                  {uploadOpen ? <div id="recordal-instrument-upload">{uploadPanel}</div> : null}
                </div>
              ) : null}
            </fieldset>

            <fieldset
              id="recordal-parties"
              className="min-w-0 md:col-span-2 xl:col-span-3"
              aria-describedby={serverErrors["recordal-parties"] ? "recordal-parties-error" : undefined}
            >
              <legend className="mb-2 text-sm font-medium">Parties</legend>
              <div className="flex min-w-0 flex-col gap-3">
                {parties.map((party, index) => (
                  <fieldset key={index} className="grid min-w-0 gap-3 border-t border-[var(--color-line)] pt-3 md:grid-cols-[180px_minmax(0,1fr)_minmax(0,1fr)_40px]">
                    <legend className="sr-only">Party {index + 1}</legend>
                    <FormField id={`recordal-party-${index}-role`} label="Role">
                      <select id={`recordal-party-${index}-role`} className={SELECT_CLASS} value={party.role} onChange={(event) => updateParty(index, { role: event.target.value as IpRecordalPartyRole })}>
                        {PARTY_ROLES.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                      </select>
                    </FormField>
                    <FormField id={`recordal-party-${index}-name`} label="Party name">
                      <Input id={`recordal-party-${index}-name`} value={party.name} onChange={(event) => updateParty(index, { name: event.target.value })} required minLength={2} />
                    </FormField>
                    <RecordSelect
                      id={`recordal-party-${index}-instrument`}
                      label="Instrument"
                      value={instrumentIds.has(party.evidence_reference) ? party.evidence_reference : ""}
                      options={instrumentOptions}
                      disabled={!instrumentRows.length}
                      required
                      aria-describedby="recordal-instruments-status"
                      className={SELECT_CLASS}
                      onChange={(event) => updateParty(index, { evidence_reference: event.target.value })}
                    />
                    <Button className="w-8 px-0 md:mt-6" type="button" size="sm" variant="ghost" aria-label={`Remove party ${index + 1}`} title="Remove party" disabled={parties.length === 1} onClick={() => setParties((rows) => rows.filter((_, rowIndex) => rowIndex !== index))}><Trash2 className="h-4 w-4" aria-hidden /></Button>
                  </fieldset>
                ))}
              </div>
              <Button type="button" size="sm" variant="ghost" className="mt-2" onClick={() => setParties((rows) => [...rows, blankParty("subject")])}>
                <Plus className="h-4 w-4" aria-hidden /> Add party
              </Button>
              {serverErrors["recordal-parties"] ? (
                <p id="recordal-parties-error" className="mt-2 text-sm text-[var(--color-danger-500)]">{serverErrors["recordal-parties"]}</p>
              ) : null}
            </fieldset>

            {costs.length ? (
              <fieldset className="min-w-0 md:col-span-2 xl:col-span-3">
                <legend className="mb-2 text-sm font-medium">Fee and cost items</legend>
                <div className="flex flex-wrap gap-3">
                  {costs.map((cost) => <label key={cost.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={costRefs.includes(cost.id)} onChange={(event) => setCostRefs((rows) => event.target.checked ? [...new Set([...rows, cost.id])] : rows.filter((id) => id !== cost.id))} />{cost.description}</label>)}
                </div>
              </fieldset>
            ) : null}
            <div className="min-w-0 md:col-span-2 xl:col-span-3">
              <FormField id="recordal-reason" label="Creation reason" error={serverErrors["recordal-reason"]}>
                <Textarea {...controlProps("recordal-reason", serverErrors["recordal-reason"])} value={reason} onChange={(event) => setReason(event.target.value)} required minLength={5} />
              </FormField>
            </div>
            <div className="flex min-w-0 flex-col gap-2 md:col-span-2 xl:col-span-3">
              {formError ? (
                <p role="alert" className="rounded-md border border-[var(--color-danger-border)] bg-[var(--color-danger-bg)] p-3 text-sm text-[var(--color-danger-text)]">{formError}</p>
              ) : null}
              {blockers.length ? (
                <p id="recordal-create-requirements" className="text-sm text-[var(--color-mute)]">
                  To create this recordal, {formatList(blockers)}.
                </p>
              ) : null}
              <Button
                type="submit"
                className="w-full sm:w-fit"
                disabled={mutation.isPending || blockers.length > 0}
                aria-describedby={blockers.length ? "recordal-create-requirements" : undefined}
              >
                {mutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden /> : <Plus className="h-4 w-4" aria-hidden />}
                Create recordal
              </Button>
            </div>
          </form>
        </CardContent>
      ) : null}
    </Card>
  );
}

function RecordalList({ rows, selectedId, onSelect }: { rows: IpRecordalListItem[]; selectedId: string; onSelect: (id: string) => void }) {
  return (
    <Card className="min-w-0 self-start">
      <CardHeader><CardTitle as="h2">Recordals</CardTitle></CardHeader>
      <CardContent className="p-0">
        {rows.length ? <div className="divide-y divide-[var(--color-line)]">{rows.map((row) => {
          return <button key={row.id} type="button" data-recordal-id={row.id} aria-pressed={row.id === selectedId} className={row.id === selectedId ? "w-full bg-[var(--color-brand-50)] px-5 py-4 text-left" : "w-full px-5 py-4 text-left hover:bg-[var(--color-bg-2)]"} onClick={() => onSelect(row.id)}>
            <span className="block break-words font-semibold">{readable(row.recordal_type)}</span>
            <span className="mt-1 block break-words text-sm text-[var(--color-mute)]">{row.docket_title}</span>
            <span className="mt-2 flex flex-wrap gap-2"><Badge tone={row.status === "accepted" ? "success" : row.status === "defective" || row.status === "rejected" ? "warning" : "neutral"}>{readable(row.status)}</Badge><Badge tone="neutral">v{row.version}</Badge></span>
          </button>;
        })}</div> : <div className="p-6"><EmptyState title="No recordals" description="No post-registration transactions match the filters." /></div>}
      </CardContent>
    </Card>
  );
}

function RecordalDetail({ recordal, docketTitle, workspace, allDockets, workspacePending, workspaceError, onWorkspaceRetry, membershipId, canWrite, canApprove, onFamilyCatalogRequested, onChanged }: {
  recordal: IpRecordal;
  docketTitle: string;
  workspace: IpRecordalWorkspace | null;
  allDockets: IpDocket[];
  workspacePending: boolean;
  workspaceError: unknown;
  onWorkspaceRetry: () => Promise<unknown>;
  membershipId: string | null;
  canWrite: boolean;
  canApprove: boolean;
  onFamilyCatalogRequested: () => void;
  onChanged: () => Promise<unknown>;
}) {
  const docket = workspace?.docket ?? null;
  const documents = workspace?.documents ?? [];
  const registry = workspace?.registry_workspaces ?? [];
  const deadlines = workspace?.deadline_workspace.deadlines ?? [];
  // Already the documents a recordal on this docket may cite (the API's own predicate).
  const linkedDocuments = documents;
  const loadState = (
    <RecordalWorkspaceState
      pending={workspacePending}
      error={workspaceError}
      onRetry={onWorkspaceRetry}
    />
  );
  return (
    <section className="min-w-0 border border-[var(--color-line)] bg-white">
      <header className="flex min-w-0 flex-col gap-3 border-b border-[var(--color-line)] p-5 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0"><p className="break-words text-sm text-[var(--color-mute)]">{docket?.title ?? docketTitle}</p><h2 className="break-words text-xl font-semibold">{TYPE_OPTIONS.find((option) => option.value === recordal.recordal_type)?.label ?? readable(recordal.recordal_type)}</h2><div className="mt-2 flex flex-wrap gap-2"><Badge tone={recordal.status === "accepted" ? "success" : recordal.status === "defective" || recordal.status === "rejected" ? "warning" : "neutral"}>{readable(recordal.status)}</Badge><Badge tone="neutral">Version {recordal.version}</Badge></div></div>
        <Link className="inline-flex items-center gap-1 text-sm font-medium underline" href={`/app/ip?docket=${encodeURIComponent(recordal.docket_id)}`}>Open IP docket <ArrowUpRight className="h-3.5 w-3.5" /></Link>
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
            {workspace && docket ? <TransactionPanel workspace={workspace} docket={docket} documents={linkedDocuments} registry={registry} deadlines={deadlines} membershipId={membershipId} canWrite={canWrite} canApprove={canApprove} onChanged={onChanged} /> : loadState}
          </div>
        </TabsContent>
        <TabsContent value="title" className="m-0 min-w-0 p-5">{docket ? <TitleAssessment docket={docket} allDockets={allDockets} documents={documents} /> : loadState}</TabsContent>
        <TabsContent value="evidence" className="m-0 min-w-0 p-5">{docket ? <EvidencePanel recordal={recordal} docket={docket} documents={linkedDocuments} registry={registry} deadlines={deadlines} /> : loadState}</TabsContent>
        <TabsContent value="history" className="m-0 min-w-0 p-5">{workspace ? <HistoryPanel events={workspace.transactions} /> : loadState}</TabsContent>
      </Tabs>
    </section>
  );
}

function RecordalWorkspaceState({ pending, error, onRetry }: {
  pending: boolean;
  error: unknown;
  onRetry: () => Promise<unknown>;
}) {
  if (pending) return <Skeleton className="h-44" data-testid="recordal-workspace-loading" />;
  if (error) {
    return (
      <QueryErrorState
        error={error}
        title="Could not load recordal evidence"
        onRetry={onRetry}
      />
    );
  }
  return null;
}

function RecordalOverview({ recordal, documents }: { recordal: IpRecordal; documents: IpDocument[] }) {
  return <div className="grid min-w-0 gap-6 lg:grid-cols-2">
    <section><h3 className="font-semibold">Legal particulars</h3><dl className="mt-3 grid gap-3 sm:grid-cols-2"><Datum label="Legal basis" value={recordal.legal_basis} wide /><Datum label="Form" value={recordal.form_code} /><Datum label="Execution" value={displayDate(recordal.executed_on)} /><Datum label="Effective" value={displayDate(recordal.effective_on)} /><Datum label="Scope" value={readable(String(recordal.scope_json.scope_kind ?? "whole_right"))} /><Datum label="Classes" value={recordal.affected_classes_json.join(", ") || "All affected classes"} /><Datum label="Affected rights" value={recordal.affected_registration_refs_json.join(", ")} wide /></dl></section>
    <section><h3 className="font-semibold">Parties</h3><div className="mt-3 divide-y divide-[var(--color-line)]">{recordal.parties_json.map((party, index) => <div key={`${party.role}-${index}`} className="py-3 first:pt-0"><p className="font-medium">{party.name}</p><p className="text-sm text-[var(--color-mute)]">{readable(party.role)} · {documents.find((document) => document.id === party.evidence_reference)?.title ?? "Instrument not available to you"}</p></div>)}</div></section>
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
  const [effectiveAtEdited, setEffectiveAtEdited] = useState(false);
  const [effectiveAtError, setEffectiveAtError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState("");
  const [documentRefs, setDocumentRefs] = useState<string[]>([]);
  const [deadlineRefs, setDeadlineRefs] = useState<string[]>([]);
  const [costRefs, setCostRefs] = useState<string[]>([]);
  const [snapshotId, setSnapshotId] = useState("");
  const [registryRecordedOn, setRegistryRecordedOn] = useState("");
  const [conflictReviewed, setConflictReviewed] = useState(false);
  const [correctedUploadOpen, setCorrectedUploadOpen] = useState(false);
  const snapshots = registry.flatMap((item) => item.link.match_status === "confirmed" ? item.snapshots.map((snapshot) => ({ link: item, snapshot })) : []);
  const selectedSnapshot = snapshots.find((row) => row.snapshot.id === snapshotId) ?? null;
  const requiresApproval = ["review_approved", "accepted", "rejected"].includes(kind);
  const requiresEvidence = ["filed", "defect_noted", "rejected", "accepted", "corrected"].includes(kind);
  const costs = activeCostItems(docket);
  // A correction must cite the corrected instrument; never offer the action without one.
  const correctionBlocked = kind === "corrected" && !documentRefs.length;

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
        // An untouched field means now, stamped by the server's clock. The
        // input shows whole minutes and the browser clock can lag, either of
        // which would date the transaction before an event already recorded.
        effectiveAt: effectiveAtEdited ? new Date(effectiveAt).toISOString() : null,
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
      setEffectiveAt(localDateTimeInput()); setEffectiveAtEdited(false); setEffectiveAtError(null);
      await onChanged();
    },
    onMutate: () => setEffectiveAtError(null),
    onError: (error) => {
      if (isApiErrorShape(error) && error.status === 409 && /backdated/i.test(error.detail)) {
        setEffectiveAtError(effectiveAtEdited
          ? "This time is earlier than the docket's latest event. Use the current time, or record the earlier event from the IP docket, where its deadline recalculation is previewed first."
          : "The docket already has an event dated after the current time. Enter a time on or after that event, or correct that event from the IP docket.");
        return;
      }
      toast.error(apiErrorMessage(error, "Could not record transaction."));
    },
  });

  if (!options.length) return <div className="flex items-center gap-2 text-sm"><CheckCircle2 className="h-4 w-4 text-green-700" />This recordal is closed.</div>;
  if ((!canWrite && !canApprove) || (requiresApproval && !canApprove)) return <p className="text-sm text-[var(--color-mute)]">Current status: {readable(workspace.recordal.status)}</p>;

  return <form className="grid min-w-0 gap-4 md:grid-cols-2" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
    <h3 className="font-semibold md:col-span-2">Record transaction</h3>
    <Field label="Transaction"><select className={SELECT_CLASS} value={kind} onChange={(event) => setKind(event.target.value as IpRecordalTransactionKind)}>{options.filter((option) => !["review_approved", "accepted", "rejected"].includes(option) || canApprove).map((option) => <option key={option} value={option}>{readable(option)}</option>)}</select></Field>
    <FormField id="recordal-transaction-effective-at" label="Effective time" hint={effectiveAtEdited ? undefined : "Left unchanged, CaseOps records the time it receives the transaction."} error={effectiveAtError ?? undefined}>
      <Input {...controlProps("recordal-transaction-effective-at", effectiveAtError ?? undefined, effectiveAtEdited ? undefined : "recordal-transaction-effective-at-hint")} type="datetime-local" value={effectiveAt} onChange={(event) => { setEffectiveAt(event.target.value); setEffectiveAtEdited(true); setEffectiveAtError(null); }} required />
      {effectiveAtEdited ? <Button type="button" size="sm" variant="ghost" className="w-fit" onClick={() => { setEffectiveAt(localDateTimeInput()); setEffectiveAtEdited(false); setEffectiveAtError(null); }}>Use the current time</Button> : null}
    </FormField>
    <div className="md:col-span-2"><Field label="Reason"><Textarea value={reason} onChange={(event) => setReason(event.target.value)} required minLength={5} /></Field></div>
    {requiresEvidence ? <div className="md:col-span-2"><Field label="Evidence references"><Textarea value={evidence} onChange={(event) => setEvidence(event.target.value)} required /></Field></div> : null}
    {documents.length ? <CheckGroup legend={kind === "corrected" ? "Corrected instrument" : "Linked documents"} rows={documents.map((document) => ({ id: document.id, label: document.title }))} selected={documentRefs} onChange={setDocumentRefs} /> : null}
    {kind === "corrected" && documents.length ? (
      <div className="flex min-w-0 flex-col gap-3 md:col-span-2">
        <Button type="button" size="sm" variant="outline" className="w-full sm:w-fit" aria-expanded={correctedUploadOpen} aria-controls="recordal-corrected-instrument-upload" onClick={() => setCorrectedUploadOpen((value) => !value)}>
          <Upload className="h-4 w-4" aria-hidden />
          {correctedUploadOpen ? "Hide instrument upload" : "Upload the corrected instrument"}
        </Button>
        {correctedUploadOpen ? <div id="recordal-corrected-instrument-upload"><RecordalInstrumentUpload docket={docket} suggestedTaxonomyKey={suggestedInstrumentClassification(workspace.recordal.recordal_type as IpRecordalType)} onUploaded={async () => { setCorrectedUploadOpen(false); await onChanged(); }} /></div> : null}
      </div>
    ) : null}
    {kind === "corrected" && !documents.length ? (
      <div className="flex min-w-0 flex-col gap-3 md:col-span-2" data-testid="recordal-corrected-instrument-empty">
        <p id="recordal-corrected-instrument-status" role="status" className="rounded-md border border-[var(--color-warn-border)] bg-[var(--color-warn-bg)] p-3 text-sm text-[var(--color-warn-text)]">
          No instrument is filed on this docket. A correction must cite the corrected instrument: upload it here and then tick it.
        </p>
        <RecordalInstrumentUpload docket={docket} suggestedTaxonomyKey={suggestedInstrumentClassification(workspace.recordal.recordal_type as IpRecordalType)} onUploaded={async () => { await onChanged(); }} />
      </div>
    ) : null}
    {deadlines.length ? <CheckGroup legend="Resulting deadlines" rows={deadlines.map((deadline) => ({ id: deadline.id, label: deadline.title }))} selected={deadlineRefs} onChange={setDeadlineRefs} /> : null}
    {costs.length ? <CheckGroup legend="Cost items" rows={costs.map((cost) => ({ id: cost.id, label: cost.description }))} selected={costRefs} onChange={setCostRefs} /> : null}
    {kind === "accepted" ? <><Field label="Confirmed Registry snapshot"><select className={SELECT_CLASS} value={snapshotId} onChange={(event) => setSnapshotId(event.target.value)} required><option value="">Select snapshot</option>{snapshots.map(({ link, snapshot }) => <option key={snapshot.id} value={snapshot.id}>{link.link.normalized_identifier} · {displayDate(snapshot.source_retrieved_at)}</option>)}</select></Field><Field label="Registry-recorded date"><Input type="date" value={registryRecordedOn} onChange={(event) => setRegistryRecordedOn(event.target.value)} required /></Field><label className="flex min-w-0 items-start gap-2 text-sm md:col-span-2"><input type="checkbox" checked={conflictReviewed} onChange={(event) => setConflictReviewed(event.target.checked)} /><span>Client instruction, instrument, affected scope, and Registry evidence reviewed</span></label></> : null}
    <div className="flex min-w-0 flex-col gap-2 md:col-span-2">
      {correctionBlocked ? <p id="recordal-transaction-requirements" className="text-sm text-[var(--color-mute)]">{documents.length ? "Tick the corrected instrument to record the correction." : "Upload the corrected instrument to record the correction."}</p> : null}
      <Button type="submit" className="w-full sm:w-fit" disabled={mutation.isPending || (requiresApproval && !canApprove) || correctionBlocked} aria-describedby={correctionBlocked ? "recordal-transaction-requirements" : undefined}>{mutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}Record {readable(kind)}</Button>
    </div>
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
      "Registry-recorded position:", ...(registered.length ? registered.map((interest) => reportInterest(interest, documents)) : ["- No recorded interest at this date"]), "",
      "Beneficial/effective position:", ...(beneficial.length ? beneficial.map((interest) => reportInterest(interest, documents)) : ["- No supported interest at this date"]), "",
      "Unresolved issues:", ...(issues.length ? issues.map((issue) => `- ${issue}`) : ["- None detected from accessible records"]),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `title-report-${reportFileStem(docket)}-${asOf}.txt`; anchor.click(); URL.revokeObjectURL(url);
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
    if (!source) issues.push(`${interest.party_name}: the source instrument is not available to you.`);
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

function reportFileStem(docket: IpDocket) {
  const stem = (docket.primary_identifier ?? docket.title).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60);
  return stem || "ip-right";
}

function reportInterest(interest: IpTitleInterest, documents: IpDocument[]) { return `- ${interest.party_name}; ${interest.interest_type}; effective ${interest.effective_from}${interest.effective_until ? ` to ${interest.effective_until}` : " onward"}; recordal ${interest.recordal_status}; source ${documents.find((document) => document.id === interest.evidence_reference)?.title ?? "instrument not available to you"}`; }

function InterestTable({ rows, documents, empty }: { rows: IpTitleInterest[]; documents: IpDocument[]; empty: string }) {
  if (!rows.length) return <p className="mt-3 text-sm text-[var(--color-mute)]">{empty}</p>;
  return <div className="mt-3 overflow-x-auto"><table className="w-full min-w-[680px] text-left text-sm"><thead><tr className="border-b border-[var(--color-line)]"><th className="p-2">Party</th><th className="p-2">Interest</th><th className="p-2">Effective</th><th className="p-2">Recordal</th><th className="p-2">Scope</th><th className="p-2">Source</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id} className="border-b border-[var(--color-line)]"><td className="p-2 font-medium">{row.party_name}</td><td className="p-2">{readable(row.interest_type)}</td><td className="p-2">{displayDate(row.effective_from)}{row.effective_until ? ` to ${displayDate(row.effective_until)}` : " onward"}</td><td className="p-2"><Badge tone={row.recordal_status === "recorded" ? "success" : "warning"}>{readable(row.recordal_status)}</Badge></td><td className="p-2">{String(row.scope_json.scope_kind ?? "whole right").replaceAll("_", " ")}</td><td className="p-2 break-all">{documents.find((document) => document.id === row.evidence_reference)?.title ?? "Instrument not available to you"}</td></tr>)}</tbody></table></div>;
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

/** A labelled control with an optional hint and a field-anchored error (`${id}-hint`, `${id}-error`). */
function FormField({ id, label, hint, error, children }: { id: string; label: string; hint?: string; error?: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 text-sm font-medium">
      <label htmlFor={id}>{label}</label>
      {children}
      {hint ? <p id={`${id}-hint`} className="text-xs font-normal text-[var(--color-mute)]">{hint}</p> : null}
      {error ? <p id={`${id}-error`} className="text-xs font-normal text-[var(--color-danger-500)]">{error}</p> : null}
    </div>
  );
}
