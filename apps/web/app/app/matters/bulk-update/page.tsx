"use client";

import { Check, Download, Eye, FileSpreadsheet, Loader2, Upload } from "lucide-react";
import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { apiErrorMessage } from "@/lib/api/config";
import {
  applyMatterBulkUpdate,
  downloadMatterBulkUpdateTemplate,
  listMatterBulkUpdateHistory,
  previewMatterBulkUpdate,
  type MatterBulkUpdateOperation,
  type MatterBulkUpdateResult,
} from "@/lib/api/endpoints";

function resultCsv(operation: MatterBulkUpdateOperation): string {
  const cell = (value: string): string => {
    const safe = /^[=+@\-\t\r]/.test(value) ? `'${value}` : value;
    return `"${safe.replaceAll('"', '""')}"`;
  };
  const rows = [
    ["Row", "Matter Code", "Status", "Changed Fields", "Errors"],
    ...operation.rows.map((row) => [
      String(row.row_number), row.matter_code ?? "", row.status,
      row.changed_fields.join("; "), row.errors.join("; "),
    ]),
  ];
  return `\uFEFF${rows.map((row) => row.map(cell).join(",")).join("\r\n")}\r\n`;
}

export default function MatterBulkUpdatePage(): React.JSX.Element {
  const [file, setFile] = useState<File | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [preview, setPreview] = useState<MatterBulkUpdateResult | null>(null);
  const [result, setResult] = useState<MatterBulkUpdateResult | null>(null);
  const [expandedOperationId, setExpandedOperationId] = useState<string | null>(null);
  const [historyLoadFailed, setHistoryLoadFailed] = useState(false);
  const queryClient = useQueryClient();
  const [history, setHistory] = useState<Awaited<ReturnType<typeof listMatterBulkUpdateHistory>> | null>(null);
  // Only the most recently issued history read may update the page, so a slow
  // initial load can never replace the history fetched after an apply.
  const historyRequest = useRef(0);
  const mounted = useRef(true);
  const refreshHistory = useCallback((): void => {
    const request = ++historyRequest.current;
    void listMatterBulkUpdateHistory().then((response) => {
      if (!mounted.current || request !== historyRequest.current) return;
      setHistory(response);
      setHistoryLoadFailed(false);
    }).catch(() => {
      if (mounted.current && request === historyRequest.current) setHistoryLoadFailed(true);
    });
  }, []);
  useEffect(() => {
    mounted.current = true;
    refreshHistory();
    return () => { mounted.current = false; };
  }, [refreshHistory]);
  const previewMutation = useMutation({
    mutationFn: (selected: File) => previewMatterBulkUpdate(selected),
    onSuccess: (response) => { setPreview(response); setResult(null); },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not preview workbook.")),
  });
  const applyMutation = useMutation({
    mutationFn: () => {
      if (!file || !preview) throw new Error("Preview the workbook first.");
      return applyMatterBulkUpdate({ file, previewToken: preview.preview_token });
    },
    onSuccess: (response) => {
      setResult(response);
      setPreview(null);
      void queryClient.invalidateQueries({ queryKey: ["matters"] });
      refreshHistory();
      toast.success(`Updated ${response.applied_rows ?? 0} of ${response.total_rows ?? 0} rows; ${response.skipped_rows ?? 0} skipped, ${response.failed_rows ?? 0} failed.`);
    },
    onError: (error) => {
      setPreview(null);
      refreshHistory();
      toast.error(apiErrorMessage(error, "Could not apply workbook."));
    },
  });

  function downloadResult(operation: MatterBulkUpdateOperation): void {
    const blob = new Blob([resultCsv(operation)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `matter-bulk-update-${operation.id}-results.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  async function downloadTemplate(format: "csv" | "xlsx"): Promise<void> {
    try {
      setDownloading(true);
      const blob = await downloadMatterBulkUpdateTemplate(format);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `matter-bulk-update-template.${format}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(apiErrorMessage(error, "Could not download the bulk-update template."));
    } finally {
      setDownloading(false);
    }
  }

  function displayValue(value: unknown): string {
    if (value === null || value === undefined || value === "") return "—";
    return String(value);
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Matters"
        title="Bulk update existing matters"
        description="Preview and apply changes by exact Matter Code. Rows never create new matters."
        actions={<Button variant="outline" href="/app/matters"><Check className="h-4 w-4" /> Back to matters</Button>}
      />
      <section className="flex flex-col gap-4 border-y border-[var(--color-line)] py-5">
        <p className="max-w-3xl text-sm text-[var(--color-ink-2)]">
          Matter Code must identify an existing matter in this workspace. Blank cells keep current values;
          status and lifecycle changes use the matter lifecycle workflow. Formula cells are rejected.
          Preview lists exact old and new values, and only reviewed valid rows are applied.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <span className="mr-2 text-sm font-medium">Download template</span>
          <Button type="button" variant="outline" disabled={downloading} onClick={() => void downloadTemplate("xlsx")}>
            <Download className="h-4 w-4" /> XLSX
          </Button>
          <Button type="button" variant="outline" disabled={downloading} onClick={() => void downloadTemplate("csv")}>
            <Download className="h-4 w-4" /> CSV
          </Button>
          <span className="text-xs text-[var(--color-ink-2)]">Maximum 500 data rows and 5 MiB per file.</span>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex min-w-0 flex-1 flex-col gap-1.5 text-sm font-medium">
            CSV or XLSX file
            <input
              type="file"
              accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              className="block min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 py-2 text-sm"
              onChange={(event) => {
                const selected = event.target.files?.[0] ?? null;
                setFile(selected);
                setPreview(null);
                setResult(null);
              }}
            />
          </label>
          <Button
            type="button"
            disabled={!file || previewMutation.isPending}
            onClick={() => file && previewMutation.mutate(file)}
          >
            {previewMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            Preview changes
          </Button>
        </div>
        {file ? <p className="text-xs text-[var(--color-ink-2)]">{file.name} · {(file.size / (1024 * 1024)).toFixed(2)} MiB</p> : null}
        {preview?.summary ? (
          <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-[var(--color-ink-2)]" data-testid="bulk-update-summary">
            <span><strong>{preview.summary.total_rows}</strong> rows</span>
            <span><strong>{preview.summary.changed_rows}</strong> changed</span>
            <span><strong>{preview.summary.unchanged_rows}</strong> unchanged</span>
            <span><strong>{preview.summary.invalid_rows}</strong> invalid (will be skipped)</span>
          </div>
        ) : null}
        {result?.operation_id ? (
          <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm" data-testid="bulk-update-final-result">
            <strong>Final result</strong>
            <span>{result.total_rows} rows</span>
            <span>{result.valid_rows} valid</span>
            <span>{result.applied_rows} updated</span>
            <span>{result.skipped_rows} skipped</span>
            <span>{result.failed_rows} failed</span>
          </div>
        ) : null}
        {(preview ?? result) ? (
          <div className="overflow-x-auto border border-[var(--color-line)]">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-[var(--color-bg-2)] text-xs uppercase tracking-wide">
                <tr><th className="px-3 py-2">Row</th><th className="px-3 py-2">Matter</th><th className="px-3 py-2">Result</th><th className="px-3 py-2">Changes / errors</th></tr>
              </thead>
              <tbody>
                {(preview ?? result)?.rows.map((row) => (
                  <tr key={row.row_number} className="border-t border-[var(--color-line)] align-top">
                    <td className="px-3 py-2 font-mono">{row.row_number}</td>
                    <td className="px-3 py-2 font-mono">{row.matter_code ?? "—"}</td>
                    <td className="px-3 py-2">{row.status}</td>
                    <td className="px-3 py-2">
                      {row.errors.length ? <ul className="list-disc pl-4">{row.errors.map((error) => <li key={error}>{error}</li>)}</ul> : Object.keys(row.changes).length ? (
                        <dl className="grid gap-1">
                          {Object.entries(row.changes).map(([field, change]) => (
                            <div key={field} className="grid min-w-[28rem] grid-cols-[minmax(8rem,auto)_1fr] gap-x-3">
                              <dt className="font-medium">{field.replaceAll("_", " ")}</dt>
                              <dd><span className="text-[var(--color-ink-2)]">{displayValue(change.old)}</span> <span aria-hidden="true">→</span> <strong>{displayValue(change.new)}</strong></dd>
                            </div>
                          ))}
                        </dl>
                      ) : "No changes"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="flex items-center gap-2 text-sm text-[var(--color-ink-2)]"><FileSpreadsheet className="h-4 w-4" /> Select the exact workbook template to begin.</p>
        )}
        <div>
          <Button
            type="button"
            disabled={!preview || !file || preview.summary?.changed_rows === 0 || applyMutation.isPending}
            onClick={() => applyMutation.mutate()}
          >
            {applyMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
            Apply reviewed changes
          </Button>
        </div>
      </section>
      <section className="flex flex-col gap-3" aria-labelledby="bulk-update-history-heading">
        <h2 id="bulk-update-history-heading" className="text-lg font-semibold">Operation history</h2>
        {historyLoadFailed ? <p role="alert" className="text-sm">Could not load operation history. Reload to try again.</p> : null}
        {history?.operations.length ? (
          <div className="overflow-x-auto border border-[var(--color-line)]">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-[var(--color-bg-2)] text-xs uppercase"><tr><th className="px-3 py-2">File</th><th className="px-3 py-2">Uploader</th><th className="px-3 py-2">Time</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Rows</th><th className="px-3 py-2">Updated</th><th className="px-3 py-2">Skipped / failed</th><th className="px-3 py-2">Results</th></tr></thead>
              <tbody>{history.operations.map((operation) => {
                // Uploads commonly reuse one filename and can share a displayed
                // second; the operation ID keeps each action label unique.
                const uploadedAt = new Date(operation.created_at).toLocaleString();
                const isThisUpload = operation.id === result?.operation_id;
                return (
                  <Fragment key={operation.id}>
                    <tr className="border-t border-[var(--color-line)]" data-testid={`bulk-update-operation-${operation.id}`} aria-current={isThisUpload ? "true" : undefined}>
                      <td className="px-3 py-2">{operation.filename}{isThisUpload ? <span className="ml-2 text-xs font-medium text-[var(--color-ink-2)]">This upload</span> : null}</td>
                      <td className="px-3 py-2">{operation.uploader_name ?? operation.uploader_email ?? "Former member"}</td>
                      <td className="px-3 py-2">{uploadedAt}</td>
                      <td className="px-3 py-2">{operation.status}</td>
                      <td className="px-3 py-2">{operation.total_rows}</td>
                      <td className="px-3 py-2">{operation.applied_rows}</td>
                      <td className="px-3 py-2">{operation.skipped_rows} / {operation.failed_rows}</td>
                      <td className="px-3 py-2"><div className="flex gap-1"><Button type="button" variant="outline" aria-label={`View results for ${operation.filename} uploaded ${uploadedAt}, operation ${operation.id}`} aria-expanded={expandedOperationId === operation.id} onClick={() => setExpandedOperationId(expandedOperationId === operation.id ? null : operation.id)}><Eye className="h-4 w-4" /></Button><Button type="button" variant="outline" aria-label={`Download results for ${operation.filename} uploaded ${uploadedAt}, operation ${operation.id}`} onClick={() => downloadResult(operation)}><Download className="h-4 w-4" /></Button></div></td>
                    </tr>
                    {expandedOperationId === operation.id ? <tr data-testid={`bulk-update-operation-results-${operation.id}`}><td colSpan={8} className="px-3 py-2"><ul className="space-y-1 text-sm">{operation.rows.map((row) => <li key={row.row_number}>Row {row.row_number}: {row.matter_code ?? "Restricted matter"} — {row.status}{row.changed_fields.length ? ` (${row.changed_fields.join(", ")})` : ""}{row.errors.length ? ` — ${row.errors.join("; ")}` : ""}</li>)}</ul></td></tr> : null}
                  </Fragment>
                );
              })}</tbody>
            </table>
          </div>
        ) : !historyLoadFailed && history ? <p className="text-sm text-[var(--color-ink-2)]">No update operations have been recorded.</p> : null}
      </section>
    </div>
  );
}
