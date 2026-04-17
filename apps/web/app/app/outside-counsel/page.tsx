import { Users } from "lucide-react";

import { RoadmapStub } from "@/components/app/RoadmapStub";

export default function OutsideCounselPage() {
  return (
    <RoadmapStub
      icon={Users}
      eyebrow="Outside counsel"
      title="Outside counsel & spend"
      description="Rank, assign, and budget outside counsel with a full fee-collection rail built in."
      prdSection="§9.9, §10.8"
      workDocSection="§3.1 /outside-counsel"
      bullets={[
        "Counsel profiles with specialization, rate card, and matter fit.",
        "Assignment workflow: proposed → approved → active → closed.",
        "Spend dashboards — matter, counsel, and portfolio — with aging buckets.",
        "Pine Labs collection rail already wired at the API layer.",
      ]}
    />
  );
}
