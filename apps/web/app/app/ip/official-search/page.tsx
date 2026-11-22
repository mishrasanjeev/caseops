"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, ExternalLink, FileUp } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";
import type { FormEvent } from "react";
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
  dismissIpOfficialSearchImport,
  linkIpOfficialSearchImport,
  listIpOfficialSearchImports,
  stageIpOfficialSearchImport,
  uploadIpOfficialSearchPage,
  type IpOfficialSearchImport,
} from "@/lib/api/ip-official-search";
import { useCapability } from "@/lib/capabilities";
import {
  OFFICIAL_FIELD_LABELS,
  OFFICIAL_SEARCHES,
  OFFICIAL_SEARCH_ORDER,
  entrySteps,
  fieldText,
  officialSearchUrl,
  queryProblem,
  reviewReasonText,
  uploadMetadata,
  type ImportableSearchKind,
  type OfficialSearchKind,
  type OfficialSearchQuery,
} from "@/lib/ip/official-search";

const STAMP = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" });
const IMPORTS_KEY = ["ip-official-search-imports"];

const PARSE_STATUS: Record<IpOfficialSearchImport["parse_status"], { label: string; tone: "success" | "warning" | "neutral" }> = {
  parsed: { label: "Read", tone: "success" },
  needs_review: { label: "Needs review", tone: "warning" },
  unreadable: { label: "Could not be read", tone: "warning" },
};

const RESOLUTION: Record<IpOfficialSearchImport["resolution_status"], string> = {
  pending: "Not yet linked",
  linked: "Linked to the record as registry evidence",
  staged_new_record: "Staged as a new record in portfolio import",
  dismissed: "Dismissed",
};

async function copyValue(value: string) {
  try {
    await navigator.clipboard.writeText(value);
    toast.success("Copied.");
  } catch {
    toast.error("Copy is blocked in this browser. Select the value and copy it.");
  }
}

function SearchSteps({ kind, query }: { kind: OfficialSearchKind; query: OfficialSearchQuery }) {
  const definition = OFFICIAL_SEARCHES[kind];
  const ready = queryProblem(kind, query) === null;
  return (
    <section aria-labelledby="official-steps-heading" className="flex min-w-0 flex-col gap-3">
      <h3 id="official-steps-heading" className="text-sm font-semibold text-[var(--color-ink)]">
        On {definition.site}, enter
      </h3>
      <ol className="flex list-inside list-decimal flex-col gap-2 text-sm">
        {entrySteps(kind, query).map((step) => (
          <li key={step.label} className="min-w-0">
            <span>{step.label}</span>
            {step.value ? (
              <span className="ml-2 inline-flex items-center gap-2">
                <code className="rounded-[var(--radius-sm)] border border-[var(--color-line)] bg-[var(--color-bg-2)] px-1.5 py-0.5 font-mono text-[0.8125rem] tabular-nums">
                  {step.value}
                </code>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-label={`Copy ${step.label.toLowerCase()}`}
                  onClick={() => void copyValue(step.value ?? "")}
                >
                  <Copy className="h-4 w-4" aria-hidden />
                </Button>
              </span>
            ) : null}
          </li>
        ))}
      </ol>
      {kind === "tmview" ? (
        <p className="max-w-[70ch] text-sm text-[var(--color-ink-2)]">
          TMview is a pre-search aid run by the EUIPO. It is not the official register and its
          India data can lag behind. Note the update date TMview shows, then confirm the status on
          IP India&apos;s e-status or e-register before relying on it. CaseOps does not query or
          import TMview: its terms do not permit automated access.
        </p>
      ) : (
        <p className="max-w-[70ch] text-sm text-[var(--color-ink-2)]">
          IP India asks you to complete its own verification. You do that on IP India&apos;s page;
          CaseOps never fills it in, sees it or searches IP India for you.
        </p>
      )}
      <div>
        <Button
          href={officialSearchUrl(kind, query)}
          target="_blank"
          rel="noopener noreferrer"
          referrerPolicy="no-referrer"
          variant="secondary"
          size="md"
          aria-disabled={!ready}
          className={ready ? undefined : "pointer-events-none opacity-60"}
          tabIndex={ready ? undefined : -1}
        >
          Open {definition.site}
          <ExternalLink className="h-4 w-4" aria-hidden />
          <span className="sr-only">(opens in a new tab)</span>
        </Button>
      </div>
    </section>
  );
}

function UploadForm({ kind, query }: { kind: ImportableSearchKind; query: OfficialSearchQuery }) {
  const id = useId();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [inputKey, setInputKey] = useState(0);
  const problem = queryProblem(kind, query);
  const upload = useMutation({
    mutationFn: uploadIpOfficialSearchPage,
    onSuccess: async (result) => {
      toast.success(result.duplicate_upload ? "This page was already imported." : "Page imported. Check what was read below.");
      setFile(null);
      setInputKey((value) => value + 1);
      await queryClient.invalidateQueries({ queryKey: IMPORTS_KEY });
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not import the saved page.")),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!file || problem) return;
    upload.mutate({ metadata: uploadMetadata(kind, query), file });
  };
  return (
    <form onSubmit={submit} className="flex min-w-0 flex-col gap-3" aria-labelledby={`${id}-heading`}>
      <h3 id={`${id}-heading`} className="text-sm font-semibold text-[var(--color-ink)]">
        Bring the result back
      </h3>
      <p className="max-w-[70ch] text-sm text-[var(--color-ink-2)]">
        In your browser, use Save as (Webpage, HTML only) or Print, then Save as PDF. Upload that
        file here, up to 5 MB. CaseOps reads only the fields it can read reliably and sends the
        rest to review.
      </p>
      <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1">
          <Label htmlFor={`${id}-file`}>Saved result page</Label>
          <Input
            key={inputKey}
            id={`${id}-file`}
            type="file"
            accept=".html,.htm,.pdf,text/html,application/pdf"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </div>
        <Button type="submit" disabled={!file || Boolean(problem) || upload.isPending}>
          <FileUp className="h-4 w-4" aria-hidden />
          {upload.isPending ? "Importing" : "Import page"}
        </Button>
      </div>
      {problem ? <p className="text-sm text-[var(--color-mute)]">{problem}</p> : null}
    </form>
  );
}

function ImportItem({ record, canLink, canWrite }: { record: IpOfficialSearchImport; canLink: boolean; canWrite: boolean }) {
  const id = useId();
  const queryClient = useQueryClient();
  const [dismissReason, setDismissReason] = useState("");
  const refresh = () => queryClient.invalidateQueries({ queryKey: IMPORTS_KEY });
  const onError = (fallback: string) => async (error: unknown) => {
    toast.error(apiErrorMessage(error, fallback));
    await refresh();
  };
  const link = useMutation({
    mutationFn: linkIpOfficialSearchImport,
    onSuccess: async (result) => {
      toast.success(result.no_change ? "Linked. The register shows no change." : `Linked. ${result.diff_count} change${result.diff_count === 1 ? "" : "s"} wait for review in Registry reconciliation.`);
      await refresh();
    },
    onError: onError("Could not link the page."),
  });
  const stage = useMutation({
    mutationFn: stageIpOfficialSearchImport,
    onSuccess: async () => {
      toast.success("Staged in portfolio import. Review and commit it there.");
      await refresh();
    },
    onError: onError("Could not stage the new record."),
  });
  const dismiss = useMutation({
    mutationFn: dismissIpOfficialSearchImport,
    onSuccess: async () => {
      setDismissReason("");
      toast.success("Dismissed.");
      await refresh();
    },
    onError: onError("Could not dismiss the page."),
  });
  const status = PARSE_STATUS[record.parse_status];
  const open = record.resolution_status === "pending" || record.resolution_status === "staged_new_record";
  const number = record.fields.application_number;
  const readFields = Object.entries(record.fields);
  const busy = link.isPending || stage.isPending || dismiss.isPending;
  return (
    <li className="flex min-w-0 flex-col gap-3 py-4" aria-labelledby={`${id}-title`}>
      <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-2">
        <h3 id={`${id}-title`} className="min-w-0 break-words text-sm font-semibold text-[var(--color-ink)]">
          {OFFICIAL_SEARCHES[record.source_kind].site}
          {typeof number === "string" ? <span className="font-mono tabular-nums"> · {number}</span> : null}
        </h3>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={status.tone}>{status.label}</Badge>
          <span className="text-xs text-[var(--color-mute)]">{RESOLUTION[record.resolution_status]}</span>
        </div>
      </div>
      {readFields.length > 0 ? (
        <dl className="grid min-w-0 grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-[max-content_1fr]">
          {readFields.map(([field, value]) => (
            <div key={field} className="contents">
              <dt className="text-[var(--color-mute)]">{OFFICIAL_FIELD_LABELS[field] ?? field}</dt>
              <dd className="min-w-0 break-words">{fieldText(field, value)}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {record.review_items.length > 0 ? (
        <div className="min-w-0 rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-bg-2)] p-3">
          <p className="text-sm font-semibold">Needs your review</p>
          <ul className="mt-1 flex flex-col gap-1 text-sm">
            {record.review_items.map((item) => (
              <li key={`${item.field}:${item.reason}`} className="min-w-0 break-words">
                <span className="font-medium">{OFFICIAL_FIELD_LABELS[item.field] ?? item.field}:</span>{" "}
                {reviewReasonText(item.reason)}
                {record.published_values[item.field] ? (
                  <span className="text-[var(--color-mute)]"> As published: {record.published_values[item.field]}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {record.resolution_status === "pending" && record.matches.length > 0 ? (
        <div className="flex min-w-0 flex-col gap-2">
          <p className="text-sm">The application number matches {record.matches.length === 1 ? "this record" : "these records"}:</p>
          <ul className="flex flex-col gap-2">
            {record.matches.map((match) => (
              <li key={match.application_id} className="flex min-w-0 flex-wrap items-center gap-2 text-sm">
                <span className="min-w-0 break-words font-medium">{match.docket_title}</span>
                <span className="font-mono text-xs tabular-nums text-[var(--color-mute)]">{match.application_number}</span>
                {canLink ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => link.mutate({ importId: record.id, expectedVersion: record.version, applicationId: match.application_id })}
                  >
                    Link as registry evidence
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
          {canLink ? null : <p className="text-sm text-[var(--color-mute)]">An IP workspace admin links pages to records.</p>}
        </div>
      ) : null}
      {record.resolution_status === "pending" && record.matches.length === 0 && typeof number === "string" && canWrite ? (
        <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm">
          <span>No record in this workspace has this application number.</span>
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => stage.mutate({ importId: record.id, expectedVersion: record.version })}>
            Offer as a new record
          </Button>
        </div>
      ) : null}
      {record.resolution_status === "staged_new_record" && record.import_job_id ? (
        <p className="text-sm">
          <Link className="font-semibold text-[var(--color-brand-700)] hover:underline" href={`/app/ip/portfolio/imports?job=${encodeURIComponent(record.import_job_id)}`}>
            Review and confirm the staged record
          </Link>
          . After it is created, link this page to it here.
        </p>
      ) : null}
      {record.resolution_status === "linked" && record.linked_docket_id ? (
        <p className="text-sm">
          <Link className="font-semibold text-[var(--color-brand-700)] hover:underline" href={`/app/ip/registry?docket=${encodeURIComponent(record.linked_docket_id)}`}>
            Review the changes in Registry reconciliation
          </Link>
        </p>
      ) : null}
      {record.resolution_status === "dismissed" && record.resolution_reason ? (
        <p className="text-sm text-[var(--color-mute)]">Reason: {record.resolution_reason}</p>
      ) : null}
      <details className="text-xs text-[var(--color-mute)]">
        <summary className="cursor-pointer">Source and lineage</summary>
        <dl className="mt-2 grid min-w-0 grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-[max-content_1fr]">
          <dt>Official page</dt>
          <dd className="min-w-0 break-all">
            <a className="underline" href={record.official_url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">
              {record.official_url}
            </a>
          </dd>
          <dt>Uploaded</dt>
          <dd>{STAMP.format(new Date(record.uploaded_at))}{record.uploaded_by_label ? ` by ${record.uploaded_by_label}` : ""}</dd>
          <dt>File</dt>
          <dd className="min-w-0 break-all">{record.original_filename} ({record.content_kind.toUpperCase()}, {Math.ceil(record.byte_size / 1024)} KB)</dd>
          <dt>SHA-256</dt>
          <dd className="min-w-0 break-all font-mono">{record.file_sha256}</dd>
          <dt>Source</dt>
          <dd className="min-w-0 break-words">{record.attribution}</dd>
        </dl>
      </details>
      {open && canWrite ? (
        <form
          className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-end"
          onSubmit={(event) => {
            event.preventDefault();
            if (dismissReason.trim().length < 3) return;
            dismiss.mutate({ importId: record.id, expectedVersion: record.version, reason: dismissReason.trim() });
          }}
        >
          <div className="min-w-0 flex-1">
            <Label htmlFor={`${id}-dismiss`}>Reason to dismiss</Label>
            <Input id={`${id}-dismiss`} value={dismissReason} maxLength={500} onChange={(event) => setDismissReason(event.target.value)} />
          </div>
          <Button type="submit" size="sm" variant="ghost" disabled={busy || dismissReason.trim().length < 3}>
            Dismiss
          </Button>
        </form>
      ) : null}
    </li>
  );
}

export default function OfficialSearchPage() {
  const id = useId();
  const canRead = useCapability("ip:read");
  const canWrite = useCapability("ip:write");
  const canLink = useCapability("ip:registry_sync");
  const [kind, setKind] = useState<OfficialSearchKind>("ipindia_estatus");
  const [query, setQuery] = useState<OfficialSearchQuery>({ applicationNumber: "", wordMark: "", niceClass: "" });
  const imports = useQuery({ queryKey: IMPORTS_KEY, queryFn: listIpOfficialSearchImports, enabled: canRead });

  if (!canRead) {
    return (
      <div className="flex min-w-0 flex-col gap-6">
        <PageHeader title="Official trade mark search" />
        <EmptyState title="IP access required" description="Ask an owner or admin for the IP read capability." />
      </div>
    );
  }
  const definition = OFFICIAL_SEARCHES[kind];
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader
        eyebrow="IP operations"
        title="Official trade mark search"
        description="Search IP India's register yourself, then bring the saved result back as source-attributed evidence."
      />
      <Card>
        <CardHeader>
          <CardTitle as="h2">Search</CardTitle>
        </CardHeader>
        <CardContent className="flex min-w-0 flex-col gap-5">
          <fieldset className="flex min-w-0 flex-col gap-2">
            <legend className="mb-1 text-sm font-semibold">Search type</legend>
            {OFFICIAL_SEARCH_ORDER.map((option) => (
              <label key={option} className="flex min-w-0 items-start gap-2 text-sm">
                <input
                  type="radio"
                  name={`${id}-kind`}
                  value={option}
                  checked={kind === option}
                  onChange={() => setKind(option)}
                  className="mt-1"
                />
                <span className="min-w-0">
                  <span className="font-medium">{OFFICIAL_SEARCHES[option].label}</span>
                  <span className="text-[var(--color-mute)]"> · {OFFICIAL_SEARCHES[option].site}</span>
                </span>
              </label>
            ))}
          </fieldset>
          {definition.by === "number" ? (
            <div className="min-w-0 sm:max-w-xs">
              <Label htmlFor={`${id}-number`}>Application number</Label>
              <Input
                id={`${id}-number`}
                inputMode="numeric"
                autoComplete="off"
                maxLength={20}
                value={query.applicationNumber}
                onChange={(event) => setQuery({ ...query, applicationNumber: event.target.value })}
              />
            </div>
          ) : (
            <div className="flex min-w-0 flex-col gap-3 sm:flex-row">
              <div className="min-w-0 flex-1 sm:max-w-md">
                <Label htmlFor={`${id}-mark`}>Word mark</Label>
                <Input
                  id={`${id}-mark`}
                  autoComplete="off"
                  maxLength={200}
                  value={query.wordMark}
                  onChange={(event) => setQuery({ ...query, wordMark: event.target.value })}
                />
              </div>
              <div className="min-w-0 sm:w-32">
                <Label htmlFor={`${id}-class`}>Class</Label>
                <Input
                  id={`${id}-class`}
                  inputMode="numeric"
                  type="number"
                  min={1}
                  max={45}
                  value={query.niceClass}
                  onChange={(event) => setQuery({ ...query, niceClass: event.target.value })}
                />
              </div>
            </div>
          )}
          <SearchSteps kind={kind} query={query} />
          {definition.importable && canWrite ? (
            <UploadForm kind={kind as ImportableSearchKind} query={query} />
          ) : null}
        </CardContent>
      </Card>
      <section aria-labelledby={`${id}-imports`} className="flex min-w-0 flex-col gap-2">
        <h2 id={`${id}-imports`} className="text-base font-semibold">Imported pages</h2>
        {imports.isPending ? (
          <Skeleton className="h-24 w-full" />
        ) : imports.isError ? (
          <QueryErrorState error={imports.error} onRetry={() => void imports.refetch()} />
        ) : imports.data.records.length === 0 ? (
          <p className="max-w-[70ch] text-sm text-[var(--color-mute)]">
            No pages imported yet. Each page you bring back from IP India appears here with what
            was read, what needs review, and its source lineage.
          </p>
        ) : (
          <ul className="divide-y divide-[var(--color-line)] border-y border-[var(--color-line)]">
            {imports.data.records.map((record) => (
              <ImportItem key={record.id} record={record} canLink={canLink} canWrite={canWrite} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
