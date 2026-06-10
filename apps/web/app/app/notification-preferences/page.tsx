"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Loader2, Save } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  fetchNotificationPreferences,
  updateUserNotificationPreferences,
} from "@/lib/api/endpoints";
import { apiErrorMessage } from "@/lib/api/config";

const CHANNELS = ["in_app", "email", "sms", "whatsapp"] as const;

export default function NotificationPreferencesPage() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["notification-preferences"],
    queryFn: fetchNotificationPreferences,
  });
  const [channels, setChannels] = useState<Record<string, boolean>>({});
  const mutation = useMutation({
    mutationFn: () => updateUserNotificationPreferences({ channels }),
    onSuccess: () => {
      toast.success("Preferences saved");
      queryClient.invalidateQueries({ queryKey: ["notification-preferences"] });
    },
    onError: (error) =>
      toast.error(apiErrorMessage(error, "Could not save notification preferences.")),
  });
  const prefs = query.data;
  const effectiveChannels = {
    ...Object.fromEntries(
      CHANNELS.map((channel) => [
        channel,
        prefs?.user.channels[channel]?.enabled ?? channel === "in_app",
      ]),
    ),
    ...channels,
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Notifications"
        title="Preferences"
        description="In-app, email, SMS, and WhatsApp delivery controls."
        actions={
          <Button
            type="button"
            disabled={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Save className="h-4 w-4" aria-hidden />
            )}
            Save
          </Button>
        }
      />

      {query.isPending ? (
        <Card>
          <CardContent className="space-y-3">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </CardContent>
        </Card>
      ) : query.isError ? (
        <QueryErrorState
          title="Could not load preferences"
          error={query.error}
          onRetry={query.refetch}
        />
      ) : !prefs ? (
        <EmptyState icon={Bell} title="No preferences" description="No preference row exists." />
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle as="h2">Channels</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              {CHANNELS.map((channel) => {
                const channelPref = prefs.user.channels[channel];
                const providerReady = prefs.provider_configured[channel] ?? false;
                const external = channel !== "in_app";
                return (
                  <label
                    key={channel}
                    className="rounded-md border border-[var(--color-line)] bg-white p-4"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <span className="font-medium text-[var(--color-ink)]">
                        {channel.replaceAll("_", " ")}
                      </span>
                      <input
                        className="h-4 w-4"
                        type="checkbox"
                        checked={Boolean(effectiveChannels[channel])}
                        onChange={(event) =>
                          setChannels((current) => ({
                            ...current,
                            [channel]: event.target.checked,
                          }))
                        }
                      />
                    </div>
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      <Badge tone={providerReady ? "success" : "neutral"}>
                        {providerReady ? "configured" : "disabled"}
                      </Badge>
                      <Badge tone={!external || channelPref?.external_delivery_enabled ? "success" : "neutral"}>
                        {external ? "external blocked" : "in app"}
                      </Badge>
                    </div>
                  </label>
                );
              })}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle as="h2">Categories</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2 md:grid-cols-2">
              {Object.entries(prefs.user.event_categories).map(([category, enabled]) => (
                <div
                  key={category}
                  className="flex items-center justify-between rounded-md border border-[var(--color-line)] bg-white px-3 py-2 text-sm"
                >
                  <span>{category.replaceAll("_", " ")}</span>
                  <Badge tone={enabled ? "success" : "neutral"}>
                    {enabled ? "on" : "off"}
                  </Badge>
                </div>
              ))}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
