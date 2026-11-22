"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Smartphone } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { apiErrorMessage } from "@/lib/api/config";
import {
  confirmPhoneVerification,
  fetchPhoneContact,
  removePhoneContact,
  setPhoneConsent,
  startPhoneVerification,
} from "@/lib/api/endpoints";
import type { PhoneChannel, PhoneContactStatusResponse } from "@/lib/api/schemas";

const CHANNEL_LABEL: Record<PhoneChannel, string> = {
  sms: "Text message (SMS)",
  whatsapp: "WhatsApp",
};

// services/phone_notifications.py phone_admission reasons, in plain words.
export const PHONE_BLOCK_COPY: Record<string, string> = {
  kill_switch_active: "Paused for every workspace by CaseOps.",
  provider_disabled: "Not set up for this deployment yet.",
  provider_incomplete: "Not set up for this deployment yet.",
  mock_transport_outside_local: "Not set up for this deployment yet.",
  workspace_channel_disabled: "A workspace admin has not turned this on.",
  phone_requires_workspace_member: "Only workspace members can receive these.",
  phone_not_registered: "Add and verify your mobile number first.",
  phone_not_verified: "Verify your mobile number first.",
  phone_consent_missing: "Off. Turn it on to receive reminders here.",
  phone_opted_out: "Off. You turned this off.",
  sms_requires_indian_number: "Text messages need an Indian (+91) number.",
};

function consentText(channel: PhoneChannel): string {
  const via = channel === "sms" ? "text message" : "WhatsApp";
  return (
    `I agree to receive hearing reminders and workspace alerts from CaseOps by ${via} ` +
    "on this number. Each message carries only the Matter code, hearing date, time and " +
    "court. I can turn this off here at any time" +
    (channel === "whatsapp" ? ", or reply STOP on WhatsApp." : ".")
  );
}

export function PhoneChannelPreferences(): React.JSX.Element {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["notification-phone"], queryFn: fetchPhoneContact });
  const [phoneNumber, setPhoneNumber] = useState("");
  const [codeChannel, setCodeChannel] = useState<PhoneChannel>("sms");
  const [code, setCode] = useState("");
  const [editing, setEditing] = useState(false);
  const [agreed, setAgreed] = useState<Record<PhoneChannel, boolean>>({
    sms: false,
    whatsapp: false,
  });

  const settle = (data: PhoneContactStatusResponse) => {
    queryClient.setQueryData(["notification-phone"], data);
    void queryClient.invalidateQueries({ queryKey: ["notification-preferences"] });
  };
  const sendCode = useMutation({
    mutationFn: (channel: PhoneChannel) => startPhoneVerification({ phoneNumber, channel }),
    onSuccess: (data) => {
      settle(data);
      setCode("");
      toast.success("Code sent");
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not send the code.")),
  });
  const verify = useMutation({
    mutationFn: () => confirmPhoneVerification(code),
    onSuccess: (data) => {
      settle(data);
      setEditing(false);
      setPhoneNumber("");
      toast.success("Mobile number verified");
    },
    onError: (error) => toast.error(apiErrorMessage(error, "That code did not work.")),
  });
  const consent = useMutation({
    mutationFn: (input: { channel: PhoneChannel; optedIn: boolean }) =>
      setPhoneConsent({
        ...input,
        consentTextVersion: query.data?.consent_text_version,
      }),
    onSuccess: (data, input) => {
      settle(data);
      setAgreed((current) => ({ ...current, [input.channel]: false }));
      toast.success(input.optedIn ? "Reminders turned on" : "Reminders turned off");
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not save this choice.")),
  });
  const remove = useMutation({
    mutationFn: removePhoneContact,
    onSuccess: (data) => {
      settle(data);
      toast.success("Mobile number removed");
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not remove the number.")),
  });

  if (query.isPending) {
    return (
      <Card>
        <CardContent className="space-y-3">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-16 w-full" />
        </CardContent>
      </Card>
    );
  }
  if (query.isError) {
    return (
      <QueryErrorState
        title="Could not load your mobile number settings"
        error={query.error}
        onRetry={query.refetch}
      />
    );
  }

  const status = query.data;
  const channels: PhoneChannel[] = ["sms", "whatsapp"];
  const codeChannels = channels.filter(
    (channel) => status.channels[channel].tenant_enabled && status.channels[channel].provider_ready,
  );
  const selectedCodeChannel = codeChannels.includes(codeChannel) ? codeChannel : codeChannels[0];
  const showEntry = !status.verified || editing;

  return (
    <Card data-testid="phone-channel-preferences">
      <CardHeader>
        <CardTitle as="h2">Text and WhatsApp reminders</CardTitle>
        <CardDescription>
          Off unless you verify a mobile number and turn a channel on. Messages carry only the
          Matter code, hearing date, time and court.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {status.verified && !editing ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-[var(--color-line)] bg-white px-4 py-3">
            <div className="flex items-center gap-2 text-sm">
              <Smartphone className="h-4 w-4 text-[var(--color-mute)]" aria-hidden />
              <span className="font-mono tabular-nums text-[var(--color-ink)]">
                {status.phone_masked}
              </span>
              <Badge tone="success">Verified</Badge>
            </div>
            <div className="flex gap-2">
              <Button type="button" size="sm" variant="outline" onClick={() => setEditing(true)}>
                Change number
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={remove.isPending}
                onClick={() => remove.mutate()}
              >
                Remove number
              </Button>
            </div>
          </div>
        ) : null}

        {showEntry ? (
          codeChannels.length === 0 ? (
            <p className="rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] px-3 py-2 text-sm text-[var(--color-ink-2)]">
              Text and WhatsApp reminders are not available in this workspace yet. A workspace
              admin can turn them on under Admin, Notifications once the provider is set up.
            </p>
          ) : (
            <form
              className="grid gap-3 md:grid-cols-[minmax(0,16rem)_auto_auto] md:items-end"
              onSubmit={(event) => {
                event.preventDefault();
                if (selectedCodeChannel) sendCode.mutate(selectedCodeChannel);
              }}
            >
              <div className="flex flex-col gap-1">
                <Label htmlFor="phone-number">Mobile number</Label>
                <Input
                  id="phone-number"
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel"
                  placeholder="+91 98123 45678"
                  value={phoneNumber}
                  onChange={(event) => setPhoneNumber(event.target.value)}
                  required
                />
              </div>
              {codeChannels.length > 1 ? (
                <fieldset className="flex gap-3 text-sm text-[var(--color-ink-2)]">
                  <legend className="mb-1 text-xs font-medium text-[var(--color-mute)]">
                    Send the code by
                  </legend>
                  {codeChannels.map((channel) => (
                    <label key={channel} className="flex items-center gap-1.5">
                      <input
                        type="radio"
                        name="code-channel"
                        value={channel}
                        checked={selectedCodeChannel === channel}
                        onChange={() => setCodeChannel(channel)}
                      />
                      {channel === "sms" ? "SMS" : "WhatsApp"}
                    </label>
                  ))}
                </fieldset>
              ) : null}
              <Button type="submit" size="md" disabled={sendCode.isPending || !phoneNumber.trim()}>
                {sendCode.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : null}
                Send code
              </Button>
            </form>
          )
        ) : null}

        {status.verification_pending ? (
          <form
            className="grid gap-3 md:grid-cols-[minmax(0,10rem)_auto] md:items-end"
            onSubmit={(event) => {
              event.preventDefault();
              verify.mutate();
            }}
          >
            <div className="flex flex-col gap-1">
              <Label htmlFor="phone-code">
                Code sent to {status.phone_masked}
              </Label>
              <Input
                id="phone-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                maxLength={6}
                className="font-mono tabular-nums"
                value={code}
                onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
                required
              />
            </div>
            <Button type="submit" size="md" disabled={verify.isPending || code.length !== 6}>
              Verify
            </Button>
          </form>
        ) : null}

        <ul className="flex flex-col divide-y divide-[var(--color-line)] rounded-md border border-[var(--color-line)] bg-white">
          {channels.map((channel) => {
            const record = status.channels[channel];
            const blocked = record.blocked_reason
              ? PHONE_BLOCK_COPY[record.blocked_reason] ?? "Not available."
              : null;
            const canOptIn =
              status.verified && !record.opted_in && record.tenant_enabled && record.provider_ready;
            const consentId = `phone-consent-${channel}`;
            return (
              <li key={channel} className="flex flex-col gap-3 px-4 py-3" data-testid={`phone-channel-${channel}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-[var(--color-ink)]">
                    {CHANNEL_LABEL[channel]}
                  </span>
                  <Badge tone={record.deliverable ? "success" : "neutral"}>
                    {record.deliverable ? "On" : record.opted_in ? "On, not deliverable" : "Off"}
                  </Badge>
                </div>
                {!record.deliverable && blocked ? (
                  <p className="text-xs text-[var(--color-mute)]">{blocked}</p>
                ) : null}
                {record.opted_in ? (
                  <div>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={consent.isPending}
                      onClick={() => consent.mutate({ channel, optedIn: false })}
                    >
                      Turn off
                    </Button>
                  </div>
                ) : canOptIn ? (
                  <div className="flex flex-col gap-2">
                    <label htmlFor={consentId} className="flex items-start gap-2 text-sm text-[var(--color-ink-2)]">
                      <input
                        id={consentId}
                        type="checkbox"
                        className="mt-1 h-4 w-4"
                        checked={agreed[channel]}
                        onChange={(event) =>
                          setAgreed((current) => ({ ...current, [channel]: event.target.checked }))
                        }
                      />
                      <span className="max-w-[70ch]">{consentText(channel)}</span>
                    </label>
                    <div>
                      <Button
                        type="button"
                        size="sm"
                        disabled={!agreed[channel] || consent.isPending}
                        onClick={() => consent.mutate({ channel, optedIn: true })}
                      >
                        Turn on {channel === "sms" ? "SMS" : "WhatsApp"}
                      </Button>
                    </div>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}
