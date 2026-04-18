"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Briefcase, Gavel, LibraryBig, Users } from "lucide-react";
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
import { fetchCourtProfile } from "@/lib/api/endpoints";

export default function CourtProfilePage() {
  const params = useParams<{ id: string }>();
  const courtId = params.id;
  const profileQuery = useQuery({
    queryKey: ["courts", courtId, "profile"],
    queryFn: () => fetchCourtProfile(courtId),
    enabled: Boolean(courtId),
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
        title="Could not load court profile"
        error={profileQuery.error}
        onRetry={profileQuery.refetch}
      />
    );
  }
  const profile = profileQuery.data;
  if (!profile) return null;

  return (
    <div className="flex flex-col gap-6">
      <Link
        href="/app/courts"
        className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-mute)] hover:text-[var(--color-ink)]"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Back to courts
      </Link>

      <PageHeader
        eyebrow={profile.court.forum_level.replace(/_/g, " ")}
        title={profile.court.name}
        description={
          profile.court.jurisdiction
            ? `${profile.court.jurisdiction}${profile.court.seat_city ? ` · ${profile.court.seat_city}` : ""}`
            : profile.court.seat_city ?? profile.court.short_name
        }
      />

      <section className="grid gap-4 md:grid-cols-3">
        <KpiCard
          icon={Users}
          label="Judges on record"
          value={String(profile.judges.length)}
        />
        <KpiCard
          icon={Briefcase}
          label="Your matters here"
          value={String(profile.portfolio_matter_count)}
        />
        <KpiCard
          icon={LibraryBig}
          label="Authorities indexed"
          value={profile.authority_document_count.toLocaleString()}
        />
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Judges</CardTitle>
            <CardDescription>
              Active judges recorded against this court.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {profile.judges.length === 0 ? (
              <EmptyState
                icon={Users}
                title="No judges listed"
                description="The registry hasn't catalogued judges for this court yet."
              />
            ) : (
              <ul className="divide-y divide-[var(--color-line-2)]">
                {profile.judges.map((judge) => (
                  <li key={judge.id} className="py-2.5">
                    <div className="text-sm font-medium text-[var(--color-ink)]">
                      {judge.honorific ? `${judge.honorific} ` : ""}
                      {judge.full_name}
                    </div>
                    {judge.current_position ? (
                      <div className="text-xs text-[var(--color-mute)]">
                        {judge.current_position}
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Recent authorities from this court</CardTitle>
            <CardDescription>
              Most recent judgments in the indexed corpus.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {profile.recent_authorities.length === 0 ? (
              <EmptyState
                icon={Gavel}
                title="No authorities indexed"
                description="This court has no judgments in the corpus yet. They'll appear here as the ingest catches up."
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
