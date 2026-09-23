"use client";

import { Check, Download, FileSpreadsheet, Loader2, Upload } from "lucide-react";
import { useEffect, useState } from "react";
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
  type MatterBulkUpdateResult,
} from "@/lib/api/endpoints";

export default function MatterBulkUpdatePage(): React.JSX.Element {
  const [file, setFile] = useState<File | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [preview, setPreview] = useState<MatterBulkUpdateResult | null>(null);
  const queryClient = useQueryClient();
  const [history, setHistory] = useState<Awaited<ReturnType<typeof listMatterBulkUpdateHistory>> | null>(null);
  useEffect(() => {
    let active = true;
    void listMatterBulkUpdateHistory().then((result) => {
      if (active) setHistory(result);
    }).catch(() => {
      if (active) setHistory({ operations: [], total: 0 });
    });
    return () => { active = false; };
  }, []);
  const previewMutation = useMutation({
    mutationFn: (selected: File) => previewMatterBulkUpdate(selected),
    onSuccess: setPreview,
    onError: (error) => toast.error(apiErrorMessage(error, "Could not preview workbook.")),
  });
  const applyMutation = useMutation({
    mutationFn: () => {
      if (!file || !preview) throw new Error("Preview the workbook first.");
      return applyMatterBulkUpdate({ file, previewToken: preview.preview_token });
    },
    onSuccess: async (result) => {
      setPreview(result);
      await queryClient.invalidateQueries({ queryKey: ["matters"] });
      const [updatedHistory] = await Promise.all([
        listMatterBulkUpdateHistory(),
        queryClient.invalidateQueries({ queryKey: ["matters", "bulk-update-history"] }),
      ]);
      setHistory(updatedHistory);
      const skipped = result.failed_rows ?? 0;
      toast.success(`Updated ${result.applied_rows ?? 0} existing matters; ${skipped} rows were skipped or failed.`);
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not apply workbook.")),
  });

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
        {preview?.summary ? (
          <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-[var(--color-ink-2)]" data-testid="bulk-update-summary">
            <span><strong>{preview.summary.total_rows}</strong> rows</span>
            <span><strong>{preview.summary.changed_rows}</strong> changed</span>
            <span><strong>{preview.summary.unchanged_rows}</strong> unchanged</span>
            <span><strong>{preview.summary.invalid_rows}</strong> invalid (will be skipped)</span>
          </div>
        ) : null}
        {preview ? (
          <div className="overflow-x-auto border border-[var(--color-line)]">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-[var(--color-bg-2)] text-xs uppercase tracking-wide">
                <tr><th className="px-3 py-2">Row</th><th className="px-3 py-2">Matter</th><th className="px-3 py-2">Result</th><th className="px-3 py-2">Changes / errors</th></tr>
              </thead>
              <tbody>
                {preview.rows.map((row) => (
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
        {history?.operations.length ? (
          <div className="overflow-x-auto border border-[var(--color-line)]">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-[var(--color-bg-2)] text-xs uppercase"><tr><th className="px-3 py-2">File</th><th className="px-3 py-2">Uploader</th><th className="px-3 py-2">Time</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Rows</th><th className="px-3 py-2">Applied</th><th className="px-3 py-2">Invalid / failed</th></tr></thead>
              <tbody>{history.operations.map((operation) => <tr key={operation.id} className="border-t border-[var(--color-line)]"><td className="px-3 py-2">{operation.filename}</td><td className="px-3 py-2">{operation.uploader_name ?? operation.uploader_email ?? "Former member"}</td><td className="px-3 py-2">{new Date(operation.created_at).toLocaleString()}</td><td className="px-3 py-2">{operation.status}</td><td className="px-3 py-2">{operation.total_rows}</td><td className="px-3 py-2">{operation.applied_rows}</td><td className="px-3 py-2">{operation.invalid_rows} / {operation.failed_rows}</td></tr>)}</tbody>
            </table>
          </div>
        ) : <p className="text-sm text-[var(--color-ink-2)]">No update operations have been recorded.</p>}
      </section>
    </div>
  );
}
