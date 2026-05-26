"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, KeyRound, PlugZap, ShieldCheck } from "lucide-react";
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
  fetchOutlookTenantConfiguration,
  startOutlookCalendarConnection,
  testOutlookTenantConfiguration,
  updateOutlookTenantConfiguration,
  type OutlookTenantConfigurationInput,
} from "@/lib/api/endpoints";
import { apiErrorMessage } from "@/lib/api/config";
import { useCapability } from "@/lib/capabilities";

const APPROVED_SCOPES = ["offline_access", "User.Read", "Calendars.ReadWrite"];

function statusTone(
  status: "passed" | "failed" | "blocked" | "not_run",
): "success" | "warning" | "neutral" {
  if (status === "passed") return "success";
  if (status === "failed" || status === "blocked") return "warning";
  return "neutral";
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "Not run";
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

export default function AdminOutlookConfigurationPage() {
  const canAdmin = useCapability("workspace:admin");
  const queryClient = useQueryClient();
  const [form, setForm] = useState<OutlookTenantConfigurationInput>({
    clientId: "",
    clientSecret: "",
    tenantId: "organizations",
    redirectUri: "",
    scopes: APPROVED_SCOPES,
    oauthConsentModelApproved: false,
    scopesApproved: false,
    durableRunbookApproved: false,
    rollbackApproved: false,
    redactionRulesApproved: false,
    enabled: true,
  });

  const query = useQuery({
    queryKey: ["admin", "outlook-configuration"],
    queryFn: fetchOutlookTenantConfiguration,
    enabled: canAdmin,
  });

  useEffect(() => {
    if (!query.data) return;
    setForm((current) => ({
      ...current,
      scopes: query.data.approved_scopes.length
        ? query.data.approved_scopes
        : APPROVED_SCOPES,
      oauthConsentModelApproved: query.data.required_approvals.some(
        (item) => item.key === "oauth_consent_model_approved" && item.approved,
      ),
      scopesApproved: query.data.required_approvals.some(
        (item) => item.key === "scopes_approved" && item.approved,
      ),
      durableRunbookApproved: query.data.required_approvals.some(
        (item) => item.key === "durable_runbook_approved" && item.approved,
      ),
      rollbackApproved: query.data.required_approvals.some(
        (item) => item.key === "rollback_approved" && item.approved,
      ),
      redactionRulesApproved: query.data.required_approvals.some(
        (item) => item.key === "redaction_rules_approved" && item.approved,
      ),
      enabled: query.data.enabled,
    }));
  }, [query.data]);

  const saveMutation = useMutation({
    mutationFn: () => updateOutlookTenantConfiguration(form),
    onSuccess: async (result) => {
      queryClient.setQueryData(["admin", "outlook-configuration"], result);
      setForm((current) => ({
        ...current,
        clientId: "",
        clientSecret: "",
        redirectUri: "",
      }));
      toast.success("Outlook configuration saved.");
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not save Outlook configuration.")),
  });

  const connectMutation = useMutation({
    mutationFn: startOutlookCalendarConnection,
    onSuccess: (result) => {
      if (result.auth_url) {
        window.location.assign(result.auth_url);
        return;
      }
      toast.error(result.unavailable_reason ?? "Outlook is not ready.");
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not start Outlook OAuth.")),
  });

  const testMutation = useMutation({
    mutationFn: testOutlookTenantConfiguration,
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({
        queryKey: ["admin", "outlook-configuration"],
      });
      if (result.status === "passed") {
        toast.success("Outlook readiness test passed.");
      } else {
        toast.error("Outlook readiness test is not passing yet.");
      }
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not test Outlook readiness.")),
  });

  if (!canAdmin) {
    return (
      <EmptyState
        icon={KeyRound}
        title="Workspace admin required"
        description="Only workspace owners and admins can configure Outlook provider readiness."
      />
    );
  }

  const status = query.data;
  const lastTest = testMutation.data;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Admin - Outlook"
        title="Outlook configuration"
        description="Configure Microsoft Graph OAuth readiness for this law firm. Credential values are accepted once and never displayed back."
      />

      {query.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : query.isError ? (
        <QueryErrorState
          title="Could not load Outlook configuration"
          error={query.error}
          onRetry={query.refetch}
        />
      ) : status ? (
        <>
          <section className="grid gap-3 md:grid-cols-4">
            <StatusTile
              label="Provider"
              value={status.configured ? "Configured" : "Incomplete"}
              tone={status.configured ? "success" : "warning"}
            />
            <StatusTile
              label="Source"
              value={status.config_source.replaceAll("_", " ")}
              tone={status.config_source === "missing" ? "warning" : "neutral"}
            />
            <StatusTile
              label="Admin connections"
              value={`${status.connected_account_count}/${status.connection_count}`}
              tone={status.connected_account_count > 0 ? "success" : "neutral"}
            />
            <StatusTile
              label="ADP-20 gate"
              value={
                status.adp20_readiness === "ready_for_adp20_implementation"
                  ? "Ready"
                  : "Blocked"
              }
              tone={
                status.adp20_readiness === "ready_for_adp20_implementation"
                  ? "success"
                  : "warning"
              }
            />
          </section>

          <Card>
            <CardHeader className="flex-row items-start justify-between gap-4">
              <div>
                <CardTitle as="h2">Provider values</CardTitle>
                <CardDescription>
                  Enter the Entra app registration values approved by the law
                  firm admin. Existing values remain stored when a field is left
                  blank.
                </CardDescription>
              </div>
              <KeyRound className="h-5 w-5 text-[var(--color-brand-700)]" aria-hidden />
            </CardHeader>
            <CardContent>
              <form
                className="grid gap-4 md:grid-cols-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  saveMutation.mutate();
                }}
              >
                <Field
                  id="outlook-client-id"
                  label="Application client ID"
                  value={form.clientId ?? ""}
                  onChange={(value) => setForm((f) => ({ ...f, clientId: value }))}
                  placeholder="Leave blank to keep existing"
                />
                <Field
                  id="outlook-client-secret"
                  label="Client secret"
                  type="password"
                  value={form.clientSecret ?? ""}
                  onChange={(value) =>
                    setForm((f) => ({ ...f, clientSecret: value }))
                  }
                  placeholder="Leave blank to keep existing"
                />
                <Field
                  id="outlook-tenant-id"
                  label="Tenant ID or tenant mode"
                  value={form.tenantId ?? ""}
                  onChange={(value) => setForm((f) => ({ ...f, tenantId: value }))}
                  placeholder="organizations"
                />
                <Field
                  id="outlook-redirect-uri"
                  label="Redirect URI"
                  value={form.redirectUri ?? ""}
                  onChange={(value) =>
                    setForm((f) => ({ ...f, redirectUri: value }))
                  }
                  placeholder="Leave blank to keep existing"
                />
                <div className="md:col-span-2">
                  <Label>Approved scopes</Label>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {APPROVED_SCOPES.map((scope) => (
                      <Badge key={scope} tone="neutral">
                        {scope}
                      </Badge>
                    ))}
                  </div>
                </div>
                <div className="md:col-span-2">
                  <fieldset className="grid gap-2 rounded-md border border-[var(--color-line)] px-3 py-3 text-sm md:grid-cols-2">
                    <legend className="px-1 text-xs font-medium text-[var(--color-mute)]">
                      Approval checklist
                    </legend>
                    <ApprovalCheckbox
                      label="OAuth consent model approved"
                      checked={form.oauthConsentModelApproved}
                      onChange={(checked) =>
                        setForm((f) => ({
                          ...f,
                          oauthConsentModelApproved: checked,
                        }))
                      }
                    />
                    <ApprovalCheckbox
                      label="Graph scopes approved"
                      checked={form.scopesApproved}
                      onChange={(checked) =>
                        setForm((f) => ({ ...f, scopesApproved: checked }))
                      }
                    />
                    <ApprovalCheckbox
                      label="Durable operation runbook approved"
                      checked={form.durableRunbookApproved}
                      onChange={(checked) =>
                        setForm((f) => ({
                          ...f,
                          durableRunbookApproved: checked,
                        }))
                      }
                    />
                    <ApprovalCheckbox
                      label="Rollback and disable procedure approved"
                      checked={form.rollbackApproved}
                      onChange={(checked) =>
                        setForm((f) => ({ ...f, rollbackApproved: checked }))
                      }
                    />
                    <ApprovalCheckbox
                      label="Provider error redaction rules approved"
                      checked={form.redactionRulesApproved}
                      onChange={(checked) =>
                        setForm((f) => ({
                          ...f,
                          redactionRulesApproved: checked,
                        }))
                      }
                    />
                    <ApprovalCheckbox
                      label="Enable this Outlook configuration"
                      checked={form.enabled}
                      onChange={(checked) =>
                        setForm((f) => ({ ...f, enabled: checked }))
                      }
                    />
                  </fieldset>
                </div>
                <div className="md:col-span-2">
                  <Button
                    type="submit"
                    disabled={saveMutation.isPending}
                    data-testid="outlook-config-save"
                  >
                    <ShieldCheck className="h-4 w-4" aria-hidden />
                    {saveMutation.isPending ? "Saving..." : "Save configuration"}
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-start justify-between gap-4">
              <div>
                <CardTitle as="h2">Readiness test</CardTitle>
                <CardDescription>
                  Connect an admin Outlook account, then run the provider probe.
                  Passing this gate makes ADP-20 ready for implementation work.
                </CardDescription>
              </div>
              <PlugZap className="h-5 w-5 text-[var(--color-brand-700)]" aria-hidden />
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => connectMutation.mutate()}
                  disabled={connectMutation.isPending || !status.configured}
                  data-testid="outlook-config-connect"
                >
                  {connectMutation.isPending ? "Opening..." : "Connect Outlook"}
                </Button>
                <Button
                  type="button"
                  onClick={() => testMutation.mutate()}
                  disabled={testMutation.isPending}
                  data-testid="outlook-config-test"
                >
                  <CheckCircle2 className="h-4 w-4" aria-hidden />
                  {testMutation.isPending ? "Testing..." : "Run end-to-end test"}
                </Button>
              </div>
              <div className="text-sm text-[var(--color-ink-2)]">
                Last test: {formatDateTime(status.last_tested_at)}
                {" - "}
                <Badge tone={statusTone(status.last_test_status)}>
                  {status.last_test_status.replaceAll("_", " ")}
                </Badge>
              </div>
              {status.last_error_redacted ? (
                <p className="text-sm text-[var(--color-warn-700,#a55400)]">
                  {status.last_error_redacted}
                </p>
              ) : null}
              <Checklist
                config={status.required_config}
                approvals={status.required_approvals}
              />
              {lastTest ? (
                <div data-testid="outlook-config-test-results">
                  <h3 className="text-sm font-semibold text-[var(--color-ink)]">
                    Latest probe
                  </h3>
                  <ul className="mt-2 divide-y divide-[var(--color-line)] rounded-md border border-[var(--color-line)]">
                    {lastTest.checks.map((check) => (
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
                          <Badge tone={statusTone(check.status)}>
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
        </>
      ) : null}
    </div>
  );
}

function StatusTile({
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

function Field({
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

function ApprovalCheckbox({
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

function Checklist({
  config,
  approvals,
}: {
  config: { name: string; configured: boolean }[];
  approvals: { key: string; label: string; approved: boolean }[];
}) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <div>
        <h3 className="text-sm font-semibold text-[var(--color-ink)]">
          Required config
        </h3>
        <ul className="mt-2 divide-y divide-[var(--color-line)] rounded-md border border-[var(--color-line)]">
          {config.map((item) => (
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
          {approvals.map((item) => (
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
