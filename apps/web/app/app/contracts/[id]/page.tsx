"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  FileText,
  Gavel,
  Link2,
  Loader2,
  Scale,
  Save,
  Sparkles,
  Upload,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  CONTRACT_ATTACHMENT_ROLE_OPTIONS,
  CONTRACT_TYPE_OPTIONS,
  acceptContractTermSuggestion,
  comparePlaybook,
  createContractLegalReference,
  extractContractClauses,
  extractContractClausesByParty,
  extractContractObligations,
  fetchContractAttachmentRedline,
  fetchContractWorkspace,
  installDefaultPlaybook,
  rejectContractTermSuggestion,
  type ContractRedlineChange,
  type PartyClauseAmbiguousItem,
  type PartyClauseExtractionResult,
  type PartyClauseItem,
  type PlaybookFinding,
  updateContractAttachmentMetadata,
  updateContractLegalReference,
  updateContractMetadata,
  uploadContractAttachment,
} from "@/lib/api/endpoints";
import type {
  ContractAttachmentRole,
  ContractLegalReferenceRecord,
  ContractTermSuggestionRecord,
  ContractTypeKey,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

type Workspace = {
  contract: {
    id: string;
    contract_code: string;
    title: string;
    contract_type: string;
    contract_type_key: ContractTypeKey | null;
    contract_type_notes: string | null;
    counterparty_name: string | null;
    status: string;
    effective_on: string | null;
    expires_on: string | null;
    renewal_on: string | null;
    auto_renewal: boolean;
    jurisdiction: string | null;
    summary: string | null;
  };
  attachments: Array<{
    id: string;
    original_filename: string;
    content_type: string | null;
    size_bytes: number;
    processing_status: string;
    attachment_role: ContractAttachmentRole | null;
    parent_attachment_id: string | null;
    document_date: string | null;
    notes: string | null;
    created_at: string;
  }>;
  clauses: Array<{
    id: string;
    title: string;
    clause_type: string;
    clause_text: string;
    risk_level: string;
    notes: string | null;
    created_at: string;
  }>;
  obligations: Array<{
    id: string;
    title: string;
    description: string | null;
    due_on: string | null;
    status: string;
    priority: string;
    created_at: string;
  }>;
  playbook_rules: Array<{
    id: string;
    rule_name: string;
    clause_type: string;
    expected_position: string;
    severity: string;
  }>;
  legal_references: ContractLegalReferenceRecord[];
  term_suggestions: ContractTermSuggestionRecord[];
};

type WorkspaceAttachment = Workspace["attachments"][number];

export default function ContractDetailPage() {
  const params = useParams<{ id: string }>();
  const contractId = params.id;
  const queryClient = useQueryClient();
  const canEdit = useCapability("contracts:edit");
  const canManageRules = useCapability("contracts:manage_rules");
  const canUpload = useCapability("documents:upload");
  const canGenerateAI = useCapability("ai:generate");
  const fileInput = useRef<HTMLInputElement | null>(null);
  const [playbookFindings, setPlaybookFindings] = useState<PlaybookFinding[] | null>(
    null,
  );
  const [redlineAttachmentId, setRedlineAttachmentId] = useState<string | null>(null);
  const [contractTypeKey, setContractTypeKey] =
    useState<ContractTypeKey>("agreement");
  const [contractTypeNotes, setContractTypeNotes] = useState("");
  const [legalReferenceDraft, setLegalReferenceDraft] = useState({
    act_name: "",
    section_label: "",
    clause_label: "",
    evidence_attachment_id: "__none",
    evidence_quote: "",
  });
  // ADP-13: party-perspective clause extraction (stateless per-call;
  // the result is held in component state so the user can flip
  // perspective without re-uploading).
  const [partyDraft, setPartyDraft] = useState({
    first: "",
    second: "",
    firstAliases: "",
    secondAliases: "",
    represented: "first" as "first" | "second",
  });
  const [partyResult, setPartyResult] = useState<PartyClauseExtractionResult | null>(
    null,
  );

  const workspaceQuery = useQuery({
    queryKey: ["contracts", contractId, "workspace"],
    queryFn: async () => (await fetchContractWorkspace(contractId)) as Workspace,
  });

  const invalidateWorkspace = () =>
    queryClient.invalidateQueries({ queryKey: ["contracts", contractId, "workspace"] });

  const metadataMutation = useMutation({
    mutationFn: () => {
      const selectedType = CONTRACT_TYPE_OPTIONS.find(
        (option) => option.value === contractTypeKey,
      );
      const notes = contractTypeNotes.trim() || null;
      return updateContractMetadata({
        contractId,
        contract_type:
          contractTypeKey === "other" && notes
            ? notes
            : selectedType?.label ?? "Agreement",
        contract_type_key: contractTypeKey,
        contract_type_notes: notes,
      });
    },
    onSuccess: async () => {
      await invalidateWorkspace();
      toast.success("Contract metadata saved.");
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not save contract metadata.")),
  });

  const createLegalReferenceMutation = useMutation({
    mutationFn: () =>
      createContractLegalReference({
        contractId,
        act_name: legalReferenceDraft.act_name.trim(),
        section_label: legalReferenceDraft.section_label.trim() || null,
        clause_label: legalReferenceDraft.clause_label.trim() || null,
        evidence_attachment_id:
          legalReferenceDraft.evidence_attachment_id === "__none"
            ? null
            : legalReferenceDraft.evidence_attachment_id,
        evidence_quote: legalReferenceDraft.evidence_quote.trim() || null,
        source: "manual",
        status: "accepted",
      }),
    onSuccess: async () => {
      await invalidateWorkspace();
      setLegalReferenceDraft({
        act_name: "",
        section_label: "",
        clause_label: "",
        evidence_attachment_id: "__none",
        evidence_quote: "",
      });
      toast.success("Legal reference saved.");
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not save legal reference.")),
  });

  const updateLegalReferenceMutation = useMutation({
    mutationFn: (input: { referenceId: string; status: "accepted" | "rejected" }) =>
      updateContractLegalReference({
        contractId,
        referenceId: input.referenceId,
        status: input.status,
      }),
    onSuccess: async () => {
      await invalidateWorkspace();
      toast.success("Legal reference review saved.");
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not review legal reference.")),
  });

  const acceptTermSuggestionMutation = useMutation({
    mutationFn: (suggestionId: string) =>
      acceptContractTermSuggestion({ contractId, suggestionId }),
    onSuccess: async () => {
      await invalidateWorkspace();
      toast.success("Term suggestion accepted.");
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not accept term suggestion.")),
  });

  const rejectTermSuggestionMutation = useMutation({
    mutationFn: (suggestionId: string) =>
      rejectContractTermSuggestion({ contractId, suggestionId }),
    onSuccess: async () => {
      await invalidateWorkspace();
      toast.success("Term suggestion rejected.");
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not reject term suggestion.")),
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadContractAttachment({ contractId, file }),
    onSuccess: async () => {
      await invalidateWorkspace();
      toast.success("Document uploaded — processing will begin shortly.");
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not upload the file.")),
    onSettled: () => {
      if (fileInput.current) fileInput.current.value = "";
    },
  });

  const extractClauses = useMutation({
    mutationFn: () => extractContractClauses({ contractId }),
    onSuccess: async (summary) => {
      await invalidateWorkspace();
      toast.success(
        `Extracted ${summary.inserted} clause${summary.inserted === 1 ? "" : "s"} via ${summary.model}.`,
      );
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not extract clauses.")),
  });

  const splitAliases = (raw: string): string[] =>
    raw
      .split(/[,\n]/)
      .map((part) => part.trim())
      .filter((part) => part.length > 0);

  const extractPartyClauses = useMutation({
    mutationFn: () =>
      extractContractClausesByParty({
        contractId,
        firstPartyName: partyDraft.first.trim(),
        secondPartyName: partyDraft.second.trim(),
        firstPartyAliases: splitAliases(partyDraft.firstAliases),
        secondPartyAliases: splitAliases(partyDraft.secondAliases),
        representedParty: partyDraft.represented,
      }),
    onSuccess: (result) => {
      setPartyResult(result);
      const total =
        result.represented_items.length +
        result.counterparty_items.length +
        result.ambiguous_items.length;
      const dropped = result.dropped_source_unverified_count;
      toast.success(
        `Extracted ${total} party-perspective item${total === 1 ? "" : "s"}` +
          (dropped > 0
            ? ` (${dropped} dropped — no verifiable source).`
            : "."),
      );
    },
    onError: (err) =>
      toast.error(
        apiErrorMessage(err, "Could not extract party-perspective clauses."),
      ),
  });

  const extractObligations = useMutation({
    mutationFn: () => extractContractObligations({ contractId }),
    onSuccess: async (summary) => {
      await invalidateWorkspace();
      toast.success(
        `Extracted ${summary.inserted} obligation${summary.inserted === 1 ? "" : "s"}.`,
      );
    },
    onError: (err) =>
      toast.error(
        apiErrorMessage(err, "Could not extract obligations."),
      ),
  });

  const installPlaybook = useMutation({
    mutationFn: () => installDefaultPlaybook({ contractId }),
    onSuccess: async (result) => {
      await invalidateWorkspace();
      toast.success(`Installed ${result.installed} default playbook rules.`);
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not install playbook.")),
  });

  const runPlaybookCompare = useMutation({
    mutationFn: () => comparePlaybook({ contractId }),
    onSuccess: (result) => {
      setPlaybookFindings(result.findings);
      toast.success(`Playbook comparison done (${result.findings.length} findings).`);
    },
    onError: (err) =>
      toast.error(
        apiErrorMessage(err, "Could not run the playbook comparison."),
      ),
  });

  const redlineQuery = useQuery({
    queryKey: ["contracts", contractId, "redline", redlineAttachmentId],
    queryFn: async () => {
      if (!redlineAttachmentId) return null;
      return fetchContractAttachmentRedline({
        contractId,
        attachmentId: redlineAttachmentId,
      });
    },
    enabled: Boolean(redlineAttachmentId),
  });

  useEffect(() => {
    const contract = workspaceQuery.data?.contract;
    if (!contract) return;
    setContractTypeKey(contract.contract_type_key ?? "other");
    setContractTypeNotes(
      contract.contract_type_notes ??
        (contract.contract_type_key ? "" : contract.contract_type),
    );
  }, [
    workspaceQuery.data?.contract?.contract_type,
    workspaceQuery.data?.contract?.contract_type_key,
    workspaceQuery.data?.contract?.contract_type_notes,
  ]);

  if (workspaceQuery.isPending) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }
  if (workspaceQuery.isError) {
    return (
      <QueryErrorState
        title="Could not load this contract"
        error={workspaceQuery.error}
        onRetry={workspaceQuery.refetch}
      />
    );
  }
  const workspace = workspaceQuery.data;
  if (!workspace) return null;
  const {
    contract,
    attachments,
    clauses,
    obligations,
    playbook_rules,
    legal_references = [],
    term_suggestions = [],
  } = workspace;
  const attachmentGroups = groupAttachmentsByRole(attachments);

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0];
    if (selected) uploadMutation.mutate(selected);
  };

  return (
    <div className="flex flex-col gap-5">
      <Link
        href="/app/contracts"
        className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-mute)] hover:text-[var(--color-ink)]"
      >
        ← Back to contracts
      </Link>

      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-xs uppercase tracking-[0.08em] text-[var(--color-mute)]">
                {contract.contract_code} · {contract.contract_type}
              </div>
              <CardTitle as="h1" className="text-lg">
                {contract.title}
              </CardTitle>
              <CardDescription>
                {contract.counterparty_name
                  ? `with ${contract.counterparty_name}`
                  : "No counterparty recorded"}
                {contract.effective_on
                  ? ` · effective ${contract.effective_on}`
                  : ""}
                {contract.expires_on ? ` · expires ${contract.expires_on}` : ""}
              </CardDescription>
            </div>
            <StatusBadge status={contract.status} />
          </div>
        </CardHeader>
        {contract.summary ? (
          <CardContent>
            <p className="text-sm leading-relaxed text-[var(--color-ink-2)]">
              {contract.summary}
            </p>
          </CardContent>
        ) : null}
      </Card>

      <Tabs defaultValue="overview" className="w-full">
        <TabsList className="flex flex-wrap gap-1">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="attachments">
            Attachments ({attachments.length})
          </TabsTrigger>
          <TabsTrigger value="clauses">Clauses ({clauses.length})</TabsTrigger>
          <TabsTrigger value="obligations">
            Obligations ({obligations.length})
          </TabsTrigger>
          <TabsTrigger value="terms">
            Terms ({term_suggestions.length})
          </TabsTrigger>
          <TabsTrigger value="legal">
            Legal refs ({legal_references.length})
          </TabsTrigger>
          <TabsTrigger value="playbook">
            Playbook ({playbook_rules.length})
          </TabsTrigger>
          <TabsTrigger value="redline">Redline</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <Card>
            <CardContent className="grid gap-4 py-6 lg:grid-cols-[1.1fr_0.9fr]">
              <section className="rounded-lg border border-[var(--color-line)] bg-white p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 className="text-sm font-semibold text-[var(--color-ink)]">
                      Contract metadata
                    </h2>
                    <p className="mt-1 text-xs text-[var(--color-mute)]">
                      Controlled type is stored beside the legacy label.
                    </p>
                  </div>
                  {contract.contract_type_key ? (
                    <StatusBadge status={contract.contract_type_key} />
                  ) : (
                    <StatusBadge status="legacy" />
                  )}
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="contract-type-key">Controlled type</Label>
                    <Select
                      value={contractTypeKey}
                      disabled={!canEdit}
                      onValueChange={(value) =>
                        setContractTypeKey(value as ContractTypeKey)
                      }
                    >
                      <SelectTrigger id="contract-type-key">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {CONTRACT_TYPE_OPTIONS.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="contract-type-notes">Legacy / other label</Label>
                    <Input
                      id="contract-type-notes"
                      value={contractTypeNotes}
                      disabled={!canEdit}
                      onChange={(event) => setContractTypeNotes(event.target.value)}
                      placeholder={contract.contract_type}
                    />
                  </div>
                </div>
                {canEdit ? (
                  <Button
                    size="sm"
                    className="mt-3"
                    disabled={metadataMutation.isPending}
                    onClick={() => metadataMutation.mutate()}
                    data-testid="contract-save-metadata"
                  >
                    {metadataMutation.isPending ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Saving
                      </>
                    ) : (
                      <>
                        <Save className="h-4 w-4" aria-hidden /> Save metadata
                      </>
                    )}
                  </Button>
                ) : null}
              </section>

              <section className="rounded-lg border border-[var(--color-line)] bg-white p-4">
                <h2 className="text-sm font-semibold text-[var(--color-ink)]">
                  Canonical terms
                </h2>
                <dl className="mt-3 grid grid-cols-2 gap-3 text-sm">
                  <TermStat label="Effective" value={contract.effective_on} />
                  <TermStat label="Expiry" value={contract.expires_on} />
                  <TermStat label="Renewal" value={contract.renewal_on} />
                  <TermStat
                    label="Auto-renewal"
                    value={contract.auto_renewal ? "Yes" : "No"}
                  />
                </dl>
                <p className="mt-3 text-xs leading-relaxed text-[var(--color-mute)]">
                  Suggested dates stay outside canonical fields until a reviewer
                  accepts them in the Terms tab.
                </p>
              </section>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="attachments">
          <Card>
            <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
              <div>
                <CardTitle>Attachments</CardTitle>
                <CardDescription>
                  Contract PDFs, DOCX redlines, and addenda.
                </CardDescription>
              </div>
              {canUpload ? (
                <div>
                  <input
                    ref={fileInput}
                    type="file"
                    className="sr-only"
                    data-testid="contract-attachment-input"
                    accept=".pdf,.doc,.docx,.txt,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
                    onChange={handleFileChange}
                  />
                  <Button
                    size="sm"
                    disabled={uploadMutation.isPending}
                    onClick={() => fileInput.current?.click()}
                    data-testid="contract-attachment-upload"
                  >
                    {uploadMutation.isPending ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />{" "}
                        Uploading…
                      </>
                    ) : (
                      <>
                        <Upload className="h-4 w-4" aria-hidden /> Upload
                      </>
                    )}
                  </Button>
                </div>
              ) : null}
            </CardHeader>
            <CardContent>
              {attachments.length === 0 ? (
                <EmptyState
                  icon={FileText}
                  title="No attachments yet"
                  description="Upload the contract PDF or DOCX to enable clause / obligation extraction and redline parsing."
                />
              ) : (
                <div className="flex flex-col gap-5">
                  {attachmentGroups.map((group) => (
                    <section
                      key={group.key}
                      aria-labelledby={`contract-attachment-group-${group.key}`}
                    >
                      <div className="flex items-center justify-between gap-3 border-b border-[var(--color-line-2)] pb-2">
                        <h3
                          id={`contract-attachment-group-${group.key}`}
                          className="text-sm font-semibold text-[var(--color-ink)]"
                        >
                          {group.label}
                        </h3>
                        <span className="text-xs tabular-nums text-[var(--color-mute)]">
                          {group.attachments.length}
                        </span>
                      </div>
                      <ul className="divide-y divide-[var(--color-line-2)]">
                  {group.attachments.map((a) => (
                    <li
                      key={a.id}
                      className="flex flex-col gap-3 py-3 lg:flex-row lg:items-start lg:justify-between"
                    >
                      <div className="flex items-center gap-2">
                        <FileText className="h-4 w-4 text-[var(--color-mute)]" aria-hidden />
                        <div>
                          <div className="text-sm font-medium text-[var(--color-ink)]">
                            {a.original_filename}
                          </div>
                          <div className="mt-0.5 text-xs font-medium text-[var(--color-ink-2)]">
                            {formatAttachmentRole(a.attachment_role ?? "unclassified")}
                            {a.parent_attachment_id
                              ? ` linked to ${attachmentName(attachments, a.parent_attachment_id)}`
                              : ""}
                          </div>
                          {a.notes ? (
                            <div className="mt-0.5 text-xs text-[var(--color-mute)]">
                              {a.notes}
                            </div>
                          ) : null}
                          <div className="text-xs text-[var(--color-mute)]">
                            {a.content_type ?? "—"} · {(a.size_bytes / 1024).toFixed(0)} KB
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <StatusBadge status={a.processing_status ?? "unknown"} />
                        {a.original_filename.toLowerCase().endsWith(".docx") ? (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setRedlineAttachmentId(a.id)}
                            data-testid={`contract-attachment-redline-${a.id}`}
                          >
                            View redline
                          </Button>
                        ) : null}
                      </div>
                      {canEdit ? (
                        <AttachmentMetadataEditor
                          contractId={contractId}
                          attachment={a}
                          attachments={attachments}
                          onSaved={invalidateWorkspace}
                        />
                      ) : null}
                    </li>
                  ))}
                      </ul>
                    </section>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="clauses">
          <Card>
            <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
              <div>
                <CardTitle>Clauses</CardTitle>
                <CardDescription>
                  Auto-extracted from the uploaded text.
                </CardDescription>
              </div>
              {canEdit ? (
                <Button
                  size="sm"
                  disabled={extractClauses.isPending || attachments.length === 0}
                  onClick={() => extractClauses.mutate()}
                  data-testid="contract-extract-clauses"
                >
                  {extractClauses.isPending ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Extracting…
                    </>
                  ) : (
                    <>
                      <Sparkles className="h-4 w-4" aria-hidden /> Extract clauses
                    </>
                  )}
                </Button>
              ) : null}
            </CardHeader>
            <CardContent>
              {clauses.length === 0 ? (
                <EmptyState
                  icon={Scale}
                  title="No clauses extracted yet"
                  description="Upload the contract and click ‘Extract clauses’ to auto-populate this tab."
                />
              ) : (
                <ul className="flex flex-col gap-3">
                  {clauses.map((c) => (
                    <li
                      key={c.id}
                      className="rounded-xl border border-[var(--color-line)] bg-white p-4"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]">
                            {c.clause_type.replace(/_/g, " ")}
                          </div>
                          <h3 className="mt-1 text-sm font-semibold text-[var(--color-ink)]">
                            {c.title}
                          </h3>
                        </div>
                        <RiskBadge level={c.risk_level} />
                      </div>
                      <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-[var(--color-ink-2)]">
                        {c.clause_text}
                      </p>
                      {c.notes ? (
                        <p className="mt-2 text-xs text-[var(--color-mute-2)]">
                          {c.notes}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
          <Card className="mt-4" data-testid="party-perspective-panel">
            <CardHeader>
              <CardTitle>Party-perspective extraction</CardTitle>
              <CardDescription>
                Set the parties (with aliases) and the perspective you
                represent. Items are source-validated against the uploaded
                contract; ambiguous party references are surfaced separately
                and never silently routed to your side.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="flex flex-col gap-1">
                  <label
                    className="text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]"
                    htmlFor="party-first-name"
                  >
                    First party
                  </label>
                  <Input
                    id="party-first-name"
                    data-testid="party-first-name"
                    value={partyDraft.first}
                    onChange={(event) =>
                      setPartyDraft((prev) => ({
                        ...prev,
                        first: event.target.value,
                      }))
                    }
                    placeholder="Acme India Private Limited"
                  />
                  <Textarea
                    data-testid="party-first-aliases"
                    rows={2}
                    value={partyDraft.firstAliases}
                    onChange={(event) =>
                      setPartyDraft((prev) => ({
                        ...prev,
                        firstAliases: event.target.value,
                      }))
                    }
                    placeholder="Aliases (comma-separated): Acme, Supplier"
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label
                    className="text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]"
                    htmlFor="party-second-name"
                  >
                    Second party
                  </label>
                  <Input
                    id="party-second-name"
                    data-testid="party-second-name"
                    value={partyDraft.second}
                    onChange={(event) =>
                      setPartyDraft((prev) => ({
                        ...prev,
                        second: event.target.value,
                      }))
                    }
                    placeholder="Beta Software Solutions Inc."
                  />
                  <Textarea
                    data-testid="party-second-aliases"
                    rows={2}
                    value={partyDraft.secondAliases}
                    onChange={(event) =>
                      setPartyDraft((prev) => ({
                        ...prev,
                        secondAliases: event.target.value,
                      }))
                    }
                    placeholder="Aliases (comma-separated): Beta, Customer"
                  />
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]">
                  Represented party
                </span>
                <label className="flex items-center gap-1 text-sm">
                  <input
                    type="radio"
                    name="party-represented"
                    value="first"
                    data-testid="party-represented-first"
                    checked={partyDraft.represented === "first"}
                    onChange={() =>
                      setPartyDraft((prev) => ({ ...prev, represented: "first" }))
                    }
                  />
                  First party
                </label>
                <label className="flex items-center gap-1 text-sm">
                  <input
                    type="radio"
                    name="party-represented"
                    value="second"
                    data-testid="party-represented-second"
                    checked={partyDraft.represented === "second"}
                    onChange={() =>
                      setPartyDraft((prev) => ({ ...prev, represented: "second" }))
                    }
                  />
                  Second party
                </label>
                {canGenerateAI ? (
                  <Button
                    size="sm"
                    data-testid="party-extract-button"
                    className="ml-auto"
                    disabled={
                      extractPartyClauses.isPending ||
                      attachments.length === 0 ||
                      partyDraft.first.trim().length < 2 ||
                      partyDraft.second.trim().length < 2
                    }
                    onClick={() => extractPartyClauses.mutate()}
                  >
                    {extractPartyClauses.isPending ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />{" "}
                        Extracting…
                      </>
                    ) : (
                      <>
                        <Sparkles className="h-4 w-4" aria-hidden /> Extract by party
                      </>
                    )}
                  </Button>
                ) : null}
              </div>
              {partyResult ? (
                <PartyExtractionResultPanel result={partyResult} />
              ) : null}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="obligations">
          <Card>
            <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
              <div>
                <CardTitle>Obligations</CardTitle>
                <CardDescription>
                  Time-bound duties — payments, notices, renewal dates.
                </CardDescription>
              </div>
              {canEdit ? (
                <Button
                  size="sm"
                  disabled={extractObligations.isPending || attachments.length === 0}
                  onClick={() => extractObligations.mutate()}
                  data-testid="contract-extract-obligations"
                >
                  {extractObligations.isPending ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Extracting…
                    </>
                  ) : (
                    <>
                      <Clock className="h-4 w-4" aria-hidden /> Extract obligations
                    </>
                  )}
                </Button>
              ) : null}
            </CardHeader>
            <CardContent>
              {obligations.length === 0 ? (
                <EmptyState
                  icon={Clock}
                  title="No obligations extracted yet"
                  description="After uploading the contract, ‘Extract obligations’ pulls payment milestones, notice periods, and renewal deadlines."
                />
              ) : (
                <ul className="flex flex-col gap-2">
                  {obligations.map((o) => (
                    <li
                      key={o.id}
                      className="rounded-lg border border-[var(--color-line)] bg-white p-3"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold text-[var(--color-ink)]">
                            {o.title}
                          </div>
                          {o.description ? (
                            <div className="mt-1 text-xs text-[var(--color-ink-2)]">
                              {o.description}
                            </div>
                          ) : null}
                        </div>
                        <div className="text-right text-xs text-[var(--color-mute)]">
                          <div>Due: {o.due_on ?? "—"}</div>
                          <div className="capitalize">{o.priority}</div>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="terms">
          <Card>
            <CardHeader>
              <CardTitle>Term suggestions</CardTitle>
              <CardDescription>
                Suggested dates are reviewable and do not become canonical until accepted.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {term_suggestions.length === 0 ? (
                <EmptyState
                  icon={Clock}
                  title="No term suggestions"
                  description="AI or manual extraction can add suggested effective, expiry, renewal, and duration values for review."
                />
              ) : (
                <ul className="flex flex-col gap-2">
                  {term_suggestions.map((suggestion) => (
                    <li
                      key={suggestion.id}
                      className="rounded-lg border border-[var(--color-line)] bg-white p-3"
                    >
                      <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-start">
                        <div>
                          <div className="flex flex-wrap items-center gap-2">
                            <StatusBadge status={suggestion.status} />
                            {suggestion.source_attachment_name ? (
                              <span className="text-xs text-[var(--color-mute)]">
                                Source: {suggestion.source_attachment_name}
                              </span>
                            ) : null}
                          </div>
                          <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-4">
                            <TermStat label="Effective" value={suggestion.suggested_effective_on} />
                            <TermStat label="Expiry" value={suggestion.suggested_expires_on} />
                            <TermStat label="Renewal" value={suggestion.suggested_renewal_on} />
                            <TermStat
                              label="Duration"
                              value={
                                suggestion.suggested_duration_months === null
                                  ? null
                                  : `${suggestion.suggested_duration_months} months`
                              }
                            />
                          </dl>
                          {suggestion.evidence_json?.quote ? (
                            <p className="mt-2 text-xs leading-relaxed text-[var(--color-ink-2)]">
                              {String(suggestion.evidence_json.quote)}
                            </p>
                          ) : null}
                        </div>
                        {canEdit && suggestion.status === "suggested" ? (
                          <div className="flex flex-wrap gap-2">
                            <Button
                              size="sm"
                              onClick={() => acceptTermSuggestionMutation.mutate(suggestion.id)}
                              data-testid={`accept-term-suggestion-${suggestion.id}`}
                            >
                              Accept
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => rejectTermSuggestionMutation.mutate(suggestion.id)}
                            >
                              Reject
                            </Button>
                          </div>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="legal">
          <Card>
            <CardHeader>
              <CardTitle>Legal references</CardTitle>
              <CardDescription>
                Acts, sections, clauses, and source evidence for contract classification.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-5">
              {canEdit ? (
                <div className="grid gap-3 rounded-lg border border-[var(--color-line)] bg-white p-3 lg:grid-cols-[1fr_0.7fr_0.7fr]">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="legal-act-name">Act</Label>
                    <Input
                      id="legal-act-name"
                      value={legalReferenceDraft.act_name}
                      onChange={(event) =>
                        setLegalReferenceDraft((draft) => ({
                          ...draft,
                          act_name: event.target.value,
                        }))
                      }
                      placeholder="Indian Contract Act, 1872"
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="legal-section">Section</Label>
                    <Input
                      id="legal-section"
                      value={legalReferenceDraft.section_label}
                      onChange={(event) =>
                        setLegalReferenceDraft((draft) => ({
                          ...draft,
                          section_label: event.target.value,
                        }))
                      }
                      placeholder="Section 73"
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="legal-clause">Clause</Label>
                    <Input
                      id="legal-clause"
                      value={legalReferenceDraft.clause_label}
                      onChange={(event) =>
                        setLegalReferenceDraft((draft) => ({
                          ...draft,
                          clause_label: event.target.value,
                        }))
                      }
                      placeholder="Limitation of liability"
                    />
                  </div>
                  <div className="flex flex-col gap-1.5 lg:col-span-2">
                    <Label htmlFor="legal-evidence">Evidence quote</Label>
                    <Textarea
                      id="legal-evidence"
                      rows={2}
                      value={legalReferenceDraft.evidence_quote}
                      onChange={(event) =>
                        setLegalReferenceDraft((draft) => ({
                          ...draft,
                          evidence_quote: event.target.value,
                        }))
                      }
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="legal-source-attachment">Source document</Label>
                    <Select
                      value={legalReferenceDraft.evidence_attachment_id}
                      onValueChange={(value) =>
                        setLegalReferenceDraft((draft) => ({
                          ...draft,
                          evidence_attachment_id: value,
                        }))
                      }
                    >
                      <SelectTrigger id="legal-source-attachment">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__none">No attachment</SelectItem>
                        {attachments.map((attachment) => (
                          <SelectItem key={attachment.id} value={attachment.id}>
                            {attachment.original_filename}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <Button
                    size="sm"
                    className="lg:col-span-3"
                    disabled={
                      createLegalReferenceMutation.isPending ||
                      legalReferenceDraft.act_name.trim().length < 2
                    }
                    onClick={() => createLegalReferenceMutation.mutate()}
                    data-testid="contract-add-legal-reference"
                  >
                    Save legal reference
                  </Button>
                </div>
              ) : null}

              {legal_references.length === 0 ? (
                <EmptyState
                  icon={Scale}
                  title="No legal references"
                  description="Record the legal basis and source excerpt before using classification in review."
                />
              ) : (
                <ul className="flex flex-col gap-2">
                  {legal_references.map((reference) => (
                    <li
                      key={reference.id}
                      className="rounded-lg border border-[var(--color-line)] bg-white p-3"
                    >
                      <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-start">
                        <div>
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-semibold text-[var(--color-ink)]">
                              {reference.act_name}
                            </span>
                            <StatusBadge status={reference.status} />
                            <span className="text-xs text-[var(--color-mute)]">
                              {reference.source.replace(/_/g, " ")}
                            </span>
                          </div>
                          <div className="mt-1 text-xs text-[var(--color-ink-2)]">
                            {[reference.section_label, reference.clause_label]
                              .filter(Boolean)
                              .join(" - ") || "No section or clause label"}
                          </div>
                          {reference.evidence_quote ? (
                            <p className="mt-2 text-xs leading-relaxed text-[var(--color-ink-2)]">
                              {reference.evidence_quote}
                            </p>
                          ) : null}
                          {reference.evidence_attachment_name ? (
                            <div className="mt-1 text-xs text-[var(--color-mute)]">
                              Source: {reference.evidence_attachment_name}
                            </div>
                          ) : null}
                        </div>
                        {canEdit && reference.status === "suggested" ? (
                          <div className="flex flex-wrap gap-2">
                            <Button
                              size="sm"
                              onClick={() =>
                                updateLegalReferenceMutation.mutate({
                                  referenceId: reference.id,
                                  status: "accepted",
                                })
                              }
                            >
                              Accept
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() =>
                                updateLegalReferenceMutation.mutate({
                                  referenceId: reference.id,
                                  status: "rejected",
                                })
                              }
                            >
                              Reject
                            </Button>
                          </div>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="playbook">
          <Card>
            <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
              <div>
                <CardTitle>Playbook</CardTitle>
                <CardDescription>
                  Firm-preferred positions for this contract.
                </CardDescription>
              </div>
              <div className="flex flex-wrap gap-2">
                {canManageRules && playbook_rules.length === 0 ? (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={installPlaybook.isPending}
                    onClick={() => installPlaybook.mutate()}
                    data-testid="contract-install-default-playbook"
                  >
                    {installPlaybook.isPending ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Installing…
                      </>
                    ) : (
                      "Install default playbook"
                    )}
                  </Button>
                ) : null}
                {canGenerateAI && playbook_rules.length > 0 ? (
                  <Button
                    size="sm"
                    disabled={runPlaybookCompare.isPending || clauses.length === 0}
                    onClick={() => runPlaybookCompare.mutate()}
                    data-testid="contract-run-playbook-compare"
                  >
                    {runPlaybookCompare.isPending ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Comparing…
                      </>
                    ) : (
                      <>
                        <Gavel className="h-4 w-4" aria-hidden /> Run comparison
                      </>
                    )}
                  </Button>
                ) : null}
              </div>
            </CardHeader>
            <CardContent className="flex flex-col gap-5">
              {playbook_rules.length === 0 ? (
                <EmptyState
                  icon={Gavel}
                  title="No playbook rules yet"
                  description={
                    canManageRules
                      ? "Install the default Indian-commercial playbook to bootstrap 15 preferred positions. Edit per contract afterwards."
                      : "Ask a team member with playbook-management access to install the default rules."
                  }
                />
              ) : (
                <ul className="flex flex-col gap-2">
                  {playbook_rules.map((r) => (
                    <li
                      key={r.id}
                      className="rounded-lg border border-[var(--color-line)] bg-white p-3"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]">
                            {r.clause_type.replace(/_/g, " ")} · severity {r.severity}
                          </div>
                          <div className="mt-0.5 text-sm font-semibold text-[var(--color-ink)]">
                            {r.rule_name}
                          </div>
                          <p className="mt-1 text-xs text-[var(--color-ink-2)]">
                            {r.expected_position}
                          </p>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}

              {playbookFindings ? (
                <div className="rounded-xl border border-[var(--color-line)] bg-[var(--color-bg-2)] p-4">
                  <div className="mb-2 text-sm font-semibold text-[var(--color-ink)]">
                    Findings ({playbookFindings.length})
                  </div>
                  <ul className="flex flex-col gap-2">
                    {playbookFindings.map((f) => (
                      <li key={f.rule_id} className="flex items-start gap-2 text-sm">
                        <FindingIcon status={f.status} />
                        <div>
                          <div className="font-medium text-[var(--color-ink)]">
                            {f.rule_name}
                          </div>
                          <div className="text-xs text-[var(--color-ink-2)]">
                            {f.summary}
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="redline">
          <Card>
            <CardHeader>
              <CardTitle>Redline viewer</CardTitle>
              <CardDescription>
                Tracked changes from a counterparty-redlined DOCX.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {!redlineAttachmentId ? (
                <EmptyState
                  icon={FileText}
                  title="Pick an attachment"
                  description="Open the Attachments tab and click ‘View redline’ on a DOCX to load its tracked changes here."
                />
              ) : redlineQuery.isPending ? (
                <Skeleton className="h-48 w-full" />
              ) : redlineQuery.isError ? (
                <QueryErrorState
                  title="Could not parse the redline"
                  error={redlineQuery.error}
                  onRetry={redlineQuery.refetch}
                />
              ) : redlineQuery.data ? (
                <div className="flex flex-col gap-4">
                  <div className="flex flex-wrap gap-4 text-xs text-[var(--color-mute)]">
                    <div>
                      <span className="font-semibold text-[var(--color-ink-2)]">
                        {redlineQuery.data.insertion_count}
                      </span>{" "}
                      insertions
                    </div>
                    <div>
                      <span className="font-semibold text-[var(--color-ink-2)]">
                        {redlineQuery.data.deletion_count}
                      </span>{" "}
                      deletions
                    </div>
                    <div>
                      {redlineQuery.data.paragraph_count} paragraphs
                    </div>
                    {Object.entries(redlineQuery.data.author_counts).map(
                      ([author, count]) => (
                        <div key={author}>
                          {author}: {count} change{count === 1 ? "" : "s"}
                        </div>
                      ),
                    )}
                  </div>
                  {redlineQuery.data.changes.length === 0 ? (
                    <EmptyState
                      icon={CheckCircle2}
                      title="Clean document"
                      description="No tracked changes detected in this DOCX."
                    />
                  ) : (
                    <ul className="flex flex-col gap-2">
                      {redlineQuery.data.changes.map((change) => (
                        <RedlineRow key={change.index} change={change} />
                      ))}
                    </ul>
                  )}
                </div>
              ) : null}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function TermStat({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <dt className="text-[11px] font-medium uppercase tracking-[0.06em] text-[var(--color-mute)]">
        {label}
      </dt>
      <dd className="mt-0.5 text-sm font-semibold text-[var(--color-ink)]">
        {value ?? "Not set"}
      </dd>
    </div>
  );
}

function AttachmentMetadataEditor({
  contractId,
  attachment,
  attachments,
  onSaved,
}: {
  contractId: string;
  attachment: WorkspaceAttachment;
  attachments: WorkspaceAttachment[];
  onSaved: () => Promise<unknown>;
}) {
  const [role, setRole] = useState<ContractAttachmentRole | "__none">(
    attachment.attachment_role ?? "__none",
  );
  const [parentAttachmentId, setParentAttachmentId] = useState(
    attachment.parent_attachment_id ?? "__none",
  );
  const [documentDate, setDocumentDate] = useState(attachment.document_date ?? "");
  const [notes, setNotes] = useState(attachment.notes ?? "");

  useEffect(() => {
    setRole(attachment.attachment_role ?? "__none");
    setParentAttachmentId(attachment.parent_attachment_id ?? "__none");
    setDocumentDate(attachment.document_date ?? "");
    setNotes(attachment.notes ?? "");
  }, [
    attachment.attachment_role,
    attachment.document_date,
    attachment.notes,
    attachment.parent_attachment_id,
  ]);

  const mutation = useMutation({
    mutationFn: () =>
      updateContractAttachmentMetadata({
        contractId,
        attachmentId: attachment.id,
        attachment_role: role === "__none" ? null : role,
        parent_attachment_id:
          parentAttachmentId === "__none" ? null : parentAttachmentId,
        document_date: documentDate || null,
        notes: notes.trim() || null,
      }),
    onSuccess: async () => {
      await onSaved();
      toast.success("Attachment metadata saved.");
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not save attachment metadata.")),
  });

  return (
    <div className="mt-3 grid gap-2 rounded-md bg-[var(--color-bg-2)] p-3 sm:grid-cols-[0.9fr_0.9fr_0.7fr_1fr_auto]">
      <Select value={role} onValueChange={(value) => setRole(value as typeof role)}>
        <SelectTrigger aria-label={`Role for ${attachment.original_filename}`}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__none">Unclassified</SelectItem>
          {CONTRACT_ATTACHMENT_ROLE_OPTIONS.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select
        value={parentAttachmentId}
        onValueChange={(value) => setParentAttachmentId(value)}
      >
        <SelectTrigger aria-label={`Parent for ${attachment.original_filename}`}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__none">No parent</SelectItem>
          {attachments
            .filter(
              (candidate) =>
                candidate.id !== attachment.id &&
                !attachmentHasAncestor(attachments, candidate.id, attachment.id),
            )
            .map((candidate) => (
              <SelectItem key={candidate.id} value={candidate.id}>
                {candidate.original_filename}
              </SelectItem>
            ))}
        </SelectContent>
      </Select>
      <Input
        type="date"
        value={documentDate}
        onChange={(event) => setDocumentDate(event.target.value)}
        aria-label={`Date for ${attachment.original_filename}`}
      />
      <Input
        value={notes}
        onChange={(event) => setNotes(event.target.value)}
        placeholder="Notes"
        aria-label={`Notes for ${attachment.original_filename}`}
      />
      <Button
        size="sm"
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
        data-testid={`save-contract-attachment-metadata-${attachment.id}`}
      >
        Save
      </Button>
    </div>
  );
}

function attachmentName(attachments: WorkspaceAttachment[], attachmentId: string): string {
  return (
    attachments.find((attachment) => attachment.id === attachmentId)?.original_filename ??
    "another document"
  );
}

function groupAttachmentsByRole(attachments: WorkspaceAttachment[]) {
  const roleOrder = [
    ...CONTRACT_ATTACHMENT_ROLE_OPTIONS.map((option) => option.value),
    "unclassified",
  ];
  return roleOrder
    .map((role) => {
      const groupAttachments = attachments.filter(
        (attachment) => (attachment.attachment_role ?? "unclassified") === role,
      );
      return {
        key: role,
        label: formatAttachmentRole(role),
        attachments: groupAttachments,
      };
    })
    .filter((group) => group.attachments.length > 0);
}

function attachmentHasAncestor(
  attachments: WorkspaceAttachment[],
  attachmentId: string,
  ancestorId: string,
): boolean {
  const byId = new Map(attachments.map((attachment) => [attachment.id, attachment]));
  let current = byId.get(attachmentId)?.parent_attachment_id ?? null;
  const seen = new Set<string>();
  while (current) {
    if (current === ancestorId) return true;
    if (seen.has(current)) return true;
    seen.add(current);
    current = byId.get(current)?.parent_attachment_id ?? null;
  }
  return false;
}

function formatAttachmentRole(role: string): string {
  if (role === "unclassified") return "Unclassified";
  return (
    CONTRACT_ATTACHMENT_ROLE_OPTIONS.find((option) => option.value === role)?.label ??
    role.replace(/_/g, " ")
  );
}

function RiskBadge({ level }: { level: string }) {
  const palette: Record<string, string> = {
    low: "bg-emerald-50 text-emerald-700 border-emerald-200",
    medium: "bg-amber-50 text-amber-800 border-amber-200",
    high: "bg-rose-50 text-rose-700 border-rose-200",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize ${palette[level] ?? palette.medium}`}
    >
      {level} risk
    </span>
  );
}

function FindingIcon({ status }: { status: string }) {
  if (status === "matched") {
    return <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-600" aria-hidden />;
  }
  if (status === "deviation") {
    return <AlertTriangle className="mt-0.5 h-4 w-4 text-amber-600" aria-hidden />;
  }
  return <XCircle className="mt-0.5 h-4 w-4 text-rose-600" aria-hidden />;
}

function RedlineRow({ change }: { change: ContractRedlineChange }) {
  const color =
    change.kind === "insertion"
      ? "bg-emerald-50 text-emerald-800 border-emerald-200"
      : change.kind === "deletion"
        ? "bg-rose-50 text-rose-800 border-rose-200"
        : "bg-slate-100 text-slate-800 border-slate-200";
  const label =
    change.kind === "insertion"
      ? "Inserted"
      : change.kind === "deletion"
        ? "Deleted"
        : "Formatting";
  return (
    <li className="rounded-lg border border-[var(--color-line)] bg-white p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--color-mute)]">
        <span
          className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${color}`}
        >
          {label} · paragraph {change.paragraph_index + 1}
        </span>
        {change.author ? <span>by {change.author}</span> : null}
        {change.timestamp ? (
          <span>{new Date(change.timestamp).toLocaleString()}</span>
        ) : null}
      </div>
      <p className="mt-2 text-sm leading-relaxed text-[var(--color-ink-2)]">
        {change.context_before}
        <strong
          className={
            change.kind === "deletion"
              ? "text-rose-700 line-through"
              : change.kind === "insertion"
                ? "text-emerald-700"
                : "text-slate-700"
          }
        >
          {change.text}
        </strong>
        {change.context_after}
      </p>
    </li>
  );
}

function PartyExtractionResultPanel({
  result,
}: {
  result: PartyClauseExtractionResult;
}) {
  const representedLabel =
    result.represented_party === "first"
      ? result.first_party_name || "First party"
      : result.second_party_name || "Second party";
  const counterpartyLabel =
    result.represented_party === "first"
      ? result.second_party_name || "Second party"
      : result.first_party_name || "First party";
  return (
    <div
      className="mt-2 flex flex-col gap-3"
      data-testid="party-extract-results"
    >
      <div className="rounded-lg border border-[var(--color-line)] bg-white p-3">
        <h4 className="text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]">
          Represented party — {representedLabel}
        </h4>
        <PartyItemList items={result.represented_items} emptyMsg="No items for the represented party." />
      </div>
      <div className="rounded-lg border border-[var(--color-line)] bg-white p-3">
        <h4 className="text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]">
          Counterparty — {counterpartyLabel}
        </h4>
        <PartyItemList items={result.counterparty_items} emptyMsg="No items for the counterparty." />
      </div>
      {result.ambiguous_items.length > 0 ? (
        <div
          className="rounded-lg border border-amber-300 bg-amber-50 p-3"
          data-testid="party-extract-ambiguous"
        >
          <h4 className="text-xs uppercase tracking-[0.06em] text-amber-900">
            Ambiguous — needs review ({result.ambiguous_items.length})
          </h4>
          <ul className="mt-2 flex flex-col gap-2">
            {result.ambiguous_items.map((item, idx) => (
              <li
                key={`amb-${idx}`}
                className="text-sm text-amber-900"
              >
                <div className="font-medium">
                  {item.category.replace(/_/g, " ")} — {item.summary}
                </div>
                <div className="text-xs italic">{item.ambiguity_reason}</div>
                <PartySourceBadge source={item.source} />
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {result.dropped_source_unverified_count > 0 ? (
        <p
          className="text-xs text-[var(--color-mute)]"
          data-testid="party-extract-dropped"
        >
          {result.dropped_source_unverified_count} item
          {result.dropped_source_unverified_count === 1 ? "" : "s"} dropped —
          source snippet could not be located in the uploaded contract.
        </p>
      ) : null}
    </div>
  );
}

function PartyItemList({
  items,
  emptyMsg,
}: {
  items: PartyClauseItem[];
  emptyMsg: string;
}) {
  if (items.length === 0) {
    return (
      <p className="mt-2 text-xs text-[var(--color-mute)]">{emptyMsg}</p>
    );
  }
  return (
    <ul className="mt-2 flex flex-col gap-2">
      {items.map((item, idx) => (
        <li
          key={`pi-${idx}`}
          className="text-sm text-[var(--color-ink-2)]"
        >
          <div className="font-medium text-[var(--color-ink)]">
            {item.category.replace(/_/g, " ")} — {item.summary}
          </div>
          <PartySourceBadge source={item.source} />
        </li>
      ))}
    </ul>
  );
}

function PartySourceBadge({
  source,
}: {
  source: PartyClauseAmbiguousItem["source"];
}) {
  return (
    <div className="mt-1 flex items-start gap-1 text-xs text-[var(--color-mute-2)]">
      <span className="rounded bg-slate-100 px-1 py-0.5 font-medium">
        Source
      </span>
      <span className="italic">
        {source.locator ? `${source.locator}: ` : ""}“{source.snippet}”
      </span>
    </div>
  );
}
