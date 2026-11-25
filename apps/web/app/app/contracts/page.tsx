"use client";

import { keepPreviousData, useInfiniteQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { RotateCcw, Scale } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { NewContractDialog } from "@/components/app/NewContractDialog";
import { Button } from "@/components/ui/Button";
import { DataTable } from "@/components/ui/DataTable";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { listContracts } from "@/lib/api/endpoints";
import type { Contract } from "@/lib/api/schemas";
import { useCapability } from "@/lib/capabilities";
import { formatLegalDate } from "@/lib/dates";
import { useServerPages } from "@/lib/use-server-pages";

// Search and paging run on the server; see components/ui/DataTable server mode.
const PAGE_SIZE = 50;
const SEARCH_DEBOUNCE_MS = 300;

function formatDate(value: string | null | undefined): string {
  // Contract effective_on / expires_on are SQL Date values —
  // render in local calendar to prevent off-by-one in US timezones.
  return formatLegalDate(value, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
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
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const handle = window.setTimeout(() => setQuery(search.trim()), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [search]);
  const {
    data,
    isPending,
    isError,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isPlaceholderData,
    refetch,
  } = useInfiniteQuery({
    queryKey: ["contracts", "list", { query }],
    queryFn: ({ pageParam }) =>
      listContracts({
        limit: PAGE_SIZE,
        cursor: pageParam ?? null,
        q: query || undefined,
        include_total: pageParam === null,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    placeholderData: keepPreviousData,
  });
  const pager = useServerPages({
    listKey: query,
    data,
    hasNextPage: Boolean(hasNextPage),
    fetchNextPage,
    errorMessage: "Could not load the next page of contracts.",
  });
  const canCreateContract = useCapability("contracts:create");

  const columns = useMemo<ColumnDef<Contract>[]>(
    () => [
      {
        accessorKey: "contract_code",
        header: "Code",
        cell: (ctx) => (
          <Link
            href={`/app/contracts/${ctx.row.original.id}`}
            className="tabular font-mono text-xs font-medium text-[var(--color-brand-700)] hover:underline"
          >
            {ctx.getValue<string>()}
          </Link>
        ),
      },
      {
        accessorKey: "title",
        header: "Contract",
        cell: (ctx) => (
          <div className="flex flex-col">
            <Link
              href={`/app/contracts/${ctx.row.original.id}`}
              className="font-medium text-[var(--color-ink)] hover:underline"
            >
              {ctx.getValue<string>()}
            </Link>
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

  const contracts = pager.page?.contracts ?? [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Contracts"
        title="Contract repository"
        description="Every contract under your workspace. Open one to extract clauses, run the playbook comparison, and view counterparty redlines."
        actions={canCreateContract ? <NewContractDialog /> : null}
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
      ) : contracts.length === 0 && !query && !search.trim() && !isPlaceholderData ? (
        <EmptyState
          icon={Scale}
          title="No contracts yet"
          description={
            canCreateContract
              ? "Create your first contract. You can upload the draft, extract clauses and obligations, and run the playbook comparison from the detail page."
              : "Ask a team member with contract-create access to add the first contract."
          }
          action={canCreateContract ? <NewContractDialog /> : undefined}
        />
      ) : (
        <DataTable
          data={contracts}
          columns={columns}
          filterPlaceholder="Search contracts, codes, counterparties…"
          getRowId={(c) => c.id}
          emptyState={
            <div className="flex flex-col items-center gap-3">
              <span>No contracts match this search.</span>
              <Button type="button" variant="outline" onClick={() => setSearch("")}>
                <RotateCcw className="h-4 w-4" /> Clear search
              </Button>
            </div>
          }
          server={{
            search,
            onSearchChange: setSearch,
            pageIndex: pager.pageIndex,
            pageSize: PAGE_SIZE,
            totalCount: pager.firstPage?.total_count ?? null,
            canPreviousPage: pager.canPreviousPage,
            canNextPage: pager.canNextPage,
            busy: isFetchingNextPage || isPlaceholderData,
            onPreviousPage: pager.goToPreviousPage,
            onNextPage: () => void pager.goToNextPage(),
          }}
        />
      )}
    </div>
  );
}
