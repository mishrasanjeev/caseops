"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Scale } from "lucide-react";
import { useMemo } from "react";

import { Button } from "@/components/ui/Button";
import { DataTable } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { listContracts } from "@/lib/api/endpoints";
import type { Contract } from "@/lib/api/schemas";

const PAGE_SIZE = 50;

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleDateString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return value;
  }
}

function formatMoney(minor: number | null, currency: string): string {
  if (minor === null || minor === undefined) return "—";
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    minimumFractionDigits: 0,
  }).format(minor / 100);
}

export default function ContractsPage() {
  const {
    data,
    isPending,
    isError,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    refetch,
  } = useInfiniteQuery({
    queryKey: ["contracts", "list"],
    queryFn: ({ pageParam }) =>
      listContracts({ limit: PAGE_SIZE, cursor: pageParam ?? null }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });

  const columns = useMemo<ColumnDef<Contract>[]>(
    () => [
      {
        accessorKey: "contract_code",
        header: "Code",
        cell: (ctx) => (
          <span className="tabular font-mono text-xs text-[var(--color-ink-2)]">
            {ctx.getValue<string>()}
          </span>
        ),
      },
      {
        accessorKey: "title",
        header: "Contract",
        cell: (ctx) => (
          <div className="flex flex-col">
            <span className="font-medium text-[var(--color-ink)]">
              {ctx.getValue<string>()}
            </span>
            {ctx.row.original.counterparty_name ? (
              <span className="text-xs text-[var(--color-mute)]">
                with {ctx.row.original.counterparty_name}
              </span>
            ) : null}
          </div>
        ),
      },
      {
        accessorKey: "contract_type",
        header: "Type",
        cell: (ctx) => (
          <span className="text-xs text-[var(--color-mute)]">
            {ctx.getValue<string>()}
          </span>
        ),
      },
      {
        accessorKey: "effective_on",
        header: "Effective",
        cell: (ctx) => (
          <span className="tabular">{formatDate(ctx.getValue<string | null>())}</span>
        ),
      },
      {
        accessorKey: "expires_on",
        header: "Expires",
        cell: (ctx) => (
          <span className="tabular">{formatDate(ctx.getValue<string | null>())}</span>
        ),
      },
      {
        accessorKey: "total_value_minor",
        header: "Value",
        cell: (ctx) => (
          <span className="tabular">
            {formatMoney(ctx.getValue<number | null>(), ctx.row.original.currency)}
          </span>
        ),
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: (ctx) => <StatusBadge status={ctx.getValue<string>()} />,
      },
    ],
    [],
  );

  const contracts = useMemo(
    () => data?.pages.flatMap((page) => page.contracts) ?? [],
    [data],
  );

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Contracts"
        title="Contract repository"
        description="Every contract under your workspace. Full redline workspace rebuilt here lands with §9.2; use the legacy console for authoring until then."
        actions={
          <Button href="/legacy" variant="outline">
            Open legacy contracts
          </Button>
        }
      />

      {isPending ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      ) : isError ? (
        <QueryErrorState
          title="Could not load contracts"
          error={error}
          onRetry={refetch}
        />
      ) : contracts.length === 0 ? (
        <EmptyState
          icon={Scale}
          title="No contracts yet"
          description="Create your first contract from the legacy console while the rebuilt contract workspace is in progress."
          action={
            <Button href="/legacy" variant="outline">
              Open legacy console
            </Button>
          }
        />
      ) : (
        <>
          <DataTable
            data={contracts}
            columns={columns}
            filterPlaceholder="Search contracts, codes, counterparties…"
            getRowId={(c) => c.id}
          />
          {hasNextPage ? (
            <div className="flex justify-center">
              <Button
                variant="outline"
                onClick={() => fetchNextPage()}
                disabled={isFetchingNextPage}
              >
                {isFetchingNextPage ? "Loading…" : "Load more"}
              </Button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
