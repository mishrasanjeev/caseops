import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  workspace: vi.fn(),
  users: vi.fn(),
  proposeCalendar: vi.fn(),
  activateCalendar: vi.fn(),
  proposeRule: vi.fn(),
  activateRule: vi.fn(),
  impact: vi.fn(),
  transition: vi.fn(),
  policies: vi.fn(),
  selectPolicy: vi.fn(),
  withdrawCalendar: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/api/endpoints", () => ({
  fetchIpDeadlineWorkspace: mocks.workspace,
  listCompanyUsers: mocks.users,
  proposeIpWorkingCalendar: mocks.proposeCalendar,
  activateIpWorkingCalendar: mocks.activateCalendar,
  proposeIpDeadlineRule: mocks.proposeRule,
  activateIpDeadlineRule: mocks.activateRule,
  fetchIpDeadlineRuleImpact: mocks.impact,
  transitionIpDeadlineRule: mocks.transition,
  fetchIpRulePolicies: mocks.policies,
  selectIpRulePolicy: mocks.selectPolicy,
  withdrawIpWorkingCalendar: mocks.withdrawCalendar,
}));

import { IpDeadlineGovernanceCard } from "@/components/ip/IpDeadlineGovernanceCard";
import { ApiError } from "@/lib/api/config";
import type { IpDeadlineWorkspace, IpDocket } from "@/lib/api/endpoints";
import {
  availableGovernance,
  governanceDecision,
  governedRule,
  rolloutPausedGovernance,
  workingCalendar,
} from "@/test/ip-governance-fixtures";

async function sha256(text: string): Promise<string> {
  return Array.from(
    new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text))),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");
}

/** Chooses a source file through the hidden file input and waits for its digest. */
async function chooseSource(id: string, text: string, name = "source.pdf"): Promise<string> {
  const digest = await sha256(text);
  fireEvent.change(await screen.findByTestId(`${id}-file`), {
    target: { files: [new File([text], name, { type: "application/pdf" })] },
  });
  await waitFor(() => expect(document.getElementById(`${id}-result`)).toHaveTextContent(digest));
  return digest;
}
const docket = { id: "docket-1", title: "PINE LABS" } as IpDocket;

function workspace(overrides: Partial<IpDeadlineWorkspace> = {}): IpDeadlineWorkspace {
  return {
    docket_id: "docket-1",
    rules: [],
    eligible_rule_version_ids: [],
    eligible_responsible_membership_ids: [],
    calendars: [],
    deadlines: [],
    exceptions: [],
    automation_state: "explicit_confirmation_only",
    governance: availableGovernance(),
    ...overrides,
  };
}

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IpDeadlineGovernanceCard docket={docket} />
    </QueryClientProvider>,
  );
}

function described(element: HTMLElement): string {
  return (element.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .map((id) => document.getElementById(id)?.textContent ?? "")
    .join(" ");
}

describe("IpDeadlineGovernanceCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState(null, "", "/app/ip?docket=docket-1");
    mocks.users.mockResolvedValue({
      users: [
        { membership_id: "membership-ram", full_name: "Ram Gupta", email: "ram@example.com", role: "owner", membership_active: true, user_active: true },
        { membership_id: "membership-b", full_name: "Bina Reviewer", email: "bina@example.com", role: "partner", membership_active: true, user_active: true },
        { membership_id: "membership-c", full_name: "Chetan Approver", email: "chetan@example.com", role: "admin", membership_active: true, user_active: true },
      ],
    });
    mocks.policies.mockResolvedValue([]);
  });

  it("BUG-006 flag off: rule writes are read-only and say they are paused by CaseOps", async () => {
    mocks.workspace.mockResolvedValue(workspace({
      governance: rolloutPausedGovernance(),
      rules: [governedRule({ id: "rule-active", status: "active" })],
    }));
    renderCard();

    const status = await screen.findByTestId("ip-governance-status");
    expect(within(status).getByTestId("ip-governance-blocked-rule-propose")).toHaveTextContent("Paused by CaseOps");
    expect(status).toHaveTextContent("Rule publication is paused by CaseOps while governance ownership is rolled out.");
    expect(screen.queryByRole("button", { name: "Propose rule and fixture" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Emergency-disable|Retire rule|Preview impact/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Propose calendar version" })).toBeEnabled();
    expect(within(status).getByTestId("ip-governance-calendars-open")).toHaveTextContent(
      "Working calendars stay open while rule publication is paused",
    );
    expect(screen.queryByText(/membership-ram/)).not.toBeInTheDocument();
  });

  it("BUG-005/006 unentitled workspace renders no write control and names the plan", async () => {
    mocks.workspace.mockResolvedValue(workspace({
      governance: {
        calendar_proposal: governanceDecision(["missing_entitlement"], "calendar"),
        calendar_activation: governanceDecision(["missing_entitlement"], "calendar", "activate"),
        rule_proposal: governanceDecision(["rollout_disabled", "missing_entitlement"]),
        rule_activation: governanceDecision(["rollout_disabled", "missing_entitlement"], "rule", "activate"),
      },
      calendars: [workingCalendar({ id: "cal-candidate", status: "candidate", activation_blocked_reasons: ["missing_entitlement"] })],
    }));
    renderCard();

    const status = await screen.findByTestId("ip-governance-status");
    expect(status).toHaveTextContent("Not in your plan");
    expect(status).toHaveTextContent("Paused by CaseOps");
    const card = screen.getByTestId("ip-deadline-governance");
    expect(within(card).queryAllByRole("button")).toHaveLength(0);
    expect(within(card).queryAllByRole("textbox")).toHaveLength(0);
  });

  it("BUG-005 calendar form validates the source file and holidays on the field before any request", async () => {
    mocks.workspace.mockResolvedValue(workspace());
    renderCard();

    fireEvent.change(await screen.findByLabelText("Official source reference"), { target: { value: "https://ipindia.gov.in/holidays-2026" } });
    fireEvent.change(screen.getByLabelText("Holiday dates"), { target: { value: "26/01/2026, 31/02/2026" } });
    const submit = screen.getByRole("button", { name: "Propose calendar version" });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    const source = document.getElementById("calendar-source-hash") as HTMLElement;
    expect(source).toHaveTextContent("Choose source file");
    expect(described(source)).toContain("Choose the official source file so its SHA-256 can be computed.");
    expect(screen.queryByRole("textbox", { name: /sha-?256/i })).not.toBeInTheDocument();
    const holidays = screen.getByLabelText("Holiday dates");
    expect(holidays).toHaveAttribute("aria-invalid", "true");
    expect(described(holidays)).toContain("\"31/02/2026\" is not a date.");
    expect(mocks.proposeCalendar).not.toHaveBeenCalled();
  });

  it("BUG-005 a valid calendar proposal sends ISO holidays and resets the evidence fields", async () => {
    mocks.workspace.mockResolvedValue(workspace());
    mocks.proposeCalendar.mockResolvedValue(workingCalendar({ status: "candidate" }));
    renderCard();

    fireEvent.change(await screen.findByLabelText("Official source reference"), { target: { value: "gazette:2026" } });
    fireEvent.change(screen.getByLabelText("Holiday dates"), { target: { value: "26/01/2026, 2026-08-15" } });
    const digest = await chooseSource("calendar-source-hash", "Gazette holiday list 2026");
    fireEvent.click(screen.getByRole("button", { name: "Propose calendar version" }));

    await waitFor(() => expect(mocks.proposeCalendar).toHaveBeenCalledOnce());
    expect(mocks.proposeCalendar).toHaveBeenCalledWith(expect.objectContaining({
      holidays: ["2026-01-26", "2026-08-15"],
      sourceReference: "gazette:2026",
      sourceHash: digest,
    }));
    await waitFor(() => expect(document.getElementById("calendar-source-hash")).toHaveTextContent("Choose source file"));
  });

  it("BUG-005 maps a server 422 onto the source hash field", async () => {
    mocks.workspace.mockResolvedValue(workspace());
    mocks.proposeCalendar.mockRejectedValue(new ApiError(422, "Source hash: String should match pattern", {
      errors: [{ loc: ["body", "source_hash"], msg: "String should match pattern '^[0-9a-fA-F]{64}$'", type: "string_pattern_mismatch" }],
    }));
    renderCard();

    fireEvent.change(await screen.findByLabelText("Official source reference"), { target: { value: "gazette:2026" } });
    await chooseSource("calendar-source-hash", "Gazette holiday list 2026");
    fireEvent.click(screen.getByRole("button", { name: "Propose calendar version" }));

    const source = document.getElementById("calendar-source-hash") as HTMLElement;
    await waitFor(() => expect(described(source)).toContain("String should match pattern"));
  });

  it("BUG-005 computes the SHA-256 from a chosen source file in the browser", async () => {
    mocks.workspace.mockResolvedValue(workspace());
    renderCard();

    const digest = await chooseSource("calendar-source-hash", "IP India holiday list 2026", "holidays-2026.pdf");
    expect(document.getElementById("calendar-source-hash-result")).toHaveTextContent(
      `SHA-256 ${digest} from holidays-2026.pdf (26 bytes), computed in this browser; the file was not uploaded.`,
    );
  });

  it("BUG-005 the proposer of a candidate calendar sees why another approver must activate it", async () => {
    mocks.workspace.mockResolvedValue(workspace({
      calendars: [workingCalendar({
        id: "cal-own",
        status: "candidate",
        can_activate: false,
        activation_blocked_reason: "proposer_cannot_self_approve",
        activation_blocked_reasons: ["proposer_cannot_self_approve"],
      })],
    }));
    renderCard();

    const blocked = await screen.findByTestId("ip-calendar-activation-blocked-cal-own");
    expect(blocked).toHaveTextContent("You proposed this version, so another owner, admin or partner must activate it.");
    expect(screen.queryByRole("button", { name: "Independently activate calendar" })).not.toBeInTheDocument();
  });

  it("BUG-006 rule form needs an active calendar and says which candidate awaits approval", async () => {
    mocks.workspace.mockResolvedValue(workspace({
      calendars: [workingCalendar({ id: "cal-own", name: "Delhi calendar", status: "candidate" })],
    }));
    renderCard();

    const submit = await screen.findByRole("button", { name: "Propose rule and fixture" });
    expect(submit).toBeDisabled();
    expect(described(submit)).toContain("Delhi calendar v1 is awaiting activation by an approver other than the proposer.");
  });

  it("BUG-006 many pending calendars are summarised in one bounded sentence", async () => {
    mocks.workspace.mockResolvedValue(workspace({
      calendars: ["A", "B", "C", "D"].map((name, index) =>
        workingCalendar({ id: `cal-${index}`, name: `${name} calendar`, status: "candidate" })),
    }));
    renderCard();

    const submit = await screen.findByRole("button", { name: "Propose rule and fixture" });
    expect(described(submit)).toContain("A calendar v1, B calendar v1 and 2 more are awaiting activation");
    expect(described(submit)).not.toContain("D calendar");
  });

  it("BUG-005 a proposer alone in the workspace is told no other approver exists and where to add one", async () => {
    mocks.workspace.mockResolvedValue(workspace({
      calendars: [workingCalendar({
        id: "cal-solo",
        status: "candidate",
        activation_blocked_reason: "proposer_cannot_self_approve",
        activation_blocked_reasons: ["proposer_cannot_self_approve", "no_other_approver"],
        can_withdraw: true,
      })],
    }));
    renderCard();

    const blocked = await screen.findByTestId("ip-calendar-activation-blocked-cal-solo");
    expect(blocked).toHaveTextContent("No other owner, admin or partner is in this workspace");
    expect(within(blocked).getByRole("link", { name: "Open the employee directory" })).toHaveAttribute("href", "/app/admin/employees");
  });

  it("BUG-005 the proposer withdraws its own candidate calendar with a reason", async () => {
    mocks.workspace.mockResolvedValue(workspace({
      calendars: [workingCalendar({ id: "cal-own", status: "candidate", can_withdraw: true, approved_at: null })],
    }));
    mocks.withdrawCalendar.mockResolvedValue(workingCalendar({ id: "cal-own", status: "retired", approved_at: null }));
    renderCard();

    const withdraw = await screen.findByRole("button", { name: "Withdraw my proposal" });
    expect(withdraw).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Reason to withdraw your proposal"), { target: { value: "Wrong holiday list." } });
    fireEvent.click(withdraw);
    await waitFor(() => expect(mocks.withdrawCalendar).toHaveBeenCalledWith({
      calendarVersionId: "cal-own", reason: "Wrong holiday list.",
    }));
  });

  it("BUG-003/006 proposes an opposition-scoped rule with its own source evidence", async () => {
    window.history.replaceState(null, "", "/app/ip?docket=docket-1&rule_scope=opponent_notice");
    mocks.workspace.mockResolvedValue(workspace({ calendars: [workingCalendar({ id: "cal-active" })] }));
    mocks.proposeRule.mockResolvedValue(governedRule({ status: "candidate" }));
    renderCard();

    expect(await screen.findByLabelText("Applies to")).toHaveValue("opponent_notice");
    expect(described(screen.getByLabelText("Applies to"))).toContain("Starts from: Trade mark advertised in the TM Journal.");
    expect(screen.queryByLabelText(/Rule key|Trigger event kind|Calendar key/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Period (months)"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("Rule citation"), { target: { value: "Trade Marks Act 1999, s.21(1)" } });
    fireEvent.change(screen.getByLabelText("Rule source reference"), { target: { value: "act:s21" } });
    const ruleDigest = await chooseSource("rule-source-hash", "Trade Marks Act 1999 section 21");
    fireEvent.change(screen.getByLabelText("Fixture trigger date"), { target: { value: "2026-01-10" } });
    fireEvent.change(screen.getByLabelText("Expected fixture deadline"), { target: { value: "2026-05-11" } });
    fireEvent.click(screen.getByRole("button", { name: "Propose rule and fixture" }));

    await waitFor(() => expect(mocks.proposeRule).toHaveBeenCalledOnce());
    const input = mocks.proposeRule.mock.calls[0][0];
    expect(input).toEqual(expect.objectContaining({
      key: "in-tm-opponent-notice",
      triggerKind: "trademark_advertised",
      proceedingKind: "opposition",
      role: "opponent",
      stage: "notice_filing_due",
      calendarMethod: "month_anniversary",
      durationValue: 4,
      sourceReference: "act:s21",
      sourceHash: ruleDigest,
      fixtureExpectedResultOn: "2026-05-11",
    }));
    expect(input.fixtureCalculation).toEqual(expect.objectContaining({
      duration_unit: "months",
      calendar: expect.objectContaining({ calendar_version_id: "cal-active" }),
    }));
  });

  async function fillRule() {
    fireEvent.change(await screen.findByLabelText("Period (months)"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("Rule citation"), { target: { value: "Trade Marks Act 1999, s.21(1)" } });
    fireEvent.change(screen.getByLabelText("Rule source reference"), { target: { value: "act:s21" } });
    await chooseSource("rule-source-hash", "Trade Marks Act 1999 section 21");
    fireEvent.change(screen.getByLabelText("Fixture trigger date"), { target: { value: "2026-01-10" } });
    fireEvent.change(screen.getByLabelText("Expected fixture deadline"), { target: { value: "2026-05-11" } });
  }

  it("B4-ADJ-08 with several active calendars nothing is preselected and the choice is field-validated", async () => {
    window.history.replaceState(null, "", "/app/ip?docket=docket-1&rule_scope=opponent_notice");
    mocks.workspace.mockResolvedValue(workspace({
      calendars: [
        workingCalendar({ id: "cal-in", name: "IP India 2026" }),
        workingCalendar({ id: "cal-delhi", name: "Delhi registry 2026", key: "delhi-2026" }),
      ],
    }));
    mocks.proposeRule.mockResolvedValue(governedRule({ status: "candidate" }));
    renderCard();

    const calendar = await screen.findByLabelText("Fixture working calendar");
    expect(calendar).toHaveValue("");
    expect(within(calendar).getByRole("option", { name: "Choose a working calendar" })).toBeDisabled();
    await fillRule();
    fireEvent.click(screen.getByRole("button", { name: "Propose rule and fixture" }));
    await waitFor(() => expect(calendar).toHaveAttribute("aria-invalid", "true"));
    expect(described(calendar)).toContain("Choose the active working calendar the fixture is calculated on.");
    expect(mocks.proposeRule).not.toHaveBeenCalled();

    fireEvent.change(calendar, { target: { value: "cal-delhi" } });
    expect(calendar).not.toHaveAttribute("aria-invalid");
    fireEvent.click(screen.getByRole("button", { name: "Propose rule and fixture" }));
    await waitFor(() => expect(mocks.proposeRule).toHaveBeenCalledOnce());
    expect(mocks.proposeRule.mock.calls[0][0].fixtureCalculation.calendar).toEqual(
      expect.objectContaining({ calendar_version_id: "cal-delhi" }),
    );
  });

  it("B4-ADJ-08 a server refusal of the fixture calendar is anchored to the calendar field", async () => {
    window.history.replaceState(null, "", "/app/ip?docket=docket-1&rule_scope=opponent_notice");
    mocks.workspace.mockResolvedValue(workspace({ calendars: [workingCalendar({ id: "cal-active" })] }));
    mocks.proposeRule.mockRejectedValue(new ApiError(422, "Fixtures › Calculation › Calendar › Calendar version ID: Choose an active working calendar of this workspace.", {
      errors: [{
        loc: ["body", "fixtures", 0, "calculation", "calendar", "calendar_version_id"],
        msg: "Choose an active working calendar of this workspace. Propose a working calendar and have another owner, admin or partner activate it first.",
        type: "ip_rule_fixture_calendar_not_active",
      }],
    }));
    renderCard();

    const calendar = await screen.findByLabelText("Fixture working calendar");
    expect(calendar).toHaveValue("cal-active");
    await fillRule();
    fireEvent.click(screen.getByRole("button", { name: "Propose rule and fixture" }));
    await waitFor(() => expect(calendar).toHaveAttribute("aria-invalid", "true"));
    expect(described(calendar)).toContain("Choose an active working calendar of this workspace.");
  });

  it("BUG-006 the reviewer picker offers exactly the server's eligible reviewers", async () => {
    mocks.workspace.mockResolvedValue(workspace({
      rules: [governedRule({
        id: "rule-candidate",
        status: "candidate",
        can_activate: true,
        activation_blocked_reason: null,
        activation_blocked_reasons: [],
        eligible_reviewer_membership_ids: ["membership-b"],
      })],
    }));
    mocks.impact.mockResolvedValue({ rule_version_id: "rule-candidate", impact_token: "token-1", company_policy_count: 0, open_deadline_count: 0, candidate_deadline_count: 0, confirmed_deadlines_preserved: true });
    mocks.activateRule.mockResolvedValue(governedRule({ id: "rule-candidate", status: "active" }));
    renderCard();

    const reviewer = await screen.findByLabelText("Independent fixture reviewer");
    await screen.findByRole("option", { name: "Bina Reviewer — bina@example.com" });
    const offered = within(reviewer).getAllByRole("option").map((option) => option.getAttribute("value")).filter(Boolean);
    expect(offered).toEqual(["membership-b"]);
    fireEvent.change(reviewer, { target: { value: "membership-b" } });
    fireEvent.change(screen.getByLabelText("Activation note"), { target: { value: "Fixture checked against s.21." } });
    const activate = screen.getByRole("button", { name: "Run fixtures and activate rule" });
    expect(activate).toBeDisabled();
    expect(described(activate)).toContain("preview the activation impact");
    fireEvent.click(screen.getByRole("button", { name: "Preview activation impact" }));
    expect(await screen.findByText("No company selection or open deadline uses this rule yet.")).toBeVisible();
    fireEvent.click(activate);
    await waitFor(() => expect(mocks.activateRule).toHaveBeenCalledWith(expect.objectContaining({
      ruleVersionId: "rule-candidate",
      reviewerMembershipId: "membership-b",
      impactToken: "token-1",
      impactAcknowledged: false,
      supersedeOverlapping: false,
    })));
  });

  function activatableV2() {
    return workspace({
      rules: [
        governedRule({ id: "rule-v1", rule_set_id: "set-1", version: 1, status: "active" }),
        governedRule({
          id: "rule-v2",
          rule_set_id: "set-1",
          version: 2,
          status: "candidate",
          effective_from: "2026-06-01",
          can_activate: true,
          activation_blocked_reason: null,
          activation_blocked_reasons: [],
          eligible_reviewer_membership_ids: ["membership-b"],
        }),
      ],
      eligible_rule_version_ids: ["rule-v1"],
    });
  }

  async function prepareActivation() {
    const row = await screen.findByTestId("ip-rule-version-rule-v2");
    await within(row).findByRole("option", { name: "Bina Reviewer — bina@example.com" });
    fireEvent.change(within(row).getByLabelText("Independent fixture reviewer"), { target: { value: "membership-b" } });
    fireEvent.change(within(row).getByLabelText("Activation note"), { target: { value: "Mid-year amendment checked." } });
    return row;
  }

  it("BUG-006 a v2 over an active v1 shows the impact and needs explicit review and supersession", async () => {
    mocks.workspace.mockResolvedValue(activatableV2());
    mocks.impact.mockResolvedValue({
      rule_version_id: "rule-v2", impact_token: "token-v2", company_policy_count: 1, open_deadline_count: 2,
      candidate_deadline_count: 1, confirmed_deadlines_preserved: true, superseded_versions: [1],
    });
    mocks.activateRule.mockResolvedValue(governedRule({ id: "rule-v2", version: 2, status: "active" }));
    renderCard();

    const row = await prepareActivation();
    const activate = within(row).getByRole("button", { name: "Run fixtures and activate rule" });
    fireEvent.click(within(row).getByRole("button", { name: "Preview activation impact" }));
    const impact = await within(row).findByTestId("ip-rule-activation-impact-rule-v2");
    expect(impact).toHaveTextContent("Activating affects 1 company selection(s), 2 open deadline(s) and 1 unconfirmed deadline(s).");
    expect(impact).toHaveTextContent("overlap active version v1, which activation retires");
    expect(activate).toBeDisabled();
    expect(described(activate)).toContain("confirm you reviewed the impact");
    expect(described(activate)).toContain("confirm the replacement of the active version");
    fireEvent.click(within(impact).getByRole("checkbox", { name: /I reviewed this impact/ }));
    expect(activate).toBeDisabled();
    expect(mocks.activateRule).not.toHaveBeenCalled();
    fireEvent.click(within(impact).getByRole("checkbox", { name: /Retire v1 and use v2/ }));
    expect(activate).toBeEnabled();
    fireEvent.click(activate);
    await waitFor(() => expect(mocks.activateRule).toHaveBeenCalledWith(expect.objectContaining({
      ruleVersionId: "rule-v2",
      impactToken: "token-v2",
      impactAcknowledged: true,
      impactReason: "Mid-year amendment checked.",
      supersedeOverlapping: true,
    })));
  });

  it("BUG-006 a stale activation preview is cleared and must be previewed again", async () => {
    mocks.workspace.mockResolvedValue(activatableV2());
    mocks.impact.mockResolvedValue({
      rule_version_id: "rule-v2", impact_token: "token-old", company_policy_count: 1, open_deadline_count: 0,
      candidate_deadline_count: 0, confirmed_deadlines_preserved: true, superseded_versions: [1],
    });
    mocks.activateRule.mockRejectedValue(new ApiError(409, "Rule impact changed; preview again.", { detail: "Rule impact changed; preview again." }));
    renderCard();

    const row = await prepareActivation();
    fireEvent.click(within(row).getByRole("button", { name: "Preview activation impact" }));
    const impact = await within(row).findByTestId("ip-rule-activation-impact-rule-v2");
    fireEvent.click(within(impact).getByRole("checkbox", { name: /I reviewed this impact/ }));
    fireEvent.click(within(impact).getByRole("checkbox", { name: /Retire v1 and use v2/ }));
    fireEvent.click(within(row).getByRole("button", { name: "Run fixtures and activate rule" }));

    expect(await within(row).findByText(/changed after your preview. Preview the impact again, then confirm./)).toBeVisible();
    expect(within(row).queryByTestId("ip-rule-activation-impact-rule-v2")).not.toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Run fixtures and activate rule" })).toBeDisabled();
    expect(within(row).getByRole("button", { name: "Preview activation impact" })).toBeEnabled();
    expect(mocks.activateRule).toHaveBeenCalledOnce();
  });

  it("BUG-006 the proposer's candidate rule shows the self-approval reason and no activate control", async () => {
    mocks.workspace.mockResolvedValue(workspace({
      rules: [governedRule({
        id: "rule-own",
        status: "candidate",
        activation_blocked_reason: "proposer_cannot_self_approve",
        activation_blocked_reasons: ["proposer_cannot_self_approve"],
      })],
    }));
    renderCard();

    expect(await screen.findByTestId("ip-rule-activation-blocked-rule-own")).toHaveTextContent(
      "You proposed this version, so another owner, admin or partner must activate it.",
    );
    expect(screen.queryByRole("button", { name: "Run fixtures and activate rule" })).not.toBeInTheDocument();
  });

  it("BUG-006 company selection is a compare-and-swap with a reload prompt on conflict", async () => {
    mocks.workspace.mockResolvedValue(workspace({
      rules: [governedRule({ id: "rule-v2", rule_set_id: "set-1", version: 2, status: "active" })],
    }));
    mocks.policies.mockResolvedValue([{
      id: "policy-1", rule_set_id: "set-1", rule_set_key: "in-tm-opponent-notice", rule_kind: "deadline",
      active_rule_version_id: "rule-v1", active_rule_version: 1, active_rule_status: "disabled",
      auto_confirm_eligible: false, auto_confirm_suspended_reason: null, internal_target_policy: {},
      version: 3, updater_label_snapshot: "Chetan Approver", updated_at: "2026-10-31T00:00:00Z",
    }]);
    mocks.selectPolicy.mockRejectedValue(new ApiError(409, "Company policy no longer matches; reload it and retry.", {
      code: "ip_rule_policy_version_conflict", expected_policy_version: 3, current_policy_version: 4,
    }));
    renderCard();

    fireEvent.click(await screen.findByRole("button", { name: "Select v2 for company deadlines" }));
    await waitFor(() => expect(mocks.selectPolicy).toHaveBeenCalledWith({
      ruleVersionId: "rule-v2", expectedPolicyVersion: 3, autoConfirmEligible: false,
    }));
    expect(await screen.findByText(/Someone changed the company selection after you loaded it/)).toBeVisible();
    const policiesCalls = mocks.policies.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Reload company selection" }));
    await waitFor(() => expect(mocks.policies.mock.calls.length).toBeGreaterThan(policiesCalls));
  });

  it("BUG-006 emergency disable asks to preview again when recipients changed", async () => {
    mocks.workspace.mockResolvedValue(workspace({
      rules: [governedRule({ id: "rule-active", status: "active" })],
      eligible_rule_version_ids: ["rule-active"],
    }));
    mocks.impact.mockResolvedValue({ rule_version_id: "rule-active", impact_token: "token-2", company_policy_count: 1, open_deadline_count: 2, candidate_deadline_count: 1, confirmed_deadlines_preserved: true });
    mocks.transition.mockRejectedValue(new ApiError(409, "Alert recipients changed; preview again.", { code: "ip_rule_transition_recipients_changed" }));
    renderCard();

    const disable = await screen.findByRole("button", { name: "Emergency-disable rule" });
    expect(disable).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Reason to disable or retire"), { target: { value: "Statute amended today." } });
    fireEvent.click(screen.getByRole("button", { name: "Preview impact" }));
    expect(await screen.findByText(/1 company selection\(s\), 2 open deadline\(s\), 1 unconfirmed deadline\(s\)/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Emergency-disable rule" }));
    await waitFor(() => expect(mocks.transition).toHaveBeenCalledWith(expect.objectContaining({ impactToken: "token-2", emergencyDisable: true })));
    expect(await screen.findByText(/Preview the impact again, then confirm./)).toBeVisible();
    expect(screen.getByRole("button", { name: "Emergency-disable rule" })).toBeDisabled();
  });
});
