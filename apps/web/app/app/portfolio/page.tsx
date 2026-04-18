import { PanelsTopLeft } from "lucide-react";

import { RoadmapStub } from "@/components/app/RoadmapStub";

export default function PortfolioPage() {
  return (
    <RoadmapStub
      icon={PanelsTopLeft}
      eyebrow="Portfolio"
      title="Firm-wide portfolio view"
      description="A single board for partners and GCs — matters at risk, deadlines, realization, and hearings."
      prdSection="§8.2 Portfolio / Board View"
      bullets={[
        "Board mode with swimlanes by stage, practice area, or assignee.",
        "Heatmap for upcoming deadlines and hearings in the next 14 days.",
        "Realization, WIP, and collections metrics per matter and per practice.",
        "Exports: CSV, PDF, and scheduled email digests.",
      ]}
    />
  );
}
