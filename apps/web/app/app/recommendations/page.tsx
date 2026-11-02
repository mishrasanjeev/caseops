"use client";

import { Sparkles } from "lucide-react";

import { MatterHubList } from "@/components/app/MatterHubList";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";

export default function RecommendationsHubPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Recommendations"
        title="Recommendations"
        description="Authority and forum recommendations live inside a matter so the reasoning can be anchored to matter facts. Pick a matter to generate or review decisions."
      />

      <Card>
        <CardHeader>
          <CardTitle as="h2" className="text-base">
            Matters
          </CardTitle>
          <CardDescription>
            Most recently updated first. Open a matter to run a recommendation or record a decision.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <MatterHubList
            scope="recommendations-hub"
            testIdPrefix="recommendations-hub"
            hrefFor={(matter) => `/app/matters/${matter.id}/recommendations`}
            emptyIcon={Sparkles}
            noMattersText="Create a matter to start generating recommendations."
          />
        </CardContent>
      </Card>
    </div>
  );
}
