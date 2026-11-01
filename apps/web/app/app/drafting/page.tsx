"use client";

import { FileSignature } from "lucide-react";

import { MatterHubList } from "@/components/app/MatterHubList";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";

export default function DraftingHubPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Drafting"
        title="Drafting studio"
        description="Drafts live inside a matter so every version keeps its facts, authorities, and approvals. Pick the matter you want to draft on."
      />

      <Card>
        <CardHeader>
          <CardTitle as="h2" className="text-base">
            Matters
          </CardTitle>
          <CardDescription>
            Most recently updated first. Search every matter you can see by code, title, client, or case number.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <MatterHubList
            scope="drafting-hub"
            testIdPrefix="drafting-hub"
            hrefFor={(matter) => `/app/matters/${matter.id}/drafts`}
            emptyIcon={FileSignature}
            noMattersText="Create a matter to start drafting. Every draft is anchored to a matter for citation lineage."
          />
        </CardContent>
      </Card>
    </div>
  );
}
