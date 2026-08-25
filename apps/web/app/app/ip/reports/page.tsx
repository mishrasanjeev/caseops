"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, FileChartColumn, LoaderCircle, Play, RefreshCw, Send } from "lucide-react";
import { useMemo, useState } from "react";
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
import { apiErrorMessage } from "@/lib/api/config";
import {
  fetchIpReportFoundation,
  previewIpReport,
  type IpReportKind,
  type IpReportPreview,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import {
  fetchAdminPortalIpGrants,
  publishIpReportToPortal,
} from "@/lib/api/portal";

const REPORT_LABEL: Record<IpReportKind, string> = {
  portfolio_register: "Portfolio register",
  application_status: "Application status",
  opposition_status: "Opposition status",
  deadline_control: "Deadline control",
  renewal: "Renewal",
  watch: "Watch",
  workload: "Workload",
  data_quality: "Data quality",
  integration_freshness: "Integration freshness",
};

const PORTFOLIO_FILTER_REPORTS = new Set<IpReportKind>([
  "portfolio_register",
  "application_status",
  "opposition_status",
  "data_quality",
]);

const RENEWAL_STATES = [
  "due",
  "instructed",
  "filing_in_progress",
  "filed",
  "accepted",
  "grace",
  "overdue",
  "completed",
  "cancelled",
] as const;

const STAMP = new Intl.DateTimeFormat("en-IN", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "UTC",
});

function label(value: string) {
  return value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not available";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.length ? value.map(displayValue).join(", ") : "None";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function freshnessTone(status: IpReportPreview["freshness"]["status"]) {
  if (status === "current") return "success" as const;
  return "warning" as const;
}

export default function IpReportsPage() {
  const canRead = useCapability("ip:read");
  const canManagePortal = useCapability("portal:manage_grants");
  const canApprove = useCapability("ip:approve");
  const canPublish = canManagePortal && canApprove;
  const [reportKind, setReportKind] = useState<IpReportKind>("portfolio_register");
  const [query, setQuery] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [renewalState, setRenewalState] = useState("all");
  const [confidentiality, setConfidentiality] = useState<"internal" | "restricted">("internal");
  const [rowLimitInput, setRowLimitInput] = useState("50");
  const [report, setReport] = useState<IpReportPreview | null>(null);
  const [portalUserId, setPortalUserId] = useState("");
  const [selectedGrantIds, setSelectedGrantIds] = useState<string[]>([]);
  const [publicationTitle, setPublicationTitle] = useState("");
  const [scheduledFor, setScheduledFor] = useState("");

  const contract = useQuery({
    queryKey: ["ip", "reports", "foundation"],
    queryFn: fetchIpReportFoundation,
    enabled: canRead,
  });
  const generation = useMutation({
    mutationFn: () =>
      previewIpReport({
        reportKind,
        rowLimit: Math.min(200, Math.max(1, Number(rowLimitInput) || 1)),
        confidentiality,
        filters: PORTFOLIO_FILTER_REPORTS.has(reportKind)
          ? {
              query: query.trim() || null,
              jurisdiction: jurisdiction.trim() ? [jurisdiction.trim()] : [],
            }
          : {},
        renewalStates:
          reportKind === "renewal" && renewalState !== "all" ? [renewalState] : [],
      }),
    onSuccess: setReport,
    onError: (error) => toast.error(apiErrorMessage(error, "Could not generate the report.")),
  });
  const grants = useQuery({
    queryKey: ["ip", "portal", "grants"],
    queryFn: fetchAdminPortalIpGrants,
    enabled: canPublish,
  });
  const activeGrants = grants.data?.grants.filter((grant) => grant.active) ?? [];
  const portalUsers = Array.from(
    new Map(activeGrants.map((grant) => [grant.portal_user_id, grant])).values(),
  );
  const publication = useMutation({
    mutationFn: () => {
      if (!report) throw new Error("Generate and review the report first.");
      return publishIpReportToPortal({
        portalUserId,
        grantIds: selectedGrantIds,
        title: publicationTitle.trim(),
        reportKind: report.report_kind,
        filters: (report.filters.portfolio as Record<string, unknown> | undefined) ?? {},
        renewalStates: (report.filters.renewal_states as string[] | undefined) ?? [],
        rowLimit: Number(report.filters.row_limit) || report.row_count || 1,
        expectedSnapshotSha256: report.snapshot_sha256,
        scheduledFor: scheduledFor ? new Date(scheduledFor).toISOString() : null,
      });
    },
    onSuccess: () => {
      toast.success(scheduledFor ? "Client report scheduled." : "Client report published.");
      setSelectedGrantIds([]);
      setPublicationTitle("");
      setScheduledFor("");
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not publish the client report.")),
  });
  const columns = useMemo(
    () => Array.from(new Set((report?.rows ?? []).flatMap((row) => Object.keys(row)))).slice(0, 10),
    [report?.rows],
  );

  if (!canRead) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title="IP reports" description="Internal IP reporting." />
        <EmptyState title="IP access required" description="Ask an owner or admin for IP read access." />
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        eyebrow="IP operations"
        title="IP reports"
        description="Current internal snapshots from the canonical IP records."
        actions={
          <Button variant="outline" size="sm" onClick={() => contract.refetch()} disabled={contract.isFetching}>
            <RefreshCw className={contract.isFetching ? "h-4 w-4 animate-spin" : "h-4 w-4"} aria-hidden />
            Refresh
          </Button>
        }
      />

      {contract.isPending ? <Skeleton className="h-60" /> : contract.isError ? (
        <QueryErrorState error={contract.error} title="Could not load IP reports" onRetry={() => contract.refetch()} />
      ) : (
        <Card>
          <CardHeader className="flex-row items-center justify-between gap-3">
            <CardTitle as="h2">Report scope</CardTitle>
            <Badge tone="neutral">Internal only</Badge>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
            <Field label="Report" htmlFor="report-kind">
              <select id="report-kind" value={reportKind} onChange={(event) => { setReportKind(event.target.value as IpReportKind); setReport(null); }} className="h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm">
                {contract.data?.definitions.map((definition) => <option key={definition.key} value={definition.key}>{REPORT_LABEL[definition.key]}</option>)}
              </select>
            </Field>
            {PORTFOLIO_FILTER_REPORTS.has(reportKind) ? (
              <>
                <Field label="Keyword" htmlFor="report-query"><Input id="report-query" value={query} onChange={(event) => setQuery(event.target.value)} /></Field>
                <Field label="Jurisdiction" htmlFor="report-jurisdiction"><Input id="report-jurisdiction" value={jurisdiction} onChange={(event) => setJurisdiction(event.target.value)} placeholder="IN" /></Field>
              </>
            ) : null}
            {reportKind === "renewal" ? (
              <Field label="Renewal state" htmlFor="renewal-state"><select id="renewal-state" value={renewalState} onChange={(event) => setRenewalState(event.target.value)} className="h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"><option value="all">All states</option>{RENEWAL_STATES.map((state) => <option key={state} value={state}>{label(state)}</option>)}</select></Field>
            ) : null}
            <Field label="Confidentiality" htmlFor="report-confidentiality"><select id="report-confidentiality" value={confidentiality} onChange={(event) => setConfidentiality(event.target.value as "internal" | "restricted")} className="h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"><option value="internal">Internal</option><option value="restricted">Restricted</option></select></Field>
            <Field label="Row limit" htmlFor="report-row-limit"><Input id="report-row-limit" type="number" min={1} max={200} value={rowLimitInput} onChange={(event) => setRowLimitInput(event.target.value)} /></Field>
            <div className="flex items-end"><Button className="w-full" onClick={() => generation.mutate()} disabled={generation.isPending}>{generation.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden /> : <Play className="h-4 w-4" aria-hidden />}{generation.isPending ? "Generating" : "Generate"}</Button></div>
          </CardContent>
        </Card>
      )}

      {report ? <ReportResult report={report} columns={columns} /> : !contract.isPending && !contract.isError ? (
        <EmptyState icon={FileChartColumn} title="No report generated" description="Select a report scope and generate a current snapshot." />
      ) : null}

      {report && canPublish && ["portfolio_register", "application_status", "opposition_status", "renewal"].includes(report.report_kind) ? (
        <Card data-testid="portal-report-publication">
          <CardHeader><CardTitle as="h2">Publish reviewed report</CardTitle></CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <Field label="Client" htmlFor="report-client"><select id="report-client" className="h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={portalUserId} onChange={(event) => { setPortalUserId(event.target.value); setSelectedGrantIds([]); }}><option value="">Select client</option>{portalUsers.map((grant) => <option key={grant.portal_user_id} value={grant.portal_user_id}>{grant.portal_user_name} · {grant.portal_user_email}</option>)}</select></Field>
            <Field label="Client title" htmlFor="report-client-title"><Input id="report-client-title" value={publicationTitle} onChange={(event) => setPublicationTitle(event.target.value)} /></Field>
            <Field label="Publish at" htmlFor="report-publish-at"><Input id="report-publish-at" type="datetime-local" value={scheduledFor} onChange={(event) => setScheduledFor(event.target.value)} /></Field>
            <div className="flex items-end"><Button className="w-full" onClick={() => publication.mutate()} disabled={publication.isPending || !portalUserId || !selectedGrantIds.length || publicationTitle.trim().length < 2 || report.confidentiality !== "internal"}><Send className="h-4 w-4" />{scheduledFor ? "Schedule" : "Publish"}</Button></div>
            <fieldset className="md:col-span-2 xl:col-span-4"><legend className="mb-2 text-sm font-semibold">Granted IP records</legend><div className="flex flex-wrap gap-3">{activeGrants.filter((grant) => grant.portal_user_id === portalUserId).map((grant) => <label key={grant.id} className="inline-flex items-center gap-2 text-sm"><input type="checkbox" checked={selectedGrantIds.includes(grant.id)} onChange={(event) => setSelectedGrantIds((current) => event.target.checked ? [...current, grant.id] : current.filter((id) => id !== grant.id))} />{grant.docket_title}</label>)}</div></fieldset>
            {report.confidentiality !== "internal" ? <p className="md:col-span-2 xl:col-span-4 text-sm text-amber-800">Generate an Internal preview before publishing. Restricted previews cannot be shared.</p> : null}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function Field({ label: fieldLabel, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) {
  return <div className="min-w-0 space-y-1.5"><Label htmlFor={htmlFor}>{fieldLabel}</Label>{children}</div>;
}

function ReportResult({ report, columns }: { report: IpReportPreview; columns: string[] }) {
  return (
    <Card className="min-w-0" data-testid="ip-report-result">
      <CardHeader className="gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle as="h2">{REPORT_LABEL[report.report_kind]}</CardTitle>
          <div className="flex flex-wrap gap-2"><Badge tone={freshnessTone(report.freshness.status)}>{label(report.freshness.status)}</Badge><Badge>{label(report.confidentiality)}</Badge><Badge>{report.row_count} rows</Badge></div>
        </div>
        <p className="text-sm text-[var(--color-mute)]">Generated {STAMP.format(new Date(report.generated_at))} UTC · Snapshot <span className="font-mono">{report.snapshot_sha256.slice(0, 12)}</span></p>
      </CardHeader>
      <CardContent className="space-y-5">
        {report.freshness.unavailable_sources.length ? <div className="flex items-start gap-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900" role="status"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /><span>Unavailable sources: {report.freshness.unavailable_sources.map(label).join(", ")}.</span></div> : null}
        <section aria-labelledby="report-summary-title"><h3 id="report-summary-title" className="mb-3 text-sm font-semibold text-[var(--color-ink)]">Summary</h3><dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2 xl:grid-cols-4">{Object.entries(report.summary).map(([key, value]) => <div key={key} className="min-w-0 border-b border-[var(--color-line)] pb-2"><dt className="text-xs text-[var(--color-mute)]">{label(key)}</dt><dd className="mt-1 break-words text-sm font-semibold text-[var(--color-ink)]">{displayValue(value)}</dd></div>)}</dl></section>
        {report.rows.length ? <div className="max-w-full overflow-x-auto"><table className="w-full min-w-[760px] table-fixed text-left text-sm"><thead className="border-y border-[var(--color-line)] bg-[var(--color-bg-2)]"><tr>{columns.map((column) => <th key={column} className="w-48 px-3 py-2 font-semibold">{label(column)}</th>)}</tr></thead><tbody>{report.rows.map((row, index) => <tr key={index} className="border-b border-[var(--color-line)] align-top">{columns.map((column) => <td key={column} className="max-w-48 break-words px-3 py-3 text-[var(--color-ink-2)]">{displayValue(row[column])}</td>)}</tr>)}</tbody></table></div> : <EmptyState title={report.freshness.status === "unavailable" ? "Report source unavailable" : "No matching records"} />}
        <div className="grid gap-3 border-t border-[var(--color-line)] pt-4 text-xs text-[var(--color-mute)] sm:grid-cols-2"><p>Audience: Internal · Restricted records outside your access are omitted without a count.</p><p className="sm:text-right">Schema {report.schema_version}{report.truncated ? " · Result truncated at the selected row limit" : ""}</p></div>
      </CardContent>
    </Card>
  );
}
