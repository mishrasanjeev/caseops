"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useParams, useSearchParams } from "next/navigation";

import { DraftTemplateCard } from "@/components/drafting/DraftTemplateCard";
import { DraftingStepper } from "@/components/drafting/DraftingStepper";
import { Button } from "@/components/ui/Button";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  listDraftingTemplates,
  type DraftTemplateType,
} from "@/lib/api/endpoints";

const KNOWN_TEMPLATE_TYPES: ReadonlySet<DraftTemplateType> = new Set([
  "bail",
  "anticipatory_bail",
  "divorce_petition",
  "property_dispute_notice",
  "cheque_bounce_notice",
  "affidavit",
  "criminal_complaint",
  "civil_suit",
  // BAAD-001 (Sprint P5, 2026-04-25). Without this entry the
  // appeal-memorandum template card 404s into the stepper — the
  // entire BAAD UI (BenchContextCard + AppealStrengthPanel) is
  // dead code from a user's perspective.
  "appeal_memorandum",
]);

function isKnownTemplateType(value: string | null): value is DraftTemplateType {
  return value !== null && KNOWN_TEMPLATE_TYPES.has(value as DraftTemplateType);
}

export default function NewDraftPage() {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const searchParams = useSearchParams();
  const typeParam = searchParams.get("type");

  if (isKnownTemplateType(typeParam)) {
    return (
      <div className="flex flex-col gap-4">
        <div>
          <Button
            href={`/app/matters/${matterId}/drafts/new`}
            variant="ghost"
            size="sm"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden /> All templates
          </Button>
        </div>
        <DraftingStepper matterId={matterId} templateType={typeParam} />
      </div>
    );
  }

  return <TemplateGrid matterId={matterId} />;
}

function TemplateGrid({ matterId }: { matterId: string }) {
  const query = useQuery({
    queryKey: ["drafting", "templates"],
    queryFn: listDraftingTemplates,
  });

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold text-[var(--color-ink)]">
          Start a new draft
        </h2>
        <p className="text-sm text-[var(--color-mute)]">
          Pick a template to launch the fact-capture stepper. Every template is
          grounded in the cited statute and feeds the same citation-checked
          generator.
        </p>
      </header>

      {query.isPending ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : query.isError ? (
        <QueryErrorState
          title="Could not load drafting templates"
          error={query.error}
          onRetry={query.refetch}
        />
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(query.data ?? []).map((template) => (
            <DraftTemplateCard
              key={template.template_type}
              matterId={matterId}
              template={template}
            />
          ))}
        </div>
      )}
    </div>
  );
}
