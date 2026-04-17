import { Scale } from "lucide-react";

import { RoadmapStub } from "@/components/app/RoadmapStub";

export default function ContractsPage() {
  return (
    <RoadmapStub
      icon={Scale}
      eyebrow="Contracts"
      title="Contract repository & playbooks"
      description="Clause extraction, playbook comparison, obligation tracking, and redlines with full version lineage."
      prdSection="§9.8, §10.7"
      workDocSection="§3.1 /contracts · §9.2 clause extraction"
      bullets={[
        "Upload, parse, and normalize clauses with Docling-backed extraction.",
        "Playbook rules with pass/warn/fail plus suggested fallback language.",
        "Obligation tracker with owner, trigger, and due-date reminders.",
        "Live today in the legacy console — fully rebuilt here with the new design system.",
      ]}
    />
  );
}
