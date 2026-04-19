"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Users } from "lucide-react";
import { useState } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
import { assignMatterTeam, listTeams } from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

const NONE_VALUE = "__none__";

export function MatterTeamPicker({
  matterId,
  currentTeamId,
}: {
  matterId: string;
  currentTeamId: string | null | undefined;
}) {
  const canManage = useCapability("matters:edit");
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<string | null>(null);

  const { data } = useQuery({
    queryKey: ["teams", "list"],
    queryFn: () => listTeams(),
    enabled: canManage,
    staleTime: 60_000,
  });

  const mutation = useMutation({
    mutationFn: (teamId: string | null) =>
      assignMatterTeam({ matterId, teamId }),
    onSettled: () => {
      setPending(null);
      void queryClient.invalidateQueries({ queryKey: ["matter-workspace", matterId] });
    },
  });

  // Hide the picker when the workspace doesn't have team-scoping enabled
  // and there are no teams to assign — saves clutter on small tenants.
  if (!canManage) return null;
  const teams = data?.teams ?? [];
  const scopingEnabled = data?.team_scoping_enabled ?? false;
  if (teams.length === 0 && !scopingEnabled) return null;

  const value = pending ?? currentTeamId ?? NONE_VALUE;

  return (
    <div className="flex items-center gap-2 rounded-full border border-[var(--color-line)] bg-white px-3 py-1.5 text-xs text-[var(--color-mute)]">
      <Users className="h-3.5 w-3.5" aria-hidden />
      <span className="font-medium uppercase tracking-[0.12em] text-[var(--color-mute-2)]">
        Team
      </span>
      <Select
        value={value}
        onValueChange={(next) => {
          setPending(next);
          mutation.mutate(next === NONE_VALUE ? null : next);
        }}
        disabled={mutation.isPending}
      >
        <SelectTrigger className="h-7 w-44 border-none bg-transparent px-2 text-xs shadow-none focus-visible:ring-1">
          <SelectValue placeholder="Unassigned" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE_VALUE}>Unassigned</SelectItem>
          {teams.map((team) => (
            <SelectItem key={team.id} value={team.id}>
              {team.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
