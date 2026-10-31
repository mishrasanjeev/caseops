import type {
  IpDeadlineGovernanceProjection,
  IpDeadlineRuleVersion,
  IpGovernanceActionDecision,
  IpGovernanceBlockReason,
  IpWorkingCalendarVersion,
} from "@/lib/api/endpoints";

/** One projection decision, shaped exactly like the server's IpGovernanceActionDecision. */
export function governanceDecision(
  reasons: IpGovernanceBlockReason[] = [],
  subject: "calendar" | "rule" = "rule",
  action: "propose" | "activate" = "propose",
): IpGovernanceActionDecision {
  return {
    available: reasons.length === 0,
    code: reasons[0] ?? "available",
    reasons,
    required_capability: action === "propose" ? "ip:rules_propose" : "ip:rules_activate",
    entitlement_key: "ip_rule_governance",
    rollout_flag: subject === "rule" ? "ip_rule_governance_enabled" : null,
  };
}

/** Every governance action available (flag on, entitled, capable viewer). */
export function availableGovernance(): IpDeadlineGovernanceProjection {
  return {
    calendar_proposal: governanceDecision([], "calendar", "propose"),
    calendar_activation: governanceDecision([], "calendar", "activate"),
    rule_proposal: governanceDecision([], "rule", "propose"),
    rule_activation: governanceDecision([], "rule", "activate"),
  };
}

/** Production before A2: rule writes paused by the rollout fence; calendars still open. */
export function rolloutPausedGovernance(): IpDeadlineGovernanceProjection {
  return {
    ...availableGovernance(),
    rule_proposal: governanceDecision(["rollout_disabled"], "rule", "propose"),
    rule_activation: governanceDecision(["rollout_disabled"], "rule", "activate"),
  };
}

export function governedRule(overrides: Partial<IpDeadlineRuleVersion> = {}): IpDeadlineRuleVersion {
  return {
    id: "rule-1",
    rule_set_id: "rule-set-1",
    key: "in-tm-opponent-notice",
    rule_kind: "deadline",
    jurisdiction: "IN",
    office: "IP India",
    right_kind: "trademark",
    proceeding_kind: "opposition",
    role: "opponent",
    stage: "notice_filing_due",
    version: 1,
    status: "active",
    source_record_id: "source-1",
    source_hash: "a".repeat(64),
    source_reference: "Trade Marks Act 1999",
    effective_from: "2026-01-01",
    effective_until: null,
    engine_compatibility: "caseops-ip-deadline-v1",
    definition: { rule_citation: "Trade Marks Act 1999, s.21(1)" },
    fixtures: [],
    proposer_label_snapshot: "Ram Gupta",
    reviewer_label_snapshot: null,
    legal_approver_label_snapshot: null,
    fixtures_passed_at: null,
    activated_at: null,
    disabled_at: null,
    created_at: "2026-10-31T00:00:00Z",
    proposed_by_membership_id: "membership-ram",
    can_activate: false,
    activation_blocked_reason: "not_candidate",
    activation_blocked_reasons: ["not_candidate"],
    eligible_reviewer_membership_ids: [],
    ...overrides,
  };
}

export function workingCalendar(overrides: Partial<IpWorkingCalendarVersion> = {}): IpWorkingCalendarVersion {
  return {
    id: "calendar-1",
    calendar_id: "calendar-root-1",
    key: "ip-india-working-calendar",
    name: "IP India working calendar",
    jurisdiction: "IN",
    office: "IP India",
    version: 1,
    status: "active",
    timezone: "Asia/Kolkata",
    weekend_days: [5, 6],
    holidays: [],
    exceptional_working_days: [],
    source_priority: ["official_source"],
    source_reference: "Gazette notification",
    source_hash: "b".repeat(64),
    effective_from: "2026-01-01",
    effective_until: null,
    proposer_label_snapshot: "Ram Gupta",
    approver_label_snapshot: "Asha Partner",
    approved_at: "2026-10-31T00:00:00Z",
    created_at: "2026-10-31T00:00:00Z",
    proposed_by_membership_id: "membership-ram",
    can_activate: false,
    activation_blocked_reason: "not_candidate",
    activation_blocked_reasons: ["not_candidate"],
    ...overrides,
  };
}
