export type PrivacyPolicySection = {
  readonly id: string;
  readonly title: string;
  readonly paragraphs: readonly string[];
  readonly bullets: readonly string[];
};

export type PrivacyPolicyDocument = {
  readonly version: string;
  readonly effectiveDate: string;
  readonly title: string;
  readonly operator: string;
  readonly product: string;
  readonly contactEmail: string;
  readonly canonicalUrl: string;
  readonly intro: string;
  readonly summary: readonly string[];
  readonly sections: readonly PrivacyPolicySection[];
};

export const privacyPolicy = {
  "version": "2026-11-03",
  "effectiveDate": "3 November 2026",
  "title": "Privacy policy",
  "operator": "Orchestrum Technologies LLP",
  "product": "CaseOps",
  "contactEmail": "sanjeev@orchestrum.in",
  "canonicalUrl": "https://caseops.ai/privacy",
  "intro": "This policy explains how Orchestrum Technologies LLP handles personal data when you use the CaseOps website, Android and iOS apps, and related services.",
  "summary": [
    "We do not sell personal data or use it for targeted advertising.",
    "Private customer content is not used to train shared AI models without explicit opt-in.",
    "You can contact sanjeev@orchestrum.in about privacy, your data or account deletion."
  ],
  "sections": [
    {
      "id": "scope",
      "title": "1. Who this policy covers",
      "paragraphs": [
        "CaseOps supports law firms, companies and legal professionals. This policy covers account holders, people who contact us and people whose information is included in a customer workspace.",
        "For legal records in a firm or company workspace, that organisation usually decides why the information is used, who may access it and what must be retained. We process those records to provide the service under the organisation’s instructions. We also handle information for our own account administration, security, billing and support."
      ],
      "bullets": []
    },
    {
      "id": "information",
      "title": "2. Information we handle",
      "paragraphs": [
        "The information depends on the features you use and what you or your organisation provide."
      ],
      "bullets": [
        "Account and contact information: name, work email, phone number, organisation, role, workspace membership and information needed to sign in and secure your account.",
        "Legal workspace information: client and party details, matters, documents, messages, notes, contracts, hearings, deadlines and billing records. These records may contain sensitive information about clients and other people.",
        "Files and optional device features: files, photos or camera images you choose to provide, with related file information. Device permissions depend on the feature and the app version.",
        "Technical and security information: IP address, browser or device type, operating system, app version, session information, access times, error reports and audit records.",
        "Billing and support information: invoice details, business or tax information you provide, payment references or status, enquiries and support communications.",
        "Connected-service information: the account details, access credentials and selected calendar, email or document information needed for an integration you authorise."
      ]
    },
    {
      "id": "use",
      "title": "3. Why we use information",
      "paragraphs": [],
      "bullets": [
        "Provide and maintain your account, workspace and requested features.",
        "Process legal records, search, document extraction, drafting or other workflows you or your organisation choose.",
        "Manage access, prevent misuse, investigate errors and protect accounts and customer records.",
        "Respond to enquiries, provide service messages, administer billing and meet applicable legal obligations."
      ]
    },
    {
      "id": "sharing",
      "title": "4. Who may receive information",
      "paragraphs": [
        "Information is available to people your organisation authorises, subject to the workspace and record-level access controls.",
        "We use service providers for hosting, storage, AI and search processing, communications, payments and support. Depending on the enabled feature, these may include Google Cloud, OpenAI, Voyage AI and SendGrid. A connected service or payment provider may also receive information when you use its integration. Relevant information is shared to perform that function.",
        "Service providers processing personal data for us must use it for the agreed service and protect it with at least the same level of protection described in this policy and required by applicable law.",
        "We may disclose information when required by law, to protect rights or security, or as part of a business transfer with appropriate protections and notice where required.",
        "We do not sell personal data or use it for targeted advertising."
      ],
      "bullets": []
    },
    {
      "id": "ai",
      "title": "5. AI-assisted features",
      "paragraphs": [
        "If you use an AI-assisted feature, relevant prompts, selected documents or other workspace content may be processed by an AI or search service provider to produce the requested result.",
        "Private customer content is not used to train shared AI models without explicit opt-in. This does not mean that a provider never temporarily stores information to deliver a service or meet its security and legal obligations.",
        "Before a CaseOps app feature shares personal data with a third-party AI service, our policy is to explain what information will be shared, with whom and for what purpose, and obtain your explicit permission. You can decline that optional processing. This permission is separate from any opt-in to training shared AI models; this privacy policy does not itself provide either permission."
      ],
      "bullets": []
    },
    {
      "id": "devices",
      "title": "6. Device permissions, storage and connections",
      "paragraphs": [
        "Optional features may ask for permission to use the camera, select files or photos, show notifications or use a device security feature. You can manage permissions in your device settings. Refusing an optional permission may prevent that feature from working.",
        "Cookies and similar storage support sign-in, security and preferences. Apps may use protected device storage for session credentials and temporary files. A file you export, download or share may remain on your device or in the app you selected.",
        "When you connect an external account, the permissions you authorise determine the information available to that integration. You can revoke access through the connected service or available CaseOps controls. Disconnecting does not by itself delete records already imported or copies already shared."
      ],
      "bullets": []
    },
    {
      "id": "security",
      "title": "7. Security and international processing",
      "paragraphs": [
        "We use measures such as HTTPS connections, account authentication, workspace access controls and audit records to protect personal data. Access is limited according to the service, role and record permissions.",
        "Information may be processed in India and other countries where our service providers operate. A particular enterprise agreement may provide additional requirements for the services it covers. We do not represent that every processing activity occurs only in India."
      ],
      "bullets": []
    },
    {
      "id": "retention",
      "title": "8. How long information is kept",
      "paragraphs": [
        "We retain information for the purposes described in this policy, taking account of the service, customer instructions and applicable legal requirements."
      ],
      "bullets": [
        "Account and workspace information is kept while needed to provide and administer the service.",
        "Legal records may need to be retained under an organisation’s lawful instructions, professional duties or a legal hold.",
        "Billing, security, fraud-prevention and audit records may be retained where needed for those purposes or required by law.",
        "When retention is no longer needed, we delete or de-identify the information, subject to applicable retention requirements. Backup copies may remain until they expire under the applicable backup cycle. Contact us for the retention and deletion position for your account or records."
      ]
    },
    {
      "id": "account-deletion",
      "title": "9. Your choices and account deletion",
      "paragraphs": [
        "To request deletion of your CaseOps account and associated personal data, email sanjeev@orchestrum.in with the subject “CaseOps account deletion”. Include the email address associated with your account. Do not send a password, security code or confidential legal documents.",
        "Where available in your app version, you can also use Account → Privacy and help → Request account deletion. A request receipt confirms that the request was received; it does not mean deletion has been completed.",
        "We will review the request, use proportionate steps to verify your identity and explain the outcome. Some information may need to be retained for the specific legal, billing, security or lawful workspace-record reasons described above; we will explain relevant exceptions. Signing out, uninstalling the app or disabling access is not account deletion.",
        "Depending on applicable law, you may also request access, a copy, correction or deletion of your personal data, or withdraw consent for relevant processing. For records managed by a law firm or employer, you may contact that organisation or ask us to help direct the request. You can contact us about your own account without needing to send client files or obtain a workspace administrator’s permission."
      ],
      "bullets": []
    },
    {
      "id": "children",
      "title": "10. Children’s information",
      "paragraphs": [
        "CaseOps is a professional service and is not directed at children. Legal records supplied by professional users may contain information about children. Such information should only be provided with the appropriate authority and for the relevant professional purpose. Contact us if you believe a child has provided personal data through an account or enquiry."
      ],
      "bullets": []
    },
    {
      "id": "changes",
      "title": "11. Changes to this policy",
      "paragraphs": [
        "We may update this policy as the service or our practices change. The current version and effective date will appear on this page. We will provide additional notice or obtain consent where required."
      ],
      "bullets": []
    },
    {
      "id": "contact",
      "title": "12. Contact us",
      "paragraphs": [
        "For privacy questions, requests or concerns, contact Orchestrum Technologies LLP at sanjeev@orchestrum.in. Please identify CaseOps and the type of request so we can direct it appropriately.",
        "The separate demo-request privacy notice explains the handling of public demo, pilot and pricing enquiries in more detail."
      ],
      "bullets": []
    }
  ]
} as const satisfies PrivacyPolicyDocument;
