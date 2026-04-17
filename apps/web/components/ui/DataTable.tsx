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

type DataTableProps<TData, TValue> = {
  columns: ColumnDef<TData, TValue>[];
  data: TData[];
  filterPlaceholder?: string;
  emptyState?: ReactNode;
  initialPageSize?: number;
  onRowClick?: (row: TData) => void;
  getRowId?: (row: TData, index: number) => string;
};

export function DataTable<TData, TValue>({
  columns,
  data,
  filterPlaceholder = "Search…",
  emptyState,
  initialPageSize = 25,
  onRowClick,
  getRowId,
}: DataTableProps<TData, TValue>) {
  const [globalFilter, setGlobalFilter] = useState("");
  const [sorting, setSorting] = useState<SortingState>([]);

  const table = useReactTable({
    data,
    columns,
    state: { globalFilter, sorting },
    onGlobalFilterChange: setGlobalFilter,
    onSortingChange: setSorting,
    globalFilterFn: "includesString",
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getRowId: getRowId as ((row: TData, index: number) => string) | undefined,
    initialState: { pagination: { pageSize: initialPageSize } },
  });

  const rowCount = table.getFilteredRowModel().rows.length;
  const pageIndex = table.getState().pagination.pageIndex;
  const pageSize = table.getState().pagination.pageSize;
  const pageFrom = rowCount === 0 ? 0 : pageIndex * pageSize + 1;
  const pageTo = Math.min((pageIndex + 1) * pageSize, rowCount);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <div className="relative w-full max-w-xs">
          <Search
            aria-hidden
            className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-mute-2)]"
          />
          <Input
            value={globalFilter}
            onChange={(e) => setGlobalFilter(e.target.value)}
            placeholder={filterPlaceholder}
            className="pl-8"
            aria-label="Filter rows"
          />
        </div>
        <div className="ml-auto text-xs text-[var(--color-mute)]">
          {rowCount === 0
            ? "No results"
            : `${pageFrom}-${pageTo} of ${rowCount}`}
        </div>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-[var(--color-line)] bg-white">
        <table className="w-full text-sm">
          <thead>
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id} className="border-b border-[var(--color-line)] bg-[var(--color-bg)]">
                {group.headers.map((header) => {
                  const canSort = header.column.getCanSort();
                  const dir = header.column.getIsSorted();
                  return (
                    <th
                      key={header.id}
                      scope="col"
                      className="px-4 py-2.5 text-left font-semibold text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]"
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
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="px-4 py-3 text-[var(--color-ink-2)]">
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
        <span>
          Page {pageIndex + 1} of {Math.max(1, table.getPageCount())}
        </span>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            aria-label="Previous page"
            className="rounded-md border border-[var(--color-line)] bg-white px-2.5 py-1 disabled:opacity-50"
            onClick={() => table.previousPage()}
            disabled={!table.getCanPreviousPage()}
          >
            Previous
          </button>
          <button
            type="button"
            aria-label="Next page"
            className="rounded-md border border-[var(--color-line)] bg-white px-2.5 py-1 disabled:opacity-50"
            onClick={() => table.nextPage()}
            disabled={!table.getCanNextPage()}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
