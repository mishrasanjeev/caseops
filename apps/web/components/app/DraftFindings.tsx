import { AlertTriangle, Info, ShieldAlert } from "lucide-react";

/**
 * The drafting service appends validator findings to
 * `DraftVersion.summary` as a trailing block formatted like:
 *
 *   [existing prose summary...]
 *
 *   Review findings:
 *   [BLOCKER] statute.bns_bnss_confusion: Section 483 is ...
 *   [WARNING] citation.coverage_gap: ...
 *
 * The reviewer needs to see these on the detail page — previously the
 * whole summary (including findings) was dropped from the UI, so the
 * reviewing partner had no signal that the draft flagged issues.
 */

export type FindingSeverity = "blocker" | "warning" | "info";

export type DraftFinding = {
  severity: FindingSeverity;
  code: string;
  message: string;
};

export type ParsedDraftSummary = {
  /** The free-text summary (without the findings block). `null` when empty. */
  prose: string | null;
  findings: DraftFinding[];
};

const FINDINGS_HEADER = /(?:^|\n)\s*Review findings:\s*\n?/i;
const FINDING_LINE = /^\s*\[(BLOCKER|WARNING|INFO)\]\s+([^:]+?):\s*(.*)$/i;

/**
 * Split the summary into the (optional) prose prefix and the list of
 * validator findings. Safe on inputs that have no findings block.
 */
export function parseDraftSummary(
  summary: string | null | undefined,
): ParsedDraftSummary {
  if (!summary) return { prose: null, findings: [] };
  const match = FINDINGS_HEADER.exec(summary);
  if (!match) {
    const trimmed = summary.trim();
    return { prose: trimmed || null, findings: [] };
  }
  const prose = summary.slice(0, match.index).trim() || null;
  const rest = summary.slice(match.index + match[0].length);
  const findings: DraftFinding[] = [];
  for (const raw of rest.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const m = FINDING_LINE.exec(line);
    if (!m) continue;
    const sev = m[1].toLowerCase() as FindingSeverity;
    findings.push({
      severity: sev === "blocker" || sev === "warning" ? sev : "info",
      code: m[2].trim(),
      message: m[3].trim(),
    });
  }
  return { prose, findings };
}

const SEVERITY_META: Record<
  FindingSeverity,
  {
    label: string;
    Icon: typeof AlertTriangle;
    className: string;
  }
> = {
  blocker: {
    label: "Blocker",
    Icon: ShieldAlert,
    className:
      "border-[color:var(--color-danger-border,#fca5a5)] bg-[color:var(--color-danger-bg,#fef2f2)] text-[color:var(--color-danger-text,#991b1b)]",
  },
  warning: {
    label: "Warning",
    Icon: AlertTriangle,
    className:
      "border-[color:var(--color-warn-border,#fcd34d)] bg-[color:var(--color-warn-bg,#fffbeb)] text-[color:var(--color-warn-text,#92400e)]",
  },
  info: {
    label: "Info",
    Icon: Info,
    className:
      "border-[var(--color-line)] bg-[var(--color-bg)] text-[var(--color-ink-2)]",
  },
};

export function DraftFindings({
  findings,
  className,
}: {
  findings: DraftFinding[];
  className?: string;
}) {
  if (!findings.length) return null;
  return (
    <ul className={`flex flex-col gap-2 text-sm ${className ?? ""}`}>
      {findings.map((f, idx) => {
        const meta = SEVERITY_META[f.severity] ?? SEVERITY_META.info;
        const Icon = meta.Icon;
        return (
          <li
            key={`${f.code}-${idx}`}
            className={`flex items-start gap-2 rounded-md border px-3 py-2 ${meta.className}`}
            data-severity={f.severity}
            data-code={f.code}
          >
            <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <div className="flex flex-col gap-0.5 min-w-0">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide">
                <span>{meta.label}</span>
                <code className="font-mono text-[10px] opacity-80">
                  {f.code}
                </code>
              </div>
              <div className="text-[13px] leading-relaxed">{f.message}</div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
