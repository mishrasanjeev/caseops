import { describe, expect, it } from "vitest";

import { linkInvoiceChoices } from "./foreign-associate-invoice";

const cost = (id: string, changes: Record<string, unknown> = {}) => ({
  id, cost_nature: "actual", lineage_status: "active", billing_link_type: "invoice", billing_link_id: `inv-${id}`,
  amount_minor: 50000, amount_withheld: false, currency: "GBP", ...changes,
});
const spend = (id: string, changes: Record<string, unknown> = {}) => ({
  id, matter_id: "matter-1", counsel_id: "counsel-1", assignment_id: "assignment-1",
  invoice_reference: `INV-${id}`, amount_minor: 50000, currency: "GBP", ...changes,
});

describe("linkInvoiceChoices (B4-ADJ-14)", () => {
  const costItems = [
    cost("billed"),
    cost("unbilled", { billing_link_type: null, billing_link_id: null }),
    cost("line-item", { billing_link_type: "invoice_line_item" }),
    cost("voided", { lineage_status: "voided" }),
    cost("estimate", { cost_nature: "estimate" }),
    cost("other-amount", { amount_minor: 1 }),
    cost("withheld", { amount_minor: null, amount_withheld: true }),
  ];
  const spends = [
    spend("ok"),
    spend("no-reference", { invoice_reference: "  " }),
    spend("other-assignment", { assignment_id: "assignment-2" }),
    spend("other-matter", { matter_id: "matter-2" }),
    spend("other-counsel", { counsel_id: "counsel-2" }),
  ];

  it("offers only what the link_invoice validator accepts", () => {
    const choices = linkInvoiceChoices({ costItems, spends, matterId: "matter-1", counselId: "counsel-1", assignmentId: "assignment-1", spendId: "" });
    expect(choices.spends.map((row) => row.id)).toEqual(["ok"]);
    expect(choices.spendsWithoutReference).toBe(1);
    expect(choices.actuals.map((row) => row.id)).toEqual(["billed", "other-amount", "withheld"]);
    expect(choices.unbilledActualCount).toBe(2);
    expect(choices.activeActualCount).toBe(5);
  });

  it("narrows actual costs to the chosen invoice's amount and currency", () => {
    const choices = linkInvoiceChoices({ costItems, spends, matterId: "matter-1", counselId: "counsel-1", assignmentId: "assignment-1", spendId: "ok" });
    expect(choices.selectedSpend?.id).toBe("ok");
    expect(choices.actuals.map((row) => row.id)).toEqual(["billed", "withheld"]);
    const inr = linkInvoiceChoices({ costItems, spends: [spend("ok", { currency: "INR" })], matterId: "matter-1", counselId: "counsel-1", assignmentId: null, spendId: "ok" });
    expect(inr.actuals.map((row) => row.id)).toEqual(["withheld"]);
  });

  it("offers no invoice for a Matterless record", () => {
    const choices = linkInvoiceChoices({ costItems, spends, matterId: null, counselId: "counsel-1", assignmentId: null, spendId: "" });
    expect(choices.spends).toEqual([]);
  });
});
