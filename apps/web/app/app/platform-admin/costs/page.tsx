"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Calculator, Loader2, Plus, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  createProviderCostProfile,
  fetchMarginSimulations,
  fetchProviderCostProfiles,
  runMarginSimulation,
  type ProviderCostProfileInput,
} from "@/lib/api/endpoints";
import type { MarginSimulationRecord, ProviderCostProfileRecord } from "@/lib/api/schemas";
import { formatMoneyMinor } from "@/lib/billing-format";
import { useCapability } from "@/lib/capabilities";

const costCategories: ProviderCostProfileInput["category"][] = [
  "case_refresh",
  "llm",
  "embedding",
  "document_processing",
  "storage",
  "payment_mdr",
  "payment_fixed_fee",
  "sms",
  "whatsapp",
  "manual_support",
];

function label(value: string): string {
  return value.replaceAll("_", " ");
}

function parseOptionalInt(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number.parseInt(trimmed, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function marginLabel(value: unknown): string {
  return typeof value === "number" ? `${(value / 100).toFixed(1)}%` : "n/a";
}

function ProfilesTable({ profiles }: { profiles: ProviderCostProfileRecord[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left text-sm">
        <thead className="border-b border-[var(--color-line)] text-xs uppercase text-[var(--color-mute)]">
          <tr>
            <th className="py-2 pr-4">Category</th>
            <th className="py-2 pr-4">Provider</th>
            <th className="py-2 pr-4">Unit</th>
            <th className="py-2 pr-4">Source</th>
            <th className="py-2 pr-4">Status</th>
          </tr>
        </thead>
        <tbody>
          {profiles.map((profile) => (
            <tr key={profile.id} className="border-b border-[var(--color-line-2)]">
              <td className="py-3 pr-4 font-medium">{label(profile.category)}</td>
              <td className="py-3 pr-4">{profile.provider}</td>
              <td className="py-3 pr-4">
                {profile.unit_amount_bps !== null
                  ? `${profile.unit_amount_bps} bps`
                  : formatMoneyMinor(profile.unit_amount_minor ?? 0)}
              </td>
              <td className="py-3 pr-4">{profile.source ?? "manual"}</td>
              <td className="py-3 pr-4">
                <Badge tone={profile.status === "active" ? "success" : "neutral"}>
                  {profile.status}
                </Badge>
              </td>
            </tr>
          ))}
          {profiles.length === 0 ? (
            <tr>
              <td className="py-4 text-[var(--color-mute)]" colSpan={5}>
                No provider cost profiles yet.
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

function SimulationList({ simulations }: { simulations: MarginSimulationRecord[] }) {
  if (simulations.length === 0) {
    return (
      <EmptyState
        icon={Calculator}
        title="No margin simulations"
        description="Run a scenario to store founder-only margin evidence."
      />
    );
  }
  return (
    <ul className="divide-y divide-[var(--color-line)]">
      {simulations.map((simulation) => (
        <li key={simulation.id} className="py-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="font-medium text-[var(--color-ink)]">
                {simulation.scenario_name ?? "Margin simulation"}
              </div>
              <div className="text-xs text-[var(--color-mute)]">
                {new Date(simulation.created_at).toLocaleString()}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge tone="brand">
                Revenue {formatMoneyMinor(Number(simulation.result.revenue_minor ?? 0))}
              </Badge>
              <Badge tone="warning">
                Cost {formatMoneyMinor(Number(simulation.result.total_variable_cost_minor ?? 0))}
              </Badge>
              <Badge tone="success">
                Margin {marginLabel(simulation.result.gross_margin_bps)}
              </Badge>
            </div>
          </div>
          {simulation.warnings.length ? (
            <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
              {simulation.warnings
                .map((warning) => String(warning.message ?? warning.type ?? "Review warning"))
                .join(" ")}
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

export default function PlatformCostsPage() {
  const canPlatform = useCapability("platform:admin");
  const queryClient = useQueryClient();
  const [category, setCategory] =
    useState<ProviderCostProfileInput["category"]>("case_refresh");
  const [provider, setProvider] = useState("default");
  const [unitMinor, setUnitMinor] = useState("");
  const [unitBps, setUnitBps] = useState("");
  const [source, setSource] = useState("manual");
  const [notes, setNotes] = useState("");
  const [scenarioName, setScenarioName] = useState("Founder smoke margin");
  const [revenueMinor, setRevenueMinor] = useState("1999900");
  const [trackedRefreshes, setTrackedRefreshes] = useState("1000");
  const [aiCredits, setAiCredits] = useState("1200");

  const profilesQuery = useQuery({
    queryKey: ["platform-admin", "cost-profiles"],
    queryFn: fetchProviderCostProfiles,
    enabled: canPlatform,
  });
  const simulationsQuery = useQuery({
    queryKey: ["platform-admin", "margin-simulations"],
    queryFn: fetchMarginSimulations,
    enabled: canPlatform,
  });

  const createMutation = useMutation({
    mutationFn: createProviderCostProfile,
    onSuccess: async () => {
      toast.success("Cost profile saved.");
      setUnitMinor("");
      setUnitBps("");
      setNotes("");
      await queryClient.invalidateQueries({ queryKey: ["platform-admin", "cost-profiles"] });
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not save cost profile.")),
  });
  const simulationMutation = useMutation({
    mutationFn: runMarginSimulation,
    onSuccess: async () => {
      toast.success("Margin simulation saved.");
      await queryClient.invalidateQueries({
        queryKey: ["platform-admin", "margin-simulations"],
      });
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not run simulation.")),
  });

  if (!canPlatform) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          eyebrow="Platform"
          title="Access denied"
          description="Provider cost and margin tools are restricted to the configured founder super-admin."
        />
      </div>
    );
  }

  const createDisabled =
    createMutation.isPending ||
    (category === "payment_mdr" ? !unitBps.trim() : !unitMinor.trim());

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Founder console"
        title="Costs and margin simulation"
        description="Founder-only provider cost calibration and gross margin scenario checks."
        actions={
          <Button href="/app/platform-admin/integrations" variant="outline">
            Integrations
          </Button>
        }
      />

      {profilesQuery.isPending || simulationsQuery.isPending ? (
        <Card>
          <CardContent className="flex items-center gap-2 text-sm text-[var(--color-mute)]">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            Loading cost controls...
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <Card>
          <CardHeader>
            <CardTitle as="h2">New cost profile</CardTitle>
            <CardDescription>
              INR minor-unit or BPS assumptions used by founder-only reports.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-2">
                <Label>Category</Label>
                <Select value={category} onValueChange={(value) => setCategory(value as typeof category)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {costCategories.map((item) => (
                      <SelectItem key={item} value={item}>
                        {label(item)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="cost-provider">Provider</Label>
                <Input
                  id="cost-provider"
                  value={provider}
                  onChange={(event) => setProvider(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="unit-minor">Unit minor</Label>
                <Input
                  id="unit-minor"
                  inputMode="numeric"
                  value={unitMinor}
                  disabled={category === "payment_mdr"}
                  onChange={(event) => setUnitMinor(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="unit-bps">Unit BPS</Label>
                <Input
                  id="unit-bps"
                  inputMode="numeric"
                  value={unitBps}
                  disabled={category !== "payment_mdr"}
                  onChange={(event) => setUnitBps(event.target.value)}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="cost-source">Source</Label>
              <Input
                id="cost-source"
                value={source}
                onChange={(event) => setSource(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="cost-notes">Platform notes</Label>
              <Textarea
                id="cost-notes"
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
              />
            </div>
            <Button
              type="button"
              disabled={createDisabled}
              onClick={() =>
                createMutation.mutate({
                  category,
                  provider,
                  unitAmountMinor: parseOptionalInt(unitMinor),
                  unitAmountBps: parseOptionalInt(unitBps),
                  source,
                  notes,
                })
              }
            >
              <Plus className="h-4 w-4" aria-hidden />
              Save cost profile
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle as="h2">Margin simulation</CardTitle>
            <CardDescription>
              Run a founder-only stress case using configured profiles and fallback defaults.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="scenario-name">Scenario</Label>
                <Input
                  id="scenario-name"
                  value={scenarioName}
                  onChange={(event) => setScenarioName(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="revenue-minor">Revenue minor</Label>
                <Input
                  id="revenue-minor"
                  inputMode="numeric"
                  value={revenueMinor}
                  onChange={(event) => setRevenueMinor(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="tracked-refreshes">Tracked-case refreshes</Label>
                <Input
                  id="tracked-refreshes"
                  inputMode="numeric"
                  value={trackedRefreshes}
                  onChange={(event) => setTrackedRefreshes(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="ai-credits">AI credits</Label>
                <Input
                  id="ai-credits"
                  inputMode="numeric"
                  value={aiCredits}
                  onChange={(event) => setAiCredits(event.target.value)}
                />
              </div>
            </div>
            <Button
              type="button"
              disabled={simulationMutation.isPending || !revenueMinor.trim()}
              onClick={() =>
                simulationMutation.mutate({
                  scenarioName,
                  revenueMinor: parseOptionalInt(revenueMinor),
                  trackedCaseRefreshes: parseOptionalInt(trackedRefreshes) ?? 0,
                  aiCredits: parseOptionalInt(aiCredits) ?? 0,
                })
              }
            >
              <Calculator className="h-4 w-4" aria-hidden />
              Run simulation
            </Button>
          </CardContent>
        </Card>
      </div>

      {profilesQuery.isError ? (
        <QueryErrorState
          title="Could not load cost profiles"
          error={profilesQuery.error}
          onRetry={profilesQuery.refetch}
        />
      ) : (
        <Card>
          <CardHeader className="flex-row items-start justify-between gap-4">
            <div>
              <CardTitle as="h2">Cost profiles</CardTitle>
              <CardDescription>
                Configured actuals override fallback defaults in founder-only calculations.
              </CardDescription>
            </div>
            <ShieldAlert className="h-5 w-5 text-amber-700" aria-hidden />
          </CardHeader>
          <CardContent>
            <ProfilesTable profiles={profilesQuery.data?.cost_profiles ?? []} />
          </CardContent>
        </Card>
      )}

      {simulationsQuery.isError ? (
        <QueryErrorState
          title="Could not load margin simulations"
          error={simulationsQuery.error}
          onRetry={simulationsQuery.refetch}
        />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle as="h2">Saved simulations</CardTitle>
            <CardDescription>Recent founder-only margin evidence.</CardDescription>
          </CardHeader>
          <CardContent>
            <SimulationList simulations={simulationsQuery.data?.simulations ?? []} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
