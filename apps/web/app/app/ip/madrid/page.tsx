"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowUpRight,
  Check,
  FileText,
  Globe2,
  Landmark,
  Link2,
  Plus,
  RefreshCw,
  Scale,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { toast } from "sonner";

import { IpDocketPicker } from "@/components/ip/IpDocketPicker";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { RecordSelect } from "@/components/ui/RecordSelect";
import { Skeleton } from "@/components/ui/Skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { Textarea } from "@/components/ui/Textarea";
import { API_FORM_ERROR_KEY, apiErrorMessage, apiFieldErrors } from "@/lib/api/config";
import {
  createMadridRecord,
  fetchIpCoreRecords,
  fetchMadridRecords,
  fetchMadridWorkspace,
  recordMadridAction,
  type IpCoreRecords,
  type MadridActionKind,
  type MadridRecord,
  type MadridWorkspace,
  type TrademarkApplication,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import { parseNiceClasses } from "@/lib/ip/nice-classes";
import { useSession } from "@/lib/use-session";

const SELECT_CLASS =
  "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm disabled:cursor-not-allowed disabled:opacity-60 aria-[invalid=true]:border-[var(--color-danger-500)]";

const ACTIONS: Array<{ value: MadridActionKind; label: string }> = [
  { value: "form_prepared", label: "MM2 or form prepared" },
  { value: "fee_recorded", label: "Fee recorded" },
  { value: "office_of_origin_certified", label: "Office of Origin certified" },
  { value: "wipo_irregularity", label: "WIPO irregularity" },
  { value: "international_registration_recorded", label: "IR number recorded" },
  { value: "wipo_notification_recorded", label: "WIPO notification" },
  { value: "national_examination_recorded", label: "National examination" },
  { value: "provisional_refusal_recorded", label: "Provisional refusal" },
  { value: "response_filed", label: "Response filed" },
  { value: "publication_recorded", label: "Publication" },
  { value: "opposition_recorded", label: "Opposition" },
  { value: "grant_statement_recorded", label: "Statement of grant" },
  { value: "refusal_statement_recorded", label: "Statement of refusal" },
  { value: "dependency_impact_review", label: "Basic-mark dependency review" },
  { value: "central_attack_impact_review", label: "Central-attack impact review" },
  { value: "source_snapshot", label: "WIPO or national source snapshot" },
  { value: "local_agent_instruction", label: "Local-agent instruction" },
  { value: "subsequent_designation_recorded", label: "Subsequent designation" },
  { value: "change_recorded", label: "WIPO change transaction" },
  { value: "renewal_transaction", label: "Renewal transaction" },
];

const DATE = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

function displayDate(value: string | null) {
  return value ? DATE.format(new Date(value)) : "Not recorded";
}

function readable(value: string) {
  return value.replaceAll("_", " ");
}

/** Nice classes as the create validator reads them: at least one, each 1-45, unique. */
function niceClassError(value: string): string | null {
  const parsed = parseNiceClasses(value);
  if (parsed.errors.length) return parsed.errors.map((row) => row.message).join(" ");
  if (!parsed.classes.length) return "Enter at least one Nice class, for example 9 or 9, 42.";
  return null;
}

/** "Application 5012345 · IP India · filed", so two applications on one docket differ. */
function applicationCaption(application: TrademarkApplication, identifiers: IpCoreRecords["identifiers"]) {
  const number = identifiers.find(
    (row) => row.application_id === application.id && row.identifier_kind === "application",
  )?.raw_value;
  return [
    number ? `Application ${number}` : "Application number not yet recorded",
    application.office,
    readable(application.filing_phase),
  ].join(" · ");
}

function authorityFor(action: MadridActionKind) {
  if (action === "source_snapshot") return "wipo" as const;
  if (["office_of_origin_certified"].includes(action)) return "office_of_origin" as const;
  if (["wipo_irregularity", "wipo_notification_recorded"].includes(action)) {
    return "wipo" as const;
  }
  if (
    [
      "national_examination_recorded",
      "provisional_refusal_recorded",
      "publication_recorded",
      "opposition_recorded",
      "grant_statement_recorded",
      "refusal_statement_recorded",
    ].includes(action)
  ) {
    return "national_office" as const;
  }
  if (action === "local_agent_instruction") return "local_agent" as const;
  return "internal" as const;
}

export default function MadridPage() {
  const canRead = useCapability("ip:read");
  const canWrite = useCapability("ip:write");
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState("");
  const records = useQuery({
    queryKey: ["ip", "madrid", "records"],
    queryFn: () => fetchMadridRecords(),
    enabled: canRead,
  });
  const workspace = useQuery({
    queryKey: ["ip", "madrid", "workspace", selectedId],
    queryFn: () => fetchMadridWorkspace(selectedId),
    enabled: canRead && Boolean(selectedId),
  });

  useEffect(() => {
    if (!selectedId && records.data?.items[0]) setSelectedId(records.data.items[0].id);
  }, [records.data, selectedId]);

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["ip", "madrid"] });
  }

  if (!canRead) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title="Madrid portfolio" />
        <EmptyState title="IP access required" description="Ask an owner for IP read access." />
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        eyebrow="International trademarks"
        title="Madrid portfolio"
        actions={
          <Button variant="outline" size="sm" onClick={refresh} disabled={records.isFetching}>
            <RefreshCw className={records.isFetching ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
            Refresh
          </Button>
        }
      />

      {records.isPending ? (
        <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
        </div>
      ) : records.isError ? (
        <QueryErrorState error={records.error} onRetry={refresh} />
      ) : (
        <>
          {canWrite ? <CreateMadridRecord onCreated={async (id) => { await refresh(); setSelectedId(id); }} /> : null}
          <div className="grid min-w-0 gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
            <RecordList records={records.data.items} selectedId={selectedId} onSelect={setSelectedId} />
            {workspace.isPending ? (
              <Skeleton className="h-[520px]" />
            ) : workspace.isError ? (
              <QueryErrorState error={workspace.error} onRetry={() => workspace.refetch()} />
            ) : workspace.data ? (
              <MadridDetail workspace={workspace.data} canWrite={canWrite} onChanged={refresh} />
            ) : (
              <Card><CardContent className="py-12"><EmptyState title="Select a Madrid record" description="Choose an international registration or designation." /></CardContent></Card>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function RecordList({ records, selectedId, onSelect }: { records: MadridRecord[]; selectedId: string; onSelect: (id: string) => void }) {
  return (
    <Card className="min-w-0 self-start">
      <CardHeader><CardTitle as="h2">Registrations and designations</CardTitle></CardHeader>
      <CardContent className="p-0">
        {records.length ? (
          <div className="divide-y divide-[var(--color-line)]">
            {records.map((record) => (
              <button key={record.id} type="button" className={record.id === selectedId ? "w-full bg-[var(--color-brand-50)] px-5 py-4 text-left" : "w-full px-5 py-4 text-left hover:bg-[var(--color-bg-2)]"} onClick={() => onSelect(record.id)}>
                <span className="block break-words font-semibold">{record.mark_name}</span>
                <span className="mt-1 block break-words text-sm text-[var(--color-mute)]">{record.record_kind === "international_registration" ? record.ir_number ?? record.wipo_reference : `${record.designated_member_code} · ${record.jurisdiction}`}</span>
                <span className="mt-2 flex flex-wrap gap-2"><Badge tone="neutral">{record.direction}</Badge><Badge tone={record.record_kind === "international_designation" ? "warning" : "success"}>{record.record_kind === "international_designation" ? "designation" : "IR"}</Badge></span>
              </button>
            ))}
          </div>
        ) : <div className="p-6"><EmptyState title="No Madrid records" description="Create the first international registration." /></div>}
      </CardContent>
    </Card>
  );
}

const CREATE_FIELD_IDS = {
  parent_registration_id: "madrid-parent-ir",
  basic_application_id: "madrid-basic-application",
  docket_title: "madrid-docket-title",
  mark_name: "madrid-mark",
  holder_name: "madrid-holder",
  wipo_reference: "madrid-wipo-reference",
  designated_member_code: "madrid-member",
  designated_office: "madrid-office",
  designation_effective_date: "madrid-designation-date",
  classes: "madrid-classes",
  goods_services: "madrid-goods",
  source_url: "madrid-source-url",
  source_reference: "madrid-source-reference",
} as const;

/**
 * Service refusals (404/409 and model-level 422s) carry no field location, so
 * anchor the known ones to the field they are about by their stable wording.
 */
function refusalFieldErrors(
  error: unknown,
  fallback: string,
  fieldMap: Readonly<Record<string, string>>,
  rules: ReadonlyArray<readonly [RegExp, string]>,
): Record<string, string> {
  const mapped = apiFieldErrors(error, fieldMap);
  // A model-level 422 carries its message as the form-level issue, not the detail.
  const message = mapped[API_FORM_ERROR_KEY] ?? apiErrorMessage(error, fallback);
  const field = rules.find(([pattern]) => pattern.test(message))?.[1];
  if (field && (!Object.keys(mapped).length || mapped[API_FORM_ERROR_KEY])) {
    delete mapped[API_FORM_ERROR_KEY];
    mapped[field] = message;
  }
  if (!Object.keys(mapped).length) mapped[API_FORM_ERROR_KEY] = message;
  return mapped;
}

const CREATE_REFUSAL_RULES = [
  [/basic (trademark application|indian application|mark must use)/i, CREATE_FIELD_IDS.basic_application_id],
  [/parent madrid registration|direction must match its parent/i, CREATE_FIELD_IDS.parent_registration_id],
] as const;

const ACTION_FIELD_IDS = {
  cost_item_refs: "madrid-action-cost",
  document_refs: "madrid-action-document",
  deadline_refs: "madrid-action-deadline",
} as const;

const ACTION_REFUSAL_RULES = [
  [/cost (item|references)/i, ACTION_FIELD_IDS.cost_item_refs],
  [/document references/i, ACTION_FIELD_IDS.document_refs],
  [/deadline references/i, ACTION_FIELD_IDS.deadline_refs],
] as const;

function invalidProps(id: string, error: string | null | undefined) {
  return error ? { id, "aria-invalid": true as const, "aria-describedby": `${id}-error` } : { id };
}

function CreateMadridRecord({ onCreated }: { onCreated: (id: string) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<MadridRecord["record_kind"]>("international_registration");
  const [direction, setDirection] = useState<MadridRecord["direction"]>("outbound");
  const [parentId, setParentId] = useState("");
  const [basicDocketId, setBasicDocketId] = useState("");
  const [basicApplicationId, setBasicApplicationId] = useState("");
  const [title, setTitle] = useState("");
  const [mark, setMark] = useState("");
  const [holder, setHolder] = useState("");
  const [wipoReference, setWipoReference] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [sourceReference, setSourceReference] = useState("");
  const [member, setMember] = useState("");
  const [office, setOffice] = useState("");
  const [classes, setClasses] = useState("9");
  const [goods, setGoods] = useState<Record<string, string>>({});
  const [effectiveDate, setEffectiveDate] = useState("");
  const [designationKind, setDesignationKind] = useState<"original" | "subsequent">("original");
  const [restricted, setRestricted] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const outbound = kind === "international_registration" && direction === "outbound";
  const core = useQuery({ queryKey: ["ip", "core-records", basicDocketId], queryFn: () => fetchIpCoreRecords(basicDocketId), enabled: outbound && Boolean(basicDocketId) });
  // Parent IR options come from the server's international-registration filter,
  // so designations never crowd a registration out of the list.
  const parents = useQuery({ queryKey: ["ip", "madrid", "records", "international_registration"], queryFn: () => fetchMadridRecords({ recordKind: "international_registration" }), enabled: open && kind === "international_designation" });
  const registrations = parents.data?.items ?? [];
  // The create validator accepts only an active application in India on a trademark docket.
  const indianApplications = (core.data?.applications ?? []).filter((row) => row.is_active && row.jurisdiction.toUpperCase() === "IN");
  const parsedClasses = parseNiceClasses(classes).classes;
  const classError = niceClassError(classes);
  const missingGoods = parsedClasses.filter((row) => !goods[String(row)]?.trim());
  const blocker = outbound && !basicApplicationId
    ? "Choose the basic mark docket and its Indian application."
    : kind === "international_designation" && !parentId
      ? "Choose the parent international registration."
      : classError
        ? "Fix the Nice classes."
        : missingGoods.length
          ? `Describe the goods/services for class ${missingGoods.join(", ")}.`
          : null;
  const mutation = useMutation({
    mutationFn: async () => {
      const parent = registrations.find((row) => row.id === parentId);
      return createMadridRecord({
        recordKind: kind,
        direction: kind === "international_designation" ? parent?.direction ?? direction : direction,
        parentRegistrationId: kind === "international_designation" ? parentId : null,
        basicApplicationId: outbound ? basicApplicationId : null,
        docketTitle: title,
        restricted,
        wipoReference,
        holderName: holder,
        markName: mark,
        officeOfOrigin: outbound ? "IP India" : null,
        designatedMemberCode: kind === "international_designation" ? member.toUpperCase() : null,
        designatedOffice: kind === "international_designation" ? office : null,
        jurisdiction: kind === "international_designation" ? member.toUpperCase() : null,
        designationKind: kind === "international_designation" ? designationKind : null,
        classes: parsedClasses,
        goodsServices: Object.fromEntries(parsedClasses.map((row) => [String(row), goods[String(row)].trim()])),
        formKind: outbound ? "MM2" : null,
        sourceUrl,
        sourceReference,
        sourceRetrievedAt: new Date().toISOString(),
        designationEffectiveDate: kind === "international_designation" ? effectiveDate : null,
      });
    },
    onSuccess: async (record) => { toast.success("Madrid record created."); setOpen(false); setFieldErrors({}); await onCreated(record.id); },
    onError: (error) => {
      setFieldErrors(refusalFieldErrors(error, "Could not create Madrid record.", CREATE_FIELD_IDS, CREATE_REFUSAL_RULES));
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    setAttempted(true);
    setFieldErrors({});
    if (!blocker) mutation.mutate();
  }
  const errorFor = (id: string) => fieldErrors[id] ?? null;
  const classMessage = (attempted || classes.trim()) && classError ? classError : errorFor(CREATE_FIELD_IDS.classes);
  const applicationError = errorFor(CREATE_FIELD_IDS.basic_application_id);

  let applicationPlaceholder = "Select the basic application";
  let applicationHint: ReactNode = null;
  if (!basicDocketId) {
    applicationPlaceholder = "Choose the basic mark docket first";
  } else if (core.isPending) {
    applicationPlaceholder = "Loading applications…";
  } else if (core.isError) {
    applicationPlaceholder = "Applications could not be loaded";
    applicationHint = <span role="alert" className="flex flex-wrap items-center gap-2 text-[var(--color-danger-500)]">{apiErrorMessage(core.error, "Applications could not be loaded.")}<Button type="button" size="sm" variant="outline" onClick={() => core.refetch()}>Retry</Button></span>;
  } else if (!indianApplications.length) {
    applicationPlaceholder = "No Indian application on this docket";
    applicationHint = <>An outbound Madrid filing needs an active Indian (IN) application on the basic mark docket. <Link className="font-semibold text-[var(--color-brand-700)]" href={`/app/ip?docket=${encodeURIComponent(basicDocketId)}`}>Add it on the docket</Link>, then choose it here.</>;
  }
  const applicationHintId = `${CREATE_FIELD_IDS.basic_application_id}-hint`;

  return (
    <Card>
      <CardHeader className="gap-3 sm:flex-row sm:items-center sm:justify-between"><CardTitle as="h2">Madrid intake</CardTitle><Button size="sm" variant={open ? "ghost" : "outline"} onClick={() => setOpen((value) => !value)}><Plus className="h-4 w-4" />{open ? "Close" : "New record"}</Button></CardHeader>
      {open ? <CardContent><form className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-4" onSubmit={submit} noValidate>
        <Field label="Record type"><select className={SELECT_CLASS} value={kind} onChange={(event) => setKind(event.target.value as MadridRecord["record_kind"])}><option value="international_registration">International registration</option><option value="international_designation">Designation</option></select></Field>
        {kind === "international_registration" ? <Field label="Direction"><select className={SELECT_CLASS} value={direction} onChange={(event) => setDirection(event.target.value as MadridRecord["direction"])}><option value="outbound">Outbound from India</option><option value="inbound">Inbound foundation</option></select></Field> : <Field label="Parent IR" htmlFor={CREATE_FIELD_IDS.parent_registration_id} error={errorFor(CREATE_FIELD_IDS.parent_registration_id)} hint={parents.isPending ? null : parents.isError ? <span role="alert" className="flex flex-wrap items-center gap-2 text-[var(--color-danger-500)]">{apiErrorMessage(parents.error, "International registrations could not be loaded.")}<Button type="button" size="sm" variant="outline" onClick={() => parents.refetch()}>Retry</Button></span> : registrations.length ? (parents.data && parents.data.total > registrations.length ? `Showing the latest ${registrations.length} of ${parents.data.total} international registrations.` : null) : "No international registration is recorded yet. Create the international registration first, then add its designations."}><select {...invalidProps(CREATE_FIELD_IDS.parent_registration_id, errorFor(CREATE_FIELD_IDS.parent_registration_id))} className={SELECT_CLASS} value={parentId} onChange={(event) => setParentId(event.target.value)} required disabled={!registrations.length}><option value="">{parents.isPending ? "Loading international registrations…" : parents.isError ? "International registrations could not be loaded" : registrations.length ? "Select IR" : "No international registration yet"}</option>{registrations.map((row) => <option key={row.id} value={row.id}>{row.mark_name} · {row.ir_number ?? row.wipo_reference}</option>)}</select></Field>}
        {outbound ? <><IpDocketPicker className="md:col-span-2" label="Basic mark docket" searchLabel="Find the basic mark docket" recordTypes={["trademark"]} value={basicDocketId} required
            onChange={(id) => { setBasicDocketId(id); setBasicApplicationId(""); }} />
          <div className="min-w-0 space-y-1.5 md:col-span-2">
            <RecordSelect id={CREATE_FIELD_IDS.basic_application_id} label="Basic Indian application" className={SELECT_CLASS} value={basicApplicationId}
              aria-invalid={applicationError ? true : undefined}
              aria-describedby={[applicationHint ? applicationHintId : "", applicationError ? `${CREATE_FIELD_IDS.basic_application_id}-error` : ""].filter(Boolean).join(" ") || undefined}
              onChange={event => setBasicApplicationId(event.target.value)} required disabled={!indianApplications.length} options={[
                { value: "", label: applicationPlaceholder, disabled: indianApplications.length > 0 },
                ...indianApplications.map(row => ({ value: row.id, label: applicationCaption(row, core.data?.identifiers ?? []) })),
              ]} />
            {applicationHint ? <p id={applicationHintId} className="min-w-0 break-words text-sm text-[var(--color-mute)]">{applicationHint}</p> : null}
            <FieldError id={CREATE_FIELD_IDS.basic_application_id} error={applicationError} />
          </div></> : null}
        <Field label="Docket title" htmlFor={CREATE_FIELD_IDS.docket_title} error={errorFor(CREATE_FIELD_IDS.docket_title)}><Input {...invalidProps(CREATE_FIELD_IDS.docket_title, errorFor(CREATE_FIELD_IDS.docket_title))} value={title} onChange={(event) => setTitle(event.target.value)} required /></Field>
        <Field label="Mark" htmlFor={CREATE_FIELD_IDS.mark_name} error={errorFor(CREATE_FIELD_IDS.mark_name)}><Input {...invalidProps(CREATE_FIELD_IDS.mark_name, errorFor(CREATE_FIELD_IDS.mark_name))} value={mark} onChange={(event) => setMark(event.target.value)} required /></Field>
        <Field label="Holder" htmlFor={CREATE_FIELD_IDS.holder_name} error={errorFor(CREATE_FIELD_IDS.holder_name)}><Input {...invalidProps(CREATE_FIELD_IDS.holder_name, errorFor(CREATE_FIELD_IDS.holder_name))} value={holder} onChange={(event) => setHolder(event.target.value)} required /></Field>
        <Field label="WIPO reference" htmlFor={CREATE_FIELD_IDS.wipo_reference} error={errorFor(CREATE_FIELD_IDS.wipo_reference)}><Input {...invalidProps(CREATE_FIELD_IDS.wipo_reference, errorFor(CREATE_FIELD_IDS.wipo_reference))} value={wipoReference} onChange={(event) => setWipoReference(event.target.value)} required /></Field>
        {kind === "international_designation" ? <><Field label="Designation type"><select className={SELECT_CLASS} value={designationKind} onChange={(event) => setDesignationKind(event.target.value as "original" | "subsequent")}><option value="original">Original designation</option><option value="subsequent">Subsequent designation</option></select></Field>
          <Field label="Member code" htmlFor={CREATE_FIELD_IDS.designated_member_code} error={errorFor(CREATE_FIELD_IDS.designated_member_code)}><Input {...invalidProps(CREATE_FIELD_IDS.designated_member_code, errorFor(CREATE_FIELD_IDS.designated_member_code))} value={member} onChange={(event) => setMember(event.target.value)} required /></Field>
          <Field label="Designated office" htmlFor={CREATE_FIELD_IDS.designated_office} error={errorFor(CREATE_FIELD_IDS.designated_office)}><Input {...invalidProps(CREATE_FIELD_IDS.designated_office, errorFor(CREATE_FIELD_IDS.designated_office))} value={office} onChange={(event) => setOffice(event.target.value)} required /></Field>
          <Field label="Designation date" htmlFor={CREATE_FIELD_IDS.designation_effective_date} error={errorFor(CREATE_FIELD_IDS.designation_effective_date)}><Input {...invalidProps(CREATE_FIELD_IDS.designation_effective_date, errorFor(CREATE_FIELD_IDS.designation_effective_date))} type="date" value={effectiveDate} onChange={(event) => setEffectiveDate(event.target.value)} required /></Field></> : null}
        <Field label="Nice classes" htmlFor={CREATE_FIELD_IDS.classes} error={classMessage}><Input {...invalidProps(CREATE_FIELD_IDS.classes, classMessage)} value={classes} onChange={(event) => setClasses(event.target.value)} placeholder="9, 42" required /></Field>
        <Field label="Source URL" htmlFor={CREATE_FIELD_IDS.source_url} error={errorFor(CREATE_FIELD_IDS.source_url)}><Input {...invalidProps(CREATE_FIELD_IDS.source_url, errorFor(CREATE_FIELD_IDS.source_url))} type="url" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} required /></Field>
        <Field label="Source reference" htmlFor={CREATE_FIELD_IDS.source_reference} error={errorFor(CREATE_FIELD_IDS.source_reference)}><Input {...invalidProps(CREATE_FIELD_IDS.source_reference, errorFor(CREATE_FIELD_IDS.source_reference))} value={sourceReference} onChange={(event) => setSourceReference(event.target.value)} required /></Field>
        {parsedClasses.map((row) => {
          const id = `${CREATE_FIELD_IDS.goods_services}-${row}`;
          const error = attempted && !goods[String(row)]?.trim() ? `Describe the goods/services for class ${row}.` : null;
          return <Field key={row} label={`Class ${row} goods/services`} htmlFor={id} error={error} wide><Textarea {...invalidProps(id, error)} value={goods[String(row)] ?? ""} onChange={(event) => setGoods((current) => ({ ...current, [String(row)]: event.target.value }))} rows={2} required /></Field>;
        })}
        <label className="flex items-center gap-2 text-sm md:col-span-2 xl:col-span-4"><input type="checkbox" checked={restricted} onChange={(event) => setRestricted(event.target.checked)} />Restrict this docket to explicitly granted members</label>
        <div className="flex min-w-0 flex-col gap-2 md:col-span-2 xl:col-span-4">
          {fieldErrors[API_FORM_ERROR_KEY] || errorFor(CREATE_FIELD_IDS.goods_services) ? <p role="alert" className="min-w-0 break-words text-sm text-[var(--color-danger-500)]">{[fieldErrors[API_FORM_ERROR_KEY], errorFor(CREATE_FIELD_IDS.goods_services)].filter(Boolean).join(" ")}</p> : null}
          {attempted && blocker ? <p role="status" className="min-w-0 break-words text-sm text-[var(--color-mute)]">{blocker}</p> : null}
          <div><Button type="submit" disabled={mutation.isPending}><Plus className="h-4 w-4" />{mutation.isPending ? "Creating…" : "Create record"}</Button></div>
        </div>
      </form></CardContent> : null}
    </Card>
  );
}

function MadridDetail({ workspace, canWrite, onChanged }: { workspace: MadridWorkspace; canWrite: boolean; onChanged: () => Promise<void> }) {
  const record = workspace.record;
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <Card><CardHeader className="gap-3 sm:flex-row sm:items-start sm:justify-between"><div className="min-w-0"><CardTitle as="h2">{record.mark_name}</CardTitle><p className="mt-1 break-words text-sm text-[var(--color-mute)]">{record.ir_number ?? record.wipo_reference}</p></div><div className="flex flex-wrap gap-2"><Badge tone={record.wipo_status ? "success" : "warning"}>WIPO: {record.wipo_status ?? "unconfirmed"}</Badge>{record.record_kind === "international_designation" ? <Badge tone={record.national_status ? "success" : "warning"}>National: {record.national_status ?? "unconfirmed"}</Badge> : null}<Badge tone={workspace.provider_mode === "contracted_sync" ? "success" : "warning"}>{readable(workspace.provider_mode)}</Badge></div></CardHeader><CardContent><div className="grid gap-4 text-sm sm:grid-cols-2 xl:grid-cols-4"><Datum label="Direction" value={record.direction} /><Datum label="Jurisdiction" value={record.jurisdiction ?? "International"} /><Datum label="Classes" value={record.classes_json.join(", ")} /><Datum label="Local agent" value={record.local_agent_name ?? "Not instructed"} /><Datum label="IR date" value={displayDate(record.international_registration_date)} /><Datum label="Notification" value={displayDate(record.notification_date)} /><Datum label="Publication" value={displayDate(record.publication_date)} /><Datum label="Renewal due" value={displayDate(record.renewal_due_date)} /></div><div className="mt-4 flex flex-wrap gap-2"><Button href={record.source_url} target="_blank" rel="noreferrer" size="sm" variant="outline"><ArrowUpRight className="h-4 w-4" />Open source</Button><Button href={`/app/ip?docket=${encodeURIComponent(workspace.docket.id)}`} size="sm" variant="ghost"><Link2 className="h-4 w-4" />Open docket</Button></div></CardContent></Card>
      {workspace.data_quality_gaps.length ? <div className="flex min-w-0 items-start gap-3 rounded-md border border-amber-300 bg-amber-50 p-4 text-sm"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" /><div className="min-w-0"><strong>Open controls</strong><div className="mt-2 flex flex-wrap gap-2">{workspace.data_quality_gaps.map((gap) => <Badge key={gap} tone="warning">{readable(gap)}</Badge>)}</div></div></div> : null}
      <Tabs defaultValue="status" className="min-w-0"><TabsList className="h-auto w-full flex-wrap justify-start"><TabsTrigger className="min-w-[140px] flex-1 sm:flex-none" value="status">Status and sources</TabsTrigger><TabsTrigger className="min-w-[140px] flex-1 sm:flex-none" value="designations">Designations</TabsTrigger><TabsTrigger className="min-w-[140px] flex-1 sm:flex-none" value="evidence">Deadlines and evidence</TabsTrigger><TabsTrigger className="min-w-[140px] flex-1 sm:flex-none" value="history">History</TabsTrigger></TabsList>
        <TabsContent value="status"><SourcePanel workspace={workspace} canWrite={canWrite} onChanged={onChanged} /></TabsContent>
        <TabsContent value="designations"><DesignationPanel workspace={workspace} /></TabsContent>
        <TabsContent value="evidence"><EvidencePanel workspace={workspace} /></TabsContent>
        <TabsContent value="history"><HistoryPanel events={workspace.events} /></TabsContent>
      </Tabs>
      {canWrite ? <MadridActionForm workspace={workspace} onChanged={onChanged} /> : null}
    </div>
  );
}

function SourcePanel({ workspace, canWrite, onChanged }: { workspace: MadridWorkspace; canWrite: boolean; onChanged: () => Promise<void> }) {
  const session = useSession();
  const mutation = useMutation({ mutationFn: (input: { eventId: string; decision: "same_fact" | "keep_separate" | "reject_candidate" }) => recordMadridAction({ recordId: workspace.record.id, expectedVersion: workspace.record.version, expectedLifecycleVersion: workspace.docket.lifecycle_version, actionKind: "source_reconciliation", authority: "internal", effectiveAt: new Date().toISOString(), responsibleMembershipId: session.context?.membership.id ?? "", reason: `Counsel reconciled source candidate as ${input.decision.replaceAll("_", " ")}.`, sourceReference: `madrid-review:${input.eventId}`, sourceRetrievedAt: new Date().toISOString(), reconcilesEventId: input.eventId, reconciliationDecision: input.decision }), onSuccess: async () => { toast.success("Source candidate reconciled."); await onChanged(); }, onError: (error) => toast.error(apiErrorMessage(error, "Could not reconcile source.")) });
  return <Card><CardHeader><CardTitle as="h3">Source reconciliation</CardTitle></CardHeader><CardContent className="space-y-3">{workspace.unresolved_source_candidates.length ? workspace.unresolved_source_candidates.map((event) => <div key={event.id} className="grid min-w-0 gap-3 rounded-md border border-[var(--color-line)] p-4 md:grid-cols-[minmax(0,1fr)_auto]"><div className="min-w-0"><div className="flex flex-wrap gap-2"><Badge tone="warning">candidate</Badge><Badge tone="neutral">{String(event.payload_json.authority ?? event.source)}</Badge></div><strong className="mt-2 block break-words">{String(event.payload_json.wipo_status ?? event.payload_json.national_status ?? "Status observation")}</strong><a href={String(event.payload_json.source_url ?? "#")} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 break-all text-sm underline">{event.source_reference}<ArrowUpRight className="h-3 w-3" /></a></div>{canWrite ? <div className="flex flex-wrap items-center gap-2"><Button size="sm" onClick={() => mutation.mutate({ eventId: event.id, decision: "same_fact" })} disabled={mutation.isPending}><Check className="h-4 w-4" />Accept</Button><Button size="sm" variant="outline" onClick={() => mutation.mutate({ eventId: event.id, decision: "keep_separate" })} disabled={mutation.isPending}>Keep separate</Button><Button size="sm" variant="ghost" onClick={() => mutation.mutate({ eventId: event.id, decision: "reject_candidate" })} disabled={mutation.isPending}>Reject</Button></div> : null}</div>) : <EmptyState title="No source conflicts" description="All WIPO and national-office snapshots are reconciled." />}</CardContent></Card>;
}

function DesignationPanel({ workspace }: { workspace: MadridWorkspace }) {
  const rows = workspace.record.record_kind === "international_registration" ? workspace.designations : workspace.parent ? [workspace.parent, workspace.record] : [workspace.record];
  return <Card><CardHeader><CardTitle as="h3">International family</CardTitle></CardHeader><CardContent className="p-0"><div className="overflow-x-auto"><table className="w-full min-w-[720px] text-left text-sm"><thead className="bg-[var(--color-bg-2)] text-xs text-[var(--color-mute)]"><tr><th className="px-4 py-3">Member</th><th className="px-4 py-3">WIPO status</th><th className="px-4 py-3">National status</th><th className="px-4 py-3">Agent</th><th className="px-4 py-3">Source</th></tr></thead><tbody className="divide-y divide-[var(--color-line)]">{rows.map((row) => <tr key={row.id}><td className="px-4 py-3 font-medium">{row.record_kind === "international_registration" ? "International registration" : row.designated_member_code}</td><td className="px-4 py-3">{row.wipo_status ?? "Unconfirmed"}</td><td className="px-4 py-3">{row.national_status ?? "Not applicable"}</td><td className="px-4 py-3">{row.local_agent_name ?? "Not instructed"}</td><td className="px-4 py-3"><a className="inline-flex items-center gap-1 underline" href={row.source_url} target="_blank" rel="noreferrer">Open<ArrowUpRight className="h-3 w-3" /></a></td></tr>)}</tbody></table></div></CardContent></Card>;
}

function EvidencePanel({ workspace }: { workspace: MadridWorkspace }) {
  return <div className="grid min-w-0 gap-4 lg:grid-cols-3"><Card><CardHeader><CardTitle as="h3"><Scale className="mr-2 inline h-4 w-4" />Deadlines</CardTitle></CardHeader><CardContent className="space-y-3">{workspace.deadlines.length ? workspace.deadlines.map((row) => <div key={row.id}><strong className="block">{row.title}</strong><span className="text-sm text-[var(--color-mute)]">{displayDate(row.result_on)} · {row.state}</span><span className="mt-1 block break-words text-xs text-[var(--color-mute)]">{row.rule_citation} · {row.source_version}</span></div>) : <EmptyState title="No Madrid deadlines" description="No versioned deadline is linked." />}</CardContent></Card><Card><CardHeader><CardTitle as="h3"><FileText className="mr-2 inline h-4 w-4" />Documents</CardTitle></CardHeader><CardContent className="space-y-3">{workspace.documents.length ? workspace.documents.map((row) => <div key={row.id}><strong className="block break-words">{row.title}</strong><span className="text-sm text-[var(--color-mute)]">{row.taxonomy_label} · v{row.current_version}</span></div>) : <EmptyState title="No linked documents" description="No document evidence is linked." />}</CardContent></Card><Card><CardHeader><CardTitle as="h3"><Landmark className="mr-2 inline h-4 w-4" />Fees and costs</CardTitle></CardHeader><CardContent className="space-y-3">{workspace.costs.length ? workspace.costs.map((row) => <div key={row.id}><strong className="block break-words">{row.description}</strong><span className="text-sm text-[var(--color-mute)]">{row.amount_withheld ? "Amount restricted" : `${row.amount_minor ?? 0} ${row.currency}`} · {row.reconciliation_status}</span></div>) : <EmptyState title="No linked costs" description="No fee or cost evidence is linked." />}</CardContent></Card></div>;
}

function HistoryPanel({ events }: { events: MadridWorkspace["events"] }) {
  return <Card><CardHeader><CardTitle as="h3">Versioned transactions</CardTitle></CardHeader><CardContent className="space-y-3">{events.length ? [...events].reverse().map((event) => { const sourceUrl = String(event.payload_json.source_url ?? event.payload_json.candidate_source_url ?? ""); return <div key={event.id} className="grid min-w-0 gap-2 border-b border-[var(--color-line)] pb-3 last:border-0 md:grid-cols-[160px_minmax(0,1fr)_auto]"><span className="text-sm tabular-nums text-[var(--color-mute)]">{displayDate(event.effective_at)}</span><div className="min-w-0"><strong className="block break-words">{readable(String(event.payload_json.action_kind ?? event.event_kind))}</strong><span className="block text-sm text-[var(--color-mute)]">{event.reason ?? event.source_reference}</span>{sourceUrl.startsWith("http") ? <a href={sourceUrl} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 break-all text-sm underline">{event.source_reference}<ArrowUpRight className="h-3 w-3" /></a> : null}</div><Badge tone={event.candidate_status === "candidate" ? "warning" : "success"}>{event.candidate_status}</Badge></div>; }) : <EmptyState title="No Madrid transactions" description="No workflow transaction is recorded." />}</CardContent></Card>;
}

function MadridActionForm({ workspace, onChanged }: { workspace: MadridWorkspace; onChanged: () => Promise<void> }) {
  const session = useSession();
  const [action, setAction] = useState<MadridActionKind>("source_snapshot");
  const [authority, setAuthority] = useState<ReturnType<typeof authorityFor>>("wipo");
  const [sourceReference, setSourceReference] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [reason, setReason] = useState("");
  const [status, setStatus] = useState("");
  const [localAgent, setLocalAgent] = useState("");
  const [eventDate, setEventDate] = useState(new Date().toISOString().slice(0, 10));
  const [irNumber, setIrNumber] = useState("");
  const [costId, setCostId] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [deadlineId, setDeadlineId] = useState("");
  const [impactScope, setImpactScope] = useState("");
  const [recommendedAction, setRecommendedAction] = useState("");
  const [actionErrors, setActionErrors] = useState<Record<string, string>>({});
  useEffect(() => { setAuthority(authorityFor(action)); setActionErrors({}); }, [action]);
  const mutation = useMutation({ mutationFn: () => recordMadridAction({ recordId: workspace.record.id, expectedVersion: workspace.record.version, expectedLifecycleVersion: workspace.docket.lifecycle_version, actionKind: action, authority, effectiveAt: new Date(`${eventDate}T12:00:00Z`).toISOString(), responsibleMembershipId: session.context?.membership.id ?? "", reason, sourceUrl: sourceUrl || null, sourceReference, sourceRetrievedAt: new Date().toISOString(), evidenceRefs: [sourceReference], documentRefs: documentId ? [documentId] : [], deadlineRefs: deadlineId ? [deadlineId] : [], costItemRefs: action === "fee_recorded" && costId ? [costId] : [], wipoStatus: action === "source_snapshot" && authority === "wipo" ? status : null, nationalStatus: action === "source_snapshot" && authority === "national_office" ? status : null, localAgentName: action === "local_agent_instruction" ? localAgent : null, irNumber: action === "international_registration_recorded" ? irNumber : null, internationalRegistrationDate: action === "international_registration_recorded" ? eventDate : null, notificationDate: action === "wipo_notification_recorded" ? eventDate : null, publicationDate: action === "publication_recorded" ? eventDate : null, statementDate: ["grant_statement_recorded", "refusal_statement_recorded"].includes(action) ? eventDate : null, renewalDueDate: action === "renewal_transaction" ? eventDate : null, details: ["dependency_impact_review", "central_attack_impact_review"].includes(action) ? { impact_scope: impactScope.split(",").map((row) => row.trim()).filter(Boolean), recommended_action: recommendedAction } : {} }), onSuccess: async (result) => { toast.success(result.impact_review_only ? "Impact review recorded without changing legal status." : "Madrid transaction recorded."); setSourceReference(""); setReason(""); setActionErrors({}); await onChanged(); }, onError: (error) => setActionErrors(refusalFieldErrors(error, "Could not record Madrid transaction.", ACTION_FIELD_IDS, ACTION_REFUSAL_RULES)) });
  function submit(event: FormEvent) { event.preventDefault(); setActionErrors({}); if (!actionBlocker) mutation.mutate(); }
  const external = ["wipo", "office_of_origin", "national_office"].includes(authority);
  // The action validator accepts only active costs on this docket.
  const activeCosts = workspace.costs.filter((row) => row.lineage_status === "active");
  const actionBlocker = action === "fee_recorded" && !costId
    ? activeCosts.length ? "Choose the canonical cost item this fee records." : "A fee transaction needs an active cost on this docket. Record the cost on the docket first."
    : null;
  const docketHref = `/app/ip?docket=${encodeURIComponent(workspace.docket.id)}`;
  const documentsHref = `${docketHref}&tab=documents`;
  return <Card><CardHeader><CardTitle as="h3"><Globe2 className="mr-2 inline h-4 w-4" />Record transaction</CardTitle></CardHeader><CardContent><form className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-4" onSubmit={submit}><Field label="Action"><select className={SELECT_CLASS} value={action} onChange={(event) => setAction(event.target.value as MadridActionKind)}>{ACTIONS.filter((row) => workspace.record.record_kind === "international_registration" ? ![..._NATIONAL_UI_ACTIONS, "local_agent_instruction", "wipo_notification_recorded"].includes(row.value) : ![..._OUTBOUND_UI_ACTIONS].includes(row.value)).map((row) => row.value === "fee_recorded" && !activeCosts.length ? <option key={row.value} value={row.value} disabled>{row.label} (needs an active cost on this docket)</option> : <option key={row.value} value={row.value}>{row.label}</option>)}</select></Field><Field label="Authority"><select className={SELECT_CLASS} value={authority} onChange={(event) => setAuthority(event.target.value as ReturnType<typeof authorityFor>)} disabled={action !== "source_snapshot"}><option value="internal">Internal</option><option value="wipo">WIPO</option><option value="office_of_origin">Office of Origin</option><option value="national_office">National office</option><option value="local_agent">Local agent</option></select></Field><Field label="Effective date"><Input type="date" value={eventDate} onChange={(event) => setEventDate(event.target.value)} required /></Field><Field label="Source reference"><Input value={sourceReference} onChange={(event) => setSourceReference(event.target.value)} required /></Field>{external ? <Field label="Source URL"><Input type="url" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} required /></Field> : null}{action === "source_snapshot" ? <Field label={authority === "wipo" ? "WIPO status" : "National status"}><Input value={status} onChange={(event) => setStatus(event.target.value)} required /></Field> : null}{action === "local_agent_instruction" ? <Field label="Local agent"><Input value={localAgent} onChange={(event) => setLocalAgent(event.target.value)} required /></Field> : null}{action === "international_registration_recorded" ? <Field label="IR number"><Input value={irNumber} onChange={(event) => setIrNumber(event.target.value)} required /></Field> : null}{action === "fee_recorded" ? <EvidenceSelect id={ACTION_FIELD_IDS.cost_item_refs} label="Canonical cost item" value={costId} onChange={setCostId} required error={actionErrors[ACTION_FIELD_IDS.cost_item_refs]} placeholder="Select cost" options={activeCosts.map((row) => ({ value: row.id, label: row.description }))} empty={<>No active fee or cost is recorded on this docket. <Link className="font-semibold text-[var(--color-brand-700)]" href={docketHref}>Record it on the docket</Link> first.</>} /> : null}<EvidenceSelect id={ACTION_FIELD_IDS.document_refs} label="Linked document" value={documentId} onChange={setDocumentId} error={actionErrors[ACTION_FIELD_IDS.document_refs]} placeholder="No document" options={workspace.documents.map((row) => ({ value: row.id, label: `${row.title} · ${row.taxonomy_label} · v${row.current_version}` }))} empty={<>No documents on this docket yet. <Link className="font-semibold text-[var(--color-brand-700)]" href={documentsHref}>Upload one in the IP workspace Documents tab</Link> to link it here.</>} /><EvidenceSelect id={ACTION_FIELD_IDS.deadline_refs} label="Linked deadline" value={deadlineId} onChange={setDeadlineId} error={actionErrors[ACTION_FIELD_IDS.deadline_refs]} placeholder="No deadline" options={workspace.deadlines.map((row) => ({ value: row.id, label: `${row.title} · ${displayDate(row.result_on)}` }))} empty={<>No deadlines on this docket yet. <Link className="font-semibold text-[var(--color-brand-700)]" href={`${docketHref}&view=schedule`}>Add one in the docket schedule</Link> to link it here.</>} />{["dependency_impact_review", "central_attack_impact_review"].includes(action) ? <><Field label="Impact scope"><Input value={impactScope} onChange={(event) => setImpactScope(event.target.value)} required /></Field><Field label="Recommended action"><Input value={recommendedAction} onChange={(event) => setRecommendedAction(event.target.value)} required /></Field></> : null}<Field label="Reason" wide><Textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={3} required /></Field><div className="flex min-w-0 flex-col gap-2 md:col-span-2 xl:col-span-4">{actionErrors[API_FORM_ERROR_KEY] ? <p role="alert" className="min-w-0 break-words text-sm text-[var(--color-danger-500)]">{actionErrors[API_FORM_ERROR_KEY]}</p> : null}{actionBlocker ? <p id="madrid-action-blocker" role="status" className="min-w-0 break-words text-sm text-[var(--color-mute)]">{actionBlocker}</p> : null}<div><Button type="submit" aria-describedby={actionBlocker ? "madrid-action-blocker" : undefined} disabled={mutation.isPending || !session.context?.membership.id || Boolean(actionBlocker)}><Check className="h-4 w-4" />Record transaction</Button></div></div></form></CardContent></Card>;
}

const _NATIONAL_UI_ACTIONS: MadridActionKind[] = ["national_examination_recorded", "provisional_refusal_recorded", "response_filed", "publication_recorded", "opposition_recorded", "grant_statement_recorded", "refusal_statement_recorded"];
const _OUTBOUND_UI_ACTIONS: MadridActionKind[] = ["form_prepared", "office_of_origin_certified", "international_registration_recorded", "dependency_impact_review", "central_attack_impact_review", "subsequent_designation_recorded"];

/**
 * Without `htmlFor` the label wraps the control. With it, the label points at
 * the control's id and a hint or error sits outside the accessible name.
 */
function Field({ label, children, wide = false, htmlFor, error, hint }: { label: string; children: ReactNode; wide?: boolean; htmlFor?: string; error?: string | null; hint?: ReactNode }) {
  const className = wide ? "min-w-0 md:col-span-2" : "min-w-0";
  if (!htmlFor) return <Label className={className}><span className="mb-1.5 block">{label}</span>{children}</Label>;
  return <div className={`${className} space-y-1.5`}><Label htmlFor={htmlFor} className="block">{label}</Label>{children}{hint ? <p className="min-w-0 break-words text-sm text-[var(--color-mute)]">{hint}</p> : null}<FieldError id={htmlFor} error={error} /></div>;
}

function FieldError({ id, error }: { id: string; error?: string | null }) {
  return error ? <p id={`${id}-error`} className="min-w-0 break-words text-sm text-[var(--color-danger-500)]">{error}</p> : null;
}

/**
 * A docket-scoped evidence choice. Options are exactly what the action
 * validator accepts for this docket; with none, the select is disabled and
 * says where to create one instead of offering a choice that does not exist.
 */
function EvidenceSelect({ id, label, value, onChange, options, placeholder, empty, required = false, error }: { id: string; label: string; value: string; onChange: (value: string) => void; options: Array<{ value: string; label: string }>; placeholder: string; empty: ReactNode; required?: boolean; error?: string | null }) {
  const none = options.length === 0;
  const describedBy = [none ? `${id}-empty` : "", error ? `${id}-error` : ""].filter(Boolean).join(" ") || undefined;
  return <div className="min-w-0 space-y-1.5"><RecordSelect id={id} label={label} className={SELECT_CLASS} value={value} onChange={(event) => onChange(event.target.value)} required={required} disabled={none} aria-invalid={error ? true : undefined} aria-describedby={describedBy} options={[{ value: "", label: none ? "None on this docket" : placeholder }, ...options]} />{none ? <p id={`${id}-empty`} className="min-w-0 break-words text-sm text-[var(--color-mute)]">{empty}</p> : null}<FieldError id={id} error={error} /></div>;
}

function Datum({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><span className="text-[var(--color-mute)]">{label}</span><strong className="mt-1 block break-words font-medium capitalize">{value.replaceAll("_", " ")}</strong></div>;
}
