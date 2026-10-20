# Platform Reports Administration

This guide describes the October 20 reports-console contract. Consult the
release evidence for deployed availability; this document alone is not a
production acceptance certificate.

## First-Time Setup

1. Open the CaseOps reports setup email sent to your invited address. The
   initial report manager is `sanjeev@orchestrum.in`.
2. Open its one-use link. For a new CaseOps identity, choose a strong password
   and enter your name. If you already have a CaseOps identity under that exact
   email address, use its current password; accepting an invitation does not
   replace an existing password or create access to a customer workspace.
3. Complete multi-factor enrollment on the Security page. Add the displayed
   setup key to your authenticator, then enter its current code.
4. Save the recovery codes securely when they are displayed. Do not email them
   to support or put them in a shared workbook. Each recovery code is single-use.
5. Open [Platform Reports](https://caseops.ai/platform/reports).

The setup link expires after 30 minutes. For a lost or expired pending setup
link, open [Platform Sign In](https://caseops.ai/platform/sign-in), expand
**Resend setup email**, and submit the invited address. A cooldown limits
repeated sends. Use the newest link; a reissue invalidates the older one.
The generic response does not reveal whether an address has an invitation.

## Daily Sign In

1. Open [Platform Sign In](https://caseops.ai/platform/sign-in).
2. Enter your invited email and CaseOps password. No customer tenant slug is
   required for this console.
3. Complete MFA and open Reports. A password without MFA cannot view
   cross-account information.
4. Use the console's sign-out action when finished, especially on shared PCs.

The reports session is separate from the normal customer workspace and the
client portal. It does not grant founder billing changes, tenant impersonation,
client-document access or the ability to invoke paid providers.

## Account Activity

- The console includes all registered accounts, including internal/QA accounts.
  Filter by name and by law firm, corporate legal, solo lawyer or other category.
  An unrecognized persisted category remains visible under Other.
- The period selector changes Day, Week, Month and All recorded metrics. Day,
  Week and Month are the last completed calendar periods in Asia/Kolkata, not
  a moving interval. The report displays their exact dates.
- Engagement classification separately covers the rolling 30 elapsed days
  ending at the displayed generation time. Today's recorded human activity
  counts; account enabled/disabled status is a different field.
- Accounts with known old activity appear in the closed, count-labelled
  **No recorded activity for 30 days** group. Expand it to inspect them.
  Collapsing never removes an account from report totals.
- Missing or inconclusive history is shown as unknown and remains expanded.
  Failed/denied actions and known unattended background operations do not
  establish human engagement. This is recorded activity, not proof that every
  real-world action was observed.
- Expand an account's details for period activity and current workload totals.
  Category totals remain available independently of the displayed account page.
  Currency values are labelled INR; recorded financial data is not a complete
  provider invoice or proof of reconciled revenue/cost.

## Other Reports

Use the report tabs for Overview, Usage, Profit, Account profitability and
Revenue. Pagination loads bounded result pages. Empty recorded usage, payment
or rollup data is not evidence that no external spending or billing occurred.
An error or an unverifiable response is not displayed as a successful empty
report.

Configured monthly and annual run rates use eligible subscriptions' selected
billing intervals. Eligible trial and manually active subscriptions can be
included; these rates are not collected payments or reconciled revenue.
Use Revenue for recorded paid receipts and the rollup fields for separately
recorded financial evidence.

## Invite Or Revoke Panel Users

Only the report manager can manage panel users.

1. Open [Administrators](https://caseops.ai/platform/admins).
2. Enter the person's name and exact email address and submit the invitation.
3. The invitee follows their own setup link, proves or sets their credential,
   and completes their own report-console MFA.
4. The invitee receives viewer access to reports across accounts, not manager
   privileges or customer workspace membership.
5. To remove a viewer, use Revoke and enter a meaningful reason. Revocation
   invalidates their report access and outstanding links; it does not delete
   their unrelated CaseOps tenant memberships or historical audit evidence.

Fresh MFA is required for manager changes. Delivery **accepted** means that
the mail provider accepted the request, not that it reached an inbox. For an
unknown outcome, inspect the current directory state before making another
explicit request; the application does not automatically retry the send.
Repeating the same pending invitation does not send another email. The invitee
can use **Resend setup email** for a replacement link. An invitation cannot
restore a revoked viewer's access.

## Reset A Password

1. Open [Password Reset](https://caseops.ai/platform/reset-password).
2. Submit your invited, activated account email.
3. Follow the latest one-use reset link and choose a password meeting the
   displayed policy. Sign in again and complete MFA.

Password reset does not bypass MFA. For an email identity also used in ordinary
CaseOps workspaces, its password is shared by that identity: changing it ends
old sessions there as well as in this console. A lost pending setup link needs
**Resend setup email**, not password reset. If both your authenticator and all
recovery codes are lost, do not expect password reset to remove the factor;
contact the platform operator for reviewed recovery.

## Scheduled Email

The configured daily Account Activity Dashboard is intended for **07:30 AM
Asia/Kolkata** and the four owner-approved recipients. Actual scheduler/image
configuration and delivery must be confirmed in the release evidence.

The scheduled email retains its existing exclusion of account names containing
`smoke`, `csrf`, `test`, `debug` or `e2e`; the authenticated console's all-account
scope does not. Therefore their account totals can legitimately differ.
Both use the same category, metric and engagement definitions. Plain text
retains dormant accounts even where an email client cannot collapse the HTML
group. No universal Gmail/Outlook collapse support or inbox delivery is promised.
