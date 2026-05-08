"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, CircleCheck, CircleX, Clock, Mail, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  createNotificationRule,
  deleteNotificationRule,
  type HearingReminderRecord,
  type HearingReminderStatus,
  listAdminNotifications,
  listNotificationRules,
  type NotificationRuleInput,
  updateNotificationRule,
} from "@/lib/api/endpoints";
import type { NotificationRuleRecord } from "@/lib/api/schemas";
import { useCapability } from "@/lib/capabilities";

type StatusFilter = "all" | HearingReminderStatus;

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "queued", label: "Queued" },
  { value: "sent", label: "Sent" },
  { value: "delivered", label: "Delivered" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

function statusTone(s: HearingReminderStatus): "neutral" | "success" | "warning" | "brand" {
  if (s === "delivered") return "success";
  if (s === "failed" || s === "cancelled") return "warning";
  if (s === "sent") return "brand";
  return "neutral";
}

function formatWhen(value: string | null | undefined): string {
  if (!value) return "—";
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


export default function AdminNotificationsPage() {
  const canManageNotifications = useCapability("notifications:manage");
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<StatusFilter>("all");
  const [ruleForm, setRuleForm] = useState<NotificationRuleInput>({
    scope_type: "company",
    scope_id: null,
    event_type: "new_order_uploaded",
    channels: ["in_app"],
    offset_minutes: null,
    enabled: true,
  });
  const query = useQuery({
    queryKey: ["admin", "notifications", { status }],
    queryFn: () => listAdminNotifications({ status }),
    enabled: canManageNotifications,
  });
  const rulesQuery = useQuery({
    queryKey: ["notification-rules"],
    queryFn: listNotificationRules,
    enabled: canManageNotifications,
  });
  const createRuleMutation = useMutation({
    mutationFn: createNotificationRule,
    onSuccess: async () => {
      toast.success("Notification rule created.");
      await queryClient.invalidateQueries({ queryKey: ["notification-rules"] });
      setRuleForm({
        scope_type: "company",
        scope_id: null,
        event_type: "new_order_uploaded",
        channels: ["in_app"],
        offset_minutes: null,
        enabled: true,
      });
    },
    onError: (error) => toast.error(String(error)),
  });
  const updateRuleMutation = useMutation({
    mutationFn: ({ id, input }: { id: string; input: Partial<NotificationRuleInput> }) =>
      updateNotificationRule(id, input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["notification-rules"] });
    },
    onError: (error) => toast.error(String(error)),
  });
  const deleteRuleMutation = useMutation({
    mutationFn: deleteNotificationRule,
    onSuccess: async () => {
      toast.success("Notification rule deleted.");
      await queryClient.invalidateQueries({ queryKey: ["notification-rules"] });
    },
    onError: (error) => toast.error(String(error)),
  });

  if (!canManageNotifications) {
    return (
      <EmptyState
        icon={Bell}
        title="Notifications access required"
        description="Notification rules and delivery status are limited to authorized workspace operators."
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Admin · Notifications"
        title="Hearing reminders"
        description="Every reminder the system intends to send, with delivery status from SendGrid. Durable — rows persist even when the provider isn't wired yet."
      />

      <Card>
        <CardContent className="flex flex-col gap-4 pt-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-[var(--color-ink)]">
                Notification rules
              </h2>
              <p className="mt-1 text-xs text-[var(--color-mute)]">
                In-app rules are transactional. External automated delivery is
                blocked pending Temporal-backed retry.
              </p>
            </div>
            <Badge tone="warning">Durable delivery blocked</Badge>
          </div>

          <div
            className="grid gap-3 rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] p-3 md:grid-cols-6"
            data-testid="notification-rule-form"
          >
            <div>
              <label className="text-[11px] font-medium text-[var(--color-mute)]">
                Scope
              </label>
              <Select
                value={ruleForm.scope_type}
                onValueChange={(value) =>
                  setRuleForm((f) => ({
                    ...f,
                    scope_type: value as NotificationRuleInput["scope_type"],
                    scope_id: value === "company" ? null : f.scope_id,
                  }))
                }
              >
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="company">Company</SelectItem>
                  <SelectItem value="matter">Matter</SelectItem>
                  <SelectItem value="user">User</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="md:col-span-2">
              <label className="text-[11px] font-medium text-[var(--color-mute)]">
                Scope ID
              </label>
              <Input
                className="mt-1"
                disabled={ruleForm.scope_type === "company"}
                value={ruleForm.scope_id ?? ""}
                onChange={(event) =>
                  setRuleForm((f) => ({
                    ...f,
                    scope_id: event.target.value || null,
                  }))
                }
                placeholder={
                  ruleForm.scope_type === "company"
                    ? "Not required"
                    : "Matter or membership id"
                }
              />
            </div>
            <div>
              <label className="text-[11px] font-medium text-[var(--color-mute)]">
                Event
              </label>
              <Select
                value={ruleForm.event_type}
                onValueChange={(value) =>
                  setRuleForm((f) => ({
                    ...f,
                    event_type: value as NotificationRuleInput["event_type"],
                  }))
                }
              >
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="new_order_uploaded">New order</SelectItem>
                  <SelectItem value="hearing_upcoming">Hearing upcoming</SelectItem>
                  <SelectItem value="stay_status_changed">Stay changed</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <label className="mt-6 flex items-center gap-2 text-xs text-[var(--color-ink-2)]">
              <input
                type="checkbox"
                checked={ruleForm.enabled ?? true}
                onChange={(event) =>
                  setRuleForm((f) => ({ ...f, enabled: event.target.checked }))
                }
              />
              Enabled
            </label>
            <div className="flex items-end">
              <Button
                type="button"
                size="sm"
                onClick={() => createRuleMutation.mutate(ruleForm)}
                disabled={createRuleMutation.isPending}
                data-testid="notification-rule-create"
              >
                <Plus className="h-4 w-4" aria-hidden /> Add rule
              </Button>
            </div>
            <div className="text-xs text-[var(--color-mute)] md:col-span-6">
              Channel: in-app. Email, SMS, and WhatsApp automation remain unavailable
              until durable delivery infrastructure is present.
            </div>
          </div>

          {rulesQuery.isPending ? (
            <Skeleton className="h-16 w-full" />
          ) : rulesQuery.isError ? (
            <QueryErrorState
              title="Could not load notification rules"
              error={rulesQuery.error}
              onRetry={rulesQuery.refetch}
            />
          ) : rulesQuery.data.rules.length === 0 ? (
            <EmptyState
              icon={Bell}
              title="No notification rules"
              description="Create a company, matter, or user scoped rule to start generating in-app notifications."
            />
          ) : (
            <ul className="divide-y divide-[var(--color-line)]">
              {rulesQuery.data.rules.map((rule) => (
                <NotificationRuleRow
                  key={rule.id}
                  rule={rule}
                  onToggle={() =>
                    updateRuleMutation.mutate({
                      id: rule.id,
                      input: { enabled: !rule.enabled },
                    })
                  }
                  onDelete={() => deleteRuleMutation.mutate(rule.id)}
                  disabled={updateRuleMutation.isPending || deleteRuleMutation.isPending}
                />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <section className="grid gap-3 md:grid-cols-4">
        <KpiCard
          icon={Clock}
          label="Queued"
          value={query.data?.total_queued ?? 0}
        />
        <KpiCard icon={Mail} label="Sent" value={query.data?.total_sent ?? 0} />
        <KpiCard
          icon={CircleCheck}
          label="Delivered"
          value={query.data?.total_delivered ?? 0}
        />
        <KpiCard
          icon={CircleX}
          label="Failed"
          value={query.data?.total_failed ?? 0}
        />
      </section>

      <Card>
        <CardContent className="flex flex-col gap-4 pt-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <label
                htmlFor="status-filter"
                className="text-xs font-medium text-[var(--color-mute-2)]"
              >
                Status
              </label>
              <Select
                value={status}
                onValueChange={(v) => setStatus(v as StatusFilter)}
              >
                <SelectTrigger id="status-filter" className="w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STATUS_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {query.isPending ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : query.isError ? (
            <QueryErrorState
              title="Could not load notifications"
              error={query.error}
              onRetry={query.refetch}
            />
          ) : query.data.reminders.length === 0 ? (
            <EmptyState
              icon={Bell}
              title="No reminders yet"
              description="Scheduled hearings will queue reminders here at T-24h and T-1h. Rows appear the moment a hearing is saved."
            />
          ) : (
            <ul className="flex flex-col divide-y divide-[var(--color-line)]">
              {query.data.reminders.map((r) => (
                <ReminderRow key={r.id} reminder={r} />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}


function NotificationRuleRow({
  rule,
  onToggle,
  onDelete,
  disabled,
}: {
  rule: NotificationRuleRecord;
  onToggle: () => void;
  onDelete: () => void;
  disabled: boolean;
}) {
  return (
    <li
      className="flex flex-wrap items-center justify-between gap-3 py-3"
      data-testid={`notification-rule-${rule.id}`}
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={rule.enabled ? "success" : "neutral"}>
            {rule.enabled ? "enabled" : "disabled"}
          </Badge>
          <span className="text-sm font-medium text-[var(--color-ink)]">
            {rule.event_type.replaceAll("_", " ")}
          </span>
        </div>
        <div className="mt-1 text-xs text-[var(--color-mute)]">
          {rule.scope_type}
          {rule.scope_id ? ` · ${rule.scope_id}` : ""}
          {" · "}
          {rule.channels.join(", ")}
          {" · "}
          {rule.durable_delivery.replaceAll("_", " ")}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={onToggle}
          disabled={disabled}
          data-testid={`notification-rule-toggle-${rule.id}`}
        >
          {rule.enabled ? "Disable" : "Enable"}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={onDelete}
          disabled={disabled}
          aria-label="Delete notification rule"
          data-testid={`notification-rule-delete-${rule.id}`}
        >
          <Trash2 className="h-4 w-4" aria-hidden />
        </Button>
      </div>
    </li>
  );
}

function KpiCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Bell;
  label: string;
  value: number;
}) {
  return (
    <Card>
      <CardContent className="flex items-start gap-3 py-4">
        <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--color-bg)] text-[var(--color-ink-3)]">
          <Icon className="h-5 w-5" aria-hidden />
        </span>
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
            {label}
          </div>
          <div className="tabular text-xl font-semibold text-[var(--color-ink)]">
            {value}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}


function ReminderRow({
  reminder: r,
}: {
  reminder: HearingReminderRecord;
}) {
  return (
    <li className="flex items-start justify-between gap-3 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={statusTone(r.status)}>{r.status}</Badge>
          <span className="text-xs text-[var(--color-mute)]">
            {r.channel}
          </span>
          <span className="text-xs text-[var(--color-mute)]">
            · {r.recipient_email ?? "no recipient"}
          </span>
        </div>
        <div className="mt-1 text-xs text-[var(--color-mute)]">
          Scheduled: {formatWhen(r.scheduled_for)}
          {r.sent_at ? ` · Sent: ${formatWhen(r.sent_at)}` : ""}
          {r.delivered_at ? ` · Delivered: ${formatWhen(r.delivered_at)}` : ""}
        </div>
        {r.last_error ? (
          <div className="mt-1 text-xs text-[var(--color-warn-700,#a55400)]">
            {r.last_error}
          </div>
        ) : null}
      </div>
      <div className="text-right text-xs text-[var(--color-mute)]">
        {r.attempts > 0 ? `${r.attempts} attempt${r.attempts === 1 ? "" : "s"}` : ""}
      </div>
    </li>
  );
}
