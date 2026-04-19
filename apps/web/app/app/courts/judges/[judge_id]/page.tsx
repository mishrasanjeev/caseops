"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Briefcase, Gavel, LibraryBig } from "lucide-react";
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

      <section className="grid gap-4 md:grid-cols-2">
        <KpiCard
          icon={Briefcase}
          label="Your matters before this judge"
          value={String(profile.portfolio_matter_count)}
        />
        <KpiCard
          icon={LibraryBig}
          label="Authorities citing this judge"
          value={profile.authority_document_count.toLocaleString()}
        />
      </section>

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
