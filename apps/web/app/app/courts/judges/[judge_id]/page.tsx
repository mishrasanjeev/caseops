"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  BarChart3,
  Briefcase,
  CalendarRange,
  ExternalLink,
  Gavel,
  LibraryBig,
  Milestone,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { fetchJudgeProfile } from "@/lib/api/endpoints";

export default function JudgeProfilePage() {
  const params = useParams<{ judge_id: string }>();
  const judgeId = params.judge_id;
  const profileQuery = useQuery({
    queryKey: ["judges", judgeId, "profile"],
    queryFn: () => fetchJudgeProfile(judgeId),
    enabled: Boolean(judgeId),
  });

  if (profileQuery.isPending) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (profileQuery.isError) {
    return (
      <QueryErrorState
        title="Could not load judge profile"
        error={profileQuery.error}
        onRetry={profileQuery.refetch}
      />
    );
  }
  const profile = profileQuery.data;
  if (!profile) return null;

  const fullName = `${profile.judge.honorific ? `${profile.judge.honorific} ` : ""}${profile.judge.full_name}`;

  return (
    <div className="flex flex-col gap-6">
      <Link
        href={`/app/courts/${profile.court.id}`}
        className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-mute)] hover:text-[var(--color-ink)]"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Back to {profile.court.short_name}
      </Link>

      <PageHeader
        eyebrow={profile.court.name}
        title={fullName}
        description={profile.judge.current_position ?? "Active judge"}
      />

      <section className="grid gap-4 sm:grid-cols-2 md:grid-cols-4">
        <KpiCard
          icon={Briefcase}
          label="Your matters before this judge"
          value={String(profile.portfolio_matter_count)}
        />
        <KpiCard
          icon={LibraryBig}
          label="Authorities indexed"
          value={profile.authority_document_count.toLocaleString()}
        />
        <KpiCard
          icon={CalendarRange}
          label="Tenure (decisions)"
          value={
            profile.earliest_decision_date && profile.latest_decision_date
              ? `${profile.earliest_decision_date.slice(0, 4)} – ${profile.latest_decision_date.slice(0, 4)}`
              : "—"
          }
        />
        <KpiCard
          icon={ShieldCheck}
          label="Structured match"
          value={
            profile.structured_match_coverage_percent !== undefined
              ? `${profile.structured_match_coverage_percent}%`
              : "—"
          }
        />
      </section>

      <Card data-testid="judge-career-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Milestone className="h-4 w-4" aria-hidden /> Career
          </CardTitle>
          <CardDescription>
            Every court this judge has served on, oldest first. Sourced from
            the official profile pages — click any source link to verify.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {profile.career && profile.career.length > 0 ? (
            <ol
              className="flex flex-col gap-3"
              data-testid="judge-career-timeline"
            >
              {profile.career.map((appt) => (
                <li
                  key={appt.id}
                  className="flex flex-col gap-1 rounded-md border border-[var(--color-line)] bg-white p-3"
                  data-testid={`judge-career-row-${appt.id}`}
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <div className="text-sm font-semibold text-[var(--color-ink)]">
                      {appt.court_name}
                    </div>
                    <div className="text-xs text-[var(--color-mute)] tabular">
                      {appt.start_date ?? "—"} →{" "}
                      {appt.end_date ?? (appt.start_date ? "present" : "—")}
                    </div>
                  </div>
                  <div className="text-xs uppercase tracking-wide text-[var(--color-mute-2)]">
                    {appt.role.replace(/_/g, " ")}
                  </div>
                  {appt.source_evidence_text ? (
                    <div className="mt-1 text-xs text-[var(--color-mute)]">
                      “{appt.source_evidence_text}”
                    </div>
                  ) : null}
                  {appt.source_url ? (
                    <a
                      href={appt.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-1 inline-flex items-center gap-1 text-xs text-[var(--color-brand-600)] hover:underline"
                    >
                      Source
                      <ExternalLink className="h-3 w-3" aria-hidden />
                    </a>
                  ) : null}
                </li>
              ))}
            </ol>
          ) : (
            <EmptyState
              icon={Milestone}
              title="Career history not yet recorded"
              description="No appointments have been backfilled for this judge. Career data is added as we scrape each court's profile pages."
            />
          )}
        </CardContent>
      </Card>

      {profile.practice_areas && profile.practice_areas.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Practice areas decided</CardTitle>
            <CardDescription>
              How the judgments where this judge sat split across the practice
              areas we recognise. Buckets are derived from the sections cited
              in each judgment — a heuristic, not an outcome claim.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <PracticeAreaBars items={profile.practice_areas} />
          </CardContent>
        </Card>
      ) : null}

      {profile.decision_volume && profile.decision_volume.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BarChart3 className="h-4 w-4" aria-hidden /> Decision volume by year
            </CardTitle>
            <CardDescription>
              Indexed decisions per calendar year. Helps spot tenure breaks and
              workload changes; does not imply trend, preference, or outcome.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <DecisionVolumeBars points={profile.decision_volume} />
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Recent authorities</CardTitle>
          <CardDescription>
            Most recent indexed judgments where this judge sat on the bench. The
            match is on bench-name string — review before relying for citation.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {profile.recent_authorities.length === 0 ? (
            <EmptyState
              icon={Gavel}
              title="No authorities indexed yet"
              description="No judgments in the corpus reference this judge. They'll appear here as the ingest catches up."
            />
          ) : (
            <ul className="flex flex-col gap-2">
              {profile.recent_authorities.map((authority) => (
                <li
                  key={authority.id}
                  className="rounded-md border border-[var(--color-line)] bg-white p-3"
                >
                  <div className="text-sm font-medium text-[var(--color-ink)]">
                    {authority.title}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[var(--color-mute)]">
                    {authority.decision_date ? (
                      <span>{authority.decision_date}</span>
                    ) : null}
                    {authority.case_reference ? (
                      <span className="font-mono">· {authority.case_reference}</span>
                    ) : null}
                    {authority.neutral_citation ? (
                      <span className="font-mono">
                        · {authority.neutral_citation}
                      </span>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function KpiCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Briefcase;
  label: string;
  value: string;
}) {
  return (
    <Card>
      <CardContent className="flex items-start gap-3 py-5">
        <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--color-bg)] text-[var(--color-ink-3)]">
          <Icon className="h-5 w-5" aria-hidden />
        </span>
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
            {label}
          </div>
          <div className="tabular text-xl font-semibold tracking-tight text-[var(--color-ink)]">
            {value}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}


function PracticeAreaBars({
  items,
}: {
  items: { area: string; count: number }[];
}) {
  const max = Math.max(...items.map((i) => i.count), 1);
  return (
    <ul className="flex flex-col gap-2" data-testid="judge-practice-area-bars">
      {items.map((it) => {
        const pct = Math.max(2, Math.round((it.count / max) * 100));
        return (
          <li key={it.area} className="flex items-center gap-3 text-sm">
            <span className="w-44 shrink-0 text-[var(--color-ink-2)]">
              {it.area}
            </span>
            <div className="relative h-2 flex-1 overflow-hidden rounded bg-[var(--color-bg)]">
              <div
                className="h-2 rounded bg-[var(--color-brand-700)]"
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="tabular w-10 shrink-0 text-right text-xs text-[var(--color-mute)]">
              {it.count}
            </span>
          </li>
        );
      })}
    </ul>
  );
}


function DecisionVolumeBars({
  points,
}: {
  points: { year: number; count: number }[];
}) {
  const max = Math.max(...points.map((p) => p.count), 1);
  return (
    <div
      className="flex h-32 items-end gap-1"
      data-testid="judge-decision-volume-bars"
    >
      {points.map((p) => {
        const h = Math.max(4, Math.round((p.count / max) * 100));
        return (
          <div
            key={p.year}
            className="flex flex-1 flex-col items-center gap-1"
            title={`${p.year}: ${p.count} decisions`}
          >
            <div
              className="w-full rounded-t bg-[var(--color-brand-700)]"
              style={{ height: `${h}%` }}
            />
            <span className="tabular text-[10px] text-[var(--color-mute)]">
              {String(p.year).slice(-2)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
