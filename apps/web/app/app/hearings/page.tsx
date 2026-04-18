import { Gavel } from "lucide-react";

import { RoadmapStub } from "@/components/app/RoadmapStub";

export default function HearingsPage() {
  return (
    <RoadmapStub
      icon={Gavel}
      eyebrow="Hearings"
      title="Portfolio-wide hearings"
      description="Every hearing across every matter — sorted, filtered, and ready for prep."
      prdSection="§9.6, §10.4"
      bullets={[
        "Cause-list sync from eCourts and High-Court portals with retry and status.",
        "Hearing pack generator: chronology, last order, pending compliance, oral points.",
        "Post-hearing outcome capture — auto-creates tasks and proposes the next date.",
        "Integration with Hearings tab inside each Matter Cockpit.",
      ]}
    />
  );
}
