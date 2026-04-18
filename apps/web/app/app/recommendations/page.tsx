import { Sparkles } from "lucide-react";

import { RoadmapStub } from "@/components/app/RoadmapStub";

export default function RecommendationsPage() {
  return (
    <RoadmapStub
      icon={Sparkles}
      eyebrow="Recommendations"
      title="Explainable recommendations"
      description="Forum and supporting-authority recommendations today, with rationale, assumptions, missing facts, and confidence on every option. Remedy, next-best-action, and counsel picks are on the roadmap."
      prdSection="§11 full pipeline"
      bullets={[
        "Today: forum and authority recommendations shipped from Matter Cockpit.",
        "Schema aligned to PRD §23.1 — options, rationale, citations, assumptions, missing facts, confidence, review_required.",
        "No recommendation persisted without at least one verified authority.",
        "Coming next: remedy, next-best-action, and outside-counsel picks from tenant-private performance history.",
      ]}
    />
  );
}
