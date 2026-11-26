"use client";

import { ArrowUp, ExternalLink } from "lucide-react";
import { useRef } from "react";
import type { ReactNode } from "react";

import { SourceAction } from "@/components/app/SourceAction";
import { formatLegalDate } from "@/lib/dates";
import type {
  ResearchAnswerRecord,
  ResearchAuthorityEntry,
  ResearchCitedText,
  ResearchSource,
} from "@/lib/api/research-answers";

const MARKER = /\[(\d{1,2})\]/g;

export function sourceAnchorId(answerId: string, number: number): string {
  return `research-${answerId}-source-${number}`;
}

function dateLabel(value: string | null | undefined): string | null {
  return value ? formatLegalDate(value.slice(0, 10)) : null;
}

/** Answer text with every [n] marker rendered as a link to source n. */
function CitedText({
  text,
  answerId,
  sources,
  onCite,
}: {
  text: ResearchCitedText;
  answerId: string;
  sources: Map<number, ResearchSource>;
  onCite: (number: number, origin: HTMLElement) => void;
}) {
  const parts: ReactNode[] = [];
  let last = 0;
  for (const match of text.text.matchAll(MARKER)) {
    const number = Number(match[1]);
    const source = sources.get(number);
    parts.push(text.text.slice(last, match.index));
    parts.push(
      source ? (
        <a
          key={`${match.index}-${number}`}
          href={`#${sourceAnchorId(answerId, number)}`}
          className="align-super text-[0.7em] font-semibold text-[var(--color-brand-600)] underline-offset-2 hover:underline"
          aria-label={`Source ${number}: ${source.title}`}
          data-testid="research-citation-marker"
          onClick={(event) => {
            event.preventDefault();
            onCite(number, event.currentTarget);
          }}
        >
          [{number}]
        </a>
      ) : (
        <span key={`${match.index}-${number}`}>[{number}]</span>
      ),
    );
    last = (match.index ?? 0) + match[0].length;
  }
  parts.push(text.text.slice(last));
  return (
    <>
      {parts}
      {text.unsupported ? (
        <span className="ml-2 inline-block rounded border border-[var(--color-warn-600)]/40 px-1.5 text-[0.7rem] font-medium text-[var(--color-warn-700)]">
          No source attached. Verify before relying.
        </span>
      ) : null}
    </>
  );
}

function AuthorityCard({
  answerId,
  source,
  entry,
  onBack,
}: {
  answerId: string;
  source: ResearchSource;
  entry: ResearchAuthorityEntry;
  onBack: () => void;
}) {
  const facts = [
    source.citation,
    source.court,
    source.bench,
    dateLabel(source.decision_date),
  ].filter(Boolean);
  return (
    <li
      id={sourceAnchorId(answerId, source.number)}
      tabIndex={-1}
      className="flex flex-col gap-3 rounded-md border border-[var(--color-line)] bg-white p-4 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-500)]"
      data-testid="research-authority-card"
    >
      <div className="flex flex-col gap-1">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="font-mono font-semibold text-[var(--color-ink)]">[{source.number}]</span>
          <span className="text-[0.7rem] font-semibold uppercase tracking-wide text-[var(--color-mute-2)]">
            {source.kind === "statute_section" ? "Statute" : "Judgment"} ·{" "}
            {entry.disposition === "contrary" ? "Contrary" : entry.disposition === "context" ? "Context" : "Supporting"}
          </span>
        </div>
        <h4 className="text-sm font-semibold text-[var(--color-ink)]">{source.title}</h4>
        {source.kind === "judgment" && source.focus_engagement ? (
          <p
            className={
              source.focus_engagement === "context_only"
                ? "text-xs font-medium text-[var(--color-warn-700)]"
                : "text-xs text-[var(--color-ink-2)]"
            }
            data-testid="research-focus-engagement"
            data-engagement={source.focus_engagement}
          >
            {source.focus_engagement === "cites"
              ? "Cites the provision researched"
              : source.focus_engagement === "names"
                ? "Names the provision researched in the retrieved text"
                : "Related context only: does not cite the provision researched"}
          </p>
        ) : null}
        {facts.length ? <p className="text-[var(--color-ink-2)]">{facts.join(" · ")}</p> : null}
      </div>
      <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-[10rem_1fr]">
        <dt className="font-medium text-[var(--color-mute-2)]">Weight</dt>
        <dd>{source.weight}</dd>
        {source.kind === "judgment" ? (
          <>
            <dt className="font-medium text-[var(--color-mute-2)]">Paragraph</dt>
            <dd>{entry.paragraph ? `Para ${entry.paragraph} (located in the source text)` : "Not verified"}</dd>
          </>
        ) : null}
        {entry.proposition ? (
          <>
            <dt className="font-medium text-[var(--color-mute-2)]">Proposition</dt>
            <dd>{entry.proposition}</dd>
          </>
        ) : null}
        {entry.relevance ? (
          <>
            <dt className="font-medium text-[var(--color-mute-2)]">Relevance</dt>
            <dd>{entry.relevance}</dd>
          </>
        ) : null}
        {source.kind === "judgment" ? (
          <>
            <dt className="font-medium text-[var(--color-mute-2)]">Treatment</dt>
            <dd>
              Treatment history not verified.
              {source.treatment_signal?.adverse_count ? (
                <span className="block text-[var(--color-warn-700)]">
                  Automated citator signal: {source.treatment_signal.adverse_count} citing judgment(s) may treat it
                  adversely. Check before relying.
                </span>
              ) : null}
            </dd>
          </>
        ) : null}
      </dl>
      {entry.passage ? (
        <blockquote className="flex flex-col gap-1 border-l-2 border-[var(--color-line)] pl-3 text-[var(--color-ink-2)]">
          <span className="text-[0.7rem] font-semibold uppercase tracking-wide text-[var(--color-mute-2)]">
            Verified passage
          </span>
          <span>{entry.passage}</span>
        </blockquote>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <SourceAction action={source.source_action ?? null} compact originSurface="research" />
        {source.in_app_href ? (
          <a
            href={source.in_app_href}
            target="_blank"
            rel="noopener"
            className="inline-flex items-center gap-1 underline"
          >
            Open section in CaseOps <ExternalLink className="h-3.5 w-3.5" aria-hidden />
          </a>
        ) : null}
        <button type="button" onClick={onBack} className="inline-flex items-center gap-1 underline">
          <ArrowUp className="h-3.5 w-3.5" aria-hidden /> Back to the answer
        </button>
      </div>
    </li>
  );
}

/** Part A, B and C headings: the top of the document's heading hierarchy. */
function PartHeading({ id, children }: { id: string; children: ReactNode }) {
  return (
    <h3
      id={id}
      className="border-b border-[var(--color-line)] pb-2 text-xl font-semibold tracking-tight text-[var(--color-ink)]"
    >
      {children}
    </h3>
  );
}

/**
 * The answer document. Every block spans the full width of its parent (the
 * page's ReadingColumn), so nothing here sets its own max width. One spacing
 * scale: gap-8 between the parts, gap-4 between blocks inside a part, gap-2
 * inside a block (a numbered sub-heading and its paragraphs).
 */
export function ResearchAnswerView({ record }: { record: ResearchAnswerRecord }) {
  const answer = record.answer;
  const lastMarker = useRef<HTMLElement | null>(null);
  const top = useRef<HTMLDivElement | null>(null);
  if (!answer) return null;
  const sources = new Map(record.sources.map((source) => [source.number, source]));
  const onCite = (number: number, origin: HTMLElement) => {
    lastMarker.current = origin;
    const target = document.getElementById(sourceAnchorId(record.id, number));
    if (!target) return;
    target.scrollIntoView({ block: "start", behavior: "smooth" });
    // A hash scroll alone does not move keyboard focus.
    target.focus({ preventScroll: true });
  };
  const onBack = () => {
    const origin = lastMarker.current ?? top.current;
    origin?.scrollIntoView({ block: "center", behavior: "smooth" });
    origin?.focus({ preventScroll: true });
  };
  const cite = (text: ResearchCitedText) => (
    <CitedText text={text} answerId={record.id} sources={sources} onCite={onCite} />
  );
  const retrievedFrom = dateLabel(answer.sources_retrieved_from);
  const retrievedTo = dateLabel(answer.sources_retrieved_to);
  return (
    <article className="flex flex-col gap-8" data-testid="research-answer" aria-label="Research answer">
      <div ref={top} tabIndex={-1} className="text-xs text-[var(--color-mute-2)] outline-none" data-testid="research-law-checked">
        Law checked as of {formatLegalDate(answer.law_checked_as_of)}
        {retrievedFrom ? ` · Sources as indexed ${retrievedFrom === retrievedTo ? retrievedFrom : `${retrievedFrom} to ${retrievedTo}`}` : ""}
        {" · Question: "}
        <span className="text-[var(--color-ink-2)]">{record.query}</span>
      </div>
      {(answer.question_focus ?? []).length ? (
        <p className="text-sm text-[var(--color-ink-2)]" data-testid="research-question-focus">
          <span className="font-medium text-[var(--color-ink)]">Researched as: </span>
          {(answer.question_focus ?? []).join("; ")}
        </p>
      ) : null}

      <section className="flex flex-col gap-4" aria-labelledby={`${record.id}-short`} data-testid="research-short-answer">
        <PartHeading id={`${record.id}-short`}>Short answer</PartHeading>
        <p className="leading-relaxed text-[var(--color-ink)]">{cite(answer.short_answer)}</p>
        {answer.key_points.length ? (
          <ul className="list-disc space-y-1 pl-5 leading-relaxed">
            {answer.key_points.map((point, index) => <li key={index}>{cite(point)}</li>)}
          </ul>
        ) : null}
        {answer.facts_insufficient || answer.missing_facts.length ? (
          <div className="flex flex-col gap-1 rounded-md border border-[var(--color-warn-600)]/30 bg-[var(--color-warn-50)] p-3 text-sm" data-testid="research-missing-facts">
            <p className="font-semibold text-[var(--color-warn-700)]">
              Facts needed before this can be applied to a specific case or deadline
            </p>
            <ul className="list-disc space-y-0.5 pl-5">
              {answer.missing_facts.map((fact, index) => <li key={index}>{fact}</li>)}
            </ul>
          </div>
        ) : null}
        {(answer.coverage_gaps ?? []).length ? (
          <div className="flex flex-col gap-1 text-sm" data-testid="research-coverage-gaps">
            <p className="font-medium text-[var(--color-mute-2)]">
              This answer does not cover
            </p>
            <ul className="list-disc space-y-0.5 pl-5">
              {(answer.coverage_gaps ?? []).map((gap, index) => <li key={index}>{gap}</li>)}
            </ul>
          </div>
        ) : null}
        {answer.assumptions.length ? (
          <div className="flex flex-col gap-1 text-sm" data-testid="research-assumptions">
            <p className="font-medium text-[var(--color-mute-2)]">Assumptions (not stated in the question)</p>
            <ul className="list-disc space-y-0.5 pl-5">
              {answer.assumptions.map((item, index) => <li key={index}>{item}</li>)}
            </ul>
          </div>
        ) : null}
        {answer.matter_facts.length ? (
          <div className="flex flex-col gap-1 rounded-md border border-[var(--color-line)] p-3 text-sm" data-testid="research-matter-facts">
            <p className="font-medium">Matter facts used (from the matter record, not legal authority)</p>
            <dl className="grid gap-x-3 gap-y-1 sm:grid-cols-[9rem_1fr]">
              {answer.matter_facts.map((fact) => (
                <div key={fact.label} className="contents">
                  <dt className="text-[var(--color-mute-2)]">{fact.label}</dt>
                  <dd>{fact.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        ) : null}
      </section>

      <section className="flex flex-col gap-4" aria-labelledby={`${record.id}-detail`} data-testid="research-detailed">
        <PartHeading id={`${record.id}-detail`}>Detailed research</PartHeading>
        {answer.sections.map((section, index) => (
          <div key={section.key} className="flex flex-col gap-2" data-testid={`research-section-${section.key}`}>
            <h4 className="text-base font-semibold text-[var(--color-ink)]">
              {index + 1}. {section.title}
            </h4>
            {section.paragraphs.map((paragraph, i) => (
              <p key={i} className="leading-relaxed">{cite(paragraph)}</p>
            ))}
            {section.timeline.length ? (
              <div className="divide-y divide-[var(--color-line)] rounded-md border border-[var(--color-line)] text-sm" role="table" aria-label={`${section.title} timeline`} data-testid="research-timeline">
                <div role="row" className="hidden bg-[var(--color-bg-2)] px-3 py-1.5 font-medium sm:grid sm:grid-cols-[1fr_1fr_2fr] sm:gap-3">
                  <span role="columnheader">Period</span>
                  <span role="columnheader">Starts</span>
                  <span role="columnheader">Detail</span>
                </div>
                {section.timeline.map((row, i) => (
                  <div key={i} role="row" className="grid gap-1 px-3 py-2 sm:grid-cols-[1fr_1fr_2fr] sm:gap-3">
                    <span role="cell" className="font-medium">{row.period}</span>
                    <span role="cell">{row.starts}</span>
                    <span role="cell">{cite(row.detail)}</span>
                  </div>
                ))}
              </div>
            ) : null}
            {section.steps.length ? (
              <ol className="list-decimal space-y-1 pl-5 leading-relaxed">
                {section.steps.map((step, i) => <li key={i}>{cite(step)}</li>)}
              </ol>
            ) : null}
          </div>
        ))}
        {answer.verification.notes.length ? (
          <div className="flex flex-col gap-1 text-xs text-[var(--color-mute-2)]" data-testid="research-verification-notes">
            <p className="font-semibold">Verification</p>
            <ul className="list-disc space-y-0.5 pl-4">
              {answer.verification.notes.map((note, index) => <li key={index}>{note}</li>)}
            </ul>
          </div>
        ) : null}
      </section>

      <section className="flex flex-col gap-4" aria-labelledby={`${record.id}-sources`} data-testid="research-authorities">
        <PartHeading id={`${record.id}-sources`}>Relevant judicial authorities &amp; sources</PartHeading>
        <ol className="flex flex-col gap-4">
          {answer.authorities.map((entry) => {
            const source = sources.get(entry.source);
            return source ? (
              <AuthorityCard key={entry.source} answerId={record.id} source={source} entry={entry} onBack={onBack} />
            ) : null;
          })}
        </ol>
        <p className="text-xs text-[var(--color-mute-2)]" data-testid="research-disclaimer">{answer.disclaimer}</p>
      </section>
    </article>
  );
}

/** Plain text in the on-screen order, for Copy. */
export function researchAnswerToText(record: ResearchAnswerRecord): string {
  const answer = record.answer;
  if (!answer) return "";
  const sources = new Map(record.sources.map((source) => [source.number, source]));
  const lines: string[] = [`Research question: ${record.query}`, `Law checked as of ${answer.law_checked_as_of}`];
  if (answer.question_focus?.length) lines.push(`Researched as: ${answer.question_focus.join("; ")}`);
  lines.push("");
  lines.push("A. SHORT ANSWER", answer.short_answer.text);
  answer.key_points.forEach((point) => lines.push(`- ${point.text}`));
  if (answer.missing_facts.length) {
    lines.push("", "Facts needed:");
    answer.missing_facts.forEach((fact) => lines.push(`- ${fact}`));
  }
  if (answer.coverage_gaps?.length) {
    lines.push("", "This answer does not cover:");
    (answer.coverage_gaps ?? []).forEach((gap) => lines.push(`- ${gap}`));
  }
  if (answer.assumptions.length) {
    lines.push("", "Assumptions:");
    answer.assumptions.forEach((item) => lines.push(`- ${item}`));
  }
  lines.push("", "B. DETAILED RESEARCH");
  answer.sections.forEach((section, index) => {
    lines.push("", `${index + 1}. ${section.title}`);
    section.paragraphs.forEach((paragraph) => lines.push(paragraph.text + (paragraph.unsupported ? " [no source attached]" : "")));
    section.timeline.forEach((row) => lines.push(`- ${row.period} | ${row.starts} | ${row.detail.text}`));
    section.steps.forEach((step, i) => lines.push(`${i + 1}) ${step.text}`));
  });
  lines.push("", "C. RELEVANT JUDICIAL AUTHORITIES & SOURCES");
  answer.authorities.forEach((entry) => {
    const source = sources.get(entry.source);
    if (!source) return;
    lines.push(
      "",
      `[${source.number}] ${source.title}`,
      [source.citation, source.court, source.decision_date].filter(Boolean).join(" | "),
      `Weight: ${source.weight}`,
    );
    if (source.kind === "judgment") lines.push(`Paragraph: ${entry.paragraph ? `para ${entry.paragraph}` : "not verified"}`);
    if (entry.proposition) lines.push(`Proposition: ${entry.proposition}`);
    if (entry.relevance) lines.push(`Relevance: ${entry.relevance}`);
    if (entry.passage) lines.push(`Verified passage: "${entry.passage}"`);
    const link = source.source_action?.open_url ?? source.source_action?.source_reference;
    if (link) lines.push(`Source: ${link}`);
  });
  lines.push("", answer.disclaimer);
  return lines.join("\n");
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char] as string);
}

/** A standalone, readable HTML document in the same section order, for Download. */
export function researchAnswerToHtml(record: ResearchAnswerRecord): string {
  const body = researchAnswerToText(record)
    .split("\n")
    .map((line) => {
      if (/^[ABC]\. /.test(line)) return `<h2>${escapeHtml(line)}</h2>`;
      if (/^\d+\. /.test(line)) return `<h3>${escapeHtml(line)}</h3>`;
      if (/^\[\d+\] /.test(line)) return `<h4>${escapeHtml(line)}</h4>`;
      return line ? `<p>${escapeHtml(line)}</p>` : "";
    })
    .join("\n");
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>CaseOps research</title>
<style>body{font-family:Georgia,serif;max-width:46rem;margin:2rem auto;padding:0 1rem;line-height:1.55;color:#1d1d1f}h2{margin-top:2rem;border-bottom:1px solid #ccc}h4{margin-bottom:.2rem}</style>
</head><body>${body}</body></html>`;
}
