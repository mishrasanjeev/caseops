# Workspace conduct gate for the first native store release

Status: policy wording and publisher contact approved; product behavior pending.
Scope: J04/J14/J15/J20, M03/M14/M22, US-MOB-04/08, MOB-22/23/39.
Do not complete store review declarations from this document alone.

Google Play's [User Generated Content policy](https://support.google.com/googleplay/android-developer/answer/9876937)
includes content shared with a verified subset of users. CaseOps notes and
attachments can be visible to other authorized workspace members. Apple's
[App Review Guideline 1.2](https://developer.apple.com/app-store/review/guidelines/#user-generated-content)
also requires an appropriate method to filter objectionable material, report
content, handle abusive users, and contact the publisher. These requirements
do not authorize copying confidential legal material into support systems.

## Approved workspace use rules, version 2026-11-08

Publisher: Orchestrum Technologies LLP. These rules supplement the agreement
that applies to your CaseOps workspace and the CaseOps Privacy Policy.

CaseOps is for authorized legal work. Keep material in the correct workspace
and matter. Share records only with people authorized to see them. Make sure
you have authority to add any material, particularly if it concerns clients,
witnesses or other third parties.

Do not use CaseOps to harass, threaten or exploit anyone; impersonate another
person; distribute unlawful material or nonconsensual intimate material;
solicit illegal activity; or send spam, malware or fraudulent content. Do not
bypass access controls or disclose confidential records without authority.

Legal work can involve sensitive or disturbing evidence. Keep such material
in a restricted matter only when you have authority and a legitimate work
purpose. Do not share it outside its authorized context or use it to harass
anyone.

If you encounter misuse, use Report a concern in CaseOps. Identify the
relevant workspace and item or user through the app; do not include
passwords, client documents or substantive matter details in the report. You
can also contact sanjeev@orchestrum.in if you cannot access CaseOps.

Orchestrum Technologies LLP and the appropriate workspace administrator can
investigate reports using the minimum information necessary. They may
restrict access, hide or remove material, or suspend a user where appropriate.
Lawful retention duties, legal holds and professional confidentiality
continue to apply. CaseOps will handle reports under its Privacy Policy.

## Required behavior and proof

- MOB-39-CONDUCT-01: present the current rules before the native app creates a
  note or uploads an attachment. Persist one authoritative acceptance per
  actor and current version. No acceptance fails closed on the actual native
  write. Decline keeps authorized read and report access.
- MOB-39-CONDUCT-02: existing web writes and records remain governed by their
  own reviewed contract; an old native build cannot bypass the native server
  fence. Verify the realm from authenticated context, preserve exact lifecycle
  locks, avoid another request around the write, and verify scanner rejection.
- MOB-39-CONDUCT-03: report a note, file, or user in the app. Recheck current
  tenant membership and authorized target scope on the server. Do not
  duplicate note content, file bytes, personal contact data or credentials.
  Acknowledgement means received. Duplicate input needs an exact idempotency
  contract and no duplicate delivery.
- MOB-39-CONDUCT-04: a designated reviewer can see a bounded receipt and take
  authorized action without gaining access to the underlying legal content.
  Preserve ethical walls, legal holds, retention, and an audit trail. Reports
  against an administrator must have a publisher escalation path with no
  exposure to the reported user.
- MOB-39-CONDUCT-05: prove inaccessible targets and foreign memberships fail
  without disclosing existence. Prove current actors, target authors, and
  operator permissions independently. Keep request data out of notification
  payloads and never use paid transports in automated verification.
- MOB-39-CONDUCT-06: exercise the positive and negative journeys on actual
  Android and iOS builds against the deployed candidate, with no customer
  records. Publish the approved wording and update the Play rating and data
  disclosures only when the behavior is available and verified.
