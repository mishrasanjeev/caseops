export const PUBLISHER_CONTACT = {
  name: "Orchestrum Technologies LLP",
  email: "sanjeev@orchestrum.in",
} as const;

export type PublisherEnquiry = "app" | "deletion";

// Fixed publisher enquiries only. No account, workspace, document, session or
// other user-provided value is added to the external mail application.
export function publisherEmailDraft(purpose: PublisherEnquiry): string {
  let subject: string;
  let body: string;
  if (purpose === "app") {
    subject = "CaseOps app enquiry";
    body = "I have a question about the CaseOps app.";
  } else if (purpose === "deletion") {
    subject = "CaseOps account and personal data deletion enquiry";
    body =
      "Please tell me how to request deletion of my CaseOps account and personal data, " +
      "including the identity verification process, how to contact my workspace " +
      "administrator, and which records may need to be retained.";
  } else {
    throw new Error("Unsupported publisher enquiry");
  }
  return `mailto:${PUBLISHER_CONTACT.email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}
