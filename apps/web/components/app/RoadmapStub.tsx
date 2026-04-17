import { ArrowRight, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";

type RoadmapStubProps = {
  eyebrow?: string;
  title: ReactNode;
  description: ReactNode;
  icon: LucideIcon;
  prdSection: string;
  workDocSection: string;
  bullets: string[];
};

export function RoadmapStub({
  eyebrow,
  title,
  description,
  icon: Icon,
  prdSection,
  workDocSection,
  bullets,
}: RoadmapStubProps) {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader eyebrow={eyebrow ?? "Roadmap"} title={title} description={description} />
      <Card>
        <CardContent className="flex flex-col gap-6 py-8 md:flex-row md:items-start md:gap-10">
          <div className="flex items-start gap-4 md:max-w-md">
            <span className="inline-flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--color-brand-50)] text-[var(--color-brand-700)]">
              <Icon className="h-6 w-6" aria-hidden />
            </span>
            <div className="flex flex-col gap-2">
              <p className="text-sm leading-relaxed text-[var(--color-mute)]">
                This surface is part of CaseOps' roadmap. We're intentionally not shipping a
                half-baked version — the full feature arrives with the workstream below.
              </p>
              <div className="flex flex-wrap gap-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--color-mute-2)]">
                <span className="rounded-full border border-[var(--color-line)] bg-white px-2 py-0.5">
                  PRD {prdSection}
                </span>
                <span className="rounded-full border border-[var(--color-line)] bg-white px-2 py-0.5">
                  Work plan {workDocSection}
                </span>
              </div>
              <Button
                href="https://github.com/"
                variant="outline"
                size="sm"
                className="mt-2 self-start"
              >
                View work plan <ArrowRight className="h-4 w-4" />
              </Button>
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
