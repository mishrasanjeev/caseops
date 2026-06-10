"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, PlugZap } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
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
  const [redirectUri, setRedirectUri] = useState("");
  const [adminConsent, setAdminConsent] = useState(false);
  const [scopesApproved, setScopesApproved] = useState(false);
  const saveMutation = useMutation({
    mutationFn: () =>
      updateMicrosoft365TenantConfiguration({
        clientId,
        clientSecret,
        tenantId,
        redirectUri,
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
      queryClient.invalidateQueries({ queryKey: ["microsoft365-configuration"] });
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not save Microsoft 365 settings.")),
  });
  const testMutation = useMutation({
    mutationFn: testMicrosoft365TenantConfiguration,
    onSuccess: () => {
      toast.success("Microsoft 365 readiness checked");
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
        description="Graph readiness for Outlook Mail, Outlook Calendar, and OneDrive/SharePoint."
        actions={
          <Button
            type="button"
            variant="outline"
            disabled={testMutation.isPending}
            onClick={() => testMutation.mutate()}
          >
            {testMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <CheckCircle2 className="h-4 w-4" aria-hidden />
            )}
            Test
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
      ) : query.isError ? (
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
              <Badge tone={config?.configured ? "success" : "warning"}>
                {config?.configured ? "configured" : "setup needed"}
              </Badge>
              <Badge tone={config?.enabled ? "success" : "neutral"}>
                {config?.enabled ? "enabled" : "disabled"}
              </Badge>
              <Badge tone={config?.last_test_status === "passed" ? "success" : "neutral"}>
                test {config?.last_test_status}
              </Badge>
              <Badge tone="neutral">{config?.connection_count ?? 0} accounts</Badge>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle as="h2">Setup</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-2">
              <div>
                <Label htmlFor="m365-client-id">Client id</Label>
                <Input id="m365-client-id" value={clientId} onChange={(e) => setClientId(e.target.value)} />
              </div>
              <div>
                <Label htmlFor="m365-secret">Client secret</Label>
                <Input id="m365-secret" type="password" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} />
              </div>
              <div>
                <Label htmlFor="m365-tenant">Tenant id</Label>
                <Input id="m365-tenant" value={tenantId} onChange={(e) => setTenantId(e.target.value)} />
              </div>
              <div>
                <Label htmlFor="m365-redirect">Redirect URI</Label>
                <Input id="m365-redirect" value={redirectUri} onChange={(e) => setRedirectUri(e.target.value)} />
              </div>
              <label className="flex items-center gap-2 text-sm text-[var(--color-ink-2)]">
                <input type="checkbox" checked={adminConsent} onChange={(e) => setAdminConsent(e.target.checked)} />
                Admin consent approved
              </label>
              <label className="flex items-center gap-2 text-sm text-[var(--color-ink-2)]">
                <input type="checkbox" checked={scopesApproved} onChange={(e) => setScopesApproved(e.target.checked)} />
                Scopes approved
              </label>
              <div className="md:col-span-2">
                <Button
                  type="button"
                  disabled={saveMutation.isPending}
                  onClick={() => saveMutation.mutate()}
                >
                  {saveMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                  ) : (
                    <PlugZap className="h-4 w-4" aria-hidden />
                  )}
                  Save
                </Button>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
