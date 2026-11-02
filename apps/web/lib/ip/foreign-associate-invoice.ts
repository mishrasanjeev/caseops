/**
 * "Link invoice" choices for a foreign-associate instruction, built from the
 * API validator's own predicates (services/ip_foreign_associates.py,
 * _require_spend_record and _require_invoice_reconciliation) so the form
 * never offers a cost or invoice that the server will refuse (B4-ADJ-14):
 *
 * - the associate invoice must be on the record's Matter, from the
 *   instruction's associate and assignment, and carry an invoice reference;
 * - the actual cost must be active, linked to a client invoice, and match the
 *   associate invoice's amount and currency.
 *
 * A rate-confidential cost whose amount this reader cannot see is still
 * offered once linked to billing; the server compares the amount.
 */
export type LinkInvoiceCost = {
  id: string;
  cost_nature: string;
  lineage_status?: string | null;
  billing_link_type: string | null;
  billing_link_id: string | null;
  amount_minor: number | null;
  amount_withheld?: boolean | null;
  currency: string;
};

export type LinkInvoiceSpend = {
  id: string;
  matter_id: string;
  counsel_id: string;
  assignment_id: string | null;
  invoice_reference?: string | null;
  amount_minor: number;
  currency: string;
};

export function linkInvoiceChoices<C extends LinkInvoiceCost, S extends LinkInvoiceSpend>({
  costItems,
  spends,
  matterId,
  counselId,
  assignmentId,
  spendId,
}: {
  costItems: C[];
  spends: S[];
  matterId: string | null;
  counselId: string;
  assignmentId: string | null;
  spendId: string;
}) {
  const fromAssociate = matterId
    ? spends.filter((row) => row.matter_id === matterId && row.counsel_id === counselId
      && (assignmentId === null || row.assignment_id === assignmentId))
    : [];
  const eligibleSpends = fromAssociate.filter((row) => (row.invoice_reference ?? "").trim().length > 0);
  const activeActuals = costItems.filter((row) => row.cost_nature === "actual" && (row.lineage_status ?? "active") === "active");
  const billedActuals = activeActuals.filter((row) => row.billing_link_type === "invoice" && Boolean(row.billing_link_id));
  const spend = eligibleSpends.find((row) => row.id === spendId);
  const actuals = spend
    ? billedActuals.filter((row) => row.amount_withheld || row.amount_minor === null
      || (row.currency.toLowerCase() === spend.currency.toLowerCase() && row.amount_minor === spend.amount_minor))
    : billedActuals;
  return {
    spends: eligibleSpends,
    actuals,
    spendsWithoutReference: fromAssociate.length - eligibleSpends.length,
    activeActualCount: activeActuals.length,
    unbilledActualCount: activeActuals.length - billedActuals.length,
    selectedSpend: spend ?? null,
  };
}
