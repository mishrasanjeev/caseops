import { LibraryBig } from "lucide-react";

import { RoadmapStub } from "@/components/app/RoadmapStub";

export default function ResearchPage() {
  return (
    <RoadmapStub
      icon={LibraryBig}
      eyebrow="Research"
      title="Grounded legal research"
      description="Hybrid retrieval across statutes, judgments, and your own precedents — every answer cited and traceable."
      prdSection="§9.4, §10.2"
      workDocSection="§4.1 LLM · §4.2 RAG · §7.4 statute entities"
      bullets={[
        "Vector + lexical hybrid search with tenant-scoped namespaces.",
        "Citation verification and refusal on weak evidence — no hallucinations.",
        "Filter by court, date range, statute, judge, and internal corpus.",
        "Save research notes back to the matter with lineage intact.",
      ]}
    />
  );
}
