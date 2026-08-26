"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  BarChart3,
  Briefcase,
  CalendarRange,
  Filter,
  Gavel,
  LibraryBig,
  Milestone,
  RotateCcw,
  Search,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

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
import { SourceAction } from "@/components/app/SourceAction";
import { Button } from "@/components/ui/Button";
import {
  fetchJudgeAuthorities,
  fetchJudgeProfile,
  type JudgeAuthoritiesResponse,
} from "@/lib/api/endpoints";

export default function JudgeProfilePage() {
  const params = useParams<{ judge_id: string }>();
  const judgeId = params.judge_id;
  const profileQuery = useQuery({
    queryKey: ["judges", judgeId, "profile"],
    queryFn: () => fetchJudgeProfile(judgeId),
    enabled: Boolean(judgeId),
  });
  const [yearFrom, setYearFrom] = useState("");
  const [yearTo, setYearTo] = useState("");
  const [mappingConfidence, setMappingConfidence] = useState("");
  const [appliedFilters, setAppliedFilters] = useState<{
    yearFrom?: number;
    yearTo?: number;
    mappingConfidence?: string;
  } | null>(null);
  const [authorityView, setAuthorityView] = useState<JudgeAuthoritiesResponse | null>(
    null,
  );
  useEffect(() => {
    setAuthorityView(null);
    setAppliedFilters(null);
    setYearFrom("");
    setYearTo("");
    setMappingConfidence("");
  }, [judgeId]);
  const authoritiesMutation = useMutation({
    mutationFn: (variables: {
      mode: "replace" | "append";
      cursor?: string | null;
      filters: {
        yearFrom?: number;
        yearTo?: number;
        mappingConfidence?: string;
      };
    }) =>
      fetchJudgeAuthorities(judgeId, {
        cursor: variables.cursor,
        limit: 20,
        ...variables.filters,
      }),
    onSuccess: (data, variables) => {
      setAuthorityView((current) => {
        if (variables.mode !== "append") return data;
        const profile = profileQuery.data;
        const initialPage = profile
          ? {
              judge_id: judgeId,
              authorities: profile.recent_authorities,
              returned_count: profile.recent_authorities.length,
              has_more: profile.recent_authorities_has_more,
              next_cursor: profile.recent_authorities_next_cursor,
              mapped_authority_count: profile.authority_document_count,
              analytics_eligible_authority_count:
                profile.analytics_eligible_authority_count,
              coverage_state: profile.coverage_state,
              coverage_disclaimer: profile.coverage_disclaimer,
            }
          : null;
        const previous = current ?? initialPage;
        if (!previous) return data;
        return {
          ...data,
          authorities: [...previous.authorities, ...data.authorities],
          returned_count: previous.returned_count + data.returned_count,
        };
      });
    },
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
  const visibleAuthorities: JudgeAuthoritiesResponse = authorityView ?? {
    judge_id: judgeId,
    authorities: profile.recent_authorities,
    returned_count: profile.recent_authorities.length,
    has_more: profile.recent_authorities_has_more,
    next_cursor: profile.recent_authorities_next_cursor,
    mapped_authority_count: profile.authority_document_count,
    analytics_eligible_authority_count: profile.analytics_eligible_authority_count,
    coverage_state: profile.coverage_state,
    coverage_disclaimer: profile.coverage_disclaimer,
  };
  const researchQuery = new URLSearchParams({
    q: `${profile.judge.full_name} ${profile.court.name}`,
  });

  function applyAuthorityFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const filters = {
      yearFrom: yearFrom ? Number(yearFrom) : undefined,
      yearTo: yearTo ? Number(yearTo) : undefined,
      mappingConfidence: mappingConfidence || undefined,
    };
    setAppliedFilters(filters);
    authoritiesMutation.mutate({ mode: "replace", filters });
  }

  function resetAuthorityFilters() {
    setYearFrom("");
    setYearTo("");
    setMappingConfidence("");
    setAppliedFilters(null);
    setAuthorityView(null);
  }

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

      <section className="flex min-w-0 flex-col gap-3 border-y border-[var(--color-line)] py-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="text-xs font-semibold uppercase text-[var(--color-mute-2)]">
            Canonical identity
          </div>
          <div className="mt-1 flex min-w-0 flex-wrap gap-1.5">
            {profile.aliases.length > 0 ? (
              profile.aliases.map((alias) => (
                <span
                  key={alias.id}
                  className="rounded-md border border-[var(--color-line)] bg-white px-2 py-1 text-xs text-[var(--color-ink-2)]"
                >
                  {alias.alias_text}
                </span>
              ))
            ) : (
              <span className="text-xs text-[var(--color-mute)]">No active aliases</span>
            )}
          </div>
        </div>
        <div className="flex min-w-0 shrink-0 flex-wrap">
          <SourceAction
            action={profile.identity_source_action}
            compact
            originSurface="judge_profile"
          />
        </div>
      </section>

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
          label="Analytics eligible"
          value={`${profile.mapping_coverage_percent}%`}
        />
      </section>

      <p className="text-xs leading-5 text-[var(--color-mute)]">
        {profile.coverage_disclaimer}
      </p>

      {profile.analytics ? (
        <Card data-testid="judge-context-explorer">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4" aria-hidden /> Court/Judge Context Explorer
            </CardTitle>
            <CardDescription>{profile.analytics.disclaimer}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            <div className="grid gap-3 md:grid-cols-3">
              <ContextStat
                label="Source records reviewed"
                value={profile.analytics.sample_size.toLocaleString()}
              />
              <ContextStat
                label="Sample status"
                value={profile.analytics.sample_size_label}
              />
              <ContextStat
                label="Case list shown"
                value={profile.analytics.case_list.length.toLocaleString()}
              />
            </div>

            {profile.analytics.limitations.length > 0 ? (
              <ul className="flex flex-col gap-1 text-xs text-[var(--color-mute)]">
                {profile.analytics.limitations.map((item) => (
                  <li key={item}>- {item}</li>
                ))}
              </ul>
            ) : null}

            <div className="grid gap-4 lg:grid-cols-3">
              <CountList
                title="Practice area counts"
                items={profile.analytics.practice_area_counts}
              />
              <CountList
                title="Act / statute counts"
                items={profile.analytics.statute_counts}
              />
              <CountList
                title="Court counts"
                items={profile.analytics.court_counts}
              />
            </div>

            {!profile.analytics.pattern_claims_suppressed &&
            profile.analytics.practice_area_trends.length > 0 ? (
              <div>
                <div className="mb-2 text-sm font-semibold text-[var(--color-ink)]">
                  Practice area counts by year
                </div>
                <ul className="grid gap-2 md:grid-cols-2">
                  {profile.analytics.practice_area_trends.slice(0, 8).map((point) => (
                    <li
                      key={`${point.year}-${point.area}`}
                      className="flex items-center justify-between rounded-md border border-[var(--color-line)] bg-white px-3 py-2 text-sm"
                    >
                      <span className="text-[var(--color-ink-2)]">
                        {point.year} - {point.area}
                      </span>
                      <span className="tabular text-xs text-[var(--color-mute)]">
                        {point.count}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <AuthorityCaseList
              title="Source-backed case list"
              items={profile.analytics.case_list.slice(0, 8)}
            />
          </CardContent>
        </Card>
      ) : null}

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
                  <div className="mt-1 flex min-w-0 flex-wrap">
                    <SourceAction
                      action={appt.source_action}
                      compact
                      originSurface="judge_profile"
                    />
                  </div>
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

      <Card data-testid="judge-mapped-authorities">
        <CardHeader>
          <CardTitle>Mapped authorities</CardTitle>
          <CardDescription>
            Canonical judge mappings with source and confidence evidence.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <form
            className="grid min-w-0 gap-3 border-b border-[var(--color-line)] pb-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.2fr)_auto] sm:items-end"
            onSubmit={applyAuthorityFilters}
          >
            <label className="min-w-0 text-xs font-medium text-[var(--color-ink-2)]">
              From year
              <input
                type="number"
                min={1900}
                max={2100}
                value={yearFrom}
                onChange={(event) => setYearFrom(event.target.value)}
                className="mt-1 h-9 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-2 text-sm"
              />
            </label>
            <label className="min-w-0 text-xs font-medium text-[var(--color-ink-2)]">
              To year
              <input
                type="number"
                min={1900}
                max={2100}
                value={yearTo}
                onChange={(event) => setYearTo(event.target.value)}
                className="mt-1 h-9 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-2 text-sm"
              />
            </label>
            <label className="min-w-0 text-xs font-medium text-[var(--color-ink-2)]">
              Mapping confidence
              <select
                value={mappingConfidence}
                onChange={(event) => setMappingConfidence(event.target.value)}
                className="mt-1 h-9 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-2 text-sm"
              >
                <option value="">All mappings</option>
                <option value="exact">Exact</option>
                <option value="initial_surname">Initial and surname</option>
                <option value="high">High</option>
                <option value="low">Low</option>
                <option value="curator_confirmed">Curator confirmed</option>
              </select>
            </label>
            <div className="flex min-w-0 flex-wrap gap-2 sm:justify-end">
              {appliedFilters ? (
                <Button type="button" variant="secondary" onClick={resetAuthorityFilters}>
                  <RotateCcw className="h-4 w-4" aria-hidden /> Reset
                </Button>
              ) : null}
              <Button type="submit" disabled={authoritiesMutation.isPending}>
                <Filter className="h-4 w-4" aria-hidden /> Filter
              </Button>
            </div>
          </form>

          <div className="flex min-w-0 flex-wrap items-center justify-between gap-2 text-xs text-[var(--color-mute)]">
            <span>
              {visibleAuthorities.returned_count.toLocaleString()} shown of{" "}
              {visibleAuthorities.mapped_authority_count.toLocaleString()} mapped
            </span>
            <Link
              href={`/app/research?${researchQuery.toString()}`}
              className="inline-flex items-center gap-1.5 font-medium text-[var(--color-brand-700)] hover:underline"
            >
              <Search className="h-3.5 w-3.5" aria-hidden /> Research this judge
            </Link>
          </div>

          {authoritiesMutation.isError ? (
            <QueryErrorState
              title="Could not load mapped authorities"
              error={authoritiesMutation.error}
              onRetry={() =>
                authoritiesMutation.mutate({
                  mode: authorityView ? "append" : "replace",
                  cursor: authorityView?.next_cursor,
                  filters: appliedFilters ?? {},
                })
              }
            />
          ) : null}

          {visibleAuthorities.authorities.length === 0 ? (
            <EmptyState
              icon={Gavel}
              title={
                visibleAuthorities.coverage_state === "no_mapped_corpus"
                  ? "No mapped court corpus"
                  : visibleAuthorities.coverage_state === "no_judgments_for_judge"
                    ? "No mapped judgments for this judge"
                    : "No authorities match these filters"
              }
              description={visibleAuthorities.coverage_disclaimer}
            />
          ) : (
            <ul className="flex flex-col gap-2">
              {visibleAuthorities.authorities.map((authority) => (
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
                        {authority.neutral_citation}
                      </span>
                    ) : null}
                    <span className="rounded border border-[var(--color-line)] px-1.5 py-0.5 uppercase">
                      {authority.mapping_confidence.replace(/_/g, " ")}
                    </span>
                    {!authority.analytics_eligible ? (
                      <span className="font-medium text-[var(--color-warning-700)]">
                        Excluded from analytics
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-2 flex min-w-0 flex-wrap">
                    <SourceAction
                      action={authority.source_action}
                      compact
                      originSurface="judge_profile"
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
          {visibleAuthorities.has_more ? (
            <div className="flex justify-center border-t border-[var(--color-line)] pt-4">
              <Button
                type="button"
                variant="secondary"
                disabled={authoritiesMutation.isPending}
                onClick={() =>
                  authoritiesMutation.mutate({
                    mode: "append",
                    cursor: visibleAuthorities.next_cursor,
                    filters: appliedFilters ?? {},
                  })
                }
              >
                <LibraryBig className="h-4 w-4" aria-hidden /> Load more
              </Button>
            </div>
          ) : null}
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


function ContextStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-[var(--color-line)] bg-white px-3 py-3">
      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
        {label}
      </div>
      <div className="mt-1 tabular text-lg font-semibold text-[var(--color-ink)]">
        {value}
      </div>
    </div>
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

function CountList({
  title,
  items,
}: {
  title: string;
  items: { label: string; count: number }[];
}) {
  if (items.length === 0) {
    return (
      <div>
        <div className="mb-2 text-sm font-semibold text-[var(--color-ink)]">
          {title}
        </div>
        <div className="text-xs text-[var(--color-mute)]">
          No indexed metadata yet.
        </div>
      </div>
    );
  }
  return (
    <div>
      <div className="mb-2 text-sm font-semibold text-[var(--color-ink)]">
        {title}
      </div>
      <ul className="flex flex-col gap-2">
        {items.map((item) => (
          <li
            key={item.label}
            className="flex items-center justify-between rounded-md border border-[var(--color-line)] bg-white px-3 py-2 text-sm"
          >
            <span className="text-[var(--color-ink-2)]">{item.label}</span>
            <span className="tabular text-xs text-[var(--color-mute)]">
              {item.count}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AuthorityCaseList({
  title,
  items,
}: {
  title: string;
  items: {
    id: string;
    title: string;
    decision_date: string | null;
    case_reference: string | null;
    neutral_citation: string | null;
    source_reference: string | null;
    source_action: import("@/components/app/SourceAction").SourceActionContract;
    practice_area: string;
    summary_preview: string | null;
  }[];
}) {
  return (
    <div>
      <div className="mb-2 text-sm font-semibold text-[var(--color-ink)]">
        {title}
      </div>
      {items.length === 0 ? (
        <div className="text-xs text-[var(--color-mute)]">
          No indexed cases are available for this profile.
        </div>
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((authority) => (
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
                <span>{authority.practice_area}</span>
                {authority.case_reference ? (
                  <span className="font-mono">{authority.case_reference}</span>
                ) : null}
                {authority.neutral_citation ? (
                  <span className="font-mono">{authority.neutral_citation}</span>
                ) : null}
              </div>
              {authority.summary_preview ? (
                <p className="mt-2 text-xs leading-5 text-[var(--color-mute)]">
                  {authority.summary_preview}
                </p>
              ) : null}
              <div className="mt-2 flex min-w-0 flex-wrap">
                <SourceAction
                  action={authority.source_action}
                  compact
                  originSurface="judge_profile"
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
