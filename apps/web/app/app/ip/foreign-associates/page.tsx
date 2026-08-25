"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  BellRing,
  CheckCircle2,
  ExternalLink,
  FileCheck2,
  LoaderCircle,
  MailCheck,
  Plus,
  RefreshCw,
  Send,
} from "lucide-react";
import { cloneElement, isValidElement, useEffect, useId, useState } from "react";
import type { ReactElement, ReactNode } from "react";
import { toast } from "sonner";

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
import { API_BASE_URL, apiErrorMessage } from "@/lib/api/config";
import {
  createIpForeignAssociateInstruction,
  fetchIpDeadlineWorkspace,
  fetchIpDocket,
  fetchIpDockets,
  fetchIpDocumentsForDocket,
  fetchIpForeignAssociateInstructions,
  fetchIpForeignAssociateWorkspace,
  fetchIpPortalClientInstructions,
  fetchMatterCommunications,
  fetchOutsideCounselWorkspace,
  recordIpForeignAssociateTransaction,
  scheduleIpForeignAssociateReminders,
  type IpDocket,
  type IpDocument,
  type IpForeignAssociateInstruction,
  type IpForeignAssociateStatus,
  type IpForeignAssociateTransactionKind,
  type IpForeignAssociateWorkspace,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import { useSession } from "@/lib/use-session";

const SELECT_CLASS =
  "h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm";

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

function Field({
  label,
  children,
  wide = false,
}: {
  label: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const id = useId();
  const control = isValidElement(children)
    ? cloneElement(children as ReactElement<{ id?: string }>, {
        id: (children.props as { id?: string }).id ?? id,
      })
    : children;
  return (
    <div className={`grid min-w-0 gap-1.5 ${wide ? "md:col-span-2 xl:col-span-4" : ""}`}>
      <Label htmlFor={id}>{label}</Label>
      {control}
    </div>
  );
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

      <div className="flex min-w-0 flex-wrap gap-2" aria-label="Instruction queues">
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
              <InstructionWorkspace instructionId={selectedId} canWrite={canWrite} canApprove={canApprove} />
            ) : (
              <EmptyState title="Select an instruction" description="" />
            )}
          </div>
        </div>
      )}
    </div>
  );
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
  const [threadKey, setThreadKey] = useState("");
  const [clientInstructionId, setClientInstructionId] = useState("");
  const [authority, setAuthority] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [counselId, setCounselId] = useState("");
  const [assignmentId, setAssignmentId] = useState("");
  const [sourceKind, setSourceKind] = useState<"application" | "search">("application");
  const [sourceReference, setSourceReference] = useState("");
  const [filingKind, setFilingKind] = useState("national trademark application");
  const [scopeFields, setScopeFields] = useState("classes=9,42");
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

  const dockets = useQuery({ queryKey: ["ip-dockets", "foreign-associate-create"], queryFn: fetchIpDockets });
  const docket = useQuery({ queryKey: ["ip-docket", docketId], queryFn: () => fetchIpDocket(docketId), enabled: Boolean(docketId) });
  const documents = useQuery({ queryKey: ["ip-documents", docketId], queryFn: () => fetchIpDocumentsForDocket(docketId), enabled: Boolean(docketId) });
  const counsel = useQuery({ queryKey: ["outside-counsel-workspace"], queryFn: fetchOutsideCounselWorkspace });
  const clientInstructions = useQuery({ queryKey: ["ip-portal-client-instructions"], queryFn: fetchIpPortalClientInstructions });

  useEffect(() => {
    setDocumentIds([]);
    setEstimateId("");
    setCounselId("");
    setAssignmentId("");
    setClientInstructionId("");
  }, [docketId]);

  const profiles = counsel.data?.profiles.filter((row) =>
    ["active", "preferred"].includes(row.panel_status)
    && (!jurisdiction || row.jurisdictions.some((value) => value.toLowerCase() === jurisdiction.toLowerCase()))
  ) ?? [];
  const assignments = counsel.data?.assignments.filter((row) =>
    row.matter_id === docket.data?.matter_id && row.counsel_id === counselId && ["approved", "active"].includes(row.status)
  ) ?? [];
  const estimates = docket.data?.cost_items.filter((row) => row.cost_nature === "estimate") ?? [];
  const acceptedInstructions = clientInstructions.data?.instructions.filter((row) =>
    row.docket_id === docketId && row.decision === "proceed" && row.status === "accepted"
  ) ?? [];

  const create = useMutation({
    mutationFn: () => createIpForeignAssociateInstruction({
      docketId,
      expectedLifecycleVersion: docket.data?.lifecycle_version ?? 0,
      instructionThreadKey: threadKey,
      sourceClientInstructionId: clientInstructionId || null,
      clientAuthorityReference: clientInstructionId ? null : authority,
      targetJurisdiction: jurisdiction,
      outsideCounselId: counselId,
      assignmentId: assignmentId || null,
      responsibleMembershipId: session.context?.membership.id ?? "",
      sourceKind,
      sourceReference,
      filingKind,
      scopedFields: Object.fromEntries(refs(scopeFields).map((item) => {
        const [key, ...rest] = item.split("=");
        return [key, rest.join("=") || true];
      })),
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
      await queryClient.invalidateQueries({ queryKey: ["ip-foreign-associates"] });
      onCreated(row);
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not create the instruction.")),
  });

  return (
    <Card>
      <CardHeader><CardTitle as="h2">New foreign-associate instruction</CardTitle></CardHeader>
      <CardContent>
        <form className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-4" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
          <Field label="IP record" wide>
            <select aria-label="IP record" className={SELECT_CLASS} value={docketId} onChange={(event) => setDocketId(event.target.value)} required>
              <option value="">Select record</option>
              {dockets.data?.dockets.map((row) => <option key={row.id} value={row.id}>{row.title} · {row.primary_identifier ?? row.record_type}</option>)}
            </select>
          </Field>
          <Field label="Thread key"><Input value={threadKey} onChange={(event) => setThreadKey(event.target.value)} required /></Field>
          <Field label="Target jurisdiction"><Input value={jurisdiction} onChange={(event) => { setJurisdiction(event.target.value); setCounselId(""); setAssignmentId(""); }} required /></Field>
          <Field label="Approved associate">
            <select aria-label="Approved associate" className={SELECT_CLASS} value={counselId} onChange={(event) => { setCounselId(event.target.value); setAssignmentId(""); }} required>
              <option value="">Select associate</option>
              {profiles.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
            </select>
          </Field>
          <Field label="Approved Matter assignment">
            <select aria-label="Approved Matter assignment" className={SELECT_CLASS} value={assignmentId} onChange={(event) => setAssignmentId(event.target.value)} required={Boolean(docket.data?.matter_id)} disabled={!docket.data?.matter_id}>
              <option value="">{docket.data?.matter_id ? "Select assignment" : "Matterless record"}</option>
              {assignments.map((row) => <option key={row.id} value={row.id}>{row.role_summary ?? row.counsel_name} · {row.budget_amount_minor === null ? "No ceiling" : money(row.budget_amount_minor, row.currency)}</option>)}
            </select>
          </Field>
          <Field label="Accepted client instruction">
            <select aria-label="Accepted client instruction" className={SELECT_CLASS} value={clientInstructionId} onChange={(event) => { setClientInstructionId(event.target.value); if (event.target.value) setAuthority(""); }}>
              <option value="">External authority evidence</option>
              {acceptedInstructions.map((row) => <option key={row.id} value={row.id}>{row.submitted_by} · v{row.instruction_version}</option>)}
            </select>
          </Field>
          <Field label="External authority evidence"><Input value={authority} onChange={(event) => setAuthority(event.target.value)} disabled={Boolean(clientInstructionId)} required={!clientInstructionId} /></Field>
          <Field label="Source kind"><select aria-label="Source kind" className={SELECT_CLASS} value={sourceKind} onChange={(event) => setSourceKind(event.target.value as "application" | "search")}><option value="application">Application</option><option value="search">Search</option></select></Field>
          <Field label="Source reference"><Input value={sourceReference} onChange={(event) => setSourceReference(event.target.value)} required /></Field>
          <Field label="Filing kind"><Input value={filingKind} onChange={(event) => setFilingKind(event.target.value)} required /></Field>
          <Field label="Scoped fields"><Input value={scopeFields} onChange={(event) => setScopeFields(event.target.value)} /></Field>
          <Field label="Estimate">
            <select aria-label="Estimate" className={SELECT_CLASS} value={estimateId} onChange={(event) => setEstimateId(event.target.value)} required>
              <option value="">Select estimate</option>
              {estimates.map((row) => <option key={row.id} value={row.id}>{row.description} · {money(row.amount_minor, row.currency)}</option>)}
            </select>
          </Field>
          <Field label="Tax type"><Input value={taxType} onChange={(event) => setTaxType(event.target.value)} /></Field>
          <Field label="Tax rate percent"><Input type="number" min="0" max="100" step="0.01" value={taxRate} onChange={(event) => setTaxRate(event.target.value)} /></Field>
          <Field label="Tax evidence"><Input value={taxEvidence} onChange={(event) => setTaxEvidence(event.target.value)} required={Boolean(taxType || taxRate)} /></Field>
          <Field label="Budget policy"><Input value={budgetPolicy} onChange={(event) => setBudgetPolicy(event.target.value)} required /></Field>
          <Field label="Response due"><Input type="datetime-local" value={responseDue} onChange={(event) => setResponseDue(event.target.value)} required /></Field>
          <Field label="Estimate assumptions" wide><Textarea value={assumptions} onChange={(event) => setAssumptions(event.target.value)} rows={2} /></Field>
          <Field label="Documents" wide>
            <div className="grid min-w-0 gap-2 sm:grid-cols-2">
              {documents.data?.items.map((row) => (
                <label key={row.id} className="flex min-w-0 items-start gap-2 rounded-md border border-[var(--color-line)] p-2 text-sm">
                  <input type="checkbox" checked={documentIds.includes(row.id)} onChange={(event) => setDocumentIds((current) => event.target.checked ? [...current, row.id] : current.filter((id) => id !== row.id))} />
                  <span className="min-w-0 break-words">{row.title}{row.is_privileged ? " · privileged" : ""}</span>
                </label>
              ))}
            </div>
          </Field>
          <Field label="Privilege approval" wide>
            <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={includePrivileged} onChange={(event) => setIncludePrivileged(event.target.checked)} disabled={!canApprove} />Explicitly include selected privileged/internal documents</label>
          </Field>
          <Field label="Reason" wide><Textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={3} required /></Field>
          <div className="flex min-w-0 md:col-span-2 xl:col-span-4">
            <Button className="w-full sm:w-auto" type="submit" disabled={create.isPending || !docket.data || !documentIds.length || !session.context?.membership.id}>
              {create.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}Create instruction
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function InstructionWorkspace({ instructionId, canWrite, canApprove }: { instructionId: string; canWrite: boolean; canApprove: boolean }) {
  const workspace = useQuery({ queryKey: ["ip-foreign-associate-workspace", instructionId], queryFn: () => fetchIpForeignAssociateWorkspace(instructionId) });
  const docket = useQuery({ queryKey: ["ip-docket", workspace.data?.instruction.docket_id], queryFn: () => fetchIpDocket(workspace.data!.instruction.docket_id), enabled: Boolean(workspace.data?.instruction.docket_id) });
  const documents = useQuery({ queryKey: ["ip-documents", workspace.data?.instruction.docket_id], queryFn: () => fetchIpDocumentsForDocket(workspace.data!.instruction.docket_id), enabled: Boolean(workspace.data?.instruction.docket_id) });
  const counsel = useQuery({ queryKey: ["outside-counsel-workspace"], queryFn: fetchOutsideCounselWorkspace });
  const deadlines = useQuery({ queryKey: ["ip-deadlines", workspace.data?.instruction.docket_id], queryFn: () => fetchIpDeadlineWorkspace(workspace.data!.instruction.docket_id), enabled: Boolean(workspace.data?.instruction.docket_id) });
  const communications = useQuery({ queryKey: ["matter-communications", docket.data?.matter_id], queryFn: () => fetchMatterCommunications(docket.data!.matter_id!), enabled: Boolean(docket.data?.matter_id) });

  if (workspace.isLoading) return <Skeleton className="h-[32rem]" />;
  if (workspace.isError) return <QueryErrorState error={workspace.error} onRetry={() => void workspace.refetch()} />;
  if (!workspace.data || !docket.data) return <EmptyState title="Instruction unavailable" description="" />;
  const selectedDocuments = documents.data?.items.filter((row) => workspace.data.instruction.selected_document_refs_json.includes(row.id)) ?? [];
  return (
    <div className="min-w-0 space-y-4">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="break-words text-xl font-semibold">{workspace.data.associate_name}</h2>
          <p className="break-words text-sm text-[var(--color-mute)]">{docket.data.title} · {workspace.data.instruction.target_jurisdiction} · v{workspace.data.instruction.instruction_version}</p>
        </div>
        <Status value={workspace.data.instruction.status} />
      </div>
      <Tabs defaultValue="instruction" className="min-w-0">
        <TabsList className="grid h-auto w-full min-w-0 grid-cols-2 gap-1 sm:grid-cols-4">
          <TabsTrigger value="instruction">Instruction</TabsTrigger>
          <TabsTrigger value="actions">Actions</TabsTrigger>
          <TabsTrigger value="reminders">Reminders</TabsTrigger>
          <TabsTrigger value="history">History</TabsTrigger>
        </TabsList>
        <TabsContent value="instruction"><InstructionSummary workspace={workspace.data} docket={docket.data} documents={selectedDocuments} /></TabsContent>
        <TabsContent value="actions"><TransactionForm workspace={workspace.data} docket={docket.data} documents={documents.data?.items ?? []} deadlines={deadlines.data?.deadlines ?? []} counsel={counsel.data} communications={communications.data?.communications ?? []} canWrite={canWrite} canApprove={canApprove} /></TabsContent>
        <TabsContent value="reminders"><ReminderPanel workspace={workspace.data} docket={docket.data} canWrite={canWrite} /></TabsContent>
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
        <Datum label="Authority" value={row.source_client_instruction_id ? `Client instruction ${row.source_client_instruction_id}` : row.client_authority_reference ?? "Not recorded"} />
        <Datum label="Estimate" value={docket.cost_items.find((cost) => cost.id === row.estimate_cost_item_id)?.description ?? row.estimate_cost_item_id} />
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
  communications,
  canWrite,
  canApprove,
}: {
  workspace: IpForeignAssociateWorkspace;
  docket: IpDocket;
  documents: IpDocument[];
  deadlines: Array<{ id: string; title: string }>;
  counsel: CounselWorkspace | undefined;
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
  const estimates = docket.cost_items.filter((row) => row.cost_nature === "estimate" && row.id !== workspace.instruction.estimate_cost_item_id);
  const actuals = docket.cost_items.filter((row) => row.cost_nature === "actual");
  const profiles = counsel?.profiles.filter((row) => ["active", "preferred"].includes(row.panel_status) && row.jurisdictions.some((value) => value.toLowerCase() === workspace.instruction.target_jurisdiction.toLowerCase())) ?? [];
  const assignments = counsel?.assignments.filter((row) => row.matter_id === docket.matter_id && row.counsel_id === replacementCounselId && ["approved", "active"].includes(row.status)) ?? [];
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
      replacementAssignmentId: kind === "reassign" ? replacementAssignmentId : null,
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
  return <Card><CardHeader><CardTitle as="h3">Record transaction</CardTitle></CardHeader><CardContent><form className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-4" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
    <Field label="Transaction"><select aria-label="Transaction" className={SELECT_CLASS} value={kind} onChange={(event) => setKind(event.target.value as IpForeignAssociateTransactionKind)}>{options.map((value) => <option key={value} value={value}>{readable(value)}</option>)}</select></Field>
    {kind === "dispatch" ? <><Field label="Approved Communication"><select aria-label="Approved Communication" className={SELECT_CLASS} value={communicationId} onChange={(event) => { setCommunicationId(event.target.value); if (event.target.value) { setExternalDispatch(""); setExternalDelivery(""); } }}><option value="">External dispatch evidence</option>{dispatches.map((row) => <option key={row.id} value={row.id}>{row.subject ?? row.channel} · {row.status}</option>)}</select></Field><Field label="External dispatch evidence"><Input value={externalDispatch} onChange={(event) => setExternalDispatch(event.target.value)} disabled={Boolean(communicationId)} required={!communicationId} /></Field><Field label="External delivery evidence"><Input value={externalDelivery} onChange={(event) => setExternalDelivery(event.target.value)} disabled={Boolean(communicationId)} /></Field></> : null}
    {kind === "acknowledge" ? <Field label="Acknowledgement evidence"><Input value={acknowledgement} onChange={(event) => setAcknowledgement(event.target.value)} required /></Field> : null}
    {kind === "report_filing" ? <Field label="Foreign filing identifier"><Input value={filingIdentifier} onChange={(event) => setFilingIdentifier(event.target.value)} required /></Field> : null}
    {["approve_fee_change", "reassign"].includes(kind) ? <><Field label="Replacement estimate"><select aria-label="Replacement estimate" className={SELECT_CLASS} value={replacementEstimateId} onChange={(event) => setReplacementEstimateId(event.target.value)} required><option value="">Select estimate</option>{estimates.map((row) => <option key={row.id} value={row.id}>{row.description} · {money(row.amount_minor, row.currency)}</option>)}</select></Field><Field label="Tax type"><Input value={taxType} onChange={(event) => setTaxType(event.target.value)} /></Field><Field label="Tax rate percent"><Input type="number" min="0" max="100" step="0.01" value={taxRate} onChange={(event) => setTaxRate(event.target.value)} /></Field><Field label="Tax evidence"><Input value={taxEvidence} onChange={(event) => setTaxEvidence(event.target.value)} required={Boolean(taxType || taxRate)} /></Field><Field label="Changed assumptions"><Input value={assumptions} onChange={(event) => setAssumptions(event.target.value)} /></Field></> : null}
    {kind === "link_invoice" ? <><Field label="Actual filing cost"><select aria-label="Actual filing cost" className={SELECT_CLASS} value={actualCostId} onChange={(event) => setActualCostId(event.target.value)} required><option value="">Select cost</option>{actuals.map((row) => <option key={row.id} value={row.id}>{row.description} · {money(row.amount_minor, row.currency)}</option>)}</select></Field><Field label="Associate invoice"><select aria-label="Associate invoice" className={SELECT_CLASS} value={spendId} onChange={(event) => setSpendId(event.target.value)} required><option value="">Select invoice</option>{spends.map((row) => <option key={row.id} value={row.id}>{row.invoice_reference ?? row.description} · {row.status}</option>)}</select></Field></> : null}
    {kind === "reassign" ? <><Field label="Replacement associate"><select aria-label="Replacement associate" className={SELECT_CLASS} value={replacementCounselId} onChange={(event) => { setReplacementCounselId(event.target.value); setReplacementAssignmentId(""); }} required><option value="">Select associate</option>{profiles.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></Field><Field label="Replacement assignment"><select aria-label="Replacement assignment" className={SELECT_CLASS} value={replacementAssignmentId} onChange={(event) => setReplacementAssignmentId(event.target.value)} required={Boolean(docket.matter_id)}><option value="">Select assignment</option>{assignments.map((row) => <option key={row.id} value={row.id}>{row.role_summary ?? row.counsel_name} · {row.budget_amount_minor === null ? "No ceiling" : money(row.budget_amount_minor, row.currency)}</option>)}</select></Field><Field label="Replacement response due"><Input type="datetime-local" value={replacementDue} onChange={(event) => setReplacementDue(event.target.value)} /></Field></> : null}
    {!["approve", "dispatch", "acknowledge", "cancel", "complete"].includes(kind) ? <Field label="Correspondence/source evidence" wide><Textarea value={evidence} onChange={(event) => setEvidence(event.target.value)} rows={2} required={["record_query", "approve_substantive_response", "approve_fee_change", "report_filing", "verify_filing_evidence", "refuse", "reassign"].includes(kind)} /></Field> : null}
    {["report_filing", "verify_filing_evidence", "record_query", "approve_substantive_response"].includes(kind) ? <Field label="Linked document"><select aria-label="Linked document" className={SELECT_CLASS} value={documentId} onChange={(event) => setDocumentId(event.target.value)} required={kind === "report_filing"}><option value="">No document</option>{documents.map((row) => <option key={row.id} value={row.id}>{row.title}</option>)}</select></Field> : null}
    <Field label="Linked deadline"><select aria-label="Linked deadline" className={SELECT_CLASS} value={deadlineId} onChange={(event) => setDeadlineId(event.target.value)}><option value="">No deadline</option>{deadlines.map((row) => <option key={row.id} value={row.id}>{row.title}</option>)}</select></Field>
    <Field label="Reason" wide><Textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={3} required /></Field>
    <div className="flex min-w-0 md:col-span-2 xl:col-span-4"><Button className="w-full sm:w-auto" type="submit" disabled={mutation.isPending || (!canWrite && !canApprove) || (needsApproval && !canApprove) || !session.context?.membership.id}>{mutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : kind === "dispatch" ? <Send className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}Record {readable(kind)}</Button></div>
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
