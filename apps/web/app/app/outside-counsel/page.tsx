"use client";

import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Banknote, Briefcase, Users } from "lucide-react";
import { useMemo } from "react";

import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { fetchOutsideCounselWorkspace } from "@/lib/api/endpoints";
import type { OutsideCounsel } from "@/lib/api/schemas";

function formatMoney(minor: number, currency: string): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    minimumFractionDigits: 0,
  }).format(minor / 100);
}

export default function OutsideCounselPage() {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ["outside-counsel", "workspace"],
    queryFn: () => fetchOutsideCounselWorkspace(),
  });

  const currency = data?.summary.currency ?? "INR";
  const profiles = data?.profiles ?? [];

  const columns = useMemo<ColumnDef<OutsideCounsel>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Counsel",
        cell: (ctx) => (
          <div className="flex flex-col">
            <span className="font-medium text-[var(--color-ink)]">
              {ctx.getValue<string>()}
            </span>
            {ctx.row.original.primary_contact_name ? (
              <span className="text-xs text-[var(--color-mute)]">
                {ctx.row.original.primary_contact_name}
                {ctx.row.original.firm_city ? ` · ${ctx.row.original.firm_city}` : ""}
              </span>
            ) : null}
          </div>
        ),
      },
      {
        id: "practice_areas",
        header: "Practice",
        accessorFn: (row) => row.practice_areas.join(", "),
        cell: (ctx) => (
          <span className="text-xs text-[var(--color-mute)]">
            {ctx.getValue<string>() || "—"}
          </span>
        ),
      },
      {
        accessorKey: "active_matters_count",
        header: "Active",
        cell: (ctx) => <span className="tabular">{ctx.getValue<number>()}</span>,
      },
      {
        accessorKey: "total_matters_count",
        header: "Total matters",
        cell: (ctx) => <span className="tabular">{ctx.getValue<number>()}</span>,
      },
      {
        accessorKey: "approved_spend_minor",
        header: "Approved spend",
        cell: (ctx) => (
          <span className="tabular">
            {formatMoney(ctx.getValue<number>(), currency)}
          </span>
        ),
      },
      {
        accessorKey: "panel_status",
        header: "Panel",
        cell: (ctx) => <StatusBadge status={ctx.getValue<string>()} />,
      },
    ],
    [currency],
  );

  const summary = data?.summary;
  const totalSpend = summary?.total_spend_minor ?? 0;
  const approved = summary?.approved_spend_minor ?? 0;
  const activeAssignments = summary?.active_assignment_count ?? 0;
  const profileCount = summary?.profile_count ?? profiles.length;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Outside counsel"
        title="Outside counsel & spend"
        description="Panel profiles, active assignments, and spend in one place. Use the legacy console for assigning counsel and logging spend until those flows are rebuilt here."
        actions={
          <Button href="/legacy" variant="outline">
            Open legacy counsel
          </Button>
        }
      />

      <section className="grid gap-4 md:grid-cols-4">
        <KpiCard
          icon={Users}
          label="Counsel profiles"
          value={String(profileCount)}
        />
        <KpiCard
          icon={Briefcase}
          label="Active assignments"
          value={String(activeAssignments)}
        />
        <KpiCard
          icon={Banknote}
          label="Approved spend"
          value={formatMoney(approved, currency)}
        />
        <KpiCard
          icon={Banknote}
          label="Total spend"
          value={formatMoney(totalSpend, currency)}
        />
      </section>

      {isPending ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      ) : isError ? (
        <QueryErrorState
          title="Could not load counsel"
          error={error}
          onRetry={refetch}
        />
      ) : profiles.length === 0 ? (
        <EmptyState
          icon={Users}
          title="No counsel on panel yet"
          description="Add outside counsel from the legacy console; a rebuilt assignment flow ships with §10.8."
          action={
            <Button href="/legacy" variant="outline">
              Open legacy console
            </Button>
          }
        />
      ) : (
        <DataTable
          data={profiles}
          columns={columns}
          filterPlaceholder="Search counsel, contact, practice…"
          getRowId={(p) => p.id}
        />
      )}
    </div>
  );
}

function KpiCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Users;
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
