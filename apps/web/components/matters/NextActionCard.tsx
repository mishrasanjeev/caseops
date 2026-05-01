"use client";

// PG-004 follow-up (2026-05-01) — per-matter Next-action card.
// Renders the single highest-priority item demanding attention on
// THIS matter as a prominent CTA at the top of the cockpit. Pulls
// from /api/matters/{id}/next-action.

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Clock, Sun } from "lucide-react";
import Link from "next/link";

import { Card, CardContent } from "@/components/ui/Card";
import { fetchMatterNextAction } from "@/lib/api/endpoints";

export function NextActionCard({ matterId }: { matterId: string }) {
  const query = useQuery({
    queryKey: ["matter", matterId, "next-action"],
    queryFn: () => fetchMatterNextAction(matterId),
  });

  if (query.isPending || query.isError) return null;
  const action = query.data;
  if (!action) return null;

  const tone =
    action.severity === "urgent"
      ? "border-red-300 bg-red-50"
      : action.severity === "soon"
        ? "border-amber-300 bg-amber-50"
        : "border-[var(--color-line)] bg-[var(--color-bg-2)]";

  const Icon =
    action.severity === "urgent" ? AlertTriangle : action.severity === "soon" ? Clock : Sun;
  const iconTone =
    action.severity === "urgent"
      ? "text-red-700"
      : action.severity === "soon"
        ? "text-amber-700"
        : "text-[var(--color-brand-700)]";

  return (
    <Card className={tone} data-testid="matter-next-action">
      <CardContent className="flex items-start gap-3 py-4">
        <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${iconTone}`} aria-hidden />
        <div className="flex-1">
          <p className="text-xs font-semibold uppercase tracking-wide text-[var(--color-mute)]">
            Next action
          </p>
          <p className="mt-0.5 text-sm font-semibold text-[var(--color-ink)]">
            {action.label}
          </p>
          <p className="mt-0.5 text-xs text-[var(--color-mute)]">{action.detail}</p>
        </div>
        <Link
          href={action.href}
          className="inline-flex items-center gap-1 self-center rounded-md border border-[var(--color-line)] bg-white px-3 py-1.5 text-xs font-medium text-[var(--color-ink)] hover:bg-[var(--color-bg-2)]"
          data-testid="matter-next-action-go"
        >
          Open <ArrowRight className="h-3.5 w-3.5" aria-hidden />
        </Link>
      </CardContent>
    </Card>
  );
}
