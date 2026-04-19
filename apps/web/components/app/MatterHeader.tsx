"use client";

import { ArrowLeft, Briefcase, ExternalLink, Gavel, Scale, User } from "lucide-react";
import Link from "next/link";

import { MatterTeamPicker } from "@/components/app/MatterTeamPicker";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { cn } from "@/lib/cn";
import type { WorkspaceMatter } from "@/lib/api/workspace-types";
import { formatLegalDate } from "@/lib/dates";

const FORUM_LABEL: Record<string, string> = {
  lower_court: "Lower court",
  high_court: "High Court",
  supreme_court: "Supreme Court",
  tribunal: "Tribunal",
};

function formatDate(value: string | null | undefined): string {
  // next_hearing_on is a SQL Date — parse local to avoid the off-by-
  // one that new Date("YYYY-MM-DD") triggers in UTC-negative zones.
  return formatLegalDate(value, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function MatterHeader({ matter }: { matter: WorkspaceMatter }) {
  const forumLabel = matter.forum_level ? FORUM_LABEL[matter.forum_level] ?? matter.forum_level : null;
  const facts: { icon: typeof Briefcase; label: string; value: string }[] = [
    { icon: Briefcase, label: "Code", value: matter.matter_code },
    { icon: Scale, label: "Forum", value: forumLabel ?? "—" },
    { icon: Gavel, label: "Next hearing", value: formatDate(matter.next_hearing_on) },
    { icon: User, label: "Client", value: matter.client_name ?? "—" },
  ];

  return (
    <div className="flex flex-col gap-4">
      <Link
        href="/app/matters"
        className="inline-flex items-center gap-1.5 self-start text-sm font-medium text-[var(--color-mute)] hover:text-[var(--color-ink)]"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden /> All matters
      </Link>

      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between md:gap-6">
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={matter.status} />
            {matter.practice_area ? (
              <span className="inline-flex items-center rounded-full border border-[var(--color-line)] bg-white px-2.5 py-0.5 text-xs font-medium text-[var(--color-ink-2)]">
                {matter.practice_area}
              </span>
            ) : null}
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--color-ink)] md:text-3xl">
            {matter.title}
          </h1>
          {matter.opposing_party ? (
            <p className="text-sm text-[var(--color-mute)]">
              {matter.client_name ?? "Client"} <span className="opacity-60">v.</span>{" "}
              {matter.opposing_party}
            </p>
          ) : null}
        </div>
        <div className="flex flex-col items-stretch gap-2 md:items-end">
          <div className="inline-flex items-center gap-2 rounded-full border border-[var(--color-line)] bg-white px-3 py-1.5 text-xs text-[var(--color-mute)]">
            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            {matter.court_name ?? "No court"}
          </div>
          <MatterTeamPicker matterId={matter.id} currentTeamId={matter.team_id} />
        </div>
      </div>

      <dl className="grid gap-2 md:grid-cols-4">
        {facts.map((fact) => (
          <div
            key={fact.label}
            className={cn(
              "flex items-center gap-3 rounded-xl border border-[var(--color-line)] bg-white px-4 py-3",
            )}
          >
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--color-bg)] text-[var(--color-ink-3)]">
              <fact.icon className="h-4 w-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <dt className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
                {fact.label}
              </dt>
              <dd className="truncate text-sm font-medium text-[var(--color-ink)]">
                {fact.value}
              </dd>
            </div>
          </div>
        ))}
      </dl>
    </div>
  );
}
