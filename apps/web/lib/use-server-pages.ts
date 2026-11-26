"use client";

import type { InfiniteData } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { apiErrorMessage } from "@/lib/api/config";

type FetchNextResult<TPage> = {
  isError: boolean;
  error: unknown;
  data?: InfiniteData<TPage, unknown>;
};

/**
 * Page-at-a-time navigation over a cursor-paged server list.
 *
 * Next shows the next loaded page, or asks the server for it, so the user
 * never has to press "Load more" before Next works (Nov 24 workbook row 4).
 * Changing `listKey` (a new search or filter) returns to page 1.
 */
export function useServerPages<TPage>({
  listKey,
  data,
  hasNextPage,
  fetchNextPage,
  errorMessage,
}: {
  listKey: string;
  data: InfiniteData<TPage, unknown> | undefined;
  hasNextPage: boolean;
  fetchNextPage: () => Promise<FetchNextResult<TPage>>;
  errorMessage: string;
}) {
  const [state, setState] = useState({ key: listKey, index: 0 });
  const pages = data?.pages ?? [];
  const requested = state.key === listKey ? state.index : 0;
  const pageIndex = Math.min(requested, Math.max(0, pages.length - 1));

  async function goToNextPage() {
    const key = listKey;
    const next = pageIndex + 1;
    if (next < pages.length) {
      setState({ key, index: next });
      return;
    }
    if (!hasNextPage) return;
    const result = await fetchNextPage();
    if (result.isError) {
      toast.error(apiErrorMessage(result.error, errorMessage));
      return;
    }
    if ((result.data?.pages.length ?? 0) > next) setState({ key, index: next });
  }

  function goToPreviousPage() {
    setState({ key: listKey, index: Math.max(0, pageIndex - 1) });
  }

  return {
    pageIndex,
    page: pages[pageIndex] as TPage | undefined,
    firstPage: pages[0] as TPage | undefined,
    canPreviousPage: pageIndex > 0,
    canNextPage: pageIndex + 1 < pages.length || hasNextPage,
    goToNextPage,
    goToPreviousPage,
  };
}
