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
import { Bot, Gauge, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { apiErrorMessage } from "@/lib/api/config";
import {
  getAITokenGovernance,
  getTenantAIPolicy,
  updateAITokenGovernance,
  updateTenantAIPolicy,
  type AITokenGovernanceSummary,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";

function humanTokens(tokens: number | null | undefined): string {
  if (tokens === null || tokens === undefined) return "Unlimited";
  if (tokens < 1000) return `${tokens}`;
  if (tokens < 1_000_000) return `${(tokens / 1000).toFixed(1)}K`;
  return `${(tokens / 1_000_000).toFixed(2)}M`;
}

function stateLabel(state: string): string {
  if (state === "hard_limit") return "Hard limit";
  if (state === "warning") return "Warning";
  if (state === "unlimited") return "Unlimited";
  return "OK";
}

function tokenInput(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

function parseTokenInput(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0 || !Number.isInteger(parsed)) {
    throw new Error("Token quota must be a non-negative whole number.");
  }
  return parsed;
}

function parseWarningThreshold(value: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || !Number.isInteger(parsed) || parsed < 1 || parsed > 100) {
    throw new Error("Warning threshold must be a whole percent from 1 to 100.");
  }
  return parsed;
}

export function TenantAIPolicyCard(): React.JSX.Element | null {
  const canAdmin = useCapability("workspace:admin");
  const queryClient = useQueryClient();
  const [firmQuotaTokens, setFirmQuotaTokens] = useState("");
  const [userQuotaTokens, setUserQuotaTokens] = useState("");
  const [warningThreshold, setWarningThreshold] = useState("90");

  const policyQuery = useQuery({
    queryKey: ["admin", "tenant-ai-policy"],
    queryFn: getTenantAIPolicy,
    enabled: canAdmin,
  });

  const tokenQuery = useQuery({
    queryKey: ["admin", "ai-token-governance"],
    queryFn: () => getAITokenGovernance(),
    enabled: canAdmin,
  });

  useEffect(() => {
    if (!tokenQuery.data) return;
    setFirmQuotaTokens(tokenInput(tokenQuery.data.firm_quota_tokens));
    setUserQuotaTokens(tokenInput(tokenQuery.data.user_quota_tokens));
    setWarningThreshold(String(tokenQuery.data.warning_threshold_percent));
  }, [
    tokenQuery.data?.firm_quota_tokens,
    tokenQuery.data?.user_quota_tokens,
    tokenQuery.data?.warning_threshold_percent,
  ]);

  const updateMutation = useMutation({
    mutationFn: (change: {
      field: "predictive_bench_strategy_enabled" | "workspace_assistant_enabled";
      next: boolean;
    }) =>
      updateTenantAIPolicy({
        [change.field]: change.next,
        expected_version: policyQuery.data?.policy_version,
      }),
    onSuccess: async (data, change) => {
      queryClient.setQueryData(["admin", "tenant-ai-policy"], data);
      const label =
        change.field === "workspace_assistant_enabled"
          ? "Workspace assistant"
          : "Predictive bench analytics";
      toast.success(`${label} ${change.next ? "enabled" : "disabled"}.`);
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not update AI policy."));
      void queryClient.invalidateQueries({ queryKey: ["admin", "tenant-ai-policy"] });
    },
  });

  const tokenMutation = useMutation({
    mutationFn: () =>
      updateAITokenGovernance({
        firmQuotaTokens: parseTokenInput(firmQuotaTokens),
        userQuotaTokens: parseTokenInput(userQuotaTokens),
        warningThresholdPercent: parseWarningThreshold(warningThreshold),
      }),
    onSuccess: async (data: AITokenGovernanceSummary) => {
      queryClient.setQueryData(["admin", "ai-token-governance"], data);
      toast.success("AI token governance updated.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not update AI token governance."));
    },
  });

  if (!canAdmin) return null;

  const enabled = policyQuery.data?.predictive_bench_strategy_enabled ?? false;
  const assistantEnabled = policyQuery.data?.workspace_assistant_enabled ?? false;
  const isPending = policyQuery.isPending || updateMutation.isPending;
  const tokenPending = tokenQuery.isPending || tokenMutation.isPending;

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
      <CardContent className="space-y-4">
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
            onClick={() =>
              updateMutation.mutate({
                field: "predictive_bench_strategy_enabled",
                next: !enabled,
              })
            }
            aria-pressed={enabled}
            aria-label="Predictive bench analytics toggle"
            data-testid="tenant-ai-policy-predictive-toggle"
          >
            {enabled ? "Disable" : "Enable"}
          </Button>
        </div>

        <div className="flex items-start justify-between gap-4 rounded-lg border border-[var(--color-line)] p-4">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-sm font-medium text-[var(--color-ink)]">
              <Bot className="h-4 w-4" aria-hidden /> Workspace assistant
            </div>
            <p className="mt-1 text-sm text-[var(--color-mute)]">
              Enables source-cited questions over Matters the signed-in user can already
              access. Retrieval, tenant boundaries, model allowlists, retention, and
              citation checks remain enforced by the server.
            </p>
            <p className="mt-2 text-xs text-[var(--color-mute-2)]">
              Status: <strong>{assistantEnabled ? "Enabled" : "Disabled"}</strong>
            </p>
          </div>
          <Button
            type="button"
            size="sm"
            variant={assistantEnabled ? "primary" : "secondary"}
            disabled={isPending}
            onClick={() =>
              updateMutation.mutate({
                field: "workspace_assistant_enabled",
                next: !assistantEnabled,
              })
            }
            aria-pressed={assistantEnabled}
            aria-label="Workspace assistant toggle"
            data-testid="tenant-ai-policy-assistant-toggle"
          >
            {assistantEnabled ? "Disable" : "Enable"}
          </Button>
        </div>

        <div
          className="rounded-lg border border-[var(--color-line)] p-4"
          data-testid="ai-token-governance-panel"
        >
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 text-sm font-medium text-[var(--color-ink)]">
                <Gauge className="h-4 w-4" aria-hidden /> Monthly token governance
              </div>
              <p className="mt-1 text-sm text-[var(--color-mute)]">
                Usage is calculated from recorded model runs for this workspace.
                Blank quota fields mean unlimited.
              </p>
            </div>
            <span className="shrink-0 rounded-md bg-[var(--color-bg-subtle)] px-2 py-1 text-xs font-medium text-[var(--color-ink)]">
              {stateLabel(tokenQuery.data?.firm_state ?? "unlimited")}
            </span>
          </div>

          {tokenQuery.data ? (
            <>
              <div className="mt-4 grid gap-3 md:grid-cols-4">
                <div className="rounded-md border border-[var(--color-line)] px-3 py-2">
                  <div className="text-xs text-[var(--color-mute)]">Firm used</div>
                  <div className="text-lg font-semibold text-[var(--color-ink)]">
                    {humanTokens(tokenQuery.data.firm_used_tokens)}
                  </div>
                </div>
                <div className="rounded-md border border-[var(--color-line)] px-3 py-2">
                  <div className="text-xs text-[var(--color-mute)]">Firm quota</div>
                  <div className="text-lg font-semibold text-[var(--color-ink)]">
                    {humanTokens(tokenQuery.data.firm_quota_tokens)}
                  </div>
                </div>
                <div className="rounded-md border border-[var(--color-line)] px-3 py-2">
                  <div className="text-xs text-[var(--color-mute)]">Remaining</div>
                  <div className="text-lg font-semibold text-[var(--color-ink)]">
                    {humanTokens(tokenQuery.data.firm_remaining_tokens)}
                  </div>
                </div>
                <div className="rounded-md border border-[var(--color-line)] px-3 py-2">
                  <div className="text-xs text-[var(--color-mute)]">Warning</div>
                  <div className="text-lg font-semibold text-[var(--color-ink)]">
                    {tokenQuery.data.warning_threshold_percent}%
                  </div>
                </div>
              </div>

              <form
                className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_10rem_auto]"
                onSubmit={(event) => {
                  event.preventDefault();
                  tokenMutation.mutate();
                }}
              >
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="firm-ai-token-quota">Firm monthly tokens</Label>
                  <Input
                    id="firm-ai-token-quota"
                    type="number"
                    min={0}
                    step={1}
                    value={firmQuotaTokens}
                    onChange={(event) => setFirmQuotaTokens(event.target.value)}
                    placeholder="Blank for unlimited"
                    data-testid="firm-ai-token-quota-input"
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="user-ai-token-quota">User monthly tokens</Label>
                  <Input
                    id="user-ai-token-quota"
                    type="number"
                    min={0}
                    step={1}
                    value={userQuotaTokens}
                    onChange={(event) => setUserQuotaTokens(event.target.value)}
                    placeholder="Blank for unlimited"
                    data-testid="user-ai-token-quota-input"
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="ai-token-warning">Warning %</Label>
                  <Input
                    id="ai-token-warning"
                    type="number"
                    min={1}
                    max={100}
                    step={1}
                    value={warningThreshold}
                    onChange={(event) => setWarningThreshold(event.target.value)}
                    data-testid="ai-token-warning-input"
                  />
                </div>
                <Button
                  type="submit"
                  className="self-end"
                  disabled={tokenPending}
                  data-testid="ai-token-governance-save"
                >
                  {tokenMutation.isPending ? "Saving..." : "Save token policy"}
                </Button>
              </form>

              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <div>
                  <h3 className="text-sm font-semibold text-[var(--color-ink)]">
                    Top users
                  </h3>
                  <div className="mt-2 overflow-hidden rounded-md border border-[var(--color-line)]">
                    {tokenQuery.data.top_users.slice(0, 5).map((user) => (
                      <div
                        key={user.actor_membership_id}
                        className="flex items-center justify-between gap-3 border-b border-[var(--color-line-2)] px-3 py-2 text-sm last:border-0"
                      >
                        <span className="min-w-0 truncate">{user.user_label}</span>
                        <span className="shrink-0 text-[var(--color-mute)]">
                          {humanTokens(user.used_tokens)}
                        </span>
                      </div>
                    ))}
                    {tokenQuery.data.top_users.length === 0 ? (
                      <div className="px-3 py-2 text-sm text-[var(--color-mute)]">
                        No model usage recorded this month.
                      </div>
                    ) : null}
                  </div>
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-[var(--color-ink)]">
                    Recent feature and model usage
                  </h3>
                  <div className="mt-2 overflow-hidden rounded-md border border-[var(--color-line)]">
                    {tokenQuery.data.usage_by_purpose_model.slice(0, 5).map((row) => (
                      <div
                        key={`${row.purpose}-${row.provider}-${row.model}`}
                        className="flex items-center justify-between gap-3 border-b border-[var(--color-line-2)] px-3 py-2 text-sm last:border-0"
                      >
                        <span className="min-w-0 truncate">
                          {row.purpose} - {row.model}
                        </span>
                        <span className="shrink-0 text-[var(--color-mute)]">
                          {humanTokens(row.used_tokens)}
                        </span>
                      </div>
                    ))}
                    {tokenQuery.data.usage_by_purpose_model.length === 0 ? (
                      <div className="px-3 py-2 text-sm text-[var(--color-mute)]">
                        No feature usage recorded this month.
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
            </>
          ) : (
            <p className="mt-3 text-sm text-[var(--color-mute)]">
              Loading token usage...
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
