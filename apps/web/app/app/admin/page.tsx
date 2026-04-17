import { Wrench } from "lucide-react";

import { RoadmapStub } from "@/components/app/RoadmapStub";

export default function AdminPage() {
  return (
    <RoadmapStub
      icon={Wrench}
      eyebrow="Workspace"
      title="Admin & governance"
      description="Users, roles, SSO, AI policy, audit export, billing plan — everything a firm admin needs."
      prdSection="§10.9"
      workDocSection="§10.1 admin · §10.2 SSO · §10.3 AI policy · §10.4 audit export"
      bullets={[
        "User directory with roles, team-based scoping, and ethical-wall rules.",
        "OIDC / SAML with JIT user provisioning and role mapping.",
        "Tenant AI policy: allowed models, prompt audit, external-share approvals.",
        "Tenant-scoped audit export as JSONL or CSV.",
      ]}
    />
  );
}
