"use client";

import { ArrowUpRight } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { apiErrorMessage } from "@/lib/api/config";
import type { IpJournalFeedStatus, IpPublicJournalDocument } from "@/lib/api/endpoints";

const DAY = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" });
const STAMP = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" });

const DOCUMENT_STATUS: Record<IpPublicJournalDocument["status"], string> = {
  pending: "Waiting to download",
  parsed: "Read",
  needs_review: "Read; pages need review",
  failed: "Could not be read",
};

const WORKSPACE_STATUS: Record<string, string> = {
  completed: "Compared with your profiles",
  no_active_profiles: "No active watch profile to compare",
  feature_unavailable: "Automated journal watch is not available to this workspace",
  actor_unavailable: "The member who turned the feed on is no longer active; turn it on again",
  incident_kill_switch: "Stopped by a risk incident",
  match_limit_exceeded: "Too many matches; narrow the watch profiles",
  failed: "Comparison failed; it is retried on the next run",
};

const CHECK_REASON: Record<string, string> = {
  challenge_detected: "the site showed a CAPTCHA or bot check, so the feed stopped",
  access_refused: "the site refused access, so the feed stopped",
  robots_disallowed: "the site's robots.txt does not allow it, so the feed stopped",
  robots_unreachable: "the site's robots.txt could not be read, so the feed stopped",
  listing_layout_changed: "the journal page layout changed",
  network_error: "the site could not be reached",
};

function fileLabel(name: string) {
  return name.split(/[\\/]/).pop()?.replace(/\.pdf$/i, "") ?? name;
}

export function feedActive(status: IpJournalFeedStatus | undefined) {
  return Boolean(status?.global_enabled && status.setting?.enabled);
}

export function JournalFeedPanel({
  status,
  loading,
  error,
  canManage,
  saving,
  onRetry,
  onToggle,
}: {
  status: IpJournalFeedStatus | undefined;
  loading: boolean;
  error: unknown;
  canManage: boolean;
  saving: boolean;
  onRetry: () => void;
  onToggle: (enabled: boolean, expectedVersion: number | null) => void;
}) {
  const enabled = Boolean(status?.setting?.enabled);
  const check = status?.last_check ?? null;
  return (
    <section
      aria-labelledby="journal-feed-title"
      data-testid="journal-feed"
      className="min-w-0 rounded-md border border-[var(--color-line)] bg-white p-4 text-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <h2 id="journal-feed-title" className="font-semibold">Public Trade Marks Journal feed</h2>
          {status ? (
            <Badge tone={feedActive(status) ? "success" : enabled ? "warning" : "neutral"}>
              {feedActive(status) ? "On" : enabled ? "On, paused by CaseOps" : "Off"}
            </Badge>
          ) : null}
        </div>
        {status && canManage ? (
          <Button
            type="button"
            size="sm"
            variant={enabled ? "outline" : "primary"}
            disabled={saving}
            onClick={() => onToggle(!enabled, status.setting?.version ?? null)}
          >
            {saving ? "Saving…" : enabled ? "Turn off for this workspace" : "Turn on for this workspace"}
          </Button>
        ) : null}
      </div>
      {loading ? (
        <p className="mt-2 text-[var(--color-mute)]" role="status">Loading feed status…</p>
      ) : error ? (
        <div role="alert" className="mt-2 flex flex-wrap items-center gap-2 text-[var(--color-danger-500)]">
          <span className="min-w-0 break-words">Could not load the journal feed: {apiErrorMessage(error, "Request failed.")}</span>
          <Button type="button" size="sm" variant="outline" onClick={onRetry}>Try again</Button>
        </div>
      ) : status ? (
        <>
          <p className="mt-2 max-w-[75ch] break-words text-[var(--color-mute)]">
            When on, CaseOps downloads each new issue of the Trade Marks Journal from IP India&apos;s public journal page,
            compares every advertised application with your active watch profiles, and records only the matches, each
            linked to its official PDF page. Manual journal intake keeps working either way. Trade mark status,
            e-register and public search pages require a CAPTCHA and are not automated.
          </p>
          {!status.global_enabled ? (
            <p className="mt-2 break-words" data-testid="journal-feed-paused">
              CaseOps has not switched the feed on yet, so no journal is downloaded.
            </p>
          ) : null}
          {!canManage ? (
            <p className="mt-2 text-[var(--color-mute)]">Your role cannot change this setting.</p>
          ) : null}
          {check ? (
            <p className="mt-2 break-words" data-testid="journal-feed-last-check">
              Last check of the journal page: {STAMP.format(new Date(check.checked_at))} ·{" "}
              {check.status === "succeeded"
                ? `${check.issues_listed.toLocaleString("en-IN")} issues listed`
                : `${check.status}: ${CHECK_REASON[check.reason_code ?? ""] ?? check.reason_code ?? "no reason recorded"}`}
            </p>
          ) : null}
          {status.documents.length ? (
            <ul className="mt-3 divide-y divide-[var(--color-line)] border-y border-[var(--color-line)]" aria-label="Recent journal files">
              {status.documents.map((item) => (
                <li key={item.id} className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2">
                  <span className="min-w-0 break-words">
                    <span className="font-medium">Journal {item.journal_number}</span>{" "}
                    <span className="text-[var(--color-mute)]">{DAY.format(new Date(item.journal_date))} · {fileLabel(item.file_name)}</span>
                  </span>
                  <span className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-[var(--color-mute)]">
                    <span>{DOCUMENT_STATUS[item.status]}</span>
                    {item.status === "parsed" || item.status === "needs_review" ? (
                      <span className="tabular-nums">
                        {item.entry_count.toLocaleString("en-IN")} entries
                        {item.review_count ? ` · ${item.review_count.toLocaleString("en-IN")} to review` : ""}
                      </span>
                    ) : null}
                    {item.workspace_status ? <span>{WORKSPACE_STATUS[item.workspace_status] ?? item.workspace_status}</span> : null}
                    <a className="inline-flex items-center gap-1 font-medium text-[var(--color-brand-700)]" href={item.source_url} target="_blank" rel="noreferrer">
                      Official PDF <ArrowUpRight className="h-3 w-3" aria-hidden="true" />
                    </a>
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          {status.review_total ? (
            <div className="mt-3" data-testid="journal-feed-review">
              <p className="font-medium">
                {status.review_total.toLocaleString("en-IN")} journal {status.review_total === 1 ? "span needs" : "spans need"} review.
                {" "}They were not compared automatically; open the official page and record any relevant entry through journal intake.
              </p>
              <ul className="mt-1 list-disc space-y-0.5 pl-5">
                {status.review_items.map((item) => (
                  <li key={item.id} className="break-words">
                    <a className="font-medium text-[var(--color-brand-700)]" href={item.source_url} target="_blank" rel="noreferrer">
                      Journal {item.journal_number}, PDF {item.page_end > item.page_start ? `pages ${item.page_start}-${item.page_end}` : `page ${item.page_start}`}
                    </a>
                    {item.application_number ? ` · application ${item.application_number}` : ""}
                    {item.review_reason ? ` · ${item.review_reason.replaceAll("_", " ").replaceAll(",", ", ")}` : ""}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <p className="mt-3 break-words text-xs text-[var(--color-mute)]">Source: {status.attribution}.</p>
        </>
      ) : null}
    </section>
  );
}
