"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Loader2, PlugZap, ShieldCheck } from "lucide-react";

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
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { fetchPlatformIntegrations } from "@/lib/api/endpoints";
import type { ConnectorRecord } from "@/lib/api/schemas";
import { useCapability } from "@/lib/capabilities";

function toneForStatus(status: ConnectorRecord["status"]) {
  if (status === "healthy") return "success";
  if (status === "blocked" || status === "degraded") return "warning";
  if (status === "disabled") return "neutral";
  return "brand";
}

function formatWhen(value: string | null): string {
  if (!value) return "None";
  try {
    return new Date(value).toLocaleString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

function PlatformConnectorTile({ connector }: { connector: ConnectorRecord }) {
  return (
    <div
      className="rounded-md border border-[var(--color-line)] bg-white p-4"
      data-testid={`platform-connector-${connector.key}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-medium uppercase text-[var(--color-mute)]">
            {connector.category}
          </div>
          <h2 className="mt-1 text-base font-semibold text-[var(--color-ink)]">
            {connector.name}
          </h2>
          <div className="mt-1 text-xs text-[var(--color-mute)]">
            {connector.provider}
          </div>
        </div>
        <Badge tone={toneForStatus(connector.status)}>
          {connector.status.replaceAll("_", " ")}
        </Badge>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        <Badge tone={connector.enabled ? "success" : "neutral"}>
          {connector.enabled ? "enabled" : "disabled"}
        </Badge>
        <Badge tone={connector.configured ? "success" : "warning"}>
          {connector.configured ? "configured" : "config needed"}
        </Badge>
        <Badge tone={connector.blocked ? "warning" : "success"}>
          {connector.blocked ? "blocked" : "unblocked"}
        </Badge>
        {connector.webhook_status ? (
          <Badge tone={connector.webhook_status === "configured" ? "success" : "neutral"}>
            webhook {connector.webhook_status}
          </Badge>
        ) : null}
      </div>

      <dl className="mt-4 grid gap-2 text-xs text-[var(--color-mute)] sm:grid-cols-2">
        <div>
          <dt className="font-medium text-[var(--color-ink-2)]">Last success</dt>
          <dd>{formatWhen(connector.last_success)}</dd>
        </div>
        <div>
          <dt className="font-medium text-[var(--color-ink-2)]">Last failure</dt>
          <dd>{formatWhen(connector.last_failure)}</dd>
        </div>
        <div>
          <dt className="font-medium text-[var(--color-ink-2)]">Next run</dt>
          <dd>{formatWhen(connector.next_run)}</dd>
        </div>
        <div>
          <dt className="font-medium text-[var(--color-ink-2)]">Token expiry</dt>
          <dd>{formatWhen(connector.token_expiry)}</dd>
        </div>
      </dl>

      {connector.internal_cost_label || connector.risk_label ? (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          <div className="flex items-center gap-2 font-semibold">
            <AlertTriangle className="h-4 w-4" aria-hidden />
            Founder-only labels
          </div>
          <div className="mt-1">
            {connector.internal_cost_label ?? "No cost label"} -{" "}
            {connector.risk_label ?? "No risk label"}
          </div>
        </div>
      ) : null}
      {connector.platform_notes.length ? (
        <ul className="mt-3 list-disc space-y-1 pl-4 text-xs text-[var(--color-mute)]">
          {connector.platform_notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export default function PlatformIntegrationsPage() {
  const canPlatform = useCapability("platform:admin");
  const integrationsQuery = useQuery({
    queryKey: ["platform-admin", "integrations"],
    queryFn: fetchPlatformIntegrations,
    enabled: canPlatform,
  });

  if (!canPlatform) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          eyebrow="Platform"
          title="Access denied"
          description="Platform integrations are restricted to the configured founder super-admin."
        />
      </div>
    );
  }

  const connectors = integrationsQuery.data?.connectors ?? [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Founder console"
        title="Platform integrations"
        description="Cross-tenant connector readiness, provider risk labels, and internal cost labels."
        actions={
          <div className="flex gap-2">
            <Button href="/app/platform-admin/costs" variant="outline">
              Costs
            </Button>
            <Button href="/app/platform-admin/provider-events" variant="outline">
              Provider events
            </Button>
          </div>
        }
      />

      {integrationsQuery.isPending ? (
        <Card>
          <CardContent className="flex flex-col gap-2">
            <div className="flex items-center gap-2 text-sm text-[var(--color-mute)]">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              Loading platform integrations...
            </div>
            <Skeleton className="h-24 w-full" />
          </CardContent>
        </Card>
      ) : integrationsQuery.isError ? (
        <QueryErrorState
          title="Could not load platform integrations"
          error={integrationsQuery.error}
          onRetry={integrationsQuery.refetch}
        />
      ) : connectors.length === 0 ? (
        <EmptyState
          icon={PlugZap}
          title="No integrations registered"
          description="Connector records will appear here as foundations are added."
        />
      ) : (
        <Card>
          <CardHeader className="flex-row items-start justify-between gap-4">
            <div>
              <CardTitle as="h2">Connector registry</CardTitle>
              <CardDescription>
                Platform-only labels are not returned to tenant integration APIs.
              </CardDescription>
            </div>
            <ShieldCheck className="h-5 w-5 text-[var(--color-brand-700)]" aria-hidden />
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 lg:grid-cols-2">
              {connectors.map((connector) => (
                <PlatformConnectorTile key={connector.key} connector={connector} />
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
