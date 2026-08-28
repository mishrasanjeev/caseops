"use client";

import { useQuery } from "@tanstack/react-query";

import { fetchMatterWorkspace } from "@/lib/api/endpoints";
import type { WorkspaceResponse } from "@/lib/api/workspace-types";

export function useMatterWorkspace(matterId: string) {
  return useQuery({
    queryKey: ["matters", matterId, "workspace"],
    queryFn: async ({ signal }) =>
      (await fetchMatterWorkspace(matterId, { signal })) as WorkspaceResponse,
    enabled: Boolean(matterId),
  });
}
