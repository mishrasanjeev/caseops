"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  FileText,
  Gavel,
  Loader2,
  Scale,
  Sparkles,
  Upload,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef, useState } from "react";
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
import { ApiError } from "@/lib/api/config";
import {
  comparePlaybook,
  extractContractClauses,
  extractContractObligations,
  fetchContractAttachmentRedline,
  fetchContractWorkspace,
  installDefaultPlaybook,
  type ContractRedlineChange,
  type PlaybookFinding,
  uploadContractAttachment,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

type Workspace = {
  contract: {
    id: string;
    contract_code: string;
    title: string;
    contract_type: string;
    counterparty_name: string | null;
    status: string;
    effective_on: string | null;
    expires_on: string | null;
    governing_law: string | null;
    summary: string | null;
  };
  attachments: Array<{
    id: string;
    original_filename: string;
    content_type: string | null;
    size_bytes: number;
    processing_status: string;
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
};

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

  const workspaceQuery = useQuery({
    queryKey: ["contracts", contractId, "workspace"],
    queryFn: async () => (await fetchContractWorkspace(contractId)) as Workspace,
  });

  const invalidateWorkspace = () =>
    queryClient.invalidateQueries({ queryKey: ["contracts", contractId, "workspace"] });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadContractAttachment({ contractId, file }),
    onSuccess: async () => {
      await invalidateWorkspace();
      toast.success("Document uploaded — processing will begin shortly.");
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "Could not upload the file."),
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
      toast.error(err instanceof ApiError ? err.detail : "Could not extract clauses."),
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
        err instanceof ApiError ? err.detail : "Could not extract obligations.",
      ),
  });

  const installPlaybook = useMutation({
    mutationFn: () => installDefaultPlaybook({ contractId }),
    onSuccess: async (result) => {
      await invalidateWorkspace();
      toast.success(`Installed ${result.installed} default playbook rules.`);
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.detail : "Could not install playbook."),
  });

  const runPlaybookCompare = useMutation({
    mutationFn: () => comparePlaybook({ contractId }),
    onSuccess: (result) => {
      setPlaybookFindings(result.findings);
      toast.success(`Playbook comparison done (${result.findings.length} findings).`);
    },
    onError: (err) =>
      toast.error(
        err instanceof ApiError ? err.detail : "Could not run the playbook comparison.",
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
  const { contract, attachments, clauses, obligations, playbook_rules } = workspace;

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
          <TabsTrigger value="playbook">
            Playbook ({playbook_rules.length})
          </TabsTrigger>
          <TabsTrigger value="redline">Redline</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <Card>
            <CardContent className="flex flex-col gap-4 py-6 text-sm text-[var(--color-ink-2)]">
              <p>
                Upload the contract under <strong>Attachments</strong>. After
                processing, run <em>Extract clauses</em> and{" "}
                <em>Extract obligations</em>. Install the default Indian
                commercial playbook to enable playbook comparison; you can
                edit the rules afterwards.
              </p>
              <p>
                For counterparty-redlined DOCX files, upload them as
                attachments and switch to the <strong>Redline</strong> tab to
                see every tracked change with author, timestamp, and inline
                context.
              </p>
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
                <ul className="divide-y divide-[var(--color-line-2)]">
                  {attachments.map((a) => (
                    <li
                      key={a.id}
                      className="flex items-center justify-between gap-3 py-3"
                    >
                      <div className="flex items-center gap-2">
                        <FileText className="h-4 w-4 text-[var(--color-mute)]" aria-hidden />
                        <div>
                          <div className="text-sm font-medium text-[var(--color-ink)]">
                            {a.original_filename}
                          </div>
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
                    </li>
                  ))}
                </ul>
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
