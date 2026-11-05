# BUG-015: recognise the browser's effective disabled state

Verdict: **Inconclusive for the complete reported production workflow.** The
isolated control-auditor regression passes; the complete original production
control crawl still needs a replacement run after publication.

The canonical production run on `bdd1480699222712475372690334659088629429`
failed the specialist-page control crawl. Privacy-preserving diagnostic run
`41746670644` observed one select with its own `disabled` property false, an
ancestor disabled fieldset, effective disabled state true and no real options.
That is a concrete auditor false positive. It does not establish an additional
product defect in an intentionally disabled control, or clear every original
BUG-015 concern.

The shared select auditor and internal-field label auditor now use
`:disabled`, which follows fieldset inheritance and the first-legend exception.
Options in disabled option groups are excluded using the same browser state.
The original page assertions and deadlines remain intact.

`tests/e2e/control-crawl-contract.spec.ts` checks independent literal results
for inherited and direct disabling, first-legend exceptions, disabled option
groups, mixed options, visibility and scoped/default audits. A real isolated
Chromium run fails with the original predicates and passes with the repaired
predicates. The original setup refusal and failing baseline are retained in
the primary chat's `outputs/mac-release-closure-20261103` evidence.

The new case is admitted only to `app-chromium`. Python and frontend source
contracts independently require its exact file and full title. Their complete
canonical inventory is 714 desktop plus 53 mobile cases; the original 21
capability/provider skips remain unchanged. These counts describe collection,
not completed browser acceptance. Same-count replacement of the required case
must be rejected.

Before closure, run the complete original production control-crawl file and
the complete required release inventory against the deployed candidate. This
test-only repair must not be represented as a new product capability.
