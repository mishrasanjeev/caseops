import { type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Card, CardContent } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";

type RoadmapStubProps = {
  eyebrow?: string;
  title: ReactNode;
  description: ReactNode;
  icon: LucideIcon;
  /**
   * Optional. When supplied, rendered as a subtle "PRD §..." chip for
   * users who want to dig into the product doc. Never a link to an
   * internal work-plan.
   */
  prdSection?: string;
  bullets: string[];
};

export function RoadmapStub({
  eyebrow,
  title,
  description,
  icon: Icon,
  prdSection,
  bullets,
}: RoadmapStubProps) {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader eyebrow={eyebrow ?? "Coming soon"} title={title} description={description} />
      <Card>
        <CardContent className="flex flex-col gap-6 py-8 md:flex-row md:items-start md:gap-10">
          <div className="flex items-start gap-4 md:max-w-md">
            <span className="inline-flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--color-brand-50)] text-[var(--color-brand-700)]">
              <Icon className="h-6 w-6" aria-hidden />
            </span>
            <div className="flex flex-col gap-2">
              <p className="text-sm leading-relaxed text-[var(--color-mute)]">
                This surface is in the works. We'd rather ship it right than
                ship a half-baked version — the bullets to the right are the
                scope we're tracking.
              </p>
              {prdSection ? (
                <div className="flex flex-wrap gap-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-mute-2)]">
                  <span className="rounded-full border border-[var(--color-line)] bg-white px-2 py-0.5">
                    PRD {prdSection}
                  </span>
                </div>
              ) : null}
            </div>
          </div>
          <ul className="flex flex-1 flex-col gap-2 border-t border-[var(--color-line)] pt-6 md:border-l md:border-t-0 md:pl-10 md:pt-0">
            {bullets.map((item) => (
              <li key={item} className="flex gap-3 text-sm text-[var(--color-ink-2)]">
                <span
                  aria-hidden
                  className="mt-[9px] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-brand-500)]"
                />
                <span className="leading-relaxed">{item}</span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
