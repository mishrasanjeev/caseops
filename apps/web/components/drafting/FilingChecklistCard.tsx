"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ClipboardList, Clock, Coins } from "lucide-react";
import { useMemo, useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  type FilingChecklistItem,
  type FilingChecklistResponse,
  fetchFilingChecklist,
} from "@/lib/api/endpoints";

type Props = {
  matterId: string;
  draftId: string;
  courtProfile?: string;
};

/**
 * PG-005 Sprint 8 (2026-05-01) — pre-filing checklist.
 *
 * Renders the per-court / per-template checklist items the lawyer
 * must assemble before filing. Items the system can auto-verify
 * (vakalat draft exists, attachments uploaded) ship pre-ticked with a
 * one-line reason. Manually-tickable items track the lawyer's local
 * progress in component state — no server round-trip on tick (the
 * checklist is descriptive, not gating).
 */
export function FilingChecklistCard({ matterId, draftId, courtProfile }: Props) {
  const query = useQuery({
    queryKey: ["filing-checklist", matterId, draftId, courtProfile ?? "auto"],
    queryFn: () => fetchFilingChecklist({ matterId, draftId, courtProfile }),
  });

  return (
    <Card data-testid="filing-checklist-card">
      <CardHeader>
        <CardTitle as="h2">
          <ClipboardList className="mr-2 inline-block h-4 w-4" aria-hidden /> Pre-filing checklist
        </CardTitle>
        <CardDescription>
          {query.data
            ? `${query.data.court_display_name} · ${query.data.copies_required} cop${
                query.data.copies_required === 1 ? "y" : "ies"
              } required`
            : "Loading the filing requirements for the destination court."}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {query.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : query.error ? (
          <p className="text-sm text-red-700">
            Failed to load checklist: {String(query.error)}
          </p>
        ) : query.data ? (
          <ChecklistBody data={query.data} />
        ) : null}
      </CardContent>
    </Card>
  );
}

function ChecklistBody({ data }: { data: FilingChecklistResponse }) {
  const [manuallyTicked, setManuallyTicked] = useState<Record<string, boolean>>({});

  const grouped = useMemo(() => {
    const groups: Record<string, FilingChecklistItem[]> = {
      document: [],
      fee: [],
      procedure: [],
      service: [],
    };
    for (const item of data.items) {
      groups[item.category]?.push(item);
    }
    return groups;
  }, [data.items]);

  const totalRequired = data.items.filter((it) => it.required).length;
  const satisfied = data.items.filter((it) => {
    if (!it.required) return false;
    if (it.auto_satisfied) return true;
    return manuallyTicked[it.id] === true;
  }).length;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium tabular text-[var(--color-ink-2)]">
          {satisfied} of {totalRequired} required items ready
        </p>
        <span className="text-xs text-[var(--color-mute)]">
          ({data.items.length - totalRequired} optional)
        </span>
      </div>

      <div
        className="rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] px-3 py-2"
        data-testid="filing-checklist-required-fields"
      >
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm font-medium text-[var(--color-ink)]">
            Court-format required fields
          </p>
          <span className="text-xs tabular text-[var(--color-mute)]">
            {data.missing_required_field_count} missing
          </span>
        </div>
        {data.required_field_findings.length === 0 ? (
          <p className="mt-1 text-xs text-[var(--color-mute)]">
            Generic profile has no additional court-format field checks.
          </p>
        ) : (
          <ul className="mt-2 flex flex-col gap-1.5">
            {data.required_field_findings.map((finding) => (
              <li
                key={finding.key}
                className="flex items-start gap-2 text-xs text-[var(--color-ink-2)]"
                data-testid={`required-field-${finding.key}`}
              >
                {finding.satisfied ? (
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-700" aria-hidden />
                ) : (
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-700" aria-hidden />
                )}
                <span>
                  <span className="font-medium">{finding.label}</span>
                  {finding.satisfied ? (
                    <span className="text-[var(--color-mute)]">
                      {" "}
                      satisfied from {finding.source ?? "matter metadata"}
                    </span>
                  ) : (
                    <span className="text-amber-800"> needs review</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {data.limitation_note ? (
        <div
          className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900"
          data-testid="filing-checklist-limitation"
        >
          <Clock className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span>{data.limitation_note}</span>
        </div>
      ) : null}

      {(["document", "fee", "procedure", "service"] as const).map((cat) => {
        const items = grouped[cat] ?? [];
        if (items.length === 0) return null;
        return (
          <div key={cat}>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-mute)]">
              {CATEGORY_LABEL[cat]}
            </h3>
            <ul className="flex flex-col gap-1.5 text-sm">
              {items.map((item) => {
                const ticked = item.auto_satisfied || manuallyTicked[item.id] === true;
                return (
                  <li
                    key={item.id}
                    className={`flex items-start gap-2 rounded-md border px-3 py-2 ${
                      ticked
                        ? "border-emerald-200 bg-emerald-50"
                        : "border-[var(--color-line)] bg-white"
                    }`}
                    data-testid={`checklist-item-${item.id}`}
                  >
                    <input
                      type="checkbox"
                      className="mt-1 h-4 w-4 shrink-0"
                      checked={ticked}
                      disabled={item.auto_satisfied}
                      onChange={(e) =>
                        setManuallyTicked((prev) => ({
                          ...prev,
                          [item.id]: e.target.checked,
                        }))
                      }
                      aria-label={item.label}
                    />
                    <div className="flex-1">
                      <div className="flex items-baseline gap-2">
                        <span
                          className={`font-medium ${
                            ticked ? "text-emerald-900" : "text-[var(--color-ink)]"
                          }`}
                        >
                          {item.label}
                        </span>
                        {!item.required ? (
                          <span className="text-xs text-[var(--color-mute)]">
                            (optional)
                          </span>
                        ) : null}
                      </div>
                      <p className="text-xs leading-relaxed text-[var(--color-mute)]">
                        {item.description}
                      </p>
                      {item.auto_satisfied && item.auto_satisfied_reason ? (
                        <p className="mt-1 flex items-center gap-1 text-xs text-emerald-700">
                          <CheckCircle2 className="h-3 w-3" aria-hidden />
                          {item.auto_satisfied_reason}
                        </p>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}

      <div
        className="flex items-start gap-2 rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] px-3 py-2 text-xs text-[var(--color-ink-2)]"
        data-testid="filing-checklist-fee-note"
      >
        <Coins className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        <span>{data.court_fee_note}</span>
      </div>
    </div>
  );
}

const CATEGORY_LABEL: Record<string, string> = {
  document: "Documents",
  fee: "Court fee",
  procedure: "Procedure",
  service: "Service of process",
};
