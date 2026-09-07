import { z } from "zod";

export const ipDomainCapabilitySchema = z.object({
  domain: z.string(),
  label: z.string(),
  stage: z.enum(["unavailable", "intake_only", "beta", "ga"]),
  contract_version: z.string(),
  jurisdictions: z.array(z.string()),
  offices: z.array(z.string()),
  intake_available: z.boolean(),
  authoritative_automation_available: z.boolean(),
  blockers: z.array(z.string()),
  required_journeys: z.array(z.string()),
}).strict();

export const ipDomainCatalogueSchema = z.object({
  catalogue_version: z.string(),
  domains: z.array(ipDomainCapabilitySchema).min(1).max(30),
}).strict().superRefine((catalogue, context) => {
  const domains = new Set<string>();
  for (const row of catalogue.domains) {
    if (domains.has(row.domain)) context.addIssue({ code: "custom", message: "Duplicate IP domain" });
    domains.add(row.domain);
    const supported = row.stage === "beta" || row.stage === "ga";
    if (supported !== row.authoritative_automation_available ||
        (row.stage === "unavailable") === row.intake_available ||
        (supported && row.blockers.length > 0)) {
      context.addIssue({ code: "custom", message: "Inconsistent IP domain availability" });
    }
  }
});

export type IpDomainCapability = z.infer<typeof ipDomainCapabilitySchema>;

export const DOMAIN_STAGE_LABELS: Record<IpDomainCapability["stage"], string> = {
  unavailable: "Unavailable",
  intake_only: "Intake only",
  beta: "Beta",
  ga: "General availability",
};
