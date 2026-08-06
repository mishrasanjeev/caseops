"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bell,
  CircleCheck,
  CircleX,
  Clock,
  Mail,
  Plus,
  RotateCcw,
  Send,
  ShieldCheck,
  Trash2,
} from "lucide-react";
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
  previewNotificationRecovery,
  recoverEmailSuppression,
  recoverNotificationIntent,
  testCurrentUserNotification,
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

function deliveryTone(status: string): "neutral" | "success" | "warning" | "brand" {
  if (status === "delivered") return "success";
  if (["blocked", "suppressed", "bounced", "dead_letter", "cancelled"].includes(status)) {
    return "warning";
  }
  if (status === "sent") return "brand";
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
  const [recoveryAction, setRecoveryAction] = useState("");
  const [replacementMembershipId, setReplacementMembershipId] = useState("");
  const [previewedIntentId, setPreviewedIntentId] = useState<string | null>(null);
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
  const testMutation = useMutation({
    mutationFn: testCurrentUserNotification,
    onSuccess: async (result) => {
      toast.success(result.message);
      await queryClient.invalidateQueries({ queryKey: ["admin", "notifications"] });
    },
    onError: (error) => toast.error(String(error)),
  });
  const previewMutation = useMutation({
    mutationFn: previewNotificationRecovery,
    onSuccess: (preview) => {
      setPreviewedIntentId(preview.original_intent_id);
      toast.success(
        preview.requires_changed_destination
          ? "Preview ready. A changed destination is required."
          : "Recovery preview ready.",
      );
    },
    onError: (error) => toast.error(String(error)),
  });
  const recoverIntentMutation = useMutation({
    mutationFn: recoverNotificationIntent,
    onSuccess: async (result) => {
      toast.success(result.message);
      setPreviewedIntentId(null);
      setRecoveryAction("");
      await queryClient.invalidateQueries({ queryKey: ["admin", "notifications"] });
    },
    onError: (error) => toast.error(String(error)),
  });
  const recoverSuppressionMutation = useMutation({
    mutationFn: recoverEmailSuppression,
    onSuccess: async () => {
      toast.success("Suppression recovered; provider evidence was retained.");
      setRecoveryAction("");
      await queryClient.invalidateQueries({ queryKey: ["admin", "notifications"] });
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
        title="Notification delivery and recovery"
        description="Every intended reminder, its immutable recipient snapshot, provider evidence, fallback, and versioned recovery path."
      />

      <Card>
        <CardContent className="flex min-w-0 flex-col gap-3 pt-5 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-[var(--color-ink)]">
              Self-service channel test
            </h2>
            <p className="mt-1 text-xs text-[var(--color-mute)]">
              Delivers a safe in-app test only. It never contacts an external provider.
            </p>
          </div>
          <Button
            type="button"
            className="w-full sm:w-auto"
            onClick={() => testMutation.mutate()}
            disabled={testMutation.isPending}
            data-testid="notification-self-test"
          >
            <Send className="h-4 w-4" aria-hidden /> Test notification
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="flex flex-col gap-4 pt-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-[var(--color-ink)]">
                Notification rules
              </h2>
              <p className="mt-1 text-xs text-[var(--color-mute)]">
                In-app rules use the durable delivery foundation. External
                automated delivery is blocked pending provider approval.
              </p>
            </div>
            <Badge tone="success">Durable foundation available</Badge>
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
              until provider policy, credentials, and runbooks are approved.
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

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          icon={Clock}
          label="Due"
          value={query.data?.metrics?.due ?? query.data?.total_queued ?? 0}
        />
        <KpiCard
          icon={Mail}
          label="Attempted"
          value={query.data?.metrics?.attempted ?? query.data?.total_sent ?? 0}
        />
        <KpiCard
          icon={CircleCheck}
          label="Delivered"
          value={query.data?.metrics?.delivered ?? query.data?.total_delivered ?? 0}
        />
        <KpiCard
          icon={CircleX}
          label="Failed"
          value={query.data?.metrics?.failed ?? query.data?.total_failed ?? 0}
        />
        <KpiCard
          icon={ShieldCheck}
          label="Suppressed"
          value={query.data?.metrics?.suppressed ?? 0}
        />
        <KpiCard
          icon={CircleX}
          label="Bounced"
          value={query.data?.metrics?.bounced ?? 0}
        />
        <KpiCard
          icon={RotateCcw}
          label="Fallback"
          value={query.data?.metrics?.fallback ?? 0}
        />
        <KpiCard
          icon={AlertTriangle}
          label="Critical alerts"
          value={query.data?.metrics?.critical_alerts ?? 0}
        />
      </section>

      <Card>
        <CardContent className="flex min-w-0 flex-col gap-4 pt-5">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-[var(--color-ink)]">
              Recent delivery intents
            </h2>
            <p className="mt-1 text-xs text-[var(--color-mute)]">
              Durable recipient snapshots and channel outcomes, newest first.
            </p>
          </div>
          {(query.data?.intents ?? []).length === 0 ? (
            <EmptyState
              icon={Bell}
              title="No delivery intents"
              description="Scheduled or self-service notification intents will appear here."
            />
          ) : (
            <ul className="flex min-w-0 flex-col divide-y divide-[var(--color-line)]">
              {(query.data?.intents ?? []).map((intent) => (
                <li
                  key={intent.id}
                  className="flex min-w-0 flex-col gap-2 py-3 lg:flex-row lg:flex-wrap lg:items-center lg:justify-between"
                  data-testid={`notification-intent-${intent.id}`}
                >
                  <div className="min-w-0">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <Badge tone={deliveryTone(intent.status)}>{intent.status}</Badge>
                      {intent.critical ? <Badge tone="warning">critical</Badge> : null}
                      <span className="break-words text-sm font-medium text-[var(--color-ink)]">
                        {intent.event_type.replaceAll("_", " ")}
                      </span>
                    </div>
                    <p className="mt-1 break-all text-xs text-[var(--color-mute)]">
                      {intent.channel} · {intent.destination ?? "No external destination"} ·
                      destination v{intent.destination_version}
                    </p>
                  </div>
                  <span className="break-all text-xs text-[var(--color-mute)]">
                    {formatWhen(intent.updated_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="flex min-w-0 flex-col gap-4 pt-5">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-[var(--color-ink)]">
              Failed and suppressed delivery recovery
            </h2>
            <p className="mt-1 text-xs text-[var(--color-mute)]">
              Preview first. Recovery creates a new destination version and never rewrites the
              original attempts or provider events.
            </p>
          </div>
          <div className="grid min-w-0 gap-3 md:grid-cols-2">
            <Input
              value={recoveryAction}
              onChange={(event) => setRecoveryAction(event.target.value)}
              placeholder="Recovery action and evidence"
              aria-label="Recovery action and evidence"
              data-testid="notification-recovery-action"
            />
            <Input
              value={replacementMembershipId}
              onChange={(event) => setReplacementMembershipId(event.target.value)}
              placeholder="Replacement membership ID for a changed destination"
              aria-label="Replacement membership ID"
              data-testid="notification-replacement-membership"
            />
          </div>
          {(query.data?.intents ?? []).filter((intent) =>
            ["blocked", "suppressed", "bounced", "dead_letter", "retry_scheduled"].includes(
              intent.status,
            ),
          ).length === 0 ? (
            <EmptyState
              icon={CircleCheck}
              title="No actionable delivery failures"
              description="Critical unsent reminders will stay visible here until recovered."
            />
          ) : (
            <ul className="flex min-w-0 flex-col divide-y divide-[var(--color-line)]">
              {(query.data?.intents ?? [])
                .filter((intent) =>
                  [
                    "blocked",
                    "suppressed",
                    "bounced",
                    "dead_letter",
                    "retry_scheduled",
                  ].includes(intent.status),
                )
                .map((intent) => (
                  <li
                    key={intent.id}
                    className="flex min-w-0 flex-col gap-3 py-3 lg:flex-row lg:flex-wrap lg:items-center lg:justify-between"
                    data-testid={`notification-recovery-intent-${intent.id}`}
                  >
                    <div className="min-w-0">
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <Badge tone={deliveryTone(intent.status)}>{intent.status}</Badge>
                        {intent.critical ? <Badge tone="warning">critical</Badge> : null}
                        <span className="break-all text-xs text-[var(--color-mute)]">
                          {intent.channel} · destination v{intent.destination_version}
                        </span>
                      </div>
                      <p className="mt-1 break-words text-xs text-[var(--color-mute)]">
                        {intent.destination ?? "No external destination"}
                        {intent.last_error_redacted ? ` · ${intent.last_error_redacted}` : ""}
                      </p>
                    </div>
                    <div className="flex w-full min-w-0 flex-col gap-2 sm:flex-row sm:flex-wrap lg:w-auto">
                      <Button
                        type="button"
                        variant="outline"
                        className="w-full sm:w-auto"
                        onClick={() => previewMutation.mutate(intent.id)}
                        disabled={previewMutation.isPending}
                        data-testid={`notification-preview-${intent.id}`}
                      >
                        Preview recovery
                      </Button>
                      <Button
                        type="button"
                        className="w-full sm:w-auto"
                        onClick={() =>
                          recoverIntentMutation.mutate({
                            intentId: intent.id,
                            recoveryAction,
                            replacementMembershipId: replacementMembershipId || null,
                          })
                        }
                        disabled={
                          previewedIntentId !== intent.id ||
                          recoveryAction.trim().length < 8 ||
                          recoverIntentMutation.isPending
                        }
                        data-testid={`notification-recover-${intent.id}`}
                      >
                        <RotateCcw className="h-4 w-4" aria-hidden /> Recover
                      </Button>
                    </div>
                  </li>
                ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="flex min-w-0 flex-col gap-4 pt-5">
          <div>
            <h2 className="text-base font-semibold text-[var(--color-ink)]">
              Suppression evidence
            </h2>
            <p className="mt-1 text-xs text-[var(--color-mute)]">
              Provider/category, first and last occurrence, affected address, fallback, and
              recovery action remain auditable.
            </p>
          </div>
          {(query.data?.suppressions ?? []).length === 0 ? (
            <EmptyState
              icon={ShieldCheck}
              title="No suppression records"
              description="Bounce, drop, spam, and unsubscribe evidence will appear here."
            />
          ) : (
            <ul className="flex min-w-0 flex-col divide-y divide-[var(--color-line)]">
              {(query.data?.suppressions ?? []).map((suppression) => (
                <li
                  key={suppression.id}
                  className="flex min-w-0 flex-col gap-3 py-3 lg:flex-row lg:flex-wrap lg:items-center lg:justify-between"
                  data-testid={`notification-suppression-${suppression.id}`}
                >
                  <div className="min-w-0 text-xs text-[var(--color-mute)]">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={suppression.recovered_at ? "success" : "warning"}>
                        {suppression.recovered_at ? "recovered" : suppression.category}
                      </Badge>
                      <span className="break-all">{suppression.affected_address}</span>
                    </div>
                    <p className="mt-1">
                      {suppression.provider} · first {formatWhen(suppression.first_occurrence)} ·
                      last {formatWhen(suppression.last_occurrence)} · fallback {" "}
                      {suppression.fallback_sent ? "sent" : "not sent"}
                    </p>
                  </div>
                  {!suppression.recovered_at ? (
                    <Button
                      type="button"
                      variant="outline"
                      className="w-full lg:w-auto"
                      onClick={() =>
                        recoverSuppressionMutation.mutate({
                          suppressionId: suppression.id,
                          recoveryAction,
                          replacementMembershipId: replacementMembershipId || null,
                        })
                      }
                      disabled={
                        recoveryAction.trim().length < 8 || recoverSuppressionMutation.isPending
                      }
                      data-testid={`suppression-recover-${suppression.id}`}
                    >
                      Recover suppression
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

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
          {r.delivery_status ? (
            <Badge tone={deliveryTone(r.delivery_status)}>{r.delivery_status}</Badge>
          ) : null}
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
        <div className="mt-1 break-words text-xs text-[var(--color-mute)]">
          {r.destination_version ? `Destination v${r.destination_version}` : ""}
          {r.fallback_sent ? " · In-app fallback sent" : ""}
          {r.superseded_by_intent_id
            ? ` · Replaced by ${r.superseded_by_intent_id}`
            : ""}
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
