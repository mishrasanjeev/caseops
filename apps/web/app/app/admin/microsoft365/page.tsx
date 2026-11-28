"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Circle, Loader2, PlugZap, XCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { CopyField } from "@/components/ui/CopyField";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  fetchMicrosoft365TenantConfiguration,
  testMicrosoft365TenantConfiguration,
  updateMicrosoft365TenantConfiguration,
} from "@/lib/api/endpoints";
import { apiErrorMessage } from "@/lib/api/config";
import type { Microsoft365ReadinessTestResponse } from "@/lib/api/schemas";
import { microsoft365ClientIdError, microsoft365TenantIdError } from "@/lib/microsoft365-setup";

const ENTRA_ADMIN_CENTER = "https://entra.microsoft.com/";

function FieldError({ id, message }: { id: string; message: string | null }) {
  if (!message) return null;
  return (
    <p id={id} role="alert" className="mt-1 text-xs text-[var(--color-danger-600)]">
      {message}
    </p>
  );
}

export default function Microsoft365AdminPage() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["microsoft365-configuration"],
    queryFn: fetchMicrosoft365TenantConfiguration,
  });
  const config = query.data;
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [adminConsent, setAdminConsent] = useState(false);
  const [scopesApproved, setScopesApproved] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const [testResult, setTestResult] = useState<Microsoft365ReadinessTestResponse | null>(null);

  // Show what is already saved (ids are not secrets; the secret never returns).
  useEffect(() => {
    if (!config || hydrated) return;
    setClientId(config.client_id ?? "");
    setTenantId(config.tenant_id ?? "");
    setAdminConsent(
      config.required_approvals.some((item) => item.key === "admin_consent_approved" && item.approved),
    );
    setScopesApproved(
      config.required_approvals.some((item) => item.key === "scopes_approved" && item.approved),
    );
    setHydrated(true);
  }, [config, hydrated]);

  const clientIdError = microsoft365ClientIdError(clientId);
  const tenantIdError = microsoft365TenantIdError(tenantId);

  const saveMutation = useMutation({
    mutationFn: () =>
      updateMicrosoft365TenantConfiguration({
        clientId: clientId.trim(),
        clientSecret,
        tenantId: tenantId.trim(),
        // Never typed: the server-computed address this deployment serves.
        redirectUri: config?.expected_redirect_uri ?? null,
        scopes: null,
        adminConsentApproved: adminConsent,
        scopesApproved,
        mailEnabled: true,
        calendarEnabled: true,
        driveEnabled: true,
        enabled: true,
      }),
    onSuccess: () => {
      toast.success("Microsoft 365 settings saved");
      setClientSecret("");
      setTestResult(null);
      queryClient.invalidateQueries({ queryKey: ["microsoft365-configuration"] });
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not save Microsoft 365 settings.")),
  });
  const testMutation = useMutation({
    mutationFn: testMicrosoft365TenantConfiguration,
    onSuccess: (result) => {
      setTestResult(result);
      toast[result.status === "passed" ? "success" : "error"](
        result.status === "passed"
          ? "Microsoft 365 values and approvals are complete"
          : "Microsoft 365 values or approvals are missing",
      );
      queryClient.invalidateQueries({ queryKey: ["microsoft365-configuration"] });
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not test Microsoft 365 readiness.")),
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Admin"
        title="Microsoft 365"
        description="Record your firm's own Microsoft Entra app registration and check that every value and approval is saved. No Microsoft account is connected from this page."
        actions={
          <Button
            type="button"
            variant="outline"
            disabled={testMutation.isPending}
            onClick={() => testMutation.mutate()}
            data-testid="m365-test"
          >
            {testMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <CheckCircle2 className="h-4 w-4" aria-hidden />
            )}
            Test setup
          </Button>
        }
      />

      {query.isPending ? (
        <Card>
          <CardContent className="space-y-3">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-40 w-full" />
          </CardContent>
        </Card>
      ) : query.isError || !config ? (
        <QueryErrorState
          title="Could not load Microsoft 365"
          error={query.error}
          onRetry={query.refetch}
        />
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle as="h2">Status</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              <Badge tone={config.configured ? "success" : "warning"}>
                {config.configured ? "values saved" : "setup needed"}
              </Badge>
              <Badge tone={config.enabled ? "success" : "neutral"}>
                {config.enabled ? "enabled" : "disabled"}
              </Badge>
              <Badge tone={config.last_test_status === "passed" ? "success" : "neutral"}>
                test {config.last_test_status}
              </Badge>
              <Badge tone="neutral">{config.connection_count} accounts</Badge>
            </CardContent>
          </Card>

          <Card data-testid="m365-setup-steps">
            <CardHeader>
              <CardTitle as="h2">Register CaseOps in your Microsoft Entra tenant</CardTitle>
              <CardDescription>
                Your firm registers its own app; CaseOps never asks for a Microsoft
                password.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div
                className="mb-4 max-w-3xl rounded-md border border-[var(--color-line)] p-3 text-sm text-[var(--color-ink-2)]"
                data-testid="m365-scope-note"
              >
                <p className="font-medium text-[var(--color-ink)]">What this page does today</p>
                <p className="mt-1">
                  Save stores these values and approvals for your workspace. Test setup
                  checks them in CaseOps without calling Microsoft. They are used only for
                  the Microsoft 365 readiness shown on{" "}
                  <Link href="/app/admin/integrations" className="underline">
                    Integrations
                  </Link>
                  . No CaseOps sign-in reads them yet, so Outlook Mail and
                  OneDrive/SharePoint cannot be connected.
                </p>
                <p className="mt-1">
                  To connect Outlook Calendar, enter the same registration on the{" "}
                  <Link href="/app/admin/outlook" className="underline">
                    Outlook calendar
                  </Link>{" "}
                  page and connect an account there. Its sign-in returns to the Redirect
                  URI below, so one registration serves both pages.
                </p>
              </div>
              <ol className="grid max-w-3xl list-decimal gap-4 pl-5 text-sm text-[var(--color-ink-2)]">
                <li>
                  Sign in to the{" "}
                  <a
                    href={ENTRA_ADMIN_CENTER}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline"
                  >
                    Microsoft Entra admin center
                  </a>{" "}
                  as an Application Administrator, open <strong>App registrations</strong>{" "}
                  and choose <strong>New registration</strong>. For supported account
                  types choose <strong>Accounts in this organizational directory only</strong>.
                </li>
                <li>
                  Under <strong>Redirect URI</strong> choose the <strong>Web</strong>{" "}
                  platform and paste this address exactly (no trailing slash):
                  <div className="mt-2">
                    <CopyField
                      id="m365-redirect-uri"
                      label="Redirect URI"
                      value={config.expected_redirect_uri}
                      description="Generated from this CaseOps deployment's API address. Microsoft returns users only to an address listed on the registration."
                    />
                  </div>
                  {config.saved_redirect_uri && !config.redirect_uri_matches_expected ? (
                    <p
                      role="alert"
                      className="mt-2 text-xs text-[var(--color-danger-600)]"
                      data-testid="m365-redirect-mismatch"
                    >
                      The saved Redirect URI ({config.saved_redirect_uri}) is not this
                      address. Save again to replace it.
                    </p>
                  ) : null}
                </li>
                <li>
                  Open <strong>API permissions</strong>, choose <strong>Add a permission</strong>{" "}
                  &gt; <strong>Microsoft Graph</strong> &gt; <strong>Delegated permissions</strong>,
                  add each permission below, then choose{" "}
                  <strong>Grant admin consent</strong> for your organization.
                  <ul className="mt-2 grid gap-1" data-testid="m365-permissions">
                    {config.required_permissions.map((permission) => (
                      <li key={permission.scope} className="flex flex-wrap gap-x-2">
                        <code className="font-mono text-xs text-[var(--color-ink)]">
                          {permission.scope}
                        </code>
                        <span className="text-xs text-[var(--color-mute)]">
                          {permission.purpose}
                        </span>
                      </li>
                    ))}
                  </ul>
                </li>
                <li>
                  Open <strong>Certificates &amp; secrets</strong>, create a{" "}
                  <strong>New client secret</strong> and copy its <strong>Value</strong>{" "}
                  (not the Secret ID) into Client secret below.
                </li>
                <li>
                  On the app&apos;s <strong>Overview</strong> page copy the{" "}
                  <strong>Application (client) ID</strong> and the{" "}
                  <strong>Directory (tenant) ID</strong> into the fields below. The
                  Directory (tenant) ID is also on the Overview page of Microsoft Entra ID
                  itself, and a verified domain such as yourfirm.onmicrosoft.com works too.
                </li>
              </ol>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle as="h2">Setup values</CardTitle>
            </CardHeader>
            <CardContent>
              <form
                className="grid gap-4 md:grid-cols-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (clientIdError || tenantIdError) return;
                  saveMutation.mutate();
                }}
              >
                <div>
                  <Label htmlFor="m365-client-id">Application (client) ID</Label>
                  <Input
                    id="m365-client-id"
                    value={clientId}
                    onChange={(e) => setClientId(e.target.value)}
                    aria-invalid={clientIdError ? true : undefined}
                    aria-describedby={clientIdError ? "m365-client-id-error" : undefined}
                    autoComplete="off"
                  />
                  <FieldError id="m365-client-id-error" message={clientIdError} />
                </div>
                <div>
                  <Label htmlFor="m365-secret">Client secret</Label>
                  <Input
                    id="m365-secret"
                    type="password"
                    value={clientSecret}
                    placeholder={config.secret_saved ? "Saved. Leave blank to keep it." : ""}
                    onChange={(e) => setClientSecret(e.target.value)}
                    autoComplete="new-password"
                  />
                </div>
                <div>
                  <Label htmlFor="m365-tenant">Directory (tenant) ID</Label>
                  <Input
                    id="m365-tenant"
                    value={tenantId}
                    placeholder="72f988bf-86f1-41af-91ab-2d7cd011db47"
                    onChange={(e) => setTenantId(e.target.value)}
                    aria-invalid={tenantIdError ? true : undefined}
                    aria-describedby={tenantIdError ? "m365-tenant-error" : "m365-tenant-help"}
                    autoComplete="off"
                  />
                  {tenantIdError ? (
                    <FieldError id="m365-tenant-error" message={tenantIdError} />
                  ) : (
                    <p id="m365-tenant-help" className="mt-1 text-xs text-[var(--color-mute)]">
                      A GUID or a verified domain of your firm&apos;s directory.
                    </p>
                  )}
                </div>
                <div className="flex flex-col justify-end gap-2">
                  <label className="flex items-center gap-2 text-sm text-[var(--color-ink-2)]">
                    <input
                      type="checkbox"
                      checked={adminConsent}
                      onChange={(e) => setAdminConsent(e.target.checked)}
                    />
                    Admin consent granted in Microsoft Entra
                  </label>
                  <label className="flex items-center gap-2 text-sm text-[var(--color-ink-2)]">
                    <input
                      type="checkbox"
                      checked={scopesApproved}
                      onChange={(e) => setScopesApproved(e.target.checked)}
                    />
                    Graph permissions reviewed for review-first workflows
                  </label>
                </div>
                <div className="md:col-span-2">
                  <Button
                    type="submit"
                    disabled={saveMutation.isPending || Boolean(clientIdError || tenantIdError)}
                    data-testid="m365-save"
                  >
                    {saveMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                    ) : (
                      <PlugZap className="h-4 w-4" aria-hidden />
                    )}
                    Save
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>

          {testResult ? (
            <Card data-testid="m365-test-results">
              <CardHeader>
                <CardTitle as="h2">
                  {testResult.status === "passed"
                    ? "All values and approvals saved"
                    : "Values or approvals missing"}
                </CardTitle>
                <CardDescription>
                  Checked in CaseOps without calling Microsoft, so a wrong secret or
                  consent not granted in Microsoft Entra is not detected here. Nothing is
                  connected by this test: connect Outlook Calendar from the{" "}
                  <Link href="/app/admin/outlook" className="underline">
                    Outlook calendar
                  </Link>{" "}
                  page.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="grid gap-2 text-sm">
                  {testResult.checks.map((check) => (
                    <li
                      key={check.key}
                      className="flex items-start gap-2"
                      data-testid={`m365-check-${check.key}`}
                      data-status={check.status}
                    >
                      {check.status === "passed" ? (
                        <CheckCircle2
                          className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-success-600)]"
                          aria-hidden
                        />
                      ) : check.status === "blocked" ? (
                        <XCircle
                          className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-danger-600)]"
                          aria-hidden
                        />
                      ) : (
                        <Circle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                      )}
                      <span className="min-w-0">
                        <span className="font-medium text-[var(--color-ink)]">{check.label}</span>
                        <span className="sr-only">
                          : {check.status === "passed" ? "passed" : "needs attention"}.
                        </span>
                        {check.detail ? (
                          <span className="block break-words text-xs text-[var(--color-mute)]">
                            {check.detail}
                          </span>
                        ) : null}
                      </span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ) : null}
        </>
      )}
    </div>
  );
}
