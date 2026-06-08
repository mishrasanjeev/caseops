"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  CalendarDays,
  CheckCircle2,
  HardDrive,
  Loader2,
  Mail,
  PlugZap,
  ShieldAlert,
} from "lucide-react";
import type { ComponentType, ReactNode } from "react";
import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  fetchGoogleDriveStatus,
  fetchTenantIntegrations,
  listGoogleDriveFiles,
  revokeGoogleDriveConnection,
  startGoogleDriveConnection,
} from "@/lib/api/endpoints";
import type { GoogleDriveFileRecord, TenantConnectorRecord } from "@/lib/api/schemas";
import { useCapability } from "@/lib/capabilities";

function toneForStatus(status: TenantConnectorRecord["status"]) {
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

function ConnectorTile({ connector }: { connector: TenantConnectorRecord }) {
  const configPreview = connector.required_config_names.slice(0, 4).join(", ");
  return (
    <div
      className="rounded-md border border-[var(--color-line)] bg-white p-4"
      data-testid={`tenant-connector-${connector.key}`}
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
      {connector.required_config_names.length ? (
        <div className="mt-3 text-xs text-[var(--color-mute)]">
          Config names: {configPreview}
          {connector.required_config_names.length > 4
            ? ` +${connector.required_config_names.length - 4}`
            : ""}
        </div>
      ) : null}
      {connector.scopes.length ? (
        <div className="mt-2 text-xs text-[var(--color-mute)]">
          Scopes: {connector.scopes.slice(0, 4).join(", ")}
          {connector.scopes.length > 4 ? ` +${connector.scopes.length - 4}` : ""}
        </div>
      ) : null}
    </div>
  );
}

type SetupIcon = ComponentType<{ className?: string; "aria-hidden"?: boolean }>;

function connectorLabel(connector: TenantConnectorRecord | undefined) {
  if (!connector) return "not registered";
  if (connector.configured && !connector.blocked) return "ready";
  if (connector.configured) return "blocked";
  return "setup needed";
}

function GoogleSetupTile({
  connector,
  icon: Icon,
  title,
  detail,
  href,
  disabled,
  children,
}: {
  connector: TenantConnectorRecord | undefined;
  icon: SetupIcon;
  title: string;
  detail: string;
  href?: string;
  disabled?: boolean;
  children?: ReactNode;
}) {
  const ready = Boolean(connector?.configured && !connector.blocked);
  const status = connector?.status ?? "disabled";
  return (
    <div
      className="flex min-h-44 flex-col justify-between rounded-md border border-[var(--color-line)] bg-white p-4"
      data-testid={`google-workspace-${connector?.key ?? title.toLowerCase()}`}
    >
      <div>
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-md bg-[var(--color-bg-2)] text-[var(--color-ink-2)]">
              <Icon className="h-4 w-4" aria-hidden />
            </span>
            <div>
              <h2 className="text-sm font-semibold text-[var(--color-ink)]">
                {title}
              </h2>
              <p className="text-xs text-[var(--color-mute)]">{detail}</p>
            </div>
          </div>
          <Badge tone={ready ? "success" : toneForStatus(status)}>
            {connectorLabel(connector)}
          </Badge>
        </div>
        {connector?.required_config_names.length ? (
          <div className="mt-3 text-xs text-[var(--color-mute)]">
            Needs {connector.required_config_names.slice(0, 2).join(", ")}
            {connector.required_config_names.length > 2
              ? ` +${connector.required_config_names.length - 2}`
              : ""}
          </div>
        ) : null}
      </div>
      <div className="mt-4">
        {children ?? (href && !disabled ? (
          <Button href={href} variant="outline" size="sm">
            Open
            <ArrowRight className="h-4 w-4" aria-hidden />
          </Button>
        ) : (
          <Button type="button" variant="outline" size="sm" disabled>
            Blocked
          </Button>
        ))}
      </div>
    </div>
  );
}

function fileSize(value: number | null): string {
  if (!value) return "-";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function DriveFileList({ files }: { files: GoogleDriveFileRecord[] }) {
  if (files.length === 0) return null;
  return (
    <div className="mt-3 max-h-40 overflow-auto rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)]">
      {files.slice(0, 5).map((file) => (
        <div
          key={file.provider_file_id}
          className="border-b border-[var(--color-line)] px-3 py-2 last:border-b-0"
        >
          <div className="truncate text-xs font-medium text-[var(--color-ink)]">
            {file.name}
          </div>
          <div className="mt-0.5 text-xs text-[var(--color-mute)]">
            {file.mime_type ?? "file"} - {fileSize(file.size_bytes)}
          </div>
        </div>
      ))}
    </div>
  );
}

function GoogleWorkspaceSetup({
  connectors,
  driveConfigured,
  driveConnected,
  driveConnectionId,
  driveMessage,
  driveFiles,
  isDriveBusy,
  onDriveConnect,
  onDriveList,
  onDriveRevoke,
}: {
  connectors: TenantConnectorRecord[];
  driveConfigured: boolean;
  driveConnected: boolean;
  driveConnectionId: string | null;
  driveMessage: string | null;
  driveFiles: GoogleDriveFileRecord[];
  isDriveBusy: boolean;
  onDriveConnect: () => void;
  onDriveList: () => void;
  onDriveRevoke: (connectionId: string) => void;
}) {
  const byKey = new Map(connectors.map((connector) => [connector.key, connector]));
  const calendar = byKey.get("google_calendar");
  const gmail = byKey.get("gmail");
  const drive = byKey.get("google_drive");
  const readyCount = [calendar, gmail, drive].filter(
    (connector) => connector?.configured && !connector.blocked,
  ).length;

  return (
    <Card data-testid="google-workspace-setup">
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle as="h2">Google Workspace</CardTitle>
          <Badge tone={readyCount > 0 ? "brand" : "warning"}>
            {readyCount}/3 ready
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 lg:grid-cols-3">
          <GoogleSetupTile
            connector={calendar}
            icon={CalendarDays}
            title="Calendar"
            detail="Hearings, tasks, deadlines"
            href="/app/calendar"
          />
          <GoogleSetupTile
            connector={gmail}
            icon={Mail}
            title="Gmail"
            detail="Mailbox import"
            href="/app/calendar"
          />
          <GoogleSetupTile
            connector={drive}
            icon={HardDrive}
            title="Drive"
            detail="Recent file metadata"
          >
            <div className="flex flex-wrap gap-2">
              {driveConnected && driveConnectionId ? (
                <>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={isDriveBusy}
                    onClick={onDriveList}
                    data-testid="google-drive-list-files"
                  >
                    List files
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={isDriveBusy}
                    onClick={() => onDriveRevoke(driveConnectionId)}
                    data-testid="google-drive-revoke"
                  >
                    Revoke
                  </Button>
                </>
              ) : (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={isDriveBusy || !driveConfigured}
                  onClick={onDriveConnect}
                  data-testid="google-drive-connect"
                >
                  Connect
                </Button>
              )}
            </div>
            {driveMessage ? (
              <div
                className="mt-2 text-xs text-[var(--color-mute)]"
                data-testid="google-drive-message"
              >
                {driveMessage}
              </div>
            ) : null}
            <DriveFileList files={driveFiles} />
          </GoogleSetupTile>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button href="/app/admin/provider-operations" variant="outline" size="sm">
            <CheckCircle2 className="h-4 w-4" aria-hidden />
            Operations
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export default function TenantIntegrationsPage() {
  const canAdmin = useCapability("workspace:admin");
  const queryClient = useQueryClient();
  const [driveMessage, setDriveMessage] = useState<string | null>(null);
  const [driveFiles, setDriveFiles] = useState<GoogleDriveFileRecord[]>([]);
  const integrationsQuery = useQuery({
    queryKey: ["admin", "integrations"],
    queryFn: fetchTenantIntegrations,
    enabled: canAdmin,
  });
  const driveStatusQuery = useQuery({
    queryKey: ["drive", "google", "status"],
    queryFn: fetchGoogleDriveStatus,
    enabled: canAdmin,
  });
  const startDriveMutation = useMutation({
    mutationFn: startGoogleDriveConnection,
    onSuccess: (result) => {
      if (result.auth_url) {
        window.location.assign(result.auth_url);
        return;
      }
      setDriveMessage(
        result.unavailable_reason ?? "Google Drive connection is unavailable.",
      );
    },
    onError: (error) => setDriveMessage(String(error)),
  });
  const listDriveMutation = useMutation({
    mutationFn: () => listGoogleDriveFiles({ limit: 10 }),
    onSuccess: (result) => {
      setDriveFiles(result.files);
      setDriveMessage(`Loaded ${result.files.length} recent Drive files.`);
      void queryClient.invalidateQueries({ queryKey: ["drive", "google", "status"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "integrations"] });
    },
    onError: (error) => setDriveMessage(String(error)),
  });
  const revokeDriveMutation = useMutation({
    mutationFn: revokeGoogleDriveConnection,
    onSuccess: () => {
      setDriveFiles([]);
      setDriveMessage("Google Drive connection revoked.");
      void queryClient.invalidateQueries({ queryKey: ["drive", "google", "status"] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "integrations"] });
    },
    onError: (error) => setDriveMessage(String(error)),
  });

  if (!canAdmin) {
    return (
      <EmptyState
        icon={ShieldAlert}
        title="Workspace admin required"
        description="Integration readiness is limited to workspace owners and admins."
      />
    );
  }

  const connectors = integrationsQuery.data?.connectors ?? [];
  const driveConnection =
    driveStatusQuery.data?.connections.find(
      (connection) => connection.status === "connected",
    ) ?? null;
  const driveConfigured = driveStatusQuery.data?.configured ?? false;
  const isDriveBusy =
    driveStatusQuery.isPending ||
    startDriveMutation.isPending ||
    listDriveMutation.isPending ||
    revokeDriveMutation.isPending;
  const effectiveDriveMessage =
    driveMessage ??
    (!driveConfigured && driveStatusQuery.data?.missing_config_names.length
      ? `Needs ${driveStatusQuery.data.missing_config_names.join(", ")}`
      : null);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Admin - Integrations"
        title="Integrations"
        description="Readiness, configuration names, and delivery gates for workspace connectors."
        actions={
          <Button href="/app/admin/provider-operations" variant="outline">
            Provider operations
          </Button>
        }
      />

      {integrationsQuery.isPending ? (
        <Card>
          <CardContent className="flex flex-col gap-2">
            <div className="flex items-center gap-2 text-sm text-[var(--color-mute)]">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              Loading integrations...
            </div>
            <Skeleton className="h-24 w-full" />
          </CardContent>
        </Card>
      ) : integrationsQuery.isError ? (
        <QueryErrorState
          title="Could not load integrations"
          error={integrationsQuery.error}
          onRetry={integrationsQuery.refetch}
        />
      ) : connectors.length === 0 ? (
        <EmptyState
          icon={PlugZap}
          title="No integrations registered"
          description="Connector readiness records will appear here as they are added."
        />
      ) : (
        <>
          <GoogleWorkspaceSetup
            connectors={connectors}
            driveConfigured={driveConfigured}
            driveConnected={Boolean(driveConnection)}
            driveConnectionId={driveConnection?.id ?? null}
            driveMessage={effectiveDriveMessage}
            driveFiles={driveFiles}
            isDriveBusy={isDriveBusy}
            onDriveConnect={() => startDriveMutation.mutate()}
            onDriveList={() => listDriveMutation.mutate()}
            onDriveRevoke={(connectionId) => revokeDriveMutation.mutate(connectionId)}
          />
          <Card>
            <CardHeader>
              <CardTitle as="h2">Connector registry</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid gap-3 lg:grid-cols-2">
                {connectors.map((connector) => (
                  <ConnectorTile key={connector.key} connector={connector} />
                ))}
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
