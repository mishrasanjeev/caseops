"use client";

import { Check, FileSpreadsheet, Loader2, Upload } from "lucide-react";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { apiErrorMessage } from "@/lib/api/config";
import {
  applyMatterBulkUpdate,
  previewMatterBulkUpdate,
  type MatterBulkUpdateResult,
} from "@/lib/api/endpoints";

export default function MatterBulkUpdatePage(): React.JSX.Element {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<MatterBulkUpdateResult | null>(null);
  const queryClient = useQueryClient();
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
      toast.success(`Updated ${result.applied_rows ?? 0} existing matters.`);
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not apply workbook.")),
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Matters"
        title="Bulk update existing matters"
        description="Preview and apply changes by exact Matter Code. Rows never create new matters."
        actions={<Button variant="outline" href="/app/matters"><Check className="h-4 w-4" /> Back to matters</Button>}
      />
      <section className="flex flex-col gap-4 border-y border-[var(--color-line)] py-5">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex min-w-0 flex-1 flex-col gap-1.5 text-sm font-medium">
            XLSX template
            <input
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
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
            <span><strong>{preview.summary.invalid_rows}</strong> invalid</span>
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
                      {row.errors.length ? row.errors.join(" ") : Object.keys(row.changes).join(", ") || "No changes"}
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
            disabled={!preview || !file || preview.summary?.changed_rows === 0 || preview.summary?.invalid_rows !== 0 || applyMutation.isPending}
            onClick={() => applyMutation.mutate()}
          >
            {applyMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
            Apply reviewed changes
          </Button>
        </div>
      </section>
    </div>
  );
}
