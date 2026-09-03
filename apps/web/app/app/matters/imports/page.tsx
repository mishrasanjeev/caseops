"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CheckCircle2,
  Download,
  FileDown,
  FileSpreadsheet,
  Loader2,
  Search,
  UploadCloud,
  XCircle,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { apiErrorMessage } from "@/lib/api/config";
import {
  cancelMatterImport,
  commitMatterImport,
  downloadMatterImportErrors,
  downloadMatterImportTemplate,
  getMatterImport,
  listMatterImports,
  previewMatterImport,
  type MatterImportJob,
  type MatterImportJobStatus,
  type MatterImportRow,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function metricTone(value: number, kind: "neutral" | "good" | "bad") {
  if (kind === "good" && value > 0) return "text-[var(--color-success-600)]";
  if (kind === "bad" && value > 0) return "text-[var(--color-danger-600)]";
  return "text-[var(--color-ink)]";
}

function Metric({
  label,
  value,
  kind = "neutral",
}: {
  label: string;
  value: number | string;
  kind?: "neutral" | "good" | "bad";
}) {
  return (
    <div className="rounded-md border border-[var(--color-line)] bg-white p-3">
      <div className="text-xs font-semibold uppercase text-[var(--color-mute)]">{label}</div>
      <div className={`mt-1 text-xl font-semibold ${typeof value === "number" ? metricTone(value, kind) : "text-[var(--color-ink)]"}`}>
        {value}
      </div>
    </div>
  );
}

function normalizedText(row: MatterImportRow, key: string): string {
  const value = row.normalized[key];
  return value === null || value === undefined ? "—" : String(value);
}

function statusTone(status: string): "success" | "warning" | "neutral" {
  if (status === "completed" || status === "created" || status === "valid") return "success";
  if (status === "failed" || status === "invalid" || status === "expired") return "warning";
  if (status === "completed_with_errors" || status === "importing") return "warning";
  // A duplicate is skipped, not rejected: it needs no correction from the user.
  return "neutral";
}

export default function BulkMatterImportPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const canBulkImport = useCapability("matters:bulk_import");
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<MatterImportJob | null>(null);
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [historyStatus, setHistoryStatus] = useState<MatterImportJobStatus | "all">("all");
  const [downloading, setDownloading] = useState<"csv" | "xlsx" | "errors" | null>(null);

  const history = useQuery({
    queryKey: ["matter-imports", "history", appliedSearch, historyStatus],
    queryFn: () => listMatterImports({ q: appliedSearch, status: historyStatus, limit: 50 }),
    enabled: canBulkImport,
  });

  const previewMutation = useMutation({
    mutationFn: (selected: File) => previewMatterImport(selected),
    onSuccess: async (result) => {
      setJob(result);
      await queryClient.invalidateQueries({ queryKey: ["matter-imports", "history"] });
      const skipped = result.duplicate_rows
        ? ` ${result.duplicate_rows} duplicate rows will be skipped.`
        : "";
      if (result.invalid_rows) {
        toast.error(
          `${result.invalid_rows} rows need correction before they can be imported.${skipped}`,
        );
      } else {
        toast.success(`All ${result.valid_rows} matter rows passed validation.${skipped}`);
      }
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not validate matter import.")),
  });

  const commitMutation = useMutation({
    mutationFn: () => {
      if (!job) throw new Error("Validate a file before importing.");
      return commitMatterImport(job.id);
    },
    onSuccess: async (result) => {
      setJob(result.job);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["matters"] }),
        queryClient.invalidateQueries({ queryKey: ["matter-imports", "history"] }),
      ]);
      const skipped = result.job.duplicate_rows
        ? `; ${result.job.duplicate_rows} duplicate rows skipped`
        : "";
      const message = `${result.job.created_count} matters created${skipped}; ${result.job.failed_count} rows failed.`;
      if (result.job.failed_count) toast.error(message);
      else toast.success(message);
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not import matter rows.")),
  });

  const cancelMutation = useMutation({
    mutationFn: () => {
      if (!job) throw new Error("No import to cancel.");
      return cancelMatterImport(job.id);
    },
    onSuccess: async (result) => {
      setJob(result);
      await queryClient.invalidateQueries({ queryKey: ["matter-imports", "history"] });
      toast.success("Matter import cancelled.");
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not cancel matter import.")),
  });

  const historyDetailMutation = useMutation({
    mutationFn: (jobId: string) => getMatterImport(jobId),
    onSuccess: (result) => setJob(result),
    onError: (error) => toast.error(apiErrorMessage(error, "Could not load import details.")),
  });

  const pending = previewMutation.isPending || commitMutation.isPending || cancelMutation.isPending;
  const canCommit = Boolean(job && job.status === "validated" && job.valid_rows > 0 && !pending);
  // Rows needing correction first, then skipped duplicates, then a sample of
  // the rows that are ready.
  const errorRows = job?.rows.filter((row) => row.status !== "duplicate" && row.errors.length > 0) ?? [];
  const duplicateRows = job?.rows.filter((row) => row.status === "duplicate") ?? [];
  const previewRows = job
    ? [
        ...errorRows,
        ...duplicateRows,
        ...job.rows
          .filter((row) => row.status !== "duplicate" && row.errors.length === 0)
          .slice(0, 50),
      ]
    : [];

  async function downloadTemplate(format: "csv" | "xlsx") {
    try {
      setDownloading(format);
      const blob = await downloadMatterImportTemplate(format);
      triggerDownload(blob, `caseops-matter-import-template.${format}`);
    } catch (error) {
      toast.error(apiErrorMessage(error, "Could not download matter template."));
    } finally {
      setDownloading(null);
    }
  }

  async function downloadErrors() {
    if (!job) return;
    try {
      setDownloading("errors");
      const blob = await downloadMatterImportErrors(job.id);
      triggerDownload(blob, `matter-import-errors-${job.id}.csv`);
    } catch (error) {
      toast.error(apiErrorMessage(error, "Could not download matter errors."));
    } finally {
      setDownloading(null);
    }
  }

  if (!canBulkImport) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          eyebrow="Matters"
          title="Bulk upload matters"
          description="This workflow is available to Owners, Admins, and delegated Matter Managers."
          actions={
            <Button variant="outline" onClick={() => router.push("/app/matters")}>
              <ArrowLeft className="h-4 w-4" /> Matter portfolio
            </Button>
          }
        />
        <div className="rounded-lg border border-[var(--color-line)] bg-white p-8 text-center">
          <XCircle className="mx-auto h-10 w-10 text-[var(--color-mute-2)]" />
          <h2 className="mt-3 font-semibold text-[var(--color-ink)]">Permission required</h2>
          <p className="mt-1 text-sm text-[var(--color-mute)]">
            Ask a workspace Owner to grant the Matter Manager bulk-import capability.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Matters"
        title="Bulk upload matters"
        description="Download the controlled template, validate every row, then import all valid matters with a permanent audit trail."
        actions={
          <Button variant="outline" onClick={() => router.push("/app/matters")}>
            <ArrowLeft className="h-4 w-4" /> Matter portfolio
          </Button>
        }
      />

      <section className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <div className="flex flex-col gap-4 rounded-lg border border-[var(--color-line)] bg-white p-4">
          <div>
            <div className="flex items-center gap-2 font-semibold text-[var(--color-ink)]">
              <FileSpreadsheet className="h-5 w-5" /> 1. Download template
            </div>
            <p className="mt-1 text-sm text-[var(--color-mute)]">
              XLSX includes reference values and instructions. CSV is provided for migrations.
            </p>
            <div
              className="mt-3 space-y-1.5 rounded-md bg-[var(--color-bg-2)] p-3 text-xs text-[var(--color-mute)]"
              data-testid="matter-import-compatibility-guidance"
            >
              <p>
                Client registers that match the documented formats are supported:
                familiar header aliases, title rows, later XLSX worksheets, and
                case-insensitive Status/Forum values are normalized where possible.
              </p>
              <p>
                Matter Title, Matter Code, Practice Area, and Forum are required. Client
                Name is optional, and blank Matter Status defaults to Active. Court Forum
                Number is stored separately from Court.
              </p>
              <p>
                Forum accepts either a hierarchy or a unique Exact Court/approved alias
                from the active catalog. Exact-court values automatically fill the full
                hierarchy; unknown, inactive, or ambiguous values are rejected rather
                than guessed.
              </p>
              <p>
                Quote fields that contain the selected CSV delimiter. Matter Code and
                selected-table formula protections remain strict. A leading + is allowed
                only for Client Contact Number; its main-number portion may use digits,
                spaces, parentheses, and hyphens. Phones need 7-20 main digits, may have a
                trailing ext, ext., or x followed by 1-10 digits, and cannot contain +
                anywhere else.
              </p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {(["xlsx", "csv"] as const).map((format) => (
              <Button
                key={format}
                variant="outline"
                disabled={downloading !== null}
                onClick={() => void downloadTemplate(format)}
                data-testid={`matter-import-template-${format}`}
              >
                {downloading === format ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />}
                {format.toUpperCase()}
              </Button>
            ))}
          </div>

          <div className="border-t border-[var(--color-line)] pt-4">
            <Label htmlFor="matter-import-file">2. Upload completed file</Label>
            <Input
              id="matter-import-file"
              className="mt-2"
              type="file"
              accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setJob(null);
              }}
              data-testid="matter-import-file"
            />
            {file ? (
              <p className="mt-2 text-xs text-[var(--color-mute)]">
                {file.name} · {Math.max(1, Math.ceil(file.size / 1024))} KB
              </p>
            ) : null}
          </div>
          <Button
            disabled={!file || pending}
            onClick={() => file && previewMutation.mutate(file)}
            data-testid="matter-import-validate"
          >
            {previewMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
            Validate data before import
          </Button>
          <p className="text-xs text-[var(--color-mute)]">
            Limit: 500 rows / 2 MB. Files are checked for unsafe formulas, tenant references, required fields, formats, and active users/teams. Rows that duplicate an existing matter are skipped automatically.
          </p>
        </div>

        <div className="min-h-96 rounded-lg border border-[var(--color-line)] bg-white">
          {!job ? (
            <div className="flex min-h-96 flex-col items-center justify-center gap-3 p-8 text-center">
              <FileSpreadsheet className="h-10 w-10 text-[var(--color-mute-2)]" />
              <div className="font-semibold text-[var(--color-ink)]">Validation results will appear here</div>
              <p className="max-w-lg text-sm text-[var(--color-mute)]">
                No matters are created until you review the row-level results and confirm the import.
              </p>
            </div>
          ) : (
            <div className="flex flex-col">
              <div className="grid gap-3 border-b border-[var(--color-line)] bg-[var(--color-bg-2)] p-4 sm:grid-cols-6">
                <Metric label="Total records" value={job.total_rows} />
                <Metric label="Valid" value={job.valid_rows} kind="good" />
                <Metric label="Duplicates skipped" value={job.duplicate_rows} />
                <Metric
                  label="Validation errors"
                  value={job.validation_error_count}
                  kind="bad"
                />
                <Metric label="Imported" value={job.created_count} kind="good" />
                <Metric label="Failed" value={job.failed_count} kind="bad" />
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--color-line)] p-4">
                <div className="flex items-center gap-2">
                  <Badge tone={statusTone(job.status)}>{job.status.replaceAll("_", " ")}</Badge>
                  <span className="text-sm text-[var(--color-mute)]">{job.filename}</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {job.invalid_rows > 0 || job.failed_count > 0 || job.duplicate_rows > 0 ? (
                    <Button variant="outline" onClick={() => void downloadErrors()} disabled={downloading !== null}>
                      {downloading === "errors" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                      Download row report
                    </Button>
                  ) : null}
                  {job.status === "validated" ? (
                    <Button variant="ghost" onClick={() => cancelMutation.mutate()} disabled={pending}>
                      Cancel
                    </Button>
                  ) : null}
                  <Button
                    onClick={() => commitMutation.mutate()}
                    disabled={!canCommit}
                    data-testid="matter-import-confirm"
                  >
                    {commitMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                    Confirm import ({job.valid_rows})
                  </Button>
                </div>
              </div>
              <div className="max-h-[520px] overflow-auto">
                <table className="min-w-full divide-y divide-[var(--color-line)] text-sm">
                  <thead className="sticky top-0 bg-[var(--color-bg-2)] text-left text-xs font-semibold uppercase text-[var(--color-mute)]">
                    <tr>
                      <th className="px-3 py-2">Row</th>
                      <th className="px-3 py-2">Matter code</th>
                      <th className="px-3 py-2">Matter title</th>
                      <th className="px-3 py-2">Client</th>
                      <th className="px-3 py-2">Court forum no.</th>
                      <th className="px-3 py-2">Status</th>
                      <th className="px-3 py-2">Outcome</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--color-line)]">
                    {previewRows.map((row) => (
                      <tr
                        key={row.id}
                        className={
                          row.status === "duplicate"
                            ? "bg-[var(--color-bg-2)]"
                            : row.errors.length
                              ? "bg-[var(--color-danger-50)]"
                              : undefined
                        }
                      >
                        <td className="px-3 py-2 tabular-nums">{row.row_number}</td>
                        <td className="px-3 py-2 font-mono text-xs">{normalizedText(row, "matter_code")}</td>
                        <td className="px-3 py-2">{normalizedText(row, "title")}</td>
                        <td className="px-3 py-2">{normalizedText(row, "client_name")}</td>
                        <td className="px-3 py-2">
                          {normalizedText(row, "court_forum_number")}
                        </td>
                        <td className="px-3 py-2"><Badge tone={statusTone(row.status)}>{row.status}</Badge></td>
                        <td className="max-w-md px-3 py-2">
                          {row.status === "duplicate" ? (
                            <div className="text-xs text-[var(--color-mute)]">
                              <div className="font-medium">Skipped — already exists</div>
                              <ul className="mt-1 space-y-1">
                                {row.errors.map((error) => <li key={error}>• {error}</li>)}
                              </ul>
                            </div>
                          ) : row.errors.length ? (
                            <ul className="space-y-1 text-xs text-[var(--color-danger-700)]">
                              {row.errors.map((error) => <li key={error}>• {error}</li>)}
                            </ul>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-xs text-[var(--color-success-600)]">
                              <CheckCircle2 className="h-3.5 w-3.5" /> Ready
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {job.rows.length > previewRows.length ? (
                <div className="border-t border-[var(--color-line)] p-3 text-xs text-[var(--color-mute)]">
                  {job.rows.length - previewRows.length} additional valid rows are hidden from this on-screen preview; all remain included in the confirmed import.
                </div>
              ) : null}
            </div>
          )}
        </div>
      </section>

      <section className="rounded-lg border border-[var(--color-line)] bg-white">
        <div className="flex flex-wrap items-end justify-between gap-3 border-b border-[var(--color-line)] p-4">
          <div>
            <h2 className="font-semibold text-[var(--color-ink)]">Import history</h2>
            <p className="text-sm text-[var(--color-mute)]">Search by file name, uploader name, or uploader email.</p>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <Label htmlFor="matter-import-history-search">Search</Label>
              <Input
                id="matter-import-history-search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                onKeyDown={(event) => event.key === "Enter" && setAppliedSearch(search)}
                placeholder="File or uploaded by"
              />
            </div>
            <div>
              <Label htmlFor="matter-import-history-status">Status</Label>
              <select
                id="matter-import-history-status"
                className="h-10 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                value={historyStatus}
                onChange={(event) => setHistoryStatus(event.target.value as MatterImportJobStatus | "all")}
              >
                <option value="all">All</option>
                <option value="validated">Validated</option>
                <option value="completed">Completed</option>
                <option value="completed_with_errors">Completed with errors</option>
                <option value="cancelled">Cancelled</option>
                <option value="failed">Failed</option>
                <option value="expired">Expired</option>
              </select>
            </div>
            <Button variant="outline" onClick={() => setAppliedSearch(search)}>
              <Search className="h-4 w-4" /> Search
            </Button>
          </div>
        </div>
        {history.isPending ? (
          <div className="flex items-center justify-center p-8"><Loader2 className="h-5 w-5 animate-spin" /></div>
        ) : history.isError ? (
          <div className="flex items-center gap-2 p-6 text-sm text-[var(--color-danger-600)]">
            <XCircle className="h-5 w-5" /> Could not load import history.
          </div>
        ) : history.data?.imports.length ? (
          <div className="overflow-auto">
            <table className="min-w-full divide-y divide-[var(--color-line)] text-sm">
              <thead className="bg-[var(--color-bg-2)] text-left text-xs font-semibold uppercase text-[var(--color-mute)]">
                <tr><th className="px-4 py-2">Upload date</th><th className="px-4 py-2">File name</th><th className="px-4 py-2">Uploaded by</th><th className="px-4 py-2">Status</th><th className="px-4 py-2">Records</th><th className="px-4 py-2">Imported</th><th className="px-4 py-2">Failed</th></tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-line)]">
                {history.data.imports.map((item) => (
                  <tr
                    key={item.id}
                    className="cursor-pointer hover:bg-[var(--color-bg-2)]"
                    onClick={() => historyDetailMutation.mutate(item.id)}
                  >
                    <td className="px-4 py-3">{new Date(item.created_at).toLocaleString()}</td>
                    <td className="px-4 py-3 font-medium">{item.filename}</td>
                    <td className="px-4 py-3">{item.uploaded_by_name ?? item.uploaded_by_email ?? "Former user"}</td>
                    <td className="px-4 py-3"><Badge tone={statusTone(item.status)}>{item.status.replaceAll("_", " ")}</Badge></td>
                    <td className="px-4 py-3 tabular-nums">{item.total_rows}</td>
                    <td className="px-4 py-3 tabular-nums">{item.created_count}</td>
                    <td className="px-4 py-3 tabular-nums">{item.failed_count || item.invalid_rows}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-8 text-center text-sm text-[var(--color-mute)]">No matching matter imports.</div>
        )}
      </section>
    </div>
  );
}
