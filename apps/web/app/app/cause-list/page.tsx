"use client";

import { useMutation } from "@tanstack/react-query";
import { Download, FileText, Loader2, Search } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { apiErrorMessage } from "@/lib/api/config";
import { downloadCauseListPdf, previewCauseList, type CauseListPreviewInput } from "@/lib/api/endpoints";

function todayIso(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(
    now.getDate(),
  ).padStart(2, "0")}`;
}

export default function CauseListPage() {
  const [dateFrom, setDateFrom] = useState(todayIso());
  const [dateTo, setDateTo] = useState(todayIso());
  const [court, setCourt] = useState("");
  const [practiceArea, setPracticeArea] = useState("");
  const [matterStatus, setMatterStatus] = useState("all");
  const [includeDisposed, setIncludeDisposed] = useState(false);
  const [source, setSource] = useState<"hearings" | "cause_list_entries" | "both">("both");
  const [sort, setSort] = useState<"hearing_date" | "court" | "lawyer" | "serial">("hearing_date");

  const payload = (): CauseListPreviewInput => ({
    date_from: dateFrom,
    date_to: dateTo,
    court: court.trim() || null,
    practice_area: practiceArea.trim() || null,
    matter_status: matterStatus === "all" ? null : matterStatus,
    include_disposed: includeDisposed,
    source,
    sort,
  });

  const previewMutation = useMutation({
    mutationFn: () => previewCauseList(payload()),
    onError: (err) => toast.error(apiErrorMessage(err, "Could not load cause list.")),
  });
  const downloadMutation = useMutation({
    mutationFn: () => downloadCauseListPdf(payload()),
    onError: (err) => toast.error(apiErrorMessage(err, "Could not download cause list.")),
  });

  const rows = previewMutation.data?.rows ?? [];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Cause list"
        description="Generate a date-wise printable cause list from visible hearings and imported cause-list entries."
      />

      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
          <CardDescription>Missing court-list fields are shown explicitly in the preview.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-[repeat(4,minmax(0,1fr))_auto] md:items-end">
          <Field label="From">
            <Input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
          </Field>
          <Field label="To">
            <Input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
          </Field>
          <Field label="Court">
            <Input value={court} onChange={(event) => setCourt(event.target.value)} />
          </Field>
          <Field label="Practice area">
            <Input value={practiceArea} onChange={(event) => setPracticeArea(event.target.value)} />
          </Field>
          <Field label="Status">
            <select
              className="h-10 rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] px-3 text-sm"
              value={matterStatus}
              onChange={(event) => setMatterStatus(event.target.value)}
            >
              <option value="all">All</option>
              <option value="intake">Intake</option>
              <option value="active">Active</option>
              <option value="on_hold">On hold</option>
              <option value="disposed">Dispose</option>
            </select>
          </Field>
          <Field label="Source">
            <select
              className="h-10 rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] px-3 text-sm"
              value={source}
              onChange={(event) => setSource(event.target.value as typeof source)}
            >
              <option value="both">Both</option>
              <option value="hearings">Hearings</option>
              <option value="cause_list_entries">Cause-list entries</option>
            </select>
          </Field>
          <Field label="Sort">
            <select
              className="h-10 rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] px-3 text-sm"
              value={sort}
              onChange={(event) => setSort(event.target.value as typeof sort)}
            >
              <option value="hearing_date">Date</option>
              <option value="court">Court</option>
              <option value="lawyer">Lawyer</option>
            </select>
          </Field>
          <label className="flex items-center gap-2 pb-2 text-sm text-[var(--color-ink-2)]">
            <input
              type="checkbox"
              checked={includeDisposed}
              onChange={(event) => setIncludeDisposed(event.target.checked)}
            />
            <span>Include disposed</span>
          </label>
          <div className="flex gap-2">
            <Button type="button" onClick={() => previewMutation.mutate()} disabled={previewMutation.isPending}>
              {previewMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              Preview
            </Button>
            <Button type="button" variant="outline" onClick={() => downloadMutation.mutate()} disabled={downloadMutation.isPending}>
              {downloadMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
              PDF
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Preview</CardTitle>
          <CardDescription>{rows.length} row{rows.length === 1 ? "" : "s"}</CardDescription>
        </CardHeader>
        <CardContent>
          {!previewMutation.data ? (
            <EmptyState icon={FileText} title="No preview yet" description="Choose a date or range and run the preview." />
          ) : rows.length === 0 ? (
            <EmptyState icon={FileText} title="No listed matters" description="No visible matters matched the selected filters." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[980px] text-sm">
                <thead>
                  <tr className="border-b border-[var(--color-line)] text-left text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]">
                    <th className="px-3 py-2">Sr</th>
                    <th className="px-3 py-2">File</th>
                    <th className="px-3 py-2">Court</th>
                    <th className="px-3 py-2">Case</th>
                    <th className="px-3 py-2">Title</th>
                    <th className="px-3 py-2">Judge</th>
                    <th className="px-3 py-2">Court/Item</th>
                    <th className="px-3 py-2">Lawyer</th>
                    <th className="px-3 py-2">Date</th>
                    <th className="px-3 py-2">Warnings</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={`${row.source}-${row.source_ref ?? row.serial_number}`} className="border-b border-[var(--color-line-2)]">
                      <td className="px-3 py-2">{row.serial_number}</td>
                      <td className="px-3 py-2 font-mono text-xs">{row.file_number}</td>
                      <td className="px-3 py-2">{row.court_name}</td>
                      <td className="px-3 py-2">{row.case_number}</td>
                      <td className="px-3 py-2">{row.case_title}</td>
                      <td className="px-3 py-2">{row.judge_name}</td>
                      <td className="px-3 py-2">{row.court_number}/{row.item_number}</td>
                      <td className="px-3 py-2">{row.lawyers_appearing}</td>
                      <td className="px-3 py-2">{row.hearing_date}</td>
                      <td className="px-3 py-2">
                        {row.missing_field_warnings.length ? (
                          <StatusBadge status="pending" />
                        ) : (
                          <StatusBadge status="completed" />
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-sm font-medium text-[var(--color-ink-2)]">{label}</span>
      {children}
    </label>
  );
}
