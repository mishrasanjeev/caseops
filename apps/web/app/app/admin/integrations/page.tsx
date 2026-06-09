"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  CalendarDays,
  CheckCircle2,
  HardDrive,
  KeyRound,
  Loader2,
  Mail,
  PlugZap,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import type { ComponentType, Dispatch, ReactNode, SetStateAction } from "react";
import { useEffect, useState } from "react";
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
import { Skeleton } from "@/components/ui/Skeleton";
import {
  fetchGoogleDriveStatus,
  fetchGoogleWorkspaceTenantConfiguration,
  fetchTenantIntegrations,
  listGoogleDriveFiles,
  revokeGoogleDriveConnection,
  startGoogleDriveConnection,
  testGoogleWorkspaceTenantConfiguration,
  updateGoogleWorkspaceTenantConfiguration,
  type GoogleWorkspaceTenantConfigurationInput,
} from "@/lib/api/endpoints";
import { apiErrorMessage } from "@/lib/api/config";
import type {
  GoogleDriveFileRecord,
  GoogleWorkspaceReadinessTestResponse,
  GoogleWorkspaceTenantConfigurationResponse,
  TenantConnectorRecord,
} from "@/lib/api/schemas";
import { useCapability } from "@/lib/capabilities";

const GOOGLE_WORKSPACE_SCOPES = [
  "https://www.googleapis.com/auth/calendar.events",
  "https://www.googleapis.com/auth/drive.readonly",
  "https://www.googleapis.com/auth/gmail.readonly",
];

function toneForStatus(status: TenantConnectorRecord["status"]) {
  if (status === "healthy") return "success";
  if (status === "blocked" || status === "degraded") return "warning";
  if (status === "disabled") return "neutral";
  return "brand";
}

function readinessTone(
  status: "passed" | "failed" | "blocked" | "not_run",
): "success" | "warning" | "neutral" {
  if (status === "passed") return "success";
  if (status === "failed" || status === "blocked") return "warning";
  return "neutral";
}

function approvalChecked(
  approvals: { key: string; approved: boolean }[] | undefined,
  key: string,
) {
  return Boolean(approvals?.some((item) => item.key === key && item.approved));
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

function ConfigField({
  id,
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  type?: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        data-testid={id}
      />
    </div>
  );
}

function ConfigCheckbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="inline-flex items-center gap-2 text-sm text-[var(--color-ink-2)]">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      {label}
    </label>
  );
}

function GoogleWorkspaceChecklist({
  status,
}: {
  status: GoogleWorkspaceTenantConfigurationResponse;
}) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <div>
        <h3 className="text-sm font-semibold text-[var(--color-ink)]">
          Required config
        </h3>
        <ul className="mt-2 divide-y divide-[var(--color-line)] rounded-md border border-[var(--color-line)]">
          {status.required_config.map((item) => (
            <li
              key={item.name}
              className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
            >
              <span>{item.name}</span>
              <Badge tone={item.configured ? "success" : "warning"}>
                {item.configured ? "set" : "missing"}
              </Badge>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h3 className="text-sm font-semibold text-[var(--color-ink)]">
          Required approvals
        </h3>
        <ul className="mt-2 divide-y divide-[var(--color-line)] rounded-md border border-[var(--color-line)]">
          {status.required_approvals.map((item) => (
            <li
              key={item.key}
              className="flex items-center justify-between gap-2 px-3 py-2 text-sm"
            >
              <span>{item.label}</span>
              <Badge tone={item.approved ? "success" : "warning"}>
                {item.approved ? "approved" : "pending"}
              </Badge>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function GoogleWorkspaceConfigurationPanel({
  status,
  latestTest,
  form,
  setForm,
  onSave,
  onTest,
  saving,
  testing,
}: {
  status: GoogleWorkspaceTenantConfigurationResponse;
  latestTest: GoogleWorkspaceReadinessTestResponse | undefined;
  form: GoogleWorkspaceTenantConfigurationInput;
  setForm: Dispatch<SetStateAction<GoogleWorkspaceTenantConfigurationInput>>;
  onSave: () => void;
  onTest: () => void;
  saving: boolean;
  testing: boolean;
}) {
  const connectionTotal =
    status.connection_counts.connected_calendar_account_count +
    status.connection_counts.connected_gmail_account_count +
    status.connection_counts.connected_drive_account_count;
  return (
    <Card data-testid="google-workspace-configuration">
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div>
          <CardTitle as="h2">Google Workspace configuration</CardTitle>
          <CardDescription>
            Tenant-owned OAuth setup for Calendar, Gmail, and Drive.
          </CardDescription>
        </div>
        <KeyRound className="h-5 w-5 text-[var(--color-brand-700)]" aria-hidden />
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <section className="grid gap-3 md:grid-cols-4">
          <StatusPill
            label="Source"
            value={status.config_source.replaceAll("_", " ")}
            tone={status.config_source === "missing" ? "warning" : "neutral"}
          />
          <StatusPill
            label="OAuth"
            value={status.configured ? "Configured" : "Incomplete"}
            tone={status.configured ? "success" : "warning"}
          />
          <StatusPill
            label="Connected users"
            value={String(connectionTotal)}
            tone={connectionTotal > 0 ? "success" : "neutral"}
          />
          <StatusPill
            label="Readiness"
            value={
              status.readiness === "ready_for_user_connections" ? "Ready" : "Blocked"
            }
            tone={
              status.readiness === "ready_for_user_connections"
                ? "success"
                : "warning"
            }
          />
        </section>
        <form
          className="grid gap-4 md:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault();
            onSave();
          }}
        >
          <ConfigField
            id="google-workspace-client-id"
            label="OAuth client ID"
            value={form.clientId ?? ""}
            onChange={(value) => setForm((current) => ({ ...current, clientId: value }))}
            placeholder="Leave blank to keep existing"
          />
          <ConfigField
            id="google-workspace-client-secret"
            label="OAuth client secret"
            type="password"
            value={form.clientSecret ?? ""}
            onChange={(value) =>
              setForm((current) => ({ ...current, clientSecret: value }))
            }
            placeholder="Leave blank to keep existing"
          />
          <ConfigField
            id="google-calendar-redirect-uri"
            label="Calendar redirect URI"
            value={form.calendarRedirectUri ?? ""}
            onChange={(value) =>
              setForm((current) => ({
                ...current,
                calendarRedirectUri: value,
              }))
            }
            placeholder="Leave blank to keep existing"
          />
          <ConfigField
            id="gmail-redirect-uri"
            label="Gmail redirect URI"
            value={form.gmailRedirectUri ?? ""}
            onChange={(value) =>
              setForm((current) => ({ ...current, gmailRedirectUri: value }))
            }
            placeholder="Leave blank to keep existing"
          />
          <ConfigField
            id="google-drive-redirect-uri"
            label="Drive redirect URI"
            value={form.driveRedirectUri ?? ""}
            onChange={(value) =>
              setForm((current) => ({ ...current, driveRedirectUri: value }))
            }
            placeholder="Leave blank to keep existing"
          />
          <div>
            <Label>Approved scopes</Label>
            <div className="mt-2 flex flex-wrap gap-2">
              {GOOGLE_WORKSPACE_SCOPES.map((scope) => (
                <Badge key={scope} tone="neutral">
                  {scope}
                </Badge>
              ))}
            </div>
          </div>
          <div className="md:col-span-2">
            <fieldset className="grid gap-2 rounded-md border border-[var(--color-line)] px-3 py-3 text-sm md:grid-cols-2">
              <legend className="px-1 text-xs font-medium text-[var(--color-mute)]">
                Services and approvals
              </legend>
              <ConfigCheckbox
                label="Enable Calendar"
                checked={form.calendarEnabled}
                onChange={(checked) =>
                  setForm((current) => ({ ...current, calendarEnabled: checked }))
                }
              />
              <ConfigCheckbox
                label="Enable Gmail"
                checked={form.gmailEnabled}
                onChange={(checked) =>
                  setForm((current) => ({ ...current, gmailEnabled: checked }))
                }
              />
              <ConfigCheckbox
                label="Enable Drive"
                checked={form.driveEnabled}
                onChange={(checked) =>
                  setForm((current) => ({ ...current, driveEnabled: checked }))
                }
              />
              <ConfigCheckbox
                label="Enable tenant Google Workspace"
                checked={form.enabled}
                onChange={(checked) =>
                  setForm((current) => ({ ...current, enabled: checked }))
                }
              />
              <ConfigCheckbox
                label="OAuth consent approved"
                checked={form.oauthConsentModelApproved}
                onChange={(checked) =>
                  setForm((current) => ({
                    ...current,
                    oauthConsentModelApproved: checked,
                  }))
                }
              />
              <ConfigCheckbox
                label="Google scopes approved"
                checked={form.scopesApproved}
                onChange={(checked) =>
                  setForm((current) => ({ ...current, scopesApproved: checked }))
                }
              />
              <ConfigCheckbox
                label="Webhook runbook reviewed"
                checked={form.webhookRunbookApproved}
                onChange={(checked) =>
                  setForm((current) => ({
                    ...current,
                    webhookRunbookApproved: checked,
                  }))
                }
              />
              <ConfigCheckbox
                label="Redaction rules approved"
                checked={form.redactionRulesApproved}
                onChange={(checked) =>
                  setForm((current) => ({
                    ...current,
                    redactionRulesApproved: checked,
                  }))
                }
              />
            </fieldset>
          </div>
          <div className="flex flex-wrap gap-2 md:col-span-2">
            <Button type="submit" disabled={saving} data-testid="google-workspace-save">
              <ShieldCheck className="h-4 w-4" aria-hidden />
              {saving ? "Saving..." : "Save configuration"}
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={testing}
              onClick={onTest}
              data-testid="google-workspace-test"
            >
              <CheckCircle2 className="h-4 w-4" aria-hidden />
              {testing ? "Testing..." : "Run readiness test"}
            </Button>
            <Badge tone={readinessTone(status.last_test_status)}>
              Last test {status.last_test_status.replaceAll("_", " ")}
            </Badge>
          </div>
        </form>
        {status.last_error_redacted ? (
          <p className="text-sm text-[var(--color-warn-700,#a55400)]">
            {status.last_error_redacted}
          </p>
        ) : null}
        <GoogleWorkspaceChecklist status={status} />
        {latestTest ? (
          <div data-testid="google-workspace-test-results">
            <h3 className="text-sm font-semibold text-[var(--color-ink)]">
              Latest readiness probe
            </h3>
            <ul className="mt-2 divide-y divide-[var(--color-line)] rounded-md border border-[var(--color-line)]">
              {latestTest.checks.map((check) => (
                <li
                  key={check.key}
                  className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm"
                >
                  <span>{check.label}</span>
                  <span className="flex items-center gap-2">
                    {check.detail ? (
                      <span className="text-xs text-[var(--color-mute)]">
                        {check.detail}
                      </span>
                    ) : null}
                    <Badge tone={readinessTone(check.status)}>
                      {check.status}
                    </Badge>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function StatusPill({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "success" | "warning" | "neutral";
}) {
  return (
    <div className="rounded-md border border-[var(--color-line)] bg-white px-3 py-2">
      <div className="text-xs text-[var(--color-mute)]">{label}</div>
      <div className="mt-1 flex items-center justify-between gap-2">
        <span className="truncate text-base font-semibold text-[var(--color-ink)]">
          {value}
        </span>
        <Badge tone={tone}>{tone}</Badge>
      </div>
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
  const [googleForm, setGoogleForm] =
    useState<GoogleWorkspaceTenantConfigurationInput>({
      clientId: "",
      clientSecret: "",
      calendarRedirectUri: "",
      gmailRedirectUri: "",
      driveRedirectUri: "",
      scopes: GOOGLE_WORKSPACE_SCOPES,
      oauthConsentModelApproved: false,
      scopesApproved: false,
      webhookRunbookApproved: false,
      redactionRulesApproved: false,
      calendarEnabled: true,
      gmailEnabled: true,
      driveEnabled: true,
      enabled: true,
    });
  const integrationsQuery = useQuery({
    queryKey: ["admin", "integrations"],
    queryFn: fetchTenantIntegrations,
    enabled: canAdmin,
  });
  const googleWorkspaceQuery = useQuery({
    queryKey: ["admin", "google-workspace-configuration"],
    queryFn: fetchGoogleWorkspaceTenantConfiguration,
    enabled: canAdmin,
  });
  const driveStatusQuery = useQuery({
    queryKey: ["drive", "google", "status"],
    queryFn: fetchGoogleDriveStatus,
    enabled: canAdmin,
  });
  useEffect(() => {
    const status = googleWorkspaceQuery.data;
    if (!status) return;
    setGoogleForm((current) => ({
      ...current,
      scopes: status.approved_scopes.length
        ? status.approved_scopes
        : GOOGLE_WORKSPACE_SCOPES,
      oauthConsentModelApproved: approvalChecked(
        status.required_approvals,
        "oauth_consent_model_approved",
      ),
      scopesApproved: approvalChecked(status.required_approvals, "scopes_approved"),
      webhookRunbookApproved: approvalChecked(
        status.required_approvals,
        "webhook_runbook_approved",
      ),
      redactionRulesApproved: approvalChecked(
        status.required_approvals,
        "redaction_rules_approved",
      ),
      calendarEnabled: status.calendar_enabled,
      gmailEnabled: status.gmail_enabled,
      driveEnabled: status.drive_enabled,
      enabled: status.enabled,
    }));
  }, [googleWorkspaceQuery.data]);
  const saveGoogleMutation = useMutation({
    mutationFn: () => updateGoogleWorkspaceTenantConfiguration(googleForm),
    onSuccess: async (result) => {
      queryClient.setQueryData(
        ["admin", "google-workspace-configuration"],
        result,
      );
      setGoogleForm((current) => ({
        ...current,
        clientId: "",
        clientSecret: "",
        calendarRedirectUri: "",
        gmailRedirectUri: "",
        driveRedirectUri: "",
      }));
      await queryClient.invalidateQueries({ queryKey: ["admin", "integrations"] });
      await queryClient.invalidateQueries({ queryKey: ["drive", "google", "status"] });
      toast.success("Google Workspace configuration saved.");
    },
    onError: (error) =>
      toast.error(
        apiErrorMessage(error, "Could not save Google Workspace configuration."),
      ),
  });
  const testGoogleMutation = useMutation({
    mutationFn: testGoogleWorkspaceTenantConfiguration,
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({
        queryKey: ["admin", "google-workspace-configuration"],
      });
      if (result.status === "passed") {
        toast.success("Google Workspace readiness test passed.");
      } else {
        toast.error("Google Workspace readiness test is blocked.");
      }
    },
    onError: (error) =>
      toast.error(
        apiErrorMessage(error, "Could not test Google Workspace readiness."),
      ),
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

      {googleWorkspaceQuery.isPending ? (
        <Skeleton className="h-80 w-full" />
      ) : googleWorkspaceQuery.isError ? (
        <QueryErrorState
          title="Could not load Google Workspace configuration"
          error={googleWorkspaceQuery.error}
          onRetry={googleWorkspaceQuery.refetch}
        />
      ) : googleWorkspaceQuery.data ? (
        <GoogleWorkspaceConfigurationPanel
          status={googleWorkspaceQuery.data}
          latestTest={testGoogleMutation.data}
          form={googleForm}
          setForm={setGoogleForm}
          onSave={() => saveGoogleMutation.mutate()}
          onTest={() => testGoogleMutation.mutate()}
          saving={saveGoogleMutation.isPending}
          testing={testGoogleMutation.isPending}
        />
      ) : null}

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
