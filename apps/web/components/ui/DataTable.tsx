"use client";

import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, Search } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";

import { Input } from "@/components/ui/Input";
import { cn } from "@/lib/cn";

// A pinned last column stays at the right edge of the scrolling table, so a
// row's actions are on screen (B4-ADJ-13). Below 40rem a pinned column would
// cover the row's other cells, so the table stacks into labelled rows instead.
const PINNED_HEADER = "@min-[40rem]:sticky @min-[40rem]:right-0 @min-[40rem]:z-[1] bg-[var(--color-bg)] @min-[40rem]:shadow-[-1px_0_0_var(--color-line)]";
const PINNED_CELL = "@min-[40rem]:sticky @min-[40rem]:right-0 @min-[40rem]:z-[1] bg-white @min-[40rem]:shadow-[-1px_0_0_var(--color-line)]";

/**
 * The server owns search and paging. Use this whenever `data` is one page of
 * a larger server list: the client filter, pager and sorting below only ever
 * see the rows they were given, so without it a search misses unloaded
 * Matters and Next stops at the last loaded row (Nov 24 workbook rows 4-5).
 */
export type DataTableServerMode = {
  search: string;
  onSearchChange: (value: string) => void;
  /** Zero-based index of the page whose rows are in `data`. */
  pageIndex: number;
  pageSize: number;
  /** Every matching row on the server, or null when the server did not say. */
  totalCount: number | null;
  canPreviousPage: boolean;
  canNextPage: boolean;
  /** A search or page request is in flight. */
  busy?: boolean;
  onPreviousPage: () => void;
  onNextPage: () => void;
};

type DataTableProps<TData, TValue> = {
  columns: ColumnDef<TData, TValue>[];
  data: TData[];
  filterPlaceholder?: string;
  emptyState?: ReactNode;
  initialPageSize?: number;
  onRowClick?: (row: TData) => void;
  getRowId?: (row: TData, index: number) => string;
  /** Keep the last column (a row's actions) on screen while the others scroll sideways. */
  pinLastColumn?: boolean;
} & (
  // Every caller must say which kind of rows it passes. The client search,
  // pager and sorting are only truthful over the complete list; a page of a
  // larger server list must use `server` (B4-ADJ-03 and Nov 24 rows 4-5 were
  // this defect, fixed per screen while the table stayed unsafe by default).
  | { server: DataTableServerMode; completeData?: never }
  | { /** `data` is every row the reader may see, not one page or a capped read. */ completeData: true; server?: never }
);

export function DataTable<TData, TValue>({
  columns,
  data,
  filterPlaceholder = "Search…",
  emptyState,
  initialPageSize = 25,
  onRowClick,
  getRowId,
  pinLastColumn = false,
  server,
}: DataTableProps<TData, TValue>) {
  const [globalFilter, setGlobalFilter] = useState("");
  const [sorting, setSorting] = useState<SortingState>([]);

  const table = useReactTable({
    data,
    columns,
    state: { globalFilter: server ? "" : globalFilter, sorting },
    onGlobalFilterChange: setGlobalFilter,
    onSortingChange: setSorting,
    globalFilterFn: "includesString",
    // Sorting one server page would present a partial order as the whole list.
    enableSorting: !server,
    manualFiltering: Boolean(server),
    manualPagination: Boolean(server),
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getRowId: getRowId as ((row: TData, index: number) => string) | undefined,
    initialState: { pagination: { pageSize: initialPageSize } },
  });

  const rowCount = server ? data.length : table.getFilteredRowModel().rows.length;
  const pageIndex = server ? server.pageIndex : table.getState().pagination.pageIndex;
  const pageSize = server ? server.pageSize : table.getState().pagination.pageSize;
  const pageFrom = rowCount === 0 ? 0 : pageIndex * pageSize + 1;
  const pageTo = server ? pageIndex * pageSize + rowCount : Math.min((pageIndex + 1) * pageSize, rowCount);
  const ofTotal = server
    ? server.totalCount === null
      ? ""
      : ` of ${server.totalCount}`
    : ` of ${rowCount}`;
  const pageCount = server
    ? server.totalCount === null
      ? null
      : Math.max(1, Math.ceil(server.totalCount / server.pageSize))
    : Math.max(1, table.getPageCount());
  const canPrevious = server ? server.canPreviousPage && !server.busy : table.getCanPreviousPage();
  const canNext = server ? server.canNextPage && !server.busy : table.getCanNextPage();

  return (
    <div className="flex flex-col gap-3" aria-busy={server?.busy || undefined}>
      <div className="flex items-center gap-2">
        <div className="relative w-full max-w-xs">
          <Search
            aria-hidden
            className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-mute-2)]"
          />
          <Input
            value={server ? server.search : globalFilter}
            onChange={(e) =>
              server ? server.onSearchChange(e.target.value) : setGlobalFilter(e.target.value)
            }
            placeholder={filterPlaceholder}
            className="pl-8"
            aria-label={server ? "Search all rows" : "Filter rows"}
            type={server ? "search" : undefined}
          />
        </div>
        <div
          className="ml-auto text-xs text-[var(--color-mute)]"
          role={server ? "status" : undefined}
          data-testid="data-table-range"
        >
          {server?.busy
            ? "Loading…"
            : rowCount === 0
              ? "No results"
              : `${pageFrom}-${pageTo}${ofTotal}`}
        </div>
      </div>

      <div className={cn("overflow-x-auto rounded-2xl border border-[var(--color-line)] bg-white", pinLastColumn && "@container")}>
        <table className={cn("w-full text-sm", pinLastColumn && "@max-[40rem]:stacked-table @max-[40rem]:px-4")}>
          <thead>
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id} className="border-b border-[var(--color-line)] bg-[var(--color-bg)]">
                {group.headers.map((header, index) => {
                  const canSort = header.column.getCanSort();
                  const dir = header.column.getIsSorted();
                  return (
                    <th
                      key={header.id}
                      scope="col"
                      className={cn(
                        "px-4 py-2.5 text-left font-semibold text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]",
                        pinLastColumn && index === group.headers.length - 1 && PINNED_HEADER,
                      )}
                    >
                      {header.isPlaceholder ? null : (
                        <button
                          type="button"
                          onClick={canSort ? header.column.getToggleSortingHandler() : undefined}
                          className={cn(
                            "inline-flex items-center gap-1.5",
                            canSort && "cursor-pointer hover:text-[var(--color-ink)]",
                          )}
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {canSort ? (
                            dir === "asc" ? (
                              <ArrowUp className="h-3 w-3" aria-hidden />
                            ) : dir === "desc" ? (
                              <ArrowDown className="h-3 w-3" aria-hidden />
                            ) : (
                              <ArrowUpDown className="h-3 w-3 opacity-40" aria-hidden />
                            )
                          ) : null}
                        </button>
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-4 py-12 text-center text-sm text-[var(--color-mute)]"
                >
                  {emptyState ?? "Nothing to show yet."}
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row) => {
                const activate = onRowClick
                  ? () => onRowClick(row.original)
                  : undefined;
                return (
                  <tr
                    key={row.id}
                    onClick={activate}
                    onKeyDown={
                      activate
                        ? (event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              activate();
                            }
                          }
                        : undefined
                    }
                    role={activate ? "button" : undefined}
                    tabIndex={activate ? 0 : undefined}
                    className={cn(
                      "border-b border-[var(--color-line-2)] last:border-0 transition-colors",
                      activate &&
                        "cursor-pointer hover:bg-[var(--color-bg-2)] focus-visible:bg-[var(--color-bg-2)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--color-brand-500)]",
                    )}
                  >
                    {row.getVisibleCells().map((cell, index, cells) => (
                      <td
                        key={cell.id}
                        data-label={pinLastColumn && typeof cell.column.columnDef.header === "string" ? cell.column.columnDef.header : undefined}
                        className={cn(
                          "px-4 py-3 text-[var(--color-ink-2)]",
                          pinLastColumn && index === cells.length - 1 && PINNED_CELL,
                        )}
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-xs text-[var(--color-mute)]">
        <span data-testid="data-table-page">
          Page {pageIndex + 1}
          {pageCount === null ? "" : ` of ${pageCount}`}
        </span>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            aria-label="Previous page"
            className="rounded-md border border-[var(--color-line)] bg-white px-2.5 py-1 disabled:opacity-50"
            onClick={() => (server ? server.onPreviousPage() : table.previousPage())}
            disabled={!canPrevious}
          >
            Previous
          </button>
          <button
            type="button"
            aria-label="Next page"
            className="rounded-md border border-[var(--color-line)] bg-white px-2.5 py-1 disabled:opacity-50"
            onClick={() => (server ? server.onNextPage() : table.nextPage())}
            disabled={!canNext}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
