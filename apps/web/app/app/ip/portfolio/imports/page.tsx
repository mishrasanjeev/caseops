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
  Pencil,
  RefreshCw,
  Upload,
  XCircle,
} from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
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
  fetchIpDocket,
  getIpPortfolioImport,
  type IpImportPreview,
  type IpImportRow,
  type IpDocket,
  listIpPortfolioImports,
  reconcileIpPortfolioImport,
  revalidateIpPortfolioImport,
  resumeIpPortfolioImport,
  uploadIpPortfolioImport,
  updateIpPortfolioRenewalDate,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

type Decision = {
  decision: "create_separate" | "link_existing" | "skip";
  targetDocketId?: string;
};

function textValue(row: IpImportRow, key: string): string {
  const value = row.normalized[key];
  if (Array.isArray(value)) return value.join(", ");
  return value === undefined || value === null || value === "" ? "Not recorded" : String(value);
}

function rowWarnings(row: IpImportRow): Array<{ field: string; code: string }> {
  const value = row.normalized._warnings;
  return Array.isArray(value) ? value : [];
}

function resultSummary(preview: IpImportPreview): string {
  const created = preview.rows.filter((row) => row.created_docket_id).length;
  const linked = preview.rows.filter((row) => row.commit_status === "committed" && !row.created_docket_id).length;
  const skipped = preview.rows.filter((row) => row.commit_status === "skipped").length;
  const duplicates = preview.rows.filter((row) => row.commit_status === "skipped" && row.commit_error_code === "duplicate_skipped").length;
  const warnings = preview.rows.filter((row) => rowWarnings(row).length).length;
  return `${created} created; ${linked} linked; ${skipped} skipped (${duplicates} duplicates); ${warnings} with warnings; ${preview.job.failed_rows} failed.`;
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
      toast.success(`${result.job.valid_rows} eligible rows; ${result.job.invalid_rows} unusable rows will be skipped.`);
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
    const selected = decisions[row.id]?.decision ?? row.reconciliation_decision ?? "skip";
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
      if (!preview) throw new Error("A saved preview is required.");
      if (preview.job.recovery_available) {
        return resumeIpPortfolioImport({
          jobId: preview.job.id,
          expectedJobVersion: preview.job.version,
          previewToken: preview.job.preview_token,
          onProgress: applyPreview,
        });
      }
      const storageKey = `ip-import-commit:${preview.job.id}`;
      let key = sessionStorage.getItem(storageKey);
      if (!key) {
        key = crypto.randomUUID();
        sessionStorage.setItem(storageKey, key);
      }
      return commitIpPortfolioImport({
        jobId: preview.job.id,
        previewToken: preview.job.preview_token ?? "retained-claim",
        idempotencyKey: key,
        onProgress: applyPreview,
      });
    },
    onSuccess: async (result) => {
      applyPreview(result);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ip-portfolio-imports"] }),
        queryClient.invalidateQueries({ queryKey: ["ip", "portfolio"] }),
      ]);
      toast.success(resultSummary(result));
    },
    onError: async (error) => {
      toast.error(apiErrorMessage(error, "Could not complete the portfolio import. Reload its history."));
      await queryClient.invalidateQueries({ queryKey: ["ip-portfolio-imports"] });
    },
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
      (preview.job.status === "preview_ready" ||
        (preview.job.status === "staged" && preview.job.recovery_available)) &&
      preview.job.valid_rows > 0 &&
      unresolvedRows.length === 0 &&
      changedDecisions.length === 0 &&
      !preview.preview_expired &&
      (preview.job.preview_token || preview.job.status === "staged") &&
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
        description="Review the source register before committing eligible rows."
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
            Source columns are optional. Missing facts remain empty; incomplete records stay in draft. Exact duplicates are skipped by default.
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
            {history.isError ? <QueryErrorState error={history.error} onRetry={() => void history.refetch()} /> : history.data?.jobs.length ? history.data.jobs.slice(0, 8).map((job) => (
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

          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-5">
            <Metric label="Rows" value={preview.job.total_rows} />
            <Metric label="Valid" value={preview.job.valid_rows} tone="success" />
            <Metric label="Unusable" value={preview.job.invalid_rows} tone="warning" />
            <Metric label="Duplicates" value={duplicateRows.length} tone={duplicateRows.length ? "warning" : "neutral"} />
            <Metric label="Warnings" value={preview.rows.filter((row) => rowWarnings(row).length).length} tone="warning" />
          </div>

          {Array.isArray(preview.rows[0]?.normalized._column_mapping) ? (
            <details className="mt-4 border-y border-[var(--color-line)] py-3">
              <summary className="cursor-pointer text-sm font-medium">Source column mapping</summary>
              <ul className="mt-2 grid gap-1 text-xs sm:grid-cols-2">
                {(preview.rows[0].normalized._column_mapping as Array<{ source: string; target: string | null; handling: string }>).map((column) => (
                  <li key={column.source} className="break-words">{column.source}: {column.target ?? "Unmapped"} ({column.handling.replaceAll("_", " ")})</li>
                ))}
              </ul>
            </details>
          ) : null}

          {preview.preview_expired ? (
            <div className="mt-4 flex gap-2 border border-[var(--color-warning-300)] bg-[var(--color-warning-50)] p-3 text-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> This preview expired. Refresh it before committing; duplicate matches will be recalculated.
            </div>
          ) : null}

          <div className="relative mt-5 overflow-x-auto border-y border-[var(--color-line)]">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="bg-[var(--color-bg-2)] text-xs uppercase text-[var(--color-mute)]">
                <tr><th className="px-3 py-2">Row</th><th className="px-3 py-2">Mark</th><th className="px-3 py-2">Application</th><th className="px-3 py-2">Class</th><th className="px-3 py-2">Applicant</th><th className="px-3 py-2">Renewal due date</th><th className="px-3 py-2">Validation</th><th className="px-3 py-2">Duplicate decision</th></tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-line)]">
                {visibleRows.map((row) => (
                  <ImportRow
                    key={row.id}
                    row={row}
                    decision={decisions[row.id]}
                    disabled={!canWrite || pending || terminal}
                    canEditDate={canWrite && !pending}
                    onDecision={(decision) => setDecisions((current) => ({ ...current, [row.id]: decision }))}
                  />
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-5 flex flex-col items-start justify-between gap-3 border-t border-[var(--color-line)] pt-4 sm:flex-row sm:items-center">
            <div className="text-sm text-[var(--color-mute)]">
              {terminal ? resultSummary(preview) :
                unresolvedRows.length ? `${unresolvedRows.length} duplicate rows still need a decision.` :
                changedDecisions.length ? "Save the changed duplicate decisions before commit." :
                "Eligible rows will be committed; duplicate and unusable rows will be skipped."}
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

function ImportRow({ row, decision, disabled, canEditDate, onDecision }: { row: IpImportRow; decision?: Decision; disabled: boolean; canEditDate: boolean; onDecision: (decision: Decision) => void }) {
  const selected = decision?.decision ?? row.reconciliation_decision ?? "skip";
  const target = decision?.targetDocketId ?? row.reconciled_target_docket_id ?? undefined;
  const docketCandidates = row.duplicate_candidates.filter((candidate) => candidate.docket_id);
  return (
    <tr className="align-top">
      <td className="px-3 py-3 font-mono text-xs">{row.row_number}</td>
      <td className="px-3 py-3"><span className="block font-medium">{textValue(row, "mark_text")}</span><span className="text-xs text-[var(--color-mute)]">{textValue(row, "title")}</span></td>
      <td className="px-3 py-3 font-mono text-xs">{textValue(row, "application_number")}</td>
      <td className="px-3 py-3">{textValue(row, "class_numbers") === "Not recorded" ? textValue(row, "class_number") : textValue(row, "class_numbers")}</td>
      <td className="px-3 py-3">{textValue(row, "applicant_name")}</td>
      <td className="px-3 py-3">
        <span className="block">{textValue(row, "renewal_due_date")}</span>
        {row.normalized.renewal_due_date ? <span className="text-xs text-[var(--color-mute)]">Source date, unverified</span> : null}
        {row.normalized._renewal_reminder ? <span className="block text-xs text-[var(--color-mute)]">Alert: {String((row.normalized._renewal_reminder as { status: string }).status).replaceAll("_", " ")}</span> : null}
      </td>
      <td className="px-3 py-3">
        <Badge tone={statusTone(row.validation_status)}>{row.validation_status}</Badge>
        {row.errors.map((error, index) => <p key={`${error.field}-${error.code}-${index}`} className="mt-1 text-xs text-[var(--color-danger-600)]">{error.field ?? "row"}: {(error.code ?? "invalid").replaceAll("_", " ")}</p>)}
        {rowWarnings(row).map((warning, index) => <p key={`warning-${index}`} className="mt-1 text-xs text-[var(--color-warning-700)]">{warning.field}: {warning.code.replaceAll("_", " ")}</p>)}
        {row.normalized._source_values ? (
          <details className="mt-2 text-xs">
            <summary className="cursor-pointer">Source values</summary>
            <dl className="mt-1 space-y-1">
              {Object.entries(row.normalized._source_values as Record<string, unknown>).map(([key, value]) => (
                <div key={key} className="break-words"><dt className="font-medium">{key}</dt><dd>{value === null || value === "" ? "Empty" : String(value)}</dd></div>
              ))}
            </dl>
          </details>
        ) : null}
        {row.created_docket_id ? <Button href={`/app/ip?docket=${row.created_docket_id}`} variant="ghost" size="sm">Open record</Button> : null}
        {row.created_docket_id && canEditDate ? <RenewalDateEditor docketId={row.created_docket_id} /> : null}
      </td>
      <td className="w-[260px] px-3 py-3">
        {row.duplicate_candidates.length ? (
          <div className="space-y-2">
            <p className="text-xs text-[var(--color-mute)]">{row.duplicate_candidates.map((candidate) => candidate.title ?? `Row ${candidate.row_number}`).join(", ")}</p>
            <Select value={selected ?? ""} disabled={disabled} onValueChange={(value) => onDecision({ decision: value as Decision["decision"] })}>
              <SelectTrigger aria-label={`Decision for row ${row.row_number}`}><SelectValue placeholder="Choose action" /></SelectTrigger>
              <SelectContent>
                {!row.normalized.application_number ? <SelectItem value="create_separate">Create separate record</SelectItem> : null}
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

function RenewalDateEditor({ docketId }: { docketId: string }) {
  const queryClient = useQueryClient();
  const [docket, setDocket] = useState<IpDocket | null>(null);
  const [due, setDue] = useState("");
  const [reason, setReason] = useState("");
  const load = useMutation({
    mutationFn: () => fetchIpDocket(docketId),
    onSuccess: (record) => {
      const source = record.current_particulars.representation_json.portfolio_import as { renewal_due_date?: string } | undefined;
      setDue(source?.renewal_due_date ?? "");
      setReason("");
      setDocket(record);
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not load the current source date.")),
  });
  const save = useMutation({
    mutationFn: () => {
      if (!docket) throw new Error("Load the current record first.");
      return updateIpPortfolioRenewalDate({ docketId, expectedCurrentVersion: docket.current_version,
        renewalDueDate: due || null, reason: reason.trim() });
    },
    onSuccess: async () => {
      setDocket(null);
      toast.success("Source date corrected. Pending alerts were replaced or cancelled.");
      await queryClient.invalidateQueries({ queryKey: ["ip", "portfolio"] });
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not correct the source date. Reload the record before trying again.")),
  });
  return <>
    <Button variant="ghost" size="sm" onClick={() => load.mutate()} disabled={load.isPending}>
      <Pencil className="h-4 w-4" /> Edit source renewal date
    </Button>
    <Dialog open={docket !== null} onOpenChange={(open) => { if (!open && !save.isPending) setDocket(null); }}>
      <DialogContent className="w-[calc(100%-2rem)] max-w-md">
        <DialogHeader>
          <DialogTitle>Correct source renewal date</DialogTitle>
          <DialogDescription><Badge tone="warning">Unverified source date</Badge></DialogDescription>
        </DialogHeader>
        <p className="break-words text-sm">{docket?.title}</p>
        <div className="space-y-2">
          <Label htmlFor={`source-due-${docketId}`}>Renewal due date</Label>
          <Input id={`source-due-${docketId}`} type="date" value={due} onChange={(event) => setDue(event.target.value)} disabled={save.isPending} />
          <Button variant="ghost" size="sm" onClick={() => setDue("")} disabled={!due || save.isPending}>Clear date</Button>
        </div>
        <div className="space-y-2">
          <Label htmlFor={`source-reason-${docketId}`}>Correction reason</Label>
          <Input id={`source-reason-${docketId}`} value={reason} maxLength={500} onChange={(event) => setReason(event.target.value)} disabled={save.isPending} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setDocket(null)} disabled={save.isPending}>Cancel</Button>
          <Button onClick={() => save.mutate()} disabled={reason.trim().length < 5 || save.isPending}>
            {save.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} Save source date
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </>;
}
