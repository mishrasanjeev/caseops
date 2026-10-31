"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  BellRing,
  CheckCircle2,
  ExternalLink,
  LoaderCircle,
  MailCheck,
  Plus,
  Send,
} from "lucide-react";
import Link from "next/link";
import { cloneElement, isValidElement, useEffect, useId, useState } from "react";
import type { KeyboardEvent, ReactElement, ReactNode } from "react";
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
import { Skeleton } from "@/components/ui/Skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { Textarea } from "@/components/ui/Textarea";
import {
  API_BASE_URL,
  API_FORM_ERROR_KEY,
  apiErrorMessage,
  apiFieldErrors,
  isApiErrorShape,
} from "@/lib/api/config";
import {
  addIpCostItem,
  createIpForeignAssociateInstruction,
  fetchIpDeadlineWorkspace,
  fetchIpDocumentsForDocket,
  fetchIpForeignAssociateCreateOptions,
  fetchIpForeignAssociateInstructions,
  fetchIpForeignAssociateWorkspace,
  fetchMatterCommunications,
  fetchOutsideCounselWorkspace,
  recordIpForeignAssociateTransaction,
  scheduleIpForeignAssociateReminders,
  type IpDocket,
  type IpDocument,
  type IpForeignAssociateCreateBlocker,
  type IpForeignAssociateCreateOptions,
  type IpForeignAssociateInstruction,
  type IpForeignAssociateStatus,
  type IpForeignAssociateTransactionKind,
  type IpForeignAssociateWorkspace,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import { parseNiceClasses } from "@/lib/ip/nice-classes";
import { useSession } from "@/lib/use-session";

const SELECT_CLASS =
  "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm disabled:cursor-not-allowed disabled:bg-[var(--color-bg-subtle)] disabled:text-[var(--color-mute)]";

const LINK_CLASS = "font-medium text-[var(--color-brand-700)] underline underline-offset-2";

const TRANSITIONS: Record<IpForeignAssociateStatus, IpForeignAssociateTransactionKind[]> = {
  draft: ["approve", "cancel"],
  approved: ["dispatch", "approve_fee_change", "cancel"],
  dispatched: ["acknowledge", "approve_fee_change", "refuse", "cancel"],
  acknowledged: [
    "record_query",
    "approve_substantive_response",
    "approve_fee_change",
    "report_filing",
    "refuse",
    "cancel",
  ],
  in_progress: [
    "record_query",
    "approve_substantive_response",
    "approve_fee_change",
    "report_filing",
    "refuse",
    "cancel",
  ],
  filing_reported: ["verify_filing_evidence", "approve_fee_change"],
  evidence_verified: ["link_invoice", "approve_fee_change"],
  invoiced: ["link_invoice", "approve_fee_change", "complete"],
  refused: ["reassign", "cancel"],
  completed: [],
  superseded: [],
  cancelled: [],
};

const DATE = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

function readable(value: string) {
  const words = value.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function refs(value: string) {
  return [...new Set(value.split(/[\n,]/).map((row) => row.trim()).filter(Boolean))];
}

function localDateTimeInput(days = 0) {
  const date = new Date(Date.now() + days * 86_400_000 - new Date().getTimezoneOffset() * 60_000);
  return date.toISOString().slice(0, 16);
}

function iso(value: string) {
  return new Date(value).toISOString();
}

function money(value: number | null | undefined, currency: string) {
  if (value === null || value === undefined) return "Amount restricted";
  return new Intl.NumberFormat("en-IN", { style: "currency", currency }).format(value / 100);
}

function Status({ value }: { value: string }) {
  const tone = ["completed", "evidence_verified", "acknowledged"].includes(value)
    ? "success"
    : ["refused", "cancelled"].includes(value)
      ? "warning"
      : ["dispatched", "filing_reported", "invoiced"].includes(value)
        ? "warning"
        : "neutral";
  return <Badge tone={tone}>{readable(value)}</Badge>;
}

export default function ForeignAssociatesPage() {
  const canRead = useCapability("ip:read");
  const canWrite = useCapability("ip:write");
  const canApprove = useCapability("ip:approve");
  const [queue, setQueue] = useState<"all" | "outstanding" | "evidence">("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const instructions = useQuery({
    queryKey: ["ip-foreign-associates", queue],
    queryFn: () => fetchIpForeignAssociateInstructions({
      outstandingResponse: queue === "outstanding" ? true : null,
      missingFilingEvidence: queue === "evidence" ? true : null,
    }),
    enabled: canRead,
  });

  useEffect(() => {
    if (!creating && !selectedId && instructions.data?.items[0]) {
      setSelectedId(instructions.data.items[0].id);
    }
  }, [creating, instructions.data?.items, selectedId]);

  if (!canRead) {
    return <EmptyState title="IP access required" description="Your role cannot read IP instructions." />;
  }

  return (
    <div className="min-w-0 space-y-5">
      <PageHeader
        title="Foreign associates"
        description="Instructions, acknowledgements, filing evidence and associate invoices."
        actions={canWrite ? (
          <Button onClick={() => { setCreating(true); setSelectedId(null); }}>
            <Plus className="h-4 w-4" />New instruction
          </Button>
        ) : null}
      />

      <div className="flex min-w-0 flex-wrap gap-2" role="group" aria-label="Instruction queues">
        {([
          ["all", "All"],
          ["outstanding", "Awaiting acknowledgement"],
          ["evidence", "Missing independent evidence"],
        ] as const).map(([value, label]) => (
          <Button
            key={value}
            size="sm"
            variant={queue === value ? "primary" : "outline"}
            onClick={() => { setQueue(value); setCreating(false); setSelectedId(null); }}
          >
            {label}
          </Button>
        ))}
      </div>

      {instructions.isError ? (
        <QueryErrorState error={instructions.error} onRetry={() => void instructions.refetch()} />
      ) : (
        <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(16rem,22rem)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-2">
            {instructions.isLoading ? <><Skeleton className="h-24" /><Skeleton className="h-24" /></> : null}
            {!instructions.isLoading && !instructions.data?.items.length && !creating ? (
              <EmptyState title="No instructions in this queue" description="" />
            ) : null}
            {instructions.data?.items.map((row) => (
              <button
                key={row.id}
                type="button"
                className={`w-full min-w-0 rounded-md border p-3 text-left ${selectedId === row.id ? "border-[var(--color-brand-500)] bg-[var(--color-brand-50)]" : "border-[var(--color-line)] bg-white"}`}
                onClick={() => { setCreating(false); setSelectedId(row.id); }}
              >
                <span className="flex min-w-0 items-start justify-between gap-2">
                  <span className="min-w-0">
                    <span className="block truncate font-semibold">{row.scope_json.filing_kind ?? "Foreign filing"}</span>
                    <span className="block break-words text-sm text-[var(--color-mute)]">{row.target_jurisdiction} · {row.scope_json.source_reference}</span>
                  </span>
                  <Status value={row.status} />
                </span>
                <span className="mt-2 block text-xs text-[var(--color-mute)]">Updated {DATE.format(new Date(row.updated_at))}</span>
              </button>
            ))}
          </div>

          <div className="min-w-0">
            {creating ? (
              <CreateInstruction
                canApprove={canApprove}
                onCreated={(row) => { setCreating(false); setSelectedId(row.id); }}
              />
            ) : selectedId ? (
              <InstructionWorkspace key={selectedId} instructionId={selectedId} canWrite={canWrite} canApprove={canApprove} />
            ) : (
              <EmptyState title="Select an instruction" description="" />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  children,
  wide = false,
  id: explicitId,
  hint,
  error,
}: {
  label: string;
  children: ReactNode;
  wide?: boolean;
  id?: string;
  hint?: ReactNode;
  error?: string;
}) {
  const generatedId = useId();
  const childId = isValidElement(children) ? (children.props as { id?: string }).id : undefined;
  const id = explicitId ?? childId ?? generatedId;
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  const control = isValidElement(children)
    ? cloneElement(children as ReactElement<Record<string, unknown>>, {
        id,
        "aria-describedby": describedBy,
        "aria-invalid": error ? true : undefined,
      })
    : children;
  return (
    <div className={`grid min-w-0 content-start gap-1.5 ${wide ? "md:col-span-2 xl:col-span-4" : ""}`}>
      <Label htmlFor={id}>{label}</Label>
      {control}
      {hint ? <div id={hintId} className="min-w-0 break-words text-xs leading-relaxed text-[var(--color-mute)]">{hint}</div> : null}
      {error ? <p id={errorId} role="alert" className="min-w-0 break-words text-xs font-medium text-[var(--color-danger-text)]">{error}</p> : null}
    </div>
  );
}

type Choice = { value: string; label: string };

/**
 * A select that is either usable or says why not. `blocked` names a missing
 * prerequisite elsewhere on the form; `empty` explains (and links to) what to
 * create when there is nothing to choose. Either one disables the select, so a
 * lawyer never opens a list that holds only a placeholder (BUG-011/013).
 */
function ChoiceField({
  id,
  label,
  value,
  onChange,
  placeholder,
  options,
  required = false,
  blocked,
  empty,
  caption,
  error,
  wide,
}: {
  id?: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  options: Choice[];
  required?: boolean;
  blocked?: ReactNode;
  empty: ReactNode;
  caption?: ReactNode;
  error?: string;
  wide?: boolean;
}) {
  const reason = blocked ?? (options.length === 0 ? empty : null);
  return (
    <Field id={id} label={label} wide={wide} hint={reason ?? caption} error={error}>
      <select
        className={SELECT_CLASS}
        value={reason ? "" : value}
        onChange={(event) => onChange(event.target.value)}
        disabled={Boolean(reason)}
        required={required && !reason}
      >
        <option value="">{placeholder}</option>
        {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </Field>
  );
}

/** Opens a prerequisite screen in a new tab so the half-filled form survives. */
function NewTabLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} target="_blank" rel="noopener noreferrer" className={LINK_CLASS}>
      {children}
      <ExternalLink className="ml-0.5 inline h-3 w-3 align-[-1px]" aria-hidden />
      <span className="sr-only"> (opens in a new tab)</span>
    </Link>
  );
}

function ServerReason({ blocker }: { blocker: IpForeignAssociateCreateBlocker | undefined }) {
  if (!blocker) return null;
  return (
    <>
      {blocker.message}
      {blocker.href && blocker.action_label ? <> <NewTabLink href={blocker.href}>{blocker.action_label}</NewTabLink></> : null}
    </>
  );
}

const OPTIONS_KEY = ["ip", "foreign-associate-create-options"] as const;

const FIELD_IDS = {
  docket: "fa-docket",
  thread: "fa-thread",
  jurisdiction: "fa-jurisdiction",
  associate: "fa-associate",
  assignment: "fa-assignment",
  clientInstruction: "fa-client-instruction",
  authority: "fa-authority",
  sourceReference: "fa-source-reference",
  filingKind: "fa-filing-kind",
  classes: "fa-classes",
  estimate: "fa-estimate",
  taxEvidence: "fa-tax-evidence",
  budgetPolicy: "fa-budget-policy",
  responseDue: "fa-response-due",
  documents: "fa-documents",
  reason: "fa-reason",
} as const;

const API_FIELD_MAP: Record<string, string> = {
  docket_id: FIELD_IDS.docket,
  instruction_thread_key: FIELD_IDS.thread,
  target_jurisdiction: FIELD_IDS.jurisdiction,
  outside_counsel_id: FIELD_IDS.associate,
  assignment_id: FIELD_IDS.assignment,
  source_client_instruction_id: FIELD_IDS.clientInstruction,
  client_authority_reference: FIELD_IDS.authority,
  "scope.source_reference": FIELD_IDS.sourceReference,
  "scope.filing_kind": FIELD_IDS.filingKind,
  "scope.scoped_fields": FIELD_IDS.classes,
  selected_document_refs: FIELD_IDS.documents,
  estimate_cost_item_id: FIELD_IDS.estimate,
  estimate_terms: FIELD_IDS.taxEvidence,
  budget_policy_reference: FIELD_IDS.budgetPolicy,
  response_due_at: FIELD_IDS.responseDue,
  reason: FIELD_IDS.reason,
};

// The create service refuses with a plain detail (no errors[]); anchor the
// known refusals to the field that caused them. Order matters: estimate and
// budget refusals also mention the assignment.
const DETAIL_FIELDS: Array<[RegExp, string]> = [
  [/estimate|budget ceiling|cost item/i, FIELD_IDS.estimate],
  [/^Associate /i, FIELD_IDS.associate],
  [/assignment|Matter-linked IP work/i, FIELD_IDS.assignment],
  [/^Client authority/i, FIELD_IDS.clientInstruction],
  [/document/i, FIELD_IDS.documents],
  [/^Instruction thread already exists/i, FIELD_IDS.thread],
];

function createErrors(error: unknown): Record<string, string> {
  const fields = apiFieldErrors(error, API_FIELD_MAP);
  if (Object.keys(fields).length || !isApiErrorShape(error)) return fields;
  const match = DETAIL_FIELDS.find(([pattern]) => pattern.test(error.detail));
  return { [match ? match[1] : API_FORM_ERROR_KEY]: error.detail };
}

function associateCaption(row: IpForeignAssociateCreateOptions["associates"][number]) {
  const contact = [row.primary_contact_name, row.primary_contact_email].filter(Boolean).join(" · ");
  return [
    row.firm_city ?? "City not recorded",
    contact || "No contact recorded",
    `Files in ${row.filing_jurisdictions.join(", ")}`,
    `Panel: ${readable(row.panel_status)}`,
  ].join(" · ");
}

function estimateLabel(row: IpForeignAssociateCreateOptions["estimates"][number]) {
  const amount = row.amount_withheld ? "Amount restricted" : money(row.amount_minor, row.currency);
  return `${row.description} · ${amount} · ${row.evidence_reference}`;
}

function CreateInstruction({
  canApprove,
  onCreated,
}: {
  canApprove: boolean;
  onCreated: (row: IpForeignAssociateInstruction) => void;
}) {
  const session = useSession();
  const queryClient = useQueryClient();
  const [docketId, setDocketId] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [counselId, setCounselId] = useState("");
  const [assignmentId, setAssignmentId] = useState("");
  const [clientInstructionId, setClientInstructionId] = useState("");
  const [authority, setAuthority] = useState("");
  const [threadKey, setThreadKey] = useState("");
  const [sourceKind, setSourceKind] = useState<"application" | "search">("application");
  const [sourceReference, setSourceReference] = useState("");
  const [filingKind, setFilingKind] = useState("national trademark application");
  const [classes, setClasses] = useState("");
  const [documentIds, setDocumentIds] = useState<string[]>([]);
  const [includePrivileged, setIncludePrivileged] = useState(false);
  const [estimateId, setEstimateId] = useState("");
  const [taxType, setTaxType] = useState("");
  const [taxRate, setTaxRate] = useState("");
  const [taxEvidence, setTaxEvidence] = useState("");
  const [assumptions, setAssumptions] = useState("");
  const [budgetPolicy, setBudgetPolicy] = useState("");
  const [responseDue, setResponseDue] = useState(localDateTimeInput(3));
  const [reason, setReason] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  const options = useQuery({
    queryKey: [...OPTIONS_KEY, docketId, jurisdiction],
    queryFn: () => fetchIpForeignAssociateCreateOptions({ docketId, targetJurisdiction: jurisdiction || null }),
    enabled: Boolean(docketId),
    // Prerequisites are created in other tabs; come back and the lists are current.
    staleTime: 0,
    refetchOnWindowFocus: true,
    placeholderData: (previous) => (previous?.docket_id === docketId ? previous : undefined),
  });
  const data = options.data?.docket_id === docketId ? options.data : undefined;

  const chooseDocket = (id: string) => {
    setDocketId(id);
    setCounselId("");
    setAssignmentId("");
    setEstimateId("");
    setClientInstructionId("");
    setDocumentIds([]);
    setErrors({});
  };

  const associate = data?.associates.find((row) => row.id === counselId);
  const counselAssignments = data?.assignments.filter((row) => row.counsel_id === counselId) ?? [];
  const assignment = counselAssignments.find((row) => row.id === assignmentId);
  const usableEstimates = !data
    ? []
    : assignment
      ? data.estimates.filter((row) => assignment.compatible_estimate_ids.includes(row.id))
      : data.assignment_required ? [] : data.estimates;
  const serverBlocker = (code: IpForeignAssociateCreateBlocker["code"]) => data?.blockers.find((row) => row.code === code);
  const parsedClasses = parseNiceClasses(classes);
  const docketHref = docketId ? `/app/ip?docket=${encodeURIComponent(docketId)}` : "/app/ip";
  const showQuoteForm = Boolean(data?.can_record_estimate) && (data?.estimates.length === 0 || (assignment !== undefined && usableEstimates.length === 0));

  const blockers: Array<{ key: string; field: string; text: string }> = [];
  if (!docketId) blockers.push({ key: "docket", field: FIELD_IDS.docket, text: "IP record: select the record this instruction is for." });
  else if (!data) blockers.push({ key: "options", field: FIELD_IDS.docket, text: options.isError ? "IP record: could not load what this record allows. Try again above." : "IP record: loading what this record allows…" });
  else {
    if (!jurisdiction) blockers.push({ key: "jurisdiction", field: FIELD_IDS.jurisdiction, text: "Target jurisdiction: choose where the associate files." });
    else if (!data.associates.length) blockers.push({ key: "associate-none", field: FIELD_IDS.associate, text: `Approved associate: none on the panel files in ${jurisdiction}.` });
    else if (!counselId) blockers.push({ key: "associate", field: FIELD_IDS.associate, text: "Approved associate: choose the associate." });
    if (data.assignment_required && counselId) {
      if (!counselAssignments.length) blockers.push({ key: "assignment-none", field: FIELD_IDS.assignment, text: "Approved Matter assignment: this associate has no budgeted assignment on the Matter." });
      else if (!assignmentId) blockers.push({ key: "assignment", field: FIELD_IDS.assignment, text: "Approved Matter assignment: choose the assignment." });
    }
    if (!data.estimates.length) blockers.push({ key: "estimate-none", field: FIELD_IDS.estimate, text: "Estimate: no active associate estimate on this record." });
    else if (assignment && !usableEstimates.length) blockers.push({ key: "estimate-fit", field: FIELD_IDS.estimate, text: "Estimate: none fits the assignment's currency and budget ceiling." });
    else if (usableEstimates.length && !estimateId) blockers.push({ key: "estimate", field: FIELD_IDS.estimate, text: "Estimate: choose the associate's estimate." });
    if (!data.documents.length) blockers.push({ key: "documents-none", field: FIELD_IDS.documents, text: "Documents: none are linked to this record." });
    else if (!documentIds.length) blockers.push({ key: "documents", field: FIELD_IDS.documents, text: "Documents: select at least one document to send." });
    if (!clientInstructionId && !authority.trim()) blockers.push({ key: "authority", field: FIELD_IDS.authority, text: "Client authority: link an accepted client instruction or record the client's written authority." });
    if (parsedClasses.errors.length) blockers.push({ key: "classes", field: FIELD_IDS.classes, text: `Nice classes: ${parsedClasses.errors[0].message}` });
  }
  if (!session.context?.membership.id) blockers.push({ key: "session", field: FIELD_IDS.docket, text: "Your session is still loading." });

  const create = useMutation({
    mutationFn: () => createIpForeignAssociateInstruction({
      docketId,
      expectedLifecycleVersion: data?.lifecycle_version ?? 0,
      instructionThreadKey: threadKey,
      sourceClientInstructionId: clientInstructionId || null,
      clientAuthorityReference: clientInstructionId ? null : authority,
      targetJurisdiction: jurisdiction,
      outsideCounselId: counselId,
      assignmentId: data?.assignment_required ? assignmentId || null : null,
      responsibleMembershipId: session.context?.membership.id ?? "",
      sourceKind,
      sourceReference,
      filingKind,
      scopedFields: parsedClasses.classes.length ? { classes: parsedClasses.classes } : {},
      selectedDocumentRefs: documentIds,
      includePrivilegedDocuments: includePrivileged,
      estimateCostItemId: estimateId,
      estimateTerms: {
        tax_type: taxType || null,
        tax_rate_percent: taxRate ? Number(taxRate) : null,
        tax_inclusive: false,
        tax_evidence_reference: taxEvidence || null,
        assumptions: refs(assumptions),
      },
      budgetPolicyReference: budgetPolicy,
      responseDueAt: responseDue ? iso(responseDue) : null,
      reason,
    }),
    onSuccess: async (row) => {
      toast.success("Foreign-associate instruction created.");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ip-foreign-associates"] }),
        queryClient.invalidateQueries({ queryKey: OPTIONS_KEY }),
      ]);
      onCreated(row);
    },
    onError: (error) => {
      setErrors(createErrors(error));
      if (isApiErrorShape(error) && error.status === 409) void options.refetch();
      toast.error(apiErrorMessage(error, "Could not create the instruction."));
    },
  });

  const recordedQuote = async (docket: IpDocket, evidenceReference: string) => {
    const known = new Set(data?.estimates.map((row) => row.id) ?? []);
    const recorded = docket.cost_items.find((row) =>
      row.cost_nature === "estimate" && row.lineage_status === "active" && !known.has(row.id)
      && row.evidence_reference === evidenceReference);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: OPTIONS_KEY }),
      queryClient.invalidateQueries({ queryKey: ["ip", "dockets", docketId] }),
    ]);
    if (recorded) setEstimateId(recorded.id);
  };

  const jurisdictionReason = !docketId
    ? "Select an IP record first."
    : options.isError
      ? "Could not load the jurisdictions. Try again above."
      : !data ? "Loading jurisdictions…" : null;
  const covered = data?.jurisdictions.filter((row) => row.associate_count > 0) ?? [];
  const jurisdictionLabel = (row: { code: string; name: string; associate_count: number }) =>
    `${row.name} (${row.code}) · ${row.associate_count === 1 ? "1 approved associate" : `${row.associate_count} approved associates`}`;

  return (
    <Card>
      <CardHeader><CardTitle as="h2">New foreign-associate instruction</CardTitle></CardHeader>
      <CardContent>
        <form
          className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-4"
          aria-label="New foreign-associate instruction"
          onSubmit={(event) => { event.preventDefault(); setErrors({}); create.mutate(); }}
        >
          <div className="grid min-w-0 gap-2 md:col-span-2 xl:col-span-4">
            <IpDocketPicker
              id={FIELD_IDS.docket}
              label="IP record"
              searchLabel="Find IP record"
              value={docketId}
              onChange={(id) => chooseDocket(id)}
              error={errors[FIELD_IDS.docket]}
              required
            />
            {docketId && options.isError ? (
              <QueryErrorState error={options.error} title="Could not load what this record allows" onRetry={() => void options.refetch()} />
            ) : null}
          </div>
          <Field id={FIELD_IDS.thread} label="Thread key" hint="Your reference for this instruction thread, for example PINE-GB-2026." error={errors[FIELD_IDS.thread]}>
            <Input value={threadKey} onChange={(event) => setThreadKey(event.target.value)} required minLength={3} maxLength={120} />
          </Field>
          <Field
            id={FIELD_IDS.jurisdiction}
            label="Target jurisdiction"
            hint={jurisdictionReason ?? (jurisdiction ? undefined : "Country code (ISO 3166) or regional office: EM (EUIPO), WO (WIPO), EP (EPO).")}
            error={errors[FIELD_IDS.jurisdiction]}
          >
            <select
              className={SELECT_CLASS}
              value={jurisdictionReason ? "" : jurisdiction}
              onChange={(event) => { setJurisdiction(event.target.value); setCounselId(""); setAssignmentId(""); setEstimateId(""); }}
              disabled={Boolean(jurisdictionReason)}
              required
            >
              <option value="">Select jurisdiction</option>
              {covered.length ? (
                <optgroup label="Where the panel has approved associates">
                  {covered.map((row) => <option key={`covered-${row.code}`} value={row.code}>{jurisdictionLabel(row)}</option>)}
                </optgroup>
              ) : null}
              <optgroup label="All jurisdictions">
                {data?.jurisdictions.map((row) => <option key={row.code} value={row.code}>{jurisdictionLabel(row)}</option>)}
              </optgroup>
            </select>
          </Field>
          <ChoiceField
            id={FIELD_IDS.associate}
            label="Approved associate"
            value={counselId}
            onChange={(value) => { setCounselId(value); setAssignmentId(""); setEstimateId(""); }}
            placeholder="Select associate"
            options={data?.associates.map((row) => ({ value: row.id, label: `${row.name} · ${row.firm_city ?? "City not recorded"}` })) ?? []}
            required
            blocked={jurisdictionReason ?? (!jurisdiction ? "Choose the target jurisdiction first." : undefined)}
            empty={<ServerReason blocker={serverBlocker("no_panel_associate") ?? serverBlocker("no_associate_for_jurisdiction")} />}
            caption={associate ? associateCaption(associate) : `Only active or preferred panel counsel approved for ${jurisdiction} are listed.`}
            error={errors[FIELD_IDS.associate]}
          />
          <ChoiceField
            id={FIELD_IDS.assignment}
            label="Approved Matter assignment"
            value={assignmentId}
            onChange={(value) => { setAssignmentId(value); setEstimateId(""); }}
            placeholder={data && !data.assignment_required ? "Not required — no linked Matter" : "Select assignment"}
            options={counselAssignments.map((row) => ({ value: row.id, label: `${row.role_summary ?? row.counsel_name} · ceiling ${money(row.budget_amount_minor, row.currency)}` }))}
            required={Boolean(data?.assignment_required)}
            blocked={
              !docketId ? "Select an IP record first."
                : !data ? "Loading the record's Matter…"
                  : !data.assignment_required ? (
                    <>This record has no linked Matter, so no Matter assignment or budget applies. To bill this work against a Matter budget, link the Matter on the IP record first. <NewTabLink href={docketHref}>Link a Matter on the IP record</NewTabLink></>
                  ) : !counselId ? "Choose the approved associate first." : undefined
            }
            empty={data?.matter_id ? (
              <>
                No approved assignment with a budget ceiling links {associate?.name ?? "this associate"} to the Matter {data.matter_title ?? ""}. Assign them on the Matter&apos;s Outside counsel tab with a budget ceiling in the quote&apos;s currency.
                {data.unbudgeted_assignment_count ? ` ${data.unbudgeted_assignment_count} assignment(s) on this Matter have no budget ceiling and cannot fund foreign-associate work.` : ""}
                {" "}<NewTabLink href={`/app/matters/${encodeURIComponent(data.matter_id)}/outside-counsel`}>Open the Matter&apos;s Outside counsel tab</NewTabLink>
              </>
            ) : null}
            caption={data?.matter_title ? `Matter: ${data.matter_title}. Only approved or active assignments with a budget ceiling are listed.` : undefined}
            error={errors[FIELD_IDS.assignment]}
          />
          {data?.client_instructions.length ? (
            <ChoiceField
              id={FIELD_IDS.clientInstruction}
              label="Accepted client instruction"
              value={clientInstructionId}
              onChange={(value) => { setClientInstructionId(value); if (value) setAuthority(""); }}
              placeholder="None — record written authority instead"
              options={data.client_instructions.map((row) => ({ value: row.id, label: `${readable(row.instruction_kind)} · ${row.submitted_by} · v${row.instruction_version} · received ${DATE.format(new Date(row.received_at))}` }))}
              empty={null}
              caption="Accepted 'proceed' instructions for this record. Choose one, or leave it and record the client's written authority."
              error={errors[FIELD_IDS.clientInstruction]}
            />
          ) : null}
          <Field
            id={FIELD_IDS.authority}
            label="Client's written authority"
            hint={clientInstructionId ? "Using the accepted client instruction above." : (
              <>
                The email or letter in which the client authorised this filing, for example &quot;Client email 30 Oct 2026, Ref PL-118&quot;.
                {data && !data.client_instructions.length ? (
                  <> No accepted client-portal instruction exists for this record, so record the written authority here, or accept the client&apos;s instruction first in <NewTabLink href="/app/ip/client-portal">IP client portal</NewTabLink>.</>
                ) : null}
              </>
            )}
            error={errors[FIELD_IDS.authority]}
          >
            <Input value={authority} onChange={(event) => setAuthority(event.target.value)} disabled={Boolean(clientInstructionId)} required={!clientInstructionId} maxLength={500} />
          </Field>
          <Field label="Source kind">
            <select className={SELECT_CLASS} value={sourceKind} onChange={(event) => setSourceKind(event.target.value as "application" | "search")}>
              <option value="application">Application</option>
              <option value="search">Search</option>
            </select>
          </Field>
          <Field id={FIELD_IDS.sourceReference} label="Source reference" hint="The application or search this instruction comes from." error={errors[FIELD_IDS.sourceReference]}>
            <Input value={sourceReference} onChange={(event) => setSourceReference(event.target.value)} required maxLength={255} />
          </Field>
          <Field id={FIELD_IDS.filingKind} label="Filing kind" error={errors[FIELD_IDS.filingKind]}>
            <Input value={filingKind} onChange={(event) => setFilingKind(event.target.value)} required minLength={2} maxLength={120} />
          </Field>
          <Field
            id={FIELD_IDS.classes}
            label="Nice classes in scope"
            hint="Optional. Class numbers separated by commas, for example 9, 35, 42."
            error={parsedClasses.errors.map((row) => row.message).join(" ") || errors[FIELD_IDS.classes]}
          >
            <Input value={classes} onChange={(event) => setClasses(event.target.value)} inputMode="numeric" />
          </Field>
          <div className="grid min-w-0 content-start gap-3 md:col-span-2 xl:col-span-4">
            <ChoiceField
              id={FIELD_IDS.estimate}
              label="Estimate"
              value={estimateId}
              onChange={setEstimateId}
              placeholder="Select estimate"
              options={usableEstimates.map((row) => ({ value: row.id, label: estimateLabel(row) }))}
              required
              blocked={
                !docketId ? "Select an IP record first."
                  : !data ? "Loading the record's estimates…"
                    : data.assignment_required && data.estimates.length && !assignment ? "Choose the Matter assignment first; the estimate must fit its currency and budget ceiling." : undefined
              }
              empty={data && !data.estimates.length ? (
                <ServerReason blocker={serverBlocker("no_active_estimate")} />
              ) : assignment ? (
                `No active estimate fits this assignment: it must be in ${assignment.currency} and at most ${money(assignment.budget_amount_minor, assignment.currency)}.`
              ) : null}
              caption={data?.can_record_estimate ? undefined : "Associate quotes are recorded by owners and admins (fee-management permission)."}
              error={errors[FIELD_IDS.estimate]}
            />
            {showQuoteForm && data ? (
              <RecordQuote
                key={assignment?.id ?? "no-assignment"}
                docketId={docketId}
                billable={Boolean(data.matter_id)}
                currency={assignment?.currency ?? "INR"}
                fitNote={assignment ? `To fit the assignment, record it in ${assignment.currency} at or below ${money(assignment.budget_amount_minor, assignment.currency)}.` : null}
                associateName={associate?.name ?? null}
                onRecorded={recordedQuote}
              />
            ) : null}
          </div>
          <Field label="Tax type"><Input value={taxType} onChange={(event) => setTaxType(event.target.value)} /></Field>
          <Field label="Tax rate percent"><Input type="number" min="0" max="100" step="0.01" value={taxRate} onChange={(event) => setTaxRate(event.target.value)} /></Field>
          <Field id={FIELD_IDS.taxEvidence} label="Tax evidence" error={errors[FIELD_IDS.taxEvidence]}><Input value={taxEvidence} onChange={(event) => setTaxEvidence(event.target.value)} required={Boolean(taxType || taxRate)} /></Field>
          <Field id={FIELD_IDS.budgetPolicy} label="Budget policy" hint="The budget approval or policy this spend falls under." error={errors[FIELD_IDS.budgetPolicy]}><Input value={budgetPolicy} onChange={(event) => setBudgetPolicy(event.target.value)} required minLength={3} maxLength={500} /></Field>
          <Field id={FIELD_IDS.responseDue} label="Response due" error={errors[FIELD_IDS.responseDue]}><Input className="min-w-0" type="datetime-local" value={responseDue} onChange={(event) => setResponseDue(event.target.value)} required /></Field>
          <Field label="Estimate assumptions" wide hint="One assumption per line."><Textarea value={assumptions} onChange={(event) => setAssumptions(event.target.value)} rows={2} /></Field>
          <fieldset
            id={FIELD_IDS.documents}
            className="grid min-w-0 gap-2 md:col-span-2 xl:col-span-4"
            aria-describedby={[`${FIELD_IDS.documents}-hint`, errors[FIELD_IDS.documents] ? `${FIELD_IDS.documents}-error` : ""].filter(Boolean).join(" ")}
            aria-invalid={errors[FIELD_IDS.documents] ? true : undefined}
          >
            <legend className="mb-1.5 text-sm font-medium">Documents to send</legend>
            <div id={`${FIELD_IDS.documents}-hint`} className="min-w-0 break-words text-xs text-[var(--color-mute)]">
              {!docketId ? "Select an IP record first." : !data ? "Loading the record's documents…" : !data.documents.length ? <ServerReason blocker={serverBlocker("no_linked_documents")} /> : "Documents linked to this IP record."}
            </div>
            {data?.documents.length ? (
              <div className="grid min-w-0 gap-2 sm:grid-cols-2">
                {data.documents.map((row) => (
                  <label key={row.id} className="flex min-w-0 items-start gap-2 rounded-md border border-[var(--color-line)] p-2 text-sm">
                    <input type="checkbox" checked={documentIds.includes(row.id)} onChange={(event) => setDocumentIds((current) => event.target.checked ? [...current, row.id] : current.filter((id) => id !== row.id))} />
                    <span className="min-w-0 break-words">{row.title}{row.is_privileged ? " · privileged" : ""}</span>
                  </label>
                ))}
              </div>
            ) : null}
            {errors[FIELD_IDS.documents] ? <p id={`${FIELD_IDS.documents}-error`} role="alert" className="text-xs font-medium text-[var(--color-danger-text)]">{errors[FIELD_IDS.documents]}</p> : null}
          </fieldset>
          <fieldset className="grid min-w-0 gap-1.5 md:col-span-2 xl:col-span-4">
            <legend className="mb-1.5 text-sm font-medium">Privilege approval</legend>
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" checked={includePrivileged} onChange={(event) => setIncludePrivileged(event.target.checked)} disabled={!canApprove} aria-describedby={canApprove ? undefined : "fa-privilege-hint"} />
              Explicitly include selected privileged/internal documents
            </label>
            {!canApprove ? <p id="fa-privilege-hint" className="text-xs text-[var(--color-mute)]">Only IP approvers can include privileged documents.</p> : null}
          </fieldset>
          <Field id={FIELD_IDS.reason} label="Reason" wide error={errors[FIELD_IDS.reason]}><Textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={3} required minLength={5} maxLength={2000} /></Field>
          {blockers.length ? (
            <div id="fa-create-blockers" className="min-w-0 rounded-md border border-[var(--color-warn-border)] bg-[var(--color-warn-bg)] p-3 text-sm text-[var(--color-warn-text)] md:col-span-2 xl:col-span-4">
              <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
                <p className="font-semibold">Before you can create this instruction</p>
                {docketId ? (
                  <Button type="button" size="sm" variant="outline" onClick={() => void options.refetch()} disabled={options.isFetching}>
                    {options.isFetching ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}Check again
                  </Button>
                ) : null}
              </div>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                {blockers.map((row) => <li key={row.key} className="break-words"><a className="underline underline-offset-2" href={`#${row.field}`}>{row.text}</a></li>)}
              </ul>
            </div>
          ) : null}
          {errors[API_FORM_ERROR_KEY] ? <p role="alert" className="min-w-0 break-words text-sm font-medium text-[var(--color-danger-text)] md:col-span-2 xl:col-span-4">{errors[API_FORM_ERROR_KEY]}</p> : null}
          <div className="flex min-w-0 md:col-span-2 xl:col-span-4">
            <Button
              className="w-full sm:w-auto"
              type="submit"
              disabled={create.isPending || blockers.length > 0}
              aria-describedby={blockers.length ? "fa-create-blockers" : undefined}
            >
              {create.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}Create instruction
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

const QUOTE_FIELDS: Record<string, string> = {
  description: "fa-quote-description",
  amount_minor: "fa-quote-amount",
  currency: "fa-quote-currency",
  evidence_reference: "fa-quote-reference",
};

/**
 * BUG-013: record the associate's quote where the instruction needs it
 * (PRD UJ-37). Only members with the fee-management permission (owners and
 * admins) see this; the API enforces the same capability.
 */
function RecordQuote({
  docketId,
  billable,
  currency: defaultCurrency,
  fitNote,
  associateName,
  onRecorded,
}: {
  docketId: string;
  billable: boolean;
  currency: string;
  fitNote: string | null;
  associateName: string | null;
  onRecorded: (docket: IpDocket, evidenceReference: string) => Promise<void>;
}) {
  const [description, setDescription] = useState(associateName ? `${associateName} filing quote` : "Associate filing quote");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState(defaultCurrency);
  const [reference, setReference] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const amountText = amount.replaceAll(",", "").trim();
  const amountValid = /^\d+(\.\d{1,2})?$/.test(amountText) && Number(amountText) > 0;

  const save = useMutation({
    mutationFn: () => addIpCostItem(docketId, {
      category: "associate_fee",
      description: description.trim(),
      amountMinor: Math.round(Number(amountText) * 100),
      currency: currency.trim().toUpperCase(),
      evidenceReference: reference.trim(),
      billable,
      costNature: "estimate",
    }),
    onSuccess: async (docket) => {
      toast.success("Associate quote recorded on the IP record.");
      const recordedReference = reference.trim();
      setAmount("");
      setReference("");
      setErrors({});
      await onRecorded(docket, recordedReference);
    },
    onError: (error) => {
      const fields = apiFieldErrors(error, QUOTE_FIELDS);
      setErrors(Object.keys(fields).length ? fields : { [API_FORM_ERROR_KEY]: apiErrorMessage(error, "Could not record the quote.") });
    },
  });

  const submit = () => {
    const local: Record<string, string> = {};
    if (description.trim().length < 3) local[QUOTE_FIELDS.description] = "Describe the quote in at least 3 characters.";
    if (!amountValid) local[QUOTE_FIELDS.amount_minor] = "Enter the quoted amount, for example 1500.00.";
    if (!/^[A-Za-z]{3}$/.test(currency.trim())) local[QUOTE_FIELDS.currency] = "Enter a 3-letter currency code, for example GBP.";
    if (reference.trim().length < 3) local[QUOTE_FIELDS.evidence_reference] = "Enter the quote's reference, for example the associate's email date.";
    setErrors(local);
    if (!Object.keys(local).length) save.mutate();
  };
  const onEnter = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") { event.preventDefault(); submit(); }
  };

  return (
    <section aria-labelledby="fa-quote-title" className="min-w-0 rounded-md border border-[var(--color-line)] bg-[var(--color-bg-subtle)] p-3">
      <h3 id="fa-quote-title" className="text-sm font-semibold">Record associate quote</h3>
      <p className="mt-1 break-words text-xs text-[var(--color-mute)]">
        Saved to this IP record&apos;s cost evidence as an estimate. Owners and admins (fee-management permission) record quotes.
        {billable ? "" : " This record has no Matter, so the quote is recorded as nonbillable."}
        {fitNote ? ` ${fitNote}` : ""}
      </p>
      <div className="mt-3 grid min-w-0 gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Field id={QUOTE_FIELDS.description} label="Quote description" error={errors[QUOTE_FIELDS.description]}>
          <Input value={description} onChange={(event) => setDescription(event.target.value)} onKeyDown={onEnter} maxLength={500} />
        </Field>
        <Field id={QUOTE_FIELDS.amount_minor} label="Quoted amount" error={errors[QUOTE_FIELDS.amount_minor]}>
          <Input value={amount} onChange={(event) => setAmount(event.target.value)} onKeyDown={onEnter} inputMode="decimal" placeholder="1500.00" />
        </Field>
        <Field id={QUOTE_FIELDS.currency} label="Quote currency" error={errors[QUOTE_FIELDS.currency]}>
          <Input value={currency} onChange={(event) => setCurrency(event.target.value.toUpperCase())} onKeyDown={onEnter} maxLength={3} autoCapitalize="characters" />
        </Field>
        <Field id={QUOTE_FIELDS.evidence_reference} label="Quote reference" hint="For example: associate email of 30 Oct 2026." error={errors[QUOTE_FIELDS.evidence_reference]}>
          <Input value={reference} onChange={(event) => setReference(event.target.value)} onKeyDown={onEnter} maxLength={500} />
        </Field>
      </div>
      {errors[API_FORM_ERROR_KEY] ? <p role="alert" className="mt-2 break-words text-sm font-medium text-[var(--color-danger-text)]">{errors[API_FORM_ERROR_KEY]}</p> : null}
      <Button className="mt-3 w-full sm:w-auto" type="button" variant="outline" onClick={submit} disabled={save.isPending}>
        {save.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}Save quote
      </Button>
    </section>
  );
}

function InstructionWorkspace({ instructionId, canWrite, canApprove }: { instructionId: string; canWrite: boolean; canApprove: boolean }) {
  const [activeTab, setActiveTab] = useState<"instruction" | "actions" | "reminders" | "history">("instruction");
  const workspace = useQuery({ queryKey: ["ip-foreign-associate-workspace", instructionId], queryFn: () => fetchIpForeignAssociateWorkspace(instructionId) });
  const actions = workspace.data ? TRANSITIONS[workspace.data.instruction.status] : [];
  const actionsEnabled = activeTab === "actions" && actions.length > 0;
  const documentsNeeded = actionsEnabled && actions.some((kind) => ["record_query", "approve_substantive_response", "report_filing", "verify_filing_evidence"].includes(kind));
  const counselNeeded = actionsEnabled && actions.some((kind) => ["link_invoice", "reassign"].includes(kind));
  const communicationsNeeded = actionsEnabled && actions.includes("dispatch");
  const documents = useQuery({ queryKey: ["ip-documents", workspace.data?.instruction.docket_id], queryFn: () => fetchIpDocumentsForDocket(workspace.data!.instruction.docket_id), enabled: documentsNeeded });
  const counsel = useQuery({ queryKey: ["outside-counsel", "workspace"], queryFn: fetchOutsideCounselWorkspace, enabled: counselNeeded });
  // Replacement associates come from the same predicate the reassign validator uses.
  const reassignNeeded = actionsEnabled && actions.includes("reassign") && (canWrite || canApprove);
  const reassignOptions = useQuery({
    queryKey: ["ip", "foreign-associate-create-options", workspace.data?.instruction.docket_id, workspace.data?.instruction.target_jurisdiction],
    queryFn: () => fetchIpForeignAssociateCreateOptions({ docketId: workspace.data!.instruction.docket_id, targetJurisdiction: workspace.data!.instruction.target_jurisdiction }),
    enabled: reassignNeeded,
  });
  const deadlines = useQuery({ queryKey: ["ip-deadlines", workspace.data?.instruction.docket_id], queryFn: () => fetchIpDeadlineWorkspace(workspace.data!.instruction.docket_id), enabled: actionsEnabled });
  const communications = useQuery({ queryKey: ["matter-communications", workspace.data?.docket.matter_id], queryFn: () => fetchMatterCommunications(workspace.data!.docket.matter_id!), enabled: communicationsNeeded && Boolean(workspace.data?.docket.matter_id) });

  if (workspace.isLoading) return <Skeleton className="h-[32rem]" />;
  if (workspace.isError) return <QueryErrorState error={workspace.error} onRetry={() => void workspace.refetch()} />;
  if (!workspace.data) return <EmptyState title="Instruction unavailable" description="" />;
  const actionQueries = [documents, counsel, deadlines, communications, reassignOptions].filter((query) => query.isLoading || query.isError);
  const actionLoading = actionQueries.some((query) => query.isLoading);
  const actionError = actionQueries.find((query) => query.isError)?.error;
  const retryActionQueries = () => {
    void Promise.all([
      ...(documentsNeeded ? [documents.refetch()] : []),
      ...(counselNeeded ? [counsel.refetch()] : []),
      ...(actionsEnabled ? [deadlines.refetch()] : []),
      ...(communicationsNeeded && workspace.data.docket.matter_id ? [communications.refetch()] : []),
      ...(reassignNeeded ? [reassignOptions.refetch()] : []),
    ]);
  };
  return (
    <div className="min-w-0 space-y-4">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="break-words text-xl font-semibold">{workspace.data.associate_name}</h2>
          <p className="break-words text-sm text-[var(--color-mute)]">{workspace.data.docket.title} · {workspace.data.instruction.target_jurisdiction} · v{workspace.data.instruction.instruction_version}</p>
        </div>
        <Status value={workspace.data.instruction.status} />
      </div>
      <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as typeof activeTab)} className="min-w-0">
        <TabsList className="grid h-auto w-full min-w-0 grid-cols-2 gap-1 sm:grid-cols-4">
          <TabsTrigger value="instruction">Instruction</TabsTrigger>
          <TabsTrigger value="actions">Actions</TabsTrigger>
          <TabsTrigger value="reminders">Reminders</TabsTrigger>
          <TabsTrigger value="history">History</TabsTrigger>
        </TabsList>
        <TabsContent value="instruction"><InstructionSummary workspace={workspace.data} docket={workspace.data.docket} documents={workspace.data.documents} /></TabsContent>
        <TabsContent value="actions">
          {actionLoading ? <Skeleton className="h-[24rem]" /> : actionError ? (
            <QueryErrorState error={actionError} onRetry={retryActionQueries} />
          ) : (
            <TransactionForm workspace={workspace.data} docket={workspace.data.docket} documents={documents.data?.items ?? []} deadlines={deadlines.data?.deadlines ?? []} counsel={counsel.data} associates={reassignOptions.data?.associates ?? []} communications={communications.data?.communications ?? []} canWrite={canWrite} canApprove={canApprove} />
          )}
        </TabsContent>
        <TabsContent value="reminders"><ReminderPanel workspace={workspace.data} docket={workspace.data.docket} canWrite={canWrite} /></TabsContent>
        <TabsContent value="history"><HistoryPanel workspace={workspace.data} /></TabsContent>
      </Tabs>
    </div>
  );
}

function InstructionSummary({ workspace, docket, documents }: { workspace: IpForeignAssociateWorkspace; docket: IpDocket; documents: IpDocument[] }) {
  const row = workspace.instruction;
  return (
    <div className="grid min-w-0 gap-4 lg:grid-cols-2">
      <Card><CardHeader><CardTitle as="h3">Instruction scope</CardTitle></CardHeader><CardContent className="space-y-3 text-sm">
        <Datum label="Source" value={`${row.scope_json.source_kind ?? "source"}: ${row.scope_json.source_reference ?? "Not recorded"}`} />
        <Datum label="Filing" value={row.scope_json.filing_kind ?? "Not recorded"} />
        <Datum label="Foreign filing ID" value={row.filing_identifier ?? "Not reported"} />
        <Datum label="Authority" value={row.source_client_instruction_id ? "Accepted client instruction (linked)" : row.client_authority_reference ?? "Not recorded"} />
        <Datum label="Estimate" value={docket.cost_items.find((cost) => cost.id === row.estimate_cost_item_id)?.description ?? "Estimate no longer visible on this record"} />
        <Datum label="Response due" value={row.response_due_at ? DATE.format(new Date(row.response_due_at)) : "Not set"} />
      </CardContent></Card>
      <Card><CardHeader><CardTitle as="h3">Delivery and evidence</CardTitle></CardHeader><CardContent className="space-y-3 text-sm">
        <Datum label="Delivery" value={readable(workspace.delivery_status)} />
        <Datum label="Acknowledgement" value={readable(workspace.acknowledgement_status)} />
        <Datum label="Filing evidence" value={readable(workspace.filing_evidence_status)} />
        <Datum label="Invoice" value={workspace.invoice_status ? readable(workspace.invoice_status) : "Not linked"} />
        {workspace.response_overdue ? <p className="flex items-start gap-2 text-sm font-semibold text-red-700"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />Associate acknowledgement overdue</p> : null}
      </CardContent></Card>
      <Card className="lg:col-span-2"><CardHeader><CardTitle as="h3">Selected documents</CardTitle></CardHeader><CardContent className="grid min-w-0 gap-2 sm:grid-cols-2">
        {documents.map((document) => {
          const version = document.versions.find((item) => item.version === document.current_version);
          return <div key={document.id} className="flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-md border border-[var(--color-line)] p-3 text-sm"><span className="min-w-0 break-words">{document.title}{document.is_privileged ? " · privileged" : ""}</span>{version ? <a href={`${API_BASE_URL}/api/ip/documents/${encodeURIComponent(document.id)}/versions/${version.version}/download`} target="_blank" rel="noopener noreferrer"><Button size="sm" variant="outline"><ExternalLink className="h-4 w-4" />Open source</Button></a> : <span className="text-xs text-[var(--color-mute)]">No version</span>}</div>;
        })}
      </CardContent></Card>
    </div>
  );
}

function Datum({ label, value }: { label: string; value: string }) {
  return <div className="grid min-w-0 grid-cols-[7rem_minmax(0,1fr)] gap-2"><span className="text-[var(--color-mute)]">{label}</span><span className="break-words font-medium">{value}</span></div>;
}

type CounselWorkspace = Awaited<ReturnType<typeof fetchOutsideCounselWorkspace>>;
type Communication = Awaited<ReturnType<typeof fetchMatterCommunications>>["communications"][number];

function TransactionForm({
  workspace,
  docket,
  documents,
  deadlines,
  counsel,
  associates,
  communications,
  canWrite,
  canApprove,
}: {
  workspace: IpForeignAssociateWorkspace;
  docket: IpDocket;
  documents: IpDocument[];
  deadlines: Array<{ id: string; title: string }>;
  counsel: CounselWorkspace | undefined;
  associates: IpForeignAssociateCreateOptions["associates"];
  communications: Communication[];
  canWrite: boolean;
  canApprove: boolean;
}) {
  const session = useSession();
  const queryClient = useQueryClient();
  const options = TRANSITIONS[workspace.instruction.status];
  const [kind, setKind] = useState<IpForeignAssociateTransactionKind | "">(options[0] ?? "");
  const [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [deadlineId, setDeadlineId] = useState("");
  const [communicationId, setCommunicationId] = useState("");
  const [externalDispatch, setExternalDispatch] = useState("");
  const [externalDelivery, setExternalDelivery] = useState("");
  const [acknowledgement, setAcknowledgement] = useState("");
  const [filingIdentifier, setFilingIdentifier] = useState("");
  const [replacementEstimateId, setReplacementEstimateId] = useState("");
  const [actualCostId, setActualCostId] = useState("");
  const [spendId, setSpendId] = useState("");
  const [replacementCounselId, setReplacementCounselId] = useState("");
  const [replacementAssignmentId, setReplacementAssignmentId] = useState("");
  const [replacementDue, setReplacementDue] = useState(localDateTimeInput(3));
  const [taxType, setTaxType] = useState("");
  const [taxRate, setTaxRate] = useState("");
  const [taxEvidence, setTaxEvidence] = useState("");
  const [assumptions, setAssumptions] = useState("");
  const needsApproval = kind ? ["approve", "approve_substantive_response", "approve_fee_change", "verify_filing_evidence", "complete", "reassign"].includes(kind) : false;
  // The API accepts only active (not voided or superseded) cost items.
  const estimates = docket.cost_items.filter((row) => row.cost_nature === "estimate" && row.lineage_status === "active" && row.id !== workspace.instruction.estimate_cost_item_id);
  const actuals = docket.cost_items.filter((row) => row.cost_nature === "actual" && row.lineage_status === "active");
  const assignments = docket.matter_id ? counsel?.assignments.filter((row) => row.matter_id === docket.matter_id && row.counsel_id === replacementCounselId && ["approved", "active"].includes(row.status)) ?? [] : [];
  const docketHref = `/app/ip?docket=${encodeURIComponent(docket.id)}`;
  const matterCounselHref = docket.matter_id ? `/app/matters/${encodeURIComponent(docket.matter_id)}/outside-counsel` : null;
  const spends = counsel?.spend_records.filter((row) => row.matter_id === docket.matter_id && row.counsel_id === workspace.instruction.outside_counsel_id) ?? [];
  const dispatches = communications.filter((row) => row.direction === "outbound" && ["logged", "sent", "delivered", "opened"].includes(row.status));

  useEffect(() => { setKind(options[0] ?? ""); }, [workspace.instruction.status]);

  const mutation = useMutation({
    mutationFn: () => recordIpForeignAssociateTransaction({
      instructionId: workspace.instruction.id,
      expectedVersion: workspace.instruction.row_version,
      expectedLifecycleVersion: docket.lifecycle_version,
      transactionKind: kind as IpForeignAssociateTransactionKind,
      effectiveAt: new Date().toISOString(),
      responsibleMembershipId: session.context?.membership.id ?? "",
      reason,
      evidenceRefs: refs(evidence),
      documentRefs: documentId ? [documentId] : [],
      deadlineRefs: deadlineId ? [deadlineId] : [],
      dispatchCommunicationId: kind === "dispatch" && communicationId ? communicationId : null,
      externalDispatchReference: kind === "dispatch" && !communicationId ? externalDispatch : null,
      externalDeliveryReference: kind === "dispatch" && !communicationId && externalDelivery ? externalDelivery : null,
      externalDeliveredAt: kind === "dispatch" && !communicationId && externalDelivery ? new Date().toISOString() : null,
      acknowledgementReference: kind === "acknowledge" ? acknowledgement : null,
      replacementEstimateCostItemId: ["approve_fee_change", "reassign"].includes(kind) ? replacementEstimateId : null,
      replacementEstimateTerms: ["approve_fee_change", "reassign"].includes(kind) ? { tax_type: taxType || null, tax_rate_percent: taxRate ? Number(taxRate) : null, tax_inclusive: false, tax_evidence_reference: taxEvidence || null, assumptions: refs(assumptions) } : null,
      filingIdentifier: kind === "report_filing" ? filingIdentifier : null,
      actualCostItemId: kind === "link_invoice" ? actualCostId : null,
      spendRecordId: kind === "link_invoice" ? spendId : null,
      replacementOutsideCounselId: kind === "reassign" ? replacementCounselId : null,
      replacementAssignmentId: kind === "reassign" && docket.matter_id ? replacementAssignmentId || null : null,
      replacementResponseDueAt: kind === "reassign" && replacementDue ? iso(replacementDue) : null,
    }),
    onSuccess: async (result) => {
      toast.success(result.successor ? "Instruction reassigned with preserved history." : `${readable(kind)} recorded.`);
      setReason(""); setEvidence(""); setDocumentId(""); setDeadlineId("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ip-foreign-associate-workspace", workspace.instruction.id] }),
        queryClient.invalidateQueries({ queryKey: ["ip-foreign-associates"] }),
      ]);
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not record the transaction.")),
  });

  if (!options.length) return <EmptyState title="No further instruction actions" description="" />;
  const approverOnly = needsApproval && !canApprove;
  return <Card><CardHeader><CardTitle as="h3">Record transaction</CardTitle></CardHeader><CardContent><form className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-4" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
    <Field label="Transaction"><select className={SELECT_CLASS} value={kind} onChange={(event) => setKind(event.target.value as IpForeignAssociateTransactionKind)}>{options.map((value) => <option key={value} value={value}>{readable(value)}</option>)}</select></Field>
    {kind === "dispatch" ? <>
      <ChoiceField
        label="Approved Communication"
        value={communicationId}
        onChange={(value) => { setCommunicationId(value); if (value) { setExternalDispatch(""); setExternalDelivery(""); } }}
        placeholder="None — record external dispatch evidence"
        options={dispatches.map((row) => ({ value: row.id, label: `${row.subject ?? row.channel} · ${row.status}` }))}
        empty={docket.matter_id ? "No sent Communication is logged on this record's Matter. Record the external dispatch evidence instead." : "This record has no Matter, so there is no Communication to link. Record the external dispatch evidence instead."}
      />
      <Field label="External dispatch evidence"><Input value={externalDispatch} onChange={(event) => setExternalDispatch(event.target.value)} disabled={Boolean(communicationId)} required={!communicationId} /></Field>
      <Field label="External delivery evidence"><Input value={externalDelivery} onChange={(event) => setExternalDelivery(event.target.value)} disabled={Boolean(communicationId)} /></Field>
    </> : null}
    {kind === "acknowledge" ? <Field label="Acknowledgement evidence"><Input value={acknowledgement} onChange={(event) => setAcknowledgement(event.target.value)} required /></Field> : null}
    {kind === "report_filing" ? <Field label="Foreign filing identifier"><Input value={filingIdentifier} onChange={(event) => setFilingIdentifier(event.target.value)} required /></Field> : null}
    {["approve_fee_change", "reassign"].includes(kind) ? <>
      <ChoiceField
        label="Replacement estimate"
        value={replacementEstimateId}
        onChange={setReplacementEstimateId}
        placeholder="Select estimate"
        options={estimates.map((row) => ({ value: row.id, label: `${row.description} · ${row.amount_withheld ? "Amount restricted" : money(row.amount_minor, row.currency)}` }))}
        required
        empty={<>No other active estimate is recorded on this record. Owners and admins (fee-management permission) record the revised quote in the IP record&apos;s cost evidence. <NewTabLink href={docketHref}>Open the IP record</NewTabLink></>}
      />
      <Field label="Tax type"><Input value={taxType} onChange={(event) => setTaxType(event.target.value)} /></Field>
      <Field label="Tax rate percent"><Input type="number" min="0" max="100" step="0.01" value={taxRate} onChange={(event) => setTaxRate(event.target.value)} /></Field>
      <Field label="Tax evidence"><Input value={taxEvidence} onChange={(event) => setTaxEvidence(event.target.value)} required={Boolean(taxType || taxRate)} /></Field>
      <Field label="Changed assumptions"><Input value={assumptions} onChange={(event) => setAssumptions(event.target.value)} /></Field>
    </> : null}
    {kind === "link_invoice" ? <>
      <ChoiceField
        label="Actual filing cost"
        value={actualCostId}
        onChange={setActualCostId}
        placeholder="Select cost"
        options={actuals.map((row) => ({ value: row.id, label: `${row.description} · ${row.amount_withheld ? "Amount restricted" : money(row.amount_minor, row.currency)}` }))}
        required
        empty={<>No active actual cost is recorded on this record. Record the associate&apos;s invoiced cost in the IP record&apos;s cost evidence. <NewTabLink href={docketHref}>Open the IP record</NewTabLink></>}
      />
      <ChoiceField
        label="Associate invoice"
        value={spendId}
        onChange={setSpendId}
        placeholder="Select invoice"
        options={spends.map((row) => ({ value: row.id, label: `${row.invoice_reference ?? row.description} · ${row.status}` }))}
        required
        empty={matterCounselHref ? <>No invoice from this associate is recorded on the Matter. Record it on the Matter&apos;s Outside counsel tab. <NewTabLink href={matterCounselHref}>Open the Matter&apos;s Outside counsel tab</NewTabLink></> : "Associate invoices are recorded against a Matter, and this record has no Matter."}
      />
    </> : null}
    {kind === "reassign" ? <>
      <ChoiceField
        label="Replacement associate"
        value={replacementCounselId}
        onChange={(value) => { setReplacementCounselId(value); setReplacementAssignmentId(""); }}
        placeholder="Select associate"
        options={associates.map((row) => ({ value: row.id, label: `${row.name} · ${row.firm_city ?? "City not recorded"}` }))}
        required
        empty={<>No approved associate on the panel files in {workspace.instruction.target_jurisdiction}. Add one in Outside Counsel with {workspace.instruction.target_jurisdiction} as a jurisdiction. <NewTabLink href="/app/outside-counsel">Add counsel in Outside Counsel</NewTabLink></>}
      />
      <ChoiceField
        label="Replacement assignment"
        value={replacementAssignmentId}
        onChange={setReplacementAssignmentId}
        placeholder={docket.matter_id ? "Select assignment" : "Not required — no linked Matter"}
        options={assignments.map((row) => ({ value: row.id, label: `${row.role_summary ?? row.counsel_name} · ${row.budget_amount_minor === null ? "No ceiling" : money(row.budget_amount_minor, row.currency)}` }))}
        required={Boolean(docket.matter_id)}
        blocked={!docket.matter_id ? "Not required: this record has no linked Matter." : !replacementCounselId ? "Choose the replacement associate first." : undefined}
        empty={matterCounselHref ? <>The replacement associate has no approved assignment on this record&apos;s Matter. Assign them on the Matter&apos;s Outside counsel tab. <NewTabLink href={matterCounselHref}>Open the Matter&apos;s Outside counsel tab</NewTabLink></> : null}
      />
      <Field label="Replacement response due"><Input className="min-w-0" type="datetime-local" value={replacementDue} onChange={(event) => setReplacementDue(event.target.value)} /></Field>
    </> : null}
    {!["approve", "dispatch", "acknowledge", "cancel", "complete"].includes(kind) ? <Field label="Correspondence/source evidence" wide><Textarea value={evidence} onChange={(event) => setEvidence(event.target.value)} rows={2} required={["record_query", "approve_substantive_response", "approve_fee_change", "report_filing", "verify_filing_evidence", "refuse", "reassign"].includes(kind)} /></Field> : null}
    {["report_filing", "verify_filing_evidence", "record_query", "approve_substantive_response"].includes(kind) ? (
      <ChoiceField
        label="Linked document"
        value={documentId}
        onChange={setDocumentId}
        placeholder={kind === "report_filing" ? "Select document" : "No document"}
        options={documents.map((row) => ({ value: row.id, label: row.title }))}
        required={kind === "report_filing"}
        empty={<>No documents are linked to this record. Upload the associate&apos;s filing documents on the IP record. <NewTabLink href={docketHref}>Open the IP record documents</NewTabLink></>}
      />
    ) : null}
    <ChoiceField
      label="Linked deadline"
      value={deadlineId}
      onChange={setDeadlineId}
      placeholder="No deadline"
      options={deadlines.map((row) => ({ value: row.id, label: row.title }))}
      empty="No deadlines are recorded on this record."
    />
    <Field label="Reason" wide><Textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={3} required /></Field>
    <div className="grid min-w-0 gap-2 md:col-span-2 xl:col-span-4">
      {approverOnly ? <p id="fa-transaction-approver" className="text-sm text-[var(--color-mute)]">Only IP approvers can record {readable(kind).toLowerCase()}.</p> : null}
      <Button className="w-full sm:w-auto sm:justify-self-start" type="submit" aria-describedby={approverOnly ? "fa-transaction-approver" : undefined} disabled={mutation.isPending || (!canWrite && !canApprove) || approverOnly || !session.context?.membership.id}>{mutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : kind === "dispatch" ? <Send className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}Record {readable(kind)}</Button>
    </div>
  </form></CardContent></Card>;
}

function ReminderPanel({ workspace, docket, canWrite }: { workspace: IpForeignAssociateWorkspace; docket: IpDocket; canWrite: boolean }) {
  const session = useSession();
  const queryClient = useQueryClient();
  const [offsets, setOffsets] = useState("72,24,0");
  const [inApp, setInApp] = useState(true);
  const [email, setEmail] = useState(false);
  const [escalationHours, setEscalationHours] = useState("24");
  const schedule = useMutation({
    mutationFn: () => scheduleIpForeignAssociateReminders({
      instruction: workspace.instruction,
      expectedLifecycleVersion: docket.lifecycle_version,
      reminderOffsetsHours: refs(offsets).map(Number),
      channels: [...(inApp ? ["in_app" as const] : []), ...(email ? ["email" as const] : [])],
      escalationAfterHours: Number(escalationHours),
      escalationMembershipId: session.context?.membership.id,
    }),
    onSuccess: async (result) => {
      toast.success(result.created_count ? `${result.created_count} reminder intents scheduled.` : "Reminder policy is already scheduled.");
      await queryClient.invalidateQueries({ queryKey: ["ip-foreign-associate-workspace", workspace.instruction.id] });
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not schedule reminders.")),
  });
  return <div className="min-w-0 space-y-4"><Card><CardHeader><CardTitle as="h3">Acknowledgement reminders</CardTitle></CardHeader><CardContent><form className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-4" onSubmit={(event) => { event.preventDefault(); schedule.mutate(); }}>
    <Field label="Hours before due"><Input value={offsets} onChange={(event) => setOffsets(event.target.value)} /></Field>
    <Field label="Escalate after hours"><Input type="number" min="1" max="168" value={escalationHours} onChange={(event) => setEscalationHours(event.target.value)} /></Field>
    <Field label="Channels" wide><div className="flex min-w-0 flex-wrap gap-4 text-sm"><label className="flex items-center gap-2"><input type="checkbox" checked={inApp} onChange={(event) => setInApp(event.target.checked)} />In app</label><label className="flex items-center gap-2"><input type="checkbox" checked={email} onChange={(event) => setEmail(event.target.checked)} />Email</label></div></Field>
    <div className="flex min-w-0 md:col-span-2 xl:col-span-4"><Button className="w-full sm:w-auto" type="submit" disabled={schedule.isPending || !canWrite || workspace.instruction.status !== "dispatched" || workspace.acknowledgement_status !== "outstanding" || (!inApp && !email)}>{schedule.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <BellRing className="h-4 w-4" />}Schedule reminders</Button></div>
  </form></CardContent></Card>
  <div className="grid min-w-0 gap-2 sm:grid-cols-2">{workspace.reminders.map((row) => <div key={row.id} className="min-w-0 rounded-md border border-[var(--color-line)] bg-white p-3 text-sm"><div className="flex min-w-0 flex-wrap items-center justify-between gap-2"><span className="flex items-center gap-2 font-semibold">{row.event_type.includes("overdue") ? <AlertTriangle className="h-4 w-4 text-amber-700" /> : <MailCheck className="h-4 w-4" />}{readable(row.event_type)}</span><Status value={row.status} /></div><p className="mt-2 break-words text-xs text-[var(--color-mute)]">{row.channel} · {row.scheduled_for ? DATE.format(new Date(row.scheduled_for)) : "No schedule"}</p></div>)}</div>
  {!workspace.reminders.length ? <EmptyState title="No reminders scheduled" description="" /> : null}</div>;
}

function HistoryPanel({ workspace }: { workspace: IpForeignAssociateWorkspace }) {
  return <Card><CardHeader><CardTitle as="h3">Instruction history</CardTitle></CardHeader><CardContent className="space-y-3">{workspace.transactions.map((event) => <div key={event.id} className="min-w-0 border-b border-[var(--color-line)] pb-3 last:border-0"><div className="flex min-w-0 flex-wrap items-start justify-between gap-2"><div className="min-w-0"><p className="break-words font-semibold">{readable(String(event.payload_json.transaction_kind ?? event.event_kind))}</p><p className="break-words text-sm text-[var(--color-mute)]">{event.reason}</p></div><span className="text-xs text-[var(--color-mute)]">{DATE.format(new Date(event.effective_at))}</span></div><div className="mt-2 flex min-w-0 flex-wrap gap-2">{event.evidence_refs_json.map((reference) => reference.startsWith("https://") ? <a key={reference} href={reference} target="_blank" rel="noopener noreferrer"><Button size="sm" variant="outline"><ExternalLink className="h-4 w-4" />Open source</Button></a> : <Badge key={reference} tone="neutral">{reference}</Badge>)}</div></div>)}</CardContent></Card>;
}
