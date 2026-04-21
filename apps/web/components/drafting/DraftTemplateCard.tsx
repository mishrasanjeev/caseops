"use client";

import { ArrowRight } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import type { DraftTemplateSummary } from "@/lib/api/endpoints";

type Props = {
  matterId: string;
  template: DraftTemplateSummary;
};

export function DraftTemplateCard({ matterId, template }: Props) {
  const href = `/app/matters/${matterId}/drafts/new?type=${template.template_type}`;
  return (
    <Card className="flex flex-col justify-between">
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <h3 className="text-base font-semibold tracking-tight text-[var(--color-ink)]">
            {template.display_name}
          </h3>
          <p className="text-sm text-[var(--color-mute)]">{template.summary}</p>
        </div>
        {template.statutory_basis.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {template.statutory_basis.map((basis) => (
              <Badge key={basis} tone="neutral">
                {basis}
              </Badge>
            ))}
          </div>
        ) : null}
        <div className="mt-2 flex justify-end">
          <Button
            href={href}
            size="sm"
            variant="outline"
            data-testid={`start-draft-${template.template_type}`}
          >
            Start drafting <ArrowRight className="h-3.5 w-3.5" aria-hidden />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
