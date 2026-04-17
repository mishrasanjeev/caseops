"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Briefcase, Gavel, LibraryBig, Sparkles } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { listMatters } from "@/lib/api/endpoints";
import type { Matter } from "@/lib/api/schemas";
import { useSession } from "@/lib/use-session";

export default function DashboardPage() {
  const session = useSession();
  const mattersQuery = useQuery({
    queryKey: ["matters", "list"],
    queryFn: () => listMatters(),
    enabled: session.status === "authenticated",
  });

  const matters = mattersQuery.data?.matters ?? [];
  const activeCount = matters.filter((m) => m.status === "active").length;
  const upcoming = [...matters]
    .filter((m) => !!m.next_hearing_on)
    .sort((a, b) => (a.next_hearing_on ?? "").localeCompare(b.next_hearing_on ?? ""))
    .slice(0, 5);
  const recent = [...matters]
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, 5);

  const userFirstName = session.context?.user.full_name.split(" ")[0] ?? "there";

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        eyebrow="Home"
        title={`Good to have you back, ${userFirstName}.`}
        description="One glance at your portfolio — matters in flight, what's coming up, and where AI can help."
        actions={
          <Button href="/app/matters">
            Open matters <ArrowUpRight className="h-4 w-4" />
          </Button>
        }
      />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          icon={Briefcase}
          label="Active matters"
          value={mattersQuery.isPending ? "—" : String(activeCount)}
          hint={mattersQuery.isPending ? "Loading" : `${matters.length} total in workspace`}
        />
        <StatCard
          icon={Gavel}
          label="Hearings this week"
          value="—"
          hint="Cause-list sync lands with §12.1"
        />
        <StatCard
          icon={Sparkles}
          label="Recommendations"
          value="—"
          hint="Engine ships in Phase 4"
        />
        <StatCard
          icon={LibraryBig}
          label="Authorities indexed"
          value="—"
          hint="Retrieval upgrade in §4.2"
        />
      </section>

      <section className="grid gap-5 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader className="flex-row items-start justify-between gap-4">
            <div>
              <CardTitle>Upcoming hearings</CardTitle>
              <CardDescription>
                Matters with a scheduled hearing, sorted by date.
              </CardDescription>
            </div>
            <Button href="/app/matters" variant="outline" size="sm">
              Open matters
            </Button>
          </CardHeader>
          <CardContent>
            {mattersQuery.isPending ? (
              <div className="flex flex-col gap-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : upcoming.length === 0 ? (
              <EmptyState
                icon={Gavel}
                title="No upcoming hearings"
                description="Add a next-hearing date to a matter and it will show up here."
              />
            ) : (
              <ul className="divide-y divide-[var(--color-line-2)]">
                {upcoming.map((matter) => (
                  <li key={matter.id} className="py-3">
                    <MatterRow matter={matter} />
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Recently opened</CardTitle>
            <CardDescription>Your last five matters.</CardDescription>
          </CardHeader>
          <CardContent>
            {mattersQuery.isPending ? (
              <div className="flex flex-col gap-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : recent.length === 0 ? (
              <EmptyState
                icon={Briefcase}
                title="No matters yet"
                description="Create your first matter to start tracking work."
                action={<Button href="/app/matters">Create a matter</Button>}
              />
            ) : (
              <ul className="flex flex-col gap-2">
                {recent.map((matter) => (
                  <li key={matter.id}>
                    <Link
                      href={`/app/matters/${matter.id}`}
                      className="flex items-center justify-between gap-3 rounded-md px-2 py-2 transition-colors hover:bg-[var(--color-bg-2)]"
                    >
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium text-[var(--color-ink)]">
                          {matter.title}
                        </div>
                        <div className="truncate text-xs text-[var(--color-mute)]">
                          {matter.matter_code}
                        </div>
                      </div>
                      <StatusBadge status={matter.status} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof Briefcase;
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <Card>
      <CardContent className="flex items-start gap-4 py-5">
        <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--color-brand-50)] text-[var(--color-brand-700)]">
          <Icon className="h-5 w-5" aria-hidden />
        </span>
        <div className="flex flex-col gap-1">
          <div className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
            {label}
          </div>
          <div className="tabular text-2xl font-semibold tracking-tight text-[var(--color-ink)]">{value}</div>
          <div className="text-xs text-[var(--color-mute)]">{hint}</div>
        </div>
      </CardContent>
    </Card>
  );
}

function MatterRow({ matter }: { matter: Matter }) {
  const hearingDate = matter.next_hearing_on
    ? new Date(matter.next_hearing_on).toLocaleDateString(undefined, {
        day: "2-digit",
        month: "short",
        year: "numeric",
      })
    : "—";
  return (
    <Link
      href={`/app/matters/${matter.id}`}
      className="flex items-center justify-between gap-3 rounded-md px-2 py-2 transition-colors hover:bg-[var(--color-bg-2)]"
    >
      <div className="min-w-0">
        <div className="truncate text-sm font-medium text-[var(--color-ink)]">{matter.title}</div>
        <div className="truncate text-xs text-[var(--color-mute)]">
          {matter.court_name ?? matter.forum_level ?? matter.matter_code}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <span className="text-xs font-medium text-[var(--color-ink-2)]">{hearingDate}</span>
        <StatusBadge status={matter.status} />
      </div>
    </Link>
  );
}
