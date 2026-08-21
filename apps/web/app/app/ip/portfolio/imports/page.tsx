"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  History,
  LoaderCircle,
  RefreshCw,
  Upload,
  XCircle,
} from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
import { apiErrorMessage } from "@/lib/api/config";
import {
  commitIpPortfolioImport,
  downloadIpPortfolioImportErrors,
  getIpPortfolioImport,
  type IpImportPreview,
  type IpImportRow,
  listIpPortfolioImports,
  reconcileIpPortfolioImport,
  revalidateIpPortfolioImport,
  uploadIpPortfolioImport,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

type Decision = {
  decision: "create_separate" | "link_existing" | "skip";
  targetDocketId?: string;
};

function textValue(row: IpImportRow, key: string): string {
  const value = row.normalized[key];
  return value === undefined || value === null || value === "" ? "Not recorded" : String(value);
}

function statusTone(status: string): "success" | "warning" | "neutral" {
  if (status === "committed" || status === "valid" || status === "created") return "success";
  if (status === "invalid" || status === "failed" || status === "committed_with_errors") return "warning";
  return "neutral";
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export default function IpPortfolioImportsPage() {
  const canRead = useCapability("ip:read");
  const canWrite = useCapability("ip:write");
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<IpImportPreview | null>(null);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [downloading, setDownloading] = useState(false);

  const history = useQuery({
    queryKey: ["ip-portfolio-imports"],
    queryFn: listIpPortfolioImports,
    enabled: canRead,
  });

  const applyPreview = (result: IpImportPreview) => {
    setPreview(result);
    setDecisions(
      Object.fromEntries(
        result.rows
          .filter((row) => row.reconciliation_decision)
          .map((row) => [
            row.id,
            {
              decision: row.reconciliation_decision!,
              targetDocketId: row.reconciled_target_docket_id ?? undefined,
            },
          ]),
      ),
    );
  };

  const uploadMutation = useMutation({
    mutationFn: uploadIpPortfolioImport,
    onSuccess: async (result) => {
      applyPreview(result);
      await queryClient.invalidateQueries({ queryKey: ["ip-portfolio-imports"] });
      if (result.job.invalid_rows) {
        toast.error(`${result.job.invalid_rows} rows need correction before import.`);
      } else {
        toast.success(`${result.job.valid_rows} rows passed validation.`);
      }
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not validate the portfolio file.")),
  });

  const detailMutation = useMutation({
    mutationFn: getIpPortfolioImport,
    onSuccess: applyPreview,
    onError: (error) => toast.error(apiErrorMessage(error, "Could not load import details.")),
  });

  const revalidateMutation = useMutation({
    mutationFn: revalidateIpPortfolioImport,
    onSuccess: async (result) => {
      applyPreview(result);
      await queryClient.invalidateQueries({ queryKey: ["ip-portfolio-imports"] });
      toast.success("Preview refreshed against current portfolio data.");
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not refresh the import preview.")),
  });

  const duplicateRows = preview?.rows.filter((row) => row.duplicate_candidates.length > 0) ?? [];
  const unresolvedRows = duplicateRows.filter((row) => {
    const selected = decisions[row.id]?.decision ?? row.reconciliation_decision;
    const target = decisions[row.id]?.targetDocketId ?? row.reconciled_target_docket_id;
    return !selected || (selected === "link_existing" && !target);
  });
  const changedDecisions = duplicateRows.flatMap((row) => {
    const selected = decisions[row.id];
    if (!selected) return [];
    if (
      selected.decision === row.reconciliation_decision &&
      (selected.targetDocketId ?? null) === row.reconciled_target_docket_id
    ) {
      return [];
    }
    return [{
      rowId: row.id,
      decision: selected.decision,
      targetDocketId: selected.decision === "link_existing" ? selected.targetDocketId : null,
    }];
  });

  const reconcileMutation = useMutation({
    mutationFn: () => {
      if (!preview || changedDecisions.length === 0) throw new Error("Choose a duplicate decision first.");
      return reconcileIpPortfolioImport({
        jobId: preview.job.id,
        expectedJobVersion: preview.job.version,
        decisions: changedDecisions,
      });
    },
    onSuccess: async (result) => {
      applyPreview(result);
      await queryClient.invalidateQueries({ queryKey: ["ip-portfolio-imports"] });
      toast.success("Duplicate decisions saved. The import preview token was renewed.");
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not save duplicate decisions.")),
  });

  const commitMutation = useMutation({
    mutationFn: () => {
      if (!preview?.job.preview_token) throw new Error("A current preview token is required.");
      return commitIpPortfolioImport({
        jobId: preview.job.id,
        previewToken: preview.job.preview_token,
        idempotencyKey: crypto.randomUUID(),
      });
    },
    onSuccess: async (result) => {
      applyPreview(result);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ip-portfolio-imports"] }),
        queryClient.invalidateQueries({ queryKey: ["ip-portfolio"] }),
      ]);
      const message = `${result.job.committed_rows} rows committed; ${result.job.failed_rows} failed.`;
      result.job.failed_rows ? toast.error(message) : toast.success(message);
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not commit the portfolio import.")),
  });

  const pending =
    uploadMutation.isPending ||
    detailMutation.isPending ||
    revalidateMutation.isPending ||
    reconcileMutation.isPending ||
    commitMutation.isPending;
  const terminal = preview?.job.status === "committed" || preview?.job.status === "committed_with_errors";
  const canCommit = Boolean(
    preview &&
      preview.job.status === "preview_ready" &&
      preview.job.invalid_rows === 0 &&
      preview.job.valid_rows > 0 &&
      unresolvedRows.length === 0 &&
      changedDecisions.length === 0 &&
      !preview.preview_expired &&
      preview.job.preview_token &&
      !pending,
  );

  const visibleRows = useMemo(() => {
    if (!preview) return [];
    return [...preview.rows].sort((left, right) => {
      const leftPriority = left.errors.length ? 0 : left.duplicate_candidates.length ? 1 : 2;
      const rightPriority = right.errors.length ? 0 : right.duplicate_candidates.length ? 1 : 2;
      return leftPriority - rightPriority || left.row_number - right.row_number;
    });
  }, [preview]);

  async function downloadErrors() {
    if (!preview) return;
    try {
      setDownloading(true);
      const blob = await downloadIpPortfolioImportErrors(preview.job.id);
      downloadBlob(blob, `ip-import-${preview.job.id}-errors.csv`);
    } catch (error) {
      toast.error(apiErrorMessage(error, "Could not download the error report."));
    } finally {
      setDownloading(false);
    }
  }

  if (!canRead) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader eyebrow="IP operations" title="Trademark portfolio import" />
        <section className="border-y border-[var(--color-line)] py-10 text-center">
          <XCircle className="mx-auto h-9 w-9 text-[var(--color-mute-2)]" />
          <h2 className="mt-3 text-base font-semibold">IP portfolio access required</h2>
        </section>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="IP operations"
        title="Trademark portfolio import"
        description="Stage a CSV or XLSX register, resolve every duplicate, then commit the reviewed rows to the portfolio."
        actions={
          <Button href="/app/ip/portfolio" variant="outline">
            <ArrowLeft className="h-4 w-4" /> Portfolio
          </Button>
        }
      />

      <section className="grid gap-5 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]" aria-label="Import controls">
        <div className="border-b border-[var(--color-line)] pb-5 lg:border-b-0 lg:border-r lg:pb-0 lg:pr-5">
          <div className="flex items-center gap-2 text-base font-semibold">
            <FileSpreadsheet className="h-5 w-5" /> Upload register
          </div>
          <p className="mt-1 text-sm text-[var(--color-mute)]">
            Required: Title, Mark Text, Nice Class and Applicant. Optional columns include Application Number, Goods/Services, Agent, Jurisdiction, Office and Matter ID.
          </p>
          <Label className="mt-4 block" htmlFor="ip-portfolio-import-file">CSV or XLSX file</Label>
          <Input
            id="ip-portfolio-import-file"
            className="mt-2"
            type="file"
            accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            disabled={!canWrite || pending}
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setPreview(null);
              setDecisions({});
            }}
          />
          {file ? <p className="mt-2 break-all text-xs text-[var(--color-mute)]">{file.name} · {Math.max(1, Math.ceil(file.size / 1024))} KB</p> : null}
          <Button
            className="mt-4 w-full"
            disabled={!canWrite || !file || pending}
            onClick={() => file && uploadMutation.mutate(file)}
          >
            {uploadMutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            Validate file
          </Button>
          <p className="mt-2 text-xs text-[var(--color-mute)]">Maximum 1,000 rows and 10 MB. Uploading does not change the live portfolio.</p>
          {!canWrite ? <p className="mt-3 text-sm text-[var(--color-danger-600)]">Write permission is required to upload or commit imports.</p> : null}
        </div>

        <div className="min-w-0">
          <div className="flex items-center justify-between gap-3">
            <h2 className="flex items-center gap-2 text-base font-semibold"><History className="h-5 w-5" /> Import history</h2>
            {history.isFetching ? <LoaderCircle className="h-4 w-4 animate-spin text-[var(--color-mute)]" aria-label="Loading import history" /> : null}
          </div>
          <div className="mt-2 divide-y divide-[var(--color-line)] border-y border-[var(--color-line)]">
            {history.data?.jobs.length ? history.data.jobs.slice(0, 8).map((job) => (
              <button
                key={job.id}
                type="button"
                className="flex w-full min-w-0 items-center justify-between gap-3 px-1 py-3 text-left hover:bg-[var(--color-bg-2)]"
                onClick={() => detailMutation.mutate(job.id)}
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{job.filename}</span>
                  <span className="block text-xs text-[var(--color-mute)]">{job.total_rows} rows · {job.creator_label_snapshot}</span>
                </span>
                <Badge tone={statusTone(job.status)}>{job.status.replaceAll("_", " ")}</Badge>
              </button>
            )) : <p className="py-6 text-sm text-[var(--color-mute)]">No portfolio imports yet.</p>}
          </div>
        </div>
      </section>

      {preview ? (
        <section aria-labelledby="import-preview-heading" className="border-t border-[var(--color-line)] pt-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 id="import-preview-heading" className="text-lg font-semibold">Review {preview.job.filename}</h2>
              <p className="mt-1 text-sm text-[var(--color-mute)]">Version {preview.job.version} · staged by {preview.job.creator_label_snapshot}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {(preview.job.invalid_rows > 0 || preview.job.failed_rows > 0) ? (
                <Button variant="outline" disabled={downloading} onClick={() => void downloadErrors()}>
                  {downloading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />} Error CSV
                </Button>
              ) : null}
              {preview.preview_expired && !terminal ? (
                <Button variant="outline" disabled={!canWrite || pending} onClick={() => revalidateMutation.mutate(preview.job.id)}>
                  <RefreshCw className="h-4 w-4" /> Refresh preview
                </Button>
              ) : null}
            </div>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Metric label="Rows" value={preview.job.total_rows} />
            <Metric label="Valid" value={preview.job.valid_rows} tone="success" />
            <Metric label="Invalid" value={preview.job.invalid_rows} tone="warning" />
            <Metric label="Duplicates" value={duplicateRows.length} tone={duplicateRows.length ? "warning" : "neutral"} />
          </div>

          {preview.preview_expired ? (
            <div className="mt-4 flex gap-2 border border-[var(--color-warning-300)] bg-[var(--color-warning-50)] p-3 text-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> This preview expired. Refresh it before committing; duplicate matches will be recalculated.
            </div>
          ) : null}

          <div className="mt-5 overflow-x-auto border-y border-[var(--color-line)]">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="bg-[var(--color-bg-2)] text-xs uppercase text-[var(--color-mute)]">
                <tr><th className="px-3 py-2">Row</th><th className="px-3 py-2">Mark</th><th className="px-3 py-2">Application</th><th className="px-3 py-2">Class</th><th className="px-3 py-2">Applicant</th><th className="px-3 py-2">Validation</th><th className="px-3 py-2">Duplicate decision</th></tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-line)]">
                {visibleRows.map((row) => (
                  <ImportRow
                    key={row.id}
                    row={row}
                    decision={decisions[row.id]}
                    disabled={!canWrite || pending || terminal}
                    onDecision={(decision) => setDecisions((current) => ({ ...current, [row.id]: decision }))}
                  />
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-5 flex flex-col items-start justify-between gap-3 border-t border-[var(--color-line)] pt-4 sm:flex-row sm:items-center">
            <div className="text-sm text-[var(--color-mute)]">
              {terminal ? `${preview.job.committed_rows} rows committed; ${preview.job.failed_rows} failed.` :
                preview.job.invalid_rows ? "Correct invalid rows in the source file and upload it again." :
                unresolvedRows.length ? `${unresolvedRows.length} duplicate rows still need a decision.` :
                changedDecisions.length ? "Save the changed duplicate decisions before commit." :
                "All rows are ready for a controlled commit."}
            </div>
            <div className="flex flex-wrap gap-2">
              {!terminal && duplicateRows.length ? (
                <Button variant="outline" disabled={!canWrite || pending || changedDecisions.length === 0 || unresolvedRows.length > 0} onClick={() => reconcileMutation.mutate()}>
                  {reconcileMutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} Save duplicate decisions
                </Button>
              ) : null}
              {!terminal ? (
                <Button disabled={!canWrite || !canCommit} onClick={() => commitMutation.mutate()}>
                  {commitMutation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} Commit to portfolio
                </Button>
              ) : null}
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
}

function Metric({ label, value, tone = "neutral" }: { label: string; value: number; tone?: "neutral" | "success" | "warning" }) {
  const color = tone === "success" ? "text-[var(--color-success-600)]" : tone === "warning" ? "text-[var(--color-warning-700)]" : "text-[var(--color-ink)]";
  return <div className="border-l-2 border-[var(--color-line)] px-3 py-1"><div className="text-xs uppercase text-[var(--color-mute)]">{label}</div><div className={`mt-1 text-xl font-semibold tabular-nums ${color}`}>{value}</div></div>;
}

function ImportRow({ row, decision, disabled, onDecision }: { row: IpImportRow; decision?: Decision; disabled: boolean; onDecision: (decision: Decision) => void }) {
  const selected = decision?.decision ?? row.reconciliation_decision ?? undefined;
  const target = decision?.targetDocketId ?? row.reconciled_target_docket_id ?? undefined;
  const docketCandidates = row.duplicate_candidates.filter((candidate) => candidate.docket_id);
  return (
    <tr className="align-top">
      <td className="px-3 py-3 font-mono text-xs">{row.row_number}</td>
      <td className="px-3 py-3"><span className="block font-medium">{textValue(row, "mark_text")}</span><span className="text-xs text-[var(--color-mute)]">{textValue(row, "title")}</span></td>
      <td className="px-3 py-3 font-mono text-xs">{textValue(row, "application_number")}</td>
      <td className="px-3 py-3">{textValue(row, "class_number")}</td>
      <td className="px-3 py-3">{textValue(row, "applicant_name")}</td>
      <td className="px-3 py-3">
        <Badge tone={statusTone(row.validation_status)}>{row.validation_status}</Badge>
        {row.errors.map((error, index) => <p key={`${error.field}-${error.code}-${index}`} className="mt-1 text-xs text-[var(--color-danger-600)]">{error.field ?? "row"}: {(error.code ?? "invalid").replaceAll("_", " ")}</p>)}
      </td>
      <td className="w-[260px] px-3 py-3">
        {row.duplicate_candidates.length ? (
          <div className="space-y-2">
            <p className="text-xs text-[var(--color-mute)]">{row.duplicate_candidates.map((candidate) => candidate.title ?? `Row ${candidate.row_number}`).join(", ")}</p>
            <Select value={selected ?? ""} disabled={disabled} onValueChange={(value) => onDecision({ decision: value as Decision["decision"] })}>
              <SelectTrigger aria-label={`Decision for row ${row.row_number}`}><SelectValue placeholder="Choose action" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="create_separate">Create separate record</SelectItem>
                {docketCandidates.length ? <SelectItem value="link_existing">Link existing docket</SelectItem> : null}
                <SelectItem value="skip">Skip row</SelectItem>
              </SelectContent>
            </Select>
            {selected === "link_existing" ? (
              <Select value={target ?? ""} disabled={disabled} onValueChange={(value) => onDecision({ decision: "link_existing", targetDocketId: value })}>
                <SelectTrigger aria-label={`Existing docket for row ${row.row_number}`}><SelectValue placeholder="Choose docket" /></SelectTrigger>
                <SelectContent>{docketCandidates.map((candidate) => <SelectItem key={candidate.docket_id} value={candidate.docket_id!}>{candidate.title ?? candidate.docket_id}</SelectItem>)}</SelectContent>
              </Select>
            ) : null}
          </div>
        ) : <span className="text-xs text-[var(--color-mute)]">No match found</span>}
      </td>
    </tr>
  );
}
