import type { UseQueryResult } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { IpGovernedDeadlinePickers, resolveGovernedSelection } from "@/components/ip/IpGovernedDeadlinePickers";
import type { IpDeadlineWorkspace } from "@/lib/api/endpoints";
import { availableGovernance, governedRule, workingCalendar } from "@/test/ip-governance-fixtures";

const scope = { proceedingKind: "opposition", role: "opponent", stage: "notice_filing_due" };

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

const ruleIn = governedRule({ id: "rule-in", jurisdiction: "IN" });
const ruleGb = governedRule({ id: "rule-gb", rule_set_id: "set-gb", key: "gb-tm-opponent-notice", jurisdiction: "GB", office: "UK IPO" });
const calendarIn = workingCalendar({ id: "cal-in", name: "IP India 2026" });
const calendarGb = workingCalendar({ id: "cal-gb", name: "UK IPO 2026", key: "uk-ipo", jurisdiction: "GB", office: "UK IPO", timezone: "Europe/London" });

function renderPickers(data: IpDeadlineWorkspace, jurisdiction: string) {
  const selection = resolveGovernedSelection(data, scope, "", "", jurisdiction);
  const query = { data, isPending: false, isError: false, isSuccess: true, error: null, refetch: () => undefined } as unknown as UseQueryResult<IpDeadlineWorkspace>;
  render(
    <IpGovernedDeadlinePickers
      docketId="docket-1"
      idPrefix="opponent-deadline"
      scope={scope}
      workspace={query}
      selection={selection}
      onRuleChange={() => undefined}
      onCalendarChange={() => undefined}
    />,
  );
  return selection;
}

describe("IpGovernedDeadlinePickers jurisdiction (B4-ADJ-08)", () => {
  it("offers only rules of the proceeding's jurisdiction and calendars of the chosen rule's", () => {
    const data = workspace({
      rules: [ruleIn, ruleGb],
      eligible_rule_version_ids: ["rule-in", "rule-gb"],
      calendars: [calendarGb, calendarIn],
    });
    const selection = renderPickers(data, " in ");
    expect(selection.rules.map((row) => row.id)).toEqual(["rule-in"]);
    expect(selection.rule?.id).toBe("rule-in");
    expect(selection.calendars.map((row) => row.id)).toEqual(["cal-in"]);
    expect(selection.calendar?.id).toBe("cal-in");
    const calendar = screen.getByLabelText("Working calendar");
    expect(within(calendar).getAllByRole("option").map((option) => option.getAttribute("value"))).toEqual(["cal-in"]);
  });

  it("names the other-jurisdiction rule and calendar instead of offering them", () => {
    const data = workspace({
      rules: [ruleGb],
      eligible_rule_version_ids: ["rule-gb"],
      calendars: [calendarGb],
    });
    const selection = renderPickers(data, "IN");
    expect(selection.rule).toBeUndefined();
    expect(selection.calendar).toBeUndefined();
    const rule = screen.getByLabelText("Governed rule");
    const calendar = screen.getByLabelText("Working calendar");
    expect(rule).toBeDisabled();
    expect(calendar).toBeDisabled();
    expect(within(calendar).getByRole("option", { name: "No active IN working calendar" })).toBeInTheDocument();
    expect(screen.getByText(/applies in another jurisdiction than this proceeding \(IN\)/)).toHaveTextContent(
      "(GB) applies in another jurisdiction than this proceeding (IN). Propose one for IN in Rule and calendar governance",
    );
    expect(screen.getByText(/No active IN working calendar exists/)).toHaveTextContent(
      "No active IN working calendar exists; active calendars exist only for GB.",
    );
    expect(screen.getByRole("link", { name: "Open rule and calendar governance" })).toBeInTheDocument();
  });
});
