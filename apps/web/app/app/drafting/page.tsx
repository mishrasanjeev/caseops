import { FileSignature } from "lucide-react";

import { RoadmapStub } from "@/components/app/RoadmapStub";

export default function DraftingPage() {
  return (
    <RoadmapStub
      icon={FileSignature}
      eyebrow="Drafting"
      title="Drafting Studio"
      description="AI-assisted first drafts from matter context and your templates — with inline citations, version history, and reviewer approval."
      prdSection="§9.5, §10.3"
      bullets={[
        "Template picker keyed to matter type and forum.",
        "Draft generation grounded in the matter graph and retrieval.",
        "Version history, reviewer workflow, approval state machine.",
        "Export to DOCX and PDF with cited authorities preserved.",
      ]}
    />
  );
}
