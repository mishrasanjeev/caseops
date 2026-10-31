/**
 * Every reason an opposition "Propose deadline" button is disabled, in the one
 * element the button is described by. Readiness gaps come from the server's
 * own proposer predicate (the workflow's `deadline_proposal_gaps`, or the
 * workspace's `readiness_gaps` where the proposer refuses on all of them).
 */

const READINESS_LABELS: Record<string, string> = {
  linked_application_required: "Link the opposed application.",
  confirmed_application_identifier_required: "Confirm the application number.",
  confirmed_opposition_identifier_required: "Record the opposition number.",
  applicant_party_required: "Add the applicant party.",
  opponent_party_required: "Add the opponent party.",
  opposition_profile_required: "Confirm the opposition profile.",
  applicable_rule_version_required: "Enter the applicable rules version.",
  forum_required: "Enter the forum.",
  source_notice_required: "Add the source notice reference or document.",
  grounds_required: "Add at least one ground of opposition.",
  challenged_scope_required: "Add the challenged goods and services.",
  service_fact_required: "Record how and when the notice was served.",
  confirmed_client_instruction_required: "Confirm the client's instruction.",
  limitation_date_required: "Enter the limitation date.",
  relied_on_right_required: "Add at least one relied-on earlier right.",
};

export function oppositionReadinessLabel(gap: string): string {
  return READINESS_LABELS[gap] ?? `${gap.replaceAll("_", " ")}.`;
}

export function IpDeadlineProposalBlockers({
  id,
  gaps,
  missing,
}: {
  id: string;
  gaps: string[];
  /** Other unmet conditions, each a complete sentence naming the fix. */
  missing: string[];
}) {
  if (!gaps.length && !missing.length) return null;
  return (
    <div
      id={id}
      className="col-span-full min-w-0 rounded-md border border-[var(--color-warn-border)] bg-[var(--color-warn-bg)] p-3 text-sm text-[var(--color-warn-text)]"
      data-testid={id}
    >
      {gaps.length ? (
        <div className="min-w-0">
          <strong>Complete the opposition workspace before proposing this deadline.</strong>
          <ul className="mt-1 flex min-w-0 list-disc flex-col gap-0.5 pl-5">
            {gaps.map((gap) => <li key={gap} data-gap={gap} className="break-words">{oppositionReadinessLabel(gap)}</li>)}
          </ul>
          <a className="mt-1 inline-block font-medium underline underline-offset-2" href="#ip-opposition-workspace">
            Open the opposition workspace
          </a>
        </div>
      ) : null}
      {missing.map((sentence) => <p key={sentence} className="mt-1 min-w-0 break-words">{sentence}</p>)}
    </div>
  );
}
