"use client";

/**
 * Workspace-admin tenant AI policy controls (PG-107).
 *
 * v1: a single toggle for `predictive_bench_strategy_enabled`. When
 * off (default) bench-strategy outputs stay evidence-only. When on,
 * appeal-memorandum drafts may use predictive language under the
 * server-side sample-size + disclaimer guards.
 *
 * Owner/admin gate: hides itself when the caller is not workspace:admin.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { toast } from "sonner";

import { apiErrorMessage } from "@/lib/api/config";
import { getTenantAIPolicy, updateTenantAIPolicy } from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";

export function TenantAIPolicyCard(): React.JSX.Element | null {
  const canAdmin = useCapability("workspace:admin");
  const queryClient = useQueryClient();

  const policyQuery = useQuery({
    queryKey: ["admin", "tenant-ai-policy"],
    queryFn: getTenantAIPolicy,
    enabled: canAdmin,
  });

  const updateMutation = useMutation({
    mutationFn: (next: boolean) =>
      updateTenantAIPolicy({ predictive_bench_strategy_enabled: next }),
    onSuccess: async (data) => {
      queryClient.setQueryData(["admin", "tenant-ai-policy"], data);
      toast.success(
        data.predictive_bench_strategy_enabled
          ? "Predictive bench analytics enabled."
          : "Predictive bench analytics disabled.",
      );
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not update AI policy."));
    },
  });

  if (!canAdmin) return null;

  const enabled = policyQuery.data?.predictive_bench_strategy_enabled ?? false;
  const isPending = policyQuery.isPending || updateMutation.isPending;

  return (
    <Card data-testid="tenant-ai-policy-card">
      <CardHeader>
        <CardTitle as="h2" className="flex items-center gap-2">
          <ShieldAlert className="h-5 w-5" /> Workspace AI policy
        </CardTitle>
        <CardDescription>
          Controls AI behaviour for everyone in this workspace. Default
          is evidence-only — bench-strategy outputs cite indexed
          decisions without favorability scoring or judge-tendency
          claims. Opt in only after reviewing the legal posture with
          your team.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-start justify-between gap-4 rounded-lg border border-[var(--color-line)] p-4">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-sm font-medium text-[var(--color-ink)]">
              Predictive bench analytics
            </div>
            <p className="mt-1 text-sm text-[var(--color-mute)]">
              When enabled, appeal-memorandum drafts may include
              statistical descriptions of how the assigned bench has
              decided comparable matters (e.g. "in N of M indexed
              decisions, this bench ruled in favour of [side]"). The
              server enforces a sample-size guard (≥5 indexed decisions
              per claim) and appends a verbatim "not legal advice"
              disclaimer. Disclaimer + mode badge surface on every
              affected output.
            </p>
            <p className="mt-2 text-xs text-[var(--color-mute-2)]">
              Status:{" "}
              <strong>
                {enabled ? "Predictive (B)" : "Evidence-only (A, default)"}
              </strong>
            </p>
          </div>
          <Button
            type="button"
            size="sm"
            variant={enabled ? "primary" : "secondary"}
            disabled={isPending}
            onClick={() => updateMutation.mutate(!enabled)}
            aria-pressed={enabled}
            aria-label="Predictive bench analytics toggle"
            data-testid="tenant-ai-policy-predictive-toggle"
          >
            {enabled ? "Disable" : "Enable"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
