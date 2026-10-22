import Link from "next/link";
import { siteConfig } from "@/lib/site";

export const metadata = { title: "Demo request privacy notice", alternates: { canonical: "/demo/privacy" } };

export default function DemoPrivacyPage() {
  return <main className="mx-auto max-w-2xl px-5 py-10 text-[var(--color-ink)]">
    <h1 className="text-3xl font-semibold">Demo request privacy notice</h1>
    <p className="mt-3 text-sm text-[var(--color-mute)]">Version 2026-10-21. This notice covers public demo, pilot and pricing requests, not tenant workspace records.</p>
    <div className="mt-8 space-y-6 text-base leading-relaxed">
      <p>We save the contact details and optional notes you submit so authorized platform managers with multi-factor authentication can review and respond to your request in the protected Leads dashboard. Do not submit client names, case details, privileged material or confidential documents.</p>
      <p>Minimal first-party attribution records only the public entry point, the selected practice segment, role, request intent and this notice version. We do not collect full URLs, query strings, referrers, tracking cookies, GA4 or other client-side analytics for this journey. A click is not an accepted lead or proof of organic conversion.</p>
      <p>The request is saved before acceptance is shown. Once server-side notification is activated, only new submissions can trigger an email to the designated CaseOps enquiry recipient through SendGrid. That email contains the request reference and a protected dashboard link, not your submitted details. Historical requests are not bulk mailed. Notification failure does not delete your request. Known rejected delivery may be retried within a fixed limit; uncertain delivery is held for inspection, not automatically resent. Provider acceptance does not guarantee inbox delivery.</p>
      <p>A 90-day expiry is proposed only for new, unconverted public-demo requests; automated deletion is disabled pending policy review. Existing enrollment, account, billing and legal records are outside that proposal. You may request earlier deletion by contacting <a className="underline" href={`mailto:${siteConfig.contact.founder}`}>{siteConfig.contact.founder}</a> with your request reference. An enrollment linked to an account or retained commercial note requires separate retention review.</p>
      <p>Submitting requests a conversation. It does not activate a subscription, authorize payment, or guarantee a response time, pilot terms, provider availability or legal outcome.</p>
    </div>
    <Link className="mt-8 inline-block underline" href="/#cta">Request a conversation</Link>
  </main>;
}
