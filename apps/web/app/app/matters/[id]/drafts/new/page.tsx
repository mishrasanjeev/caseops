"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Sparkles } from "lucide-react";
import { useParams, useSearchParams } from "next/navigation";

import { DraftTemplateCard } from "@/components/drafting/DraftTemplateCard";
import { DraftingStepper } from "@/components/drafting/DraftingStepper";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  fetchTemplateRecommendations,
  listDraftingTemplates,
  type DraftTemplateType,
} from "@/lib/api/endpoints";
import { useMatterWorkspace } from "@/lib/use-matter-workspace";

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

  // PRD §16.3 (2026-04-26) — format-to-forum recommender. Reads the
  // matter's forum_level + practice_area from the workspace cache,
  // calls the recommender endpoint, surfaces 1-3 primary templates
  // above the catch-all grid. Failure (no workspace, no recs) just
  // hides the suggestion strip — never blocks the catch-all grid.
  const workspace = useMatterWorkspace(matterId);
  const matter = workspace.data?.matter;
  const matterForum = matter?.forum_level ?? "";
  const matterPracticeArea = matter?.practice_area ?? null;
  const recommendQuery = useQuery({
    queryKey: [
      "drafting", "template-recommendations",
      matterForum, matterPracticeArea,
    ],
    queryFn: () =>
      fetchTemplateRecommendations({
        forum_level: matterForum,
        practice_area: matterPracticeArea ?? undefined,
      }),
    enabled: matterForum.length > 0,
    staleTime: 30 * 60_000,
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

      {recommendQuery.data &&
      recommendQuery.data.recommendations.length > 0 &&
      query.data ? (
        <SuggestedForMatter
          matterId={matterId}
          recommendations={recommendQuery.data.recommendations}
          allTemplates={query.data}
          forumLevel={recommendQuery.data.forum_level}
          practiceArea={recommendQuery.data.practice_area}
        />
      ) : null}

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
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--color-mute-2)]">
            All templates
          </h3>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {(query.data ?? []).map((template) => (
              <DraftTemplateCard
                key={template.template_type}
                matterId={matterId}
                template={template}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function SuggestedForMatter({
  matterId,
  recommendations,
  allTemplates,
  forumLevel,
  practiceArea,
}: {
  matterId: string;
  recommendations: { template_type: string; relevance: "primary" | "secondary"; reason: string }[];
  allTemplates: import("@/lib/api/endpoints").DraftTemplateSummary[];
  forumLevel: string;
  practiceArea: string | null;
}) {
  // Join recommendation rows to the full template metadata so each
  // suggested card shows the same display_name + summary as the
  // catch-all grid below.
  const byType = new Map(allTemplates.map((t) => [t.template_type, t]));
  const suggested = recommendations.flatMap((r) => {
    const tpl = byType.get(r.template_type as DraftTemplateType);
    return tpl
      ? [{ template: tpl, relevance: r.relevance, reason: r.reason }]
      : [];
  });

  if (suggested.length === 0) return null;

  return (
    <section
      className="rounded-2xl border border-[var(--color-line)] bg-[var(--color-bg-2)] p-4"
      data-testid="suggested-templates"
    >
      <div className="mb-3 flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-[var(--color-brand-600)]" aria-hidden />
        <h3 className="text-sm font-semibold uppercase tracking-[0.12em] text-[var(--color-mute-2)]">
          Suggested for {forumLevel.replace(/_/g, " ")}
          {practiceArea ? ` · ${practiceArea}` : null}
        </h3>
      </div>
      <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {suggested.map((s) => (
          <li
            key={s.template.template_type}
            data-testid={`suggested-template-${s.template.template_type}`}
          >
            <div className="flex flex-col gap-2">
              <div className="flex items-baseline gap-2">
                <Badge tone={s.relevance === "primary" ? "brand" : "neutral"}>
                  {s.relevance}
                </Badge>
              </div>
              <DraftTemplateCard matterId={matterId} template={s.template} />
              <p className="px-1 text-xs text-[var(--color-mute)]">
                {s.reason}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
