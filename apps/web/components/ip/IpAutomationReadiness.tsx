"use client";

import { ChevronDown, ChevronUp } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import type { IpFeatureBlockedReason, IpFeatureReadiness } from "@/lib/api/endpoints";

/**
 * Why an IP feature is unavailable, grouped by who can change it (BUG-001).
 *
 * The server lists every failing gate per feature in `blocked_reasons`. Each
 * gate belongs to exactly one group, and each group has its own wording and
 * its own fixer, so "paused by CaseOps" is never confused with "not in your
 * plan", "needs setup" or "your role cannot".
 */

export type IpReadinessGroup = "rollout" | "entitlement" | "configuration" | "capability" | "incident";

const GROUP_OF: Record<IpFeatureBlockedReason, IpReadinessGroup> = {
  unknown_feature: "rollout",
  rollout_disabled: "rollout",
  rollout_expired: "rollout",
  missing_entitlement: "entitlement",
  workspace_not_configured: "configuration",
  tenant_disabled: "configuration",
  readiness_test_failed: "configuration",
  missing_capability: "capability",
  incident_kill_switch: "incident",
};

const GROUP_ORDER: IpReadinessGroup[] = ["rollout", "entitlement", "configuration", "capability", "incident"];

const GROUP_TITLE: Record<IpReadinessGroup, string> = {
  rollout: "Paused by CaseOps",
  entitlement: "Not in your plan",
  configuration: "Needs setup",
  capability: "Your role cannot use it",
  incident: "Stopped by a risk incident",
};

const REASON_DETAIL: Record<IpFeatureBlockedReason, string> = {
  unknown_feature: "CaseOps has not released this feature.",
  rollout_disabled: "CaseOps has not switched this feature on yet. Nothing in your workspace needs to change.",
  rollout_expired: "The CaseOps pilot window for this feature has ended. CaseOps reopens it.",
  // No self-serve plan carries IP features today; CaseOps adds them on request.
  missing_entitlement: "Your workspace plan does not include it. A workspace admin can ask CaseOps to add it to the plan.",
  workspace_not_configured: "The IP workspace settings have not been saved. An IP workspace admin saves them in Workspace configuration.",
  tenant_disabled: "It is switched off in your workspace settings. An IP workspace admin can switch it on in Workspace configuration.",
  readiness_test_failed: "Its latest readiness test has not passed. An IP workspace admin re-runs the test in Workspace configuration.",
  missing_capability: "Your role does not include it. Ask a workspace admin for a role that does.",
  incident_kill_switch: "An open risk incident stopped it. It resumes when the incident owner releases the stop.",
};

function countPhrase(group: IpReadinessGroup, count: number): string {
  switch (group) {
    case "rollout":
      return `${count} paused by CaseOps`;
    case "entitlement":
      return `${count} not in your plan`;
    case "configuration":
      return `${count} ${count === 1 ? "needs" : "need"} setup`;
    case "capability":
      return `${count} your role cannot use`;
    case "incident":
      return `${count} stopped by a risk incident`;
  }
}

/** Every failing gate of a feature; older servers only send `reason`. */
export function featureBlockedReasons(feature: IpFeatureReadiness): IpFeatureBlockedReason[] {
  if (feature.blocked_reasons) return feature.blocked_reasons;
  return feature.reason === "available" ? [] : [feature.reason];
}

export function featureGroups(feature: IpFeatureReadiness): IpReadinessGroup[] {
  const groups = new Set(featureBlockedReasons(feature).map((reason) => GROUP_OF[reason]));
  return GROUP_ORDER.filter((group) => groups.has(group));
}

/** One line: how many IP features are unavailable, counted per group. */
export function readinessSummary(features: IpFeatureReadiness[], manualDocketingAvailable: boolean): string {
  const blocked = features.filter((feature) => !feature.available);
  const counts = GROUP_ORDER.map((group) => [
    group,
    blocked.filter((feature) => featureGroups(feature).includes(group)).length,
  ] as const).filter(([, count]) => count > 0);
  const lead = manualDocketingAvailable ? "Manual docketing is available. " : "";
  const noun = blocked.length === 1 ? "IP feature is" : "IP features are";
  return `${lead}${blocked.length} ${noun} unavailable: ${counts.map(([group, count]) => countPhrase(group, count)).join(", ")}.`;
}

const FEATURE_NAMES: Record<string, string> = {
  workspace_core: "IP workspace",
  manual_docketing: "Manual docketing",
  registry_sync: "Registry sync",
  deadline_automation: "Deadline automation",
  notification_automation: "Notification automation",
  filing_prepare: "Filing preparation",
  filing_confirm: "Filing confirmation",
  watch_operations: "Trademark watch",
  cost_operations: "IP costs",
  rule_governance: "Deadline rule governance",
  taxonomy_admin: "Document classification setup",
};

// What each capability lets a person do, in the words of the role editor.
const CAPABILITY_NAMES: Record<string, string> = {
  "ip:read": "view IP records",
  "ip:write": "create and edit IP records",
  "ip:registry_sync": "run registry sync",
  "ip:approve": "approve IP deadlines and notices",
  "ip:filing_prepare": "prepare filings",
  "ip:filing_confirm": "confirm filings",
  "ip:watch_manage": "manage trademark watches",
  "ip:fees_view": "view IP fees",
  "ip:rules_propose": "propose deadline rules",
  "ip:taxonomy_admin": "manage document classifications",
};

function humanize(id: string): string {
  const words = id.replace(/^ip:/, "").replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function featureName(featureId: string): string {
  return FEATURE_NAMES[featureId] ?? humanize(featureId);
}

export function capabilityName(capability: string): string {
  return CAPABILITY_NAMES[capability] ?? humanize(capability).toLowerCase();
}

export function IpAutomationReadiness({
  features,
  manualDocketingAvailable,
  canConfigure,
  onOpenConfiguration,
}: {
  features: IpFeatureReadiness[];
  manualDocketingAvailable: boolean;
  canConfigure: boolean;
  onOpenConfiguration: () => void;
}) {
  const [open, setOpen] = useState(false);
  const blocked = features.filter((feature) => !feature.available);
  if (blocked.length === 0) return null;
  const groups = new Set(blocked.flatMap(featureGroups));

  return (
    <section
      aria-labelledby="ip-automation-readiness-title"
      className="min-w-0 rounded-lg border border-[var(--color-line)] bg-[var(--color-bg-2)] px-3 py-2"
    >
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
        <h2 id="ip-automation-readiness-title" className="sr-only">IP feature readiness</h2>
        <p className="min-w-0 flex-1 break-words text-sm text-[var(--color-ink-2)]" data-testid="ip-automation-summary">
          {readinessSummary(features, manualDocketingAvailable)}
        </p>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          aria-expanded={open}
          aria-controls={open ? "ip-automation-readiness-detail" : undefined}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? <ChevronUp className="h-4 w-4" aria-hidden /> : <ChevronDown className="h-4 w-4" aria-hidden />}
          {open ? "Hide details" : "Show details"}
        </Button>
      </div>
      {open ? (
        <div id="ip-automation-readiness-detail" className="mt-2 flex min-w-0 flex-col gap-2">
          <ul className="flex min-w-0 flex-col gap-2">
            {blocked.map((feature) => (
              <li
                key={feature.feature_id}
                className="min-w-0 rounded-md border border-[var(--color-line)] bg-white p-2 text-sm"
                data-testid={`ip-automation-${feature.feature_id}`}
              >
                <div className="break-words font-semibold">{featureName(feature.feature_id)}</div>
                <ul className="mt-1 flex min-w-0 flex-col gap-1">
                  {featureBlockedReasons(feature).map((reason) => (
                    <li key={reason} className="break-words text-xs text-[var(--color-mute)]" data-reason={reason}>
                      <span className="font-semibold text-[var(--color-ink-2)]">{GROUP_TITLE[GROUP_OF[reason]]}.</span>{" "}
                      {REASON_DETAIL[reason]}
                      {reason === "missing_capability" && feature.missing_capabilities.length
                        ? ` It needs permission to ${feature.missing_capabilities.map(capabilityName).join(", ")}.`
                        : null}
                    </li>
                  ))}
                </ul>
                {feature.manual_fallback_feature_id ? (
                  <div className="mt-1 break-words text-xs text-[var(--color-mute)]">
                    Until then, use {featureName(feature.manual_fallback_feature_id).toLowerCase()}.
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
          {groups.has("configuration") && canConfigure ? (
            <div className="flex min-w-0 flex-wrap gap-2">
              <Button type="button" size="sm" variant="outline" onClick={onOpenConfiguration}>
                Open workspace configuration
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

/** Per-gate sentence for the readiness gate shown before the workspace opens. */
export function readinessReasonText(feature: IpFeatureReadiness): string {
  return featureBlockedReasons(feature)
    .map((reason) => `${GROUP_TITLE[GROUP_OF[reason]]}. ${REASON_DETAIL[reason]}`)
    .join(" ");
}
