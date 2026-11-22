"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { apiErrorMessage } from "@/lib/api/config";
import {
  fetchAdminPhoneChannels,
  updateTenantNotificationPreferences,
} from "@/lib/api/endpoints";
import type { PhoneChannel } from "@/lib/api/schemas";

const LABEL: Record<PhoneChannel, { name: string; provider: string }> = {
  sms: { name: "Text message (SMS)", provider: "MSG91, DLT templates" },
  whatsapp: { name: "WhatsApp", provider: "Meta WhatsApp Cloud API" },
};

const NOT_READY_COPY: Record<string, string> = {
  kill_switch_active: "Paused platform-wide by the CaseOps kill switch.",
  provider_disabled: "The provider is switched off for this deployment.",
  provider_incomplete: "The provider is missing configuration.",
  mock_transport_outside_local: "Live transport is not configured for this deployment.",
};

export function PhoneChannelAdminCard(): React.JSX.Element {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["admin", "notification-phone-channels"],
    queryFn: fetchAdminPhoneChannels,
  });
  const toggle = useMutation({
    mutationFn: (input: { channel: PhoneChannel; enabled: boolean }) =>
      updateTenantNotificationPreferences({ channels: { [input.channel]: input.enabled } }),
    onSuccess: (_data, input) => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "notification-phone-channels"] });
      void queryClient.invalidateQueries({ queryKey: ["notification-preferences"] });
      toast.success(
        `${LABEL[input.channel].name} ${input.enabled ? "enabled" : "disabled"} for this workspace`,
      );
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not change this channel.")),
  });

  return (
    <Card data-testid="phone-channel-admin">
      <CardContent className="flex flex-col gap-4 pt-5">
        <div>
          <h2 className="text-base font-semibold text-[var(--color-ink)]">
            Text and WhatsApp reminders
          </h2>
          <p className="mt-1 max-w-[70ch] text-xs text-[var(--color-mute)]">
            Enabling a channel lets colleagues opt in with a verified number. Nothing is sent to
            anyone who has not opted in. Each message uses an approved template with the Matter
            code, hearing date, time and court, and counts against the workspace provider budget.
          </p>
        </div>
        {query.isPending ? (
          <Skeleton className="h-24 w-full" />
        ) : query.isError ? (
          <QueryErrorState
            title="Could not load channel status"
            error={query.error}
            onRetry={query.refetch}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[36rem] text-left text-sm">
              <thead className="text-[11px] font-medium uppercase tracking-wide text-[var(--color-mute)]">
                <tr>
                  <th className="py-2 pr-3">Channel</th>
                  <th className="py-2 pr-3">Provider</th>
                  <th className="py-2 pr-3">Workspace</th>
                  <th className="py-2 pr-3 text-right">Opted in</th>
                  <th className="py-2" aria-label="Action" />
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-line)]">
                {(["sms", "whatsapp"] as const).map((channel) => {
                  const row = query.data.channels[channel];
                  const reason = row.not_ready_reason
                    ? NOT_READY_COPY[row.not_ready_reason] ?? "Not available."
                    : null;
                  return (
                    <tr key={channel} data-testid={`phone-admin-${channel}`}>
                      <td className="py-3 pr-3 align-top">
                        <div className="font-medium text-[var(--color-ink)]">
                          {LABEL[channel].name}
                        </div>
                        <div className="text-xs text-[var(--color-mute)]">
                          {LABEL[channel].provider}
                        </div>
                      </td>
                      <td className="py-3 pr-3 align-top">
                        <Badge tone={row.provider_ready ? "success" : "warning"}>
                          {row.provider_ready ? "Ready" : "Not ready"}
                        </Badge>
                        {reason ? (
                          <p className="mt-1 max-w-[32ch] text-xs text-[var(--color-mute)]">
                            {reason}
                          </p>
                        ) : null}
                        {row.missing_configuration.length ? (
                          <p className="mt-1 max-w-[40ch] break-words font-mono text-[11px] text-[var(--color-mute)]">
                            Missing: {row.missing_configuration.join(", ")}
                          </p>
                        ) : null}
                      </td>
                      <td className="py-3 pr-3 align-top">
                        <Badge tone={row.tenant_enabled ? "brand" : "neutral"}>
                          {row.tenant_enabled ? "Enabled" : "Disabled"}
                        </Badge>
                      </td>
                      <td className="py-3 pr-3 text-right align-top font-mono tabular-nums">
                        {row.opted_in_members}
                      </td>
                      <td className="py-3 text-right align-top">
                        <Button
                          type="button"
                          size="sm"
                          variant={row.tenant_enabled ? "outline" : "primary"}
                          disabled={toggle.isPending}
                          onClick={() =>
                            toggle.mutate({ channel, enabled: !row.tenant_enabled })
                          }
                        >
                          {row.tenant_enabled ? "Disable" : "Enable"}
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
