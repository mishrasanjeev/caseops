import { Sparkles } from "lucide-react";

import { RoadmapStub } from "@/components/app/RoadmapStub";

export default function RecommendationsPage() {
  return (
    <RoadmapStub
      icon={Sparkles}
      eyebrow="Recommendations"
      title="Explainable recommendations"
      description="Forum, remedy, authority, next-best action, and counsel picks — with rationale, assumptions, missing facts, and confidence."
      prdSection="§11 full pipeline"
      workDocSection="§4.4 Recommendation engine"
      bullets={[
        "Schema locked to PRD §23.1: options, rationale, citations, assumptions, missing facts, confidence, review_required.",
        "No recommendation without at least one supporting authority.",
        "User accept / reject / edit captured as structured HITL feedback.",
        "Outside-counsel picks ranked from tenant-private performance history.",
      ]}
    />
  );
}
