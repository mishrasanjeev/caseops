"use client";

import { useState } from "react";

import { Container } from "@/components/ui/Container";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { cn } from "@/lib/cn";

type Surface = {
  id: "cockpit" | "drafting" | "hearing";
  tab: string;
  headline: string;
  blurb: string;
  render: () => React.ReactNode;
};

function CockpitMock() {
  return (
    <div className="grid grid-cols-12 gap-0">
      <aside className="hidden border-r border-[var(--color-line)] bg-[var(--color-bg)] p-4 md:col-span-3 md:block">
        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
          Portfolio
        </div>
        <ul className="mt-3 space-y-1.5 text-sm">
          {[
            { m: "Arbitral award challenge", active: true, tag: "HC" },
            { m: "Trademark infringement", tag: "HC" },
            { m: "Shareholder oppression", tag: "NCLT" },
            { m: "Commercial suit — DHC", tag: "HC" },
            { m: "Bail — BNSS s.483", tag: "HC" },
            { m: "Debt recovery — DRT", tag: "DRT" },
          ].map((i) => (
            <li
              key={i.m}
              className={cn(
                "flex items-center justify-between rounded-md px-2.5 py-2",
                i.active
                  ? "bg-[var(--color-ink)] text-white"
                  : "text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]",
              )}
            >
              <span className="truncate">{i.m}</span>
              <span
                className={cn(
                  "ml-2 shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold",
                  i.active
                    ? "bg-white/15 text-white"
                    : "bg-[var(--color-bg-2)] text-[var(--color-mute-2)]",
                )}
              >
                {i.tag}
              </span>
            </li>
          ))}
        </ul>
        <div className="mt-6 rounded-md border border-dashed border-[var(--color-line)] p-3 text-xs leading-relaxed text-[var(--color-mute)]">
          <span className="font-semibold text-[var(--color-ink-2)]">Hearings this week</span>
          <br />3 listed · 1 needs pack
        </div>
      </aside>

      <div className="col-span-12 p-5 md:col-span-9 md:p-6">
        <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--color-mute)]">
          <span className="rounded-full bg-[var(--color-brand-50)] px-2 py-0.5 font-medium text-[var(--color-brand-700)]">
            Arbitration
          </span>
          <span className="rounded-full bg-[var(--color-bg-2)] px-2 py-0.5 font-medium text-[var(--color-ink-2)]">
            Stage · Setting aside
          </span>
          <span>Delhi HC · OMP (COMM) 314/2025</span>
          <span className="ml-auto font-semibold text-[var(--color-ink-2)]">
            Next hearing · 22 Apr
          </span>
        </div>

        <h3 className="mt-3 font-display text-xl font-normal leading-tight tracking-tight text-[var(--color-ink)]">
          Arbitral award challenge — Acme Pvt Ltd v. Kappa Infra
        </h3>
        <div className="mt-1 text-xs text-[var(--color-mute)]">
          Matter #M-2026-0431 · Partner · A. Menon · Associate · R. Iyer · Opened 04 Mar 2026
        </div>

        <div className="mt-5 flex gap-1 border-b border-[var(--color-line)] text-sm">
          {["Overview", "Documents", "Drafts", "Hearings", "Research", "Billing"].map(
            (tab, i) => (
              <div
                key={tab}
                className={cn(
                  "-mb-px border-b-2 px-3 py-2 text-[13px]",
                  i === 0
                    ? "border-[var(--color-ink)] font-semibold text-[var(--color-ink)]"
                    : "border-transparent text-[var(--color-mute-2)]",
                )}
              >
                {tab}
              </div>
            ),
          )}
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-3">
          {[
            { label: "Parties", v: "2 applicants · 3 respondents", sub: "Counsel assigned" },
            { label: "Documents", v: "41", sub: "38 indexed · 3 pending OCR" },
            { label: "Drafts", v: "2", sub: "v3 awaiting review" },
          ].map((s) => (
            <div
              key={s.label}
              className="rounded-lg border border-[var(--color-line)] bg-white p-3"
            >
              <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
                {s.label}
              </div>
              <div className="mt-1 font-mono text-lg font-medium tabular-nums text-[var(--color-ink)]">
                {s.v}
              </div>
              <div className="text-xs text-[var(--color-mute)]">{s.sub}</div>
            </div>
          ))}
        </div>

        <div className="mt-5 rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] p-4">
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
            Activity · last 24h
          </div>
          <ul className="mt-2 space-y-1.5 text-xs text-[var(--color-ink-2)]">
            <li className="flex gap-2">
              <span className="font-mono text-[var(--color-mute-2)]">09:14</span>
              R. Iyer uploaded <em className="not-italic font-semibold">Award_final.pdf</em>
            </li>
            <li className="flex gap-2">
              <span className="font-mono text-[var(--color-mute-2)]">11:02</span>
              Drafting Studio produced <em className="not-italic font-semibold">§34 petition v3</em>
            </li>
            <li className="flex gap-2">
              <span className="font-mono text-[var(--color-mute-2)]">14:31</span>
              Hearing pack compiled for 22 Apr listing
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
}

function DraftingMock() {
  return (
    <div className="grid grid-cols-12 gap-0">
      <div className="col-span-12 p-5 md:col-span-8 md:border-r md:border-[var(--color-line)] md:p-6">
        <div className="flex items-center gap-2 text-xs text-[var(--color-mute)]">
          <span className="rounded-full bg-[var(--color-brand-50)] px-2 py-0.5 font-medium text-[var(--color-brand-700)]">
            Drafting Studio
          </span>
          <span>§34 petition · v3 · 12:41</span>
          <span className="ml-auto font-semibold text-[var(--color-ink-2)]">
            Awaiting partner review
          </span>
        </div>

        <h3 className="mt-3 font-display text-xl font-normal leading-tight tracking-tight text-[var(--color-ink)]">
          Petition under §34 — grounds for setting aside
        </h3>

        <article className="mt-5 space-y-4 text-[13.5px] leading-[1.75] text-[var(--color-ink-2)]">
          <p>
            The impugned award dated 12 February 2026 is liable to be set aside on the ground
            of patent illegality appearing on the face of the record, as that expression was
            authoritatively explained in{" "}
            <span className="inline-flex items-baseline gap-1 rounded bg-[var(--color-brand-50)] px-1.5 py-0.5 font-medium text-[var(--color-brand-700)]">
              Ssangyong Engineering v. NHAI
              <span className="font-mono text-[10px] text-[var(--color-brand-600)]">
                (2019) 15 SCC 131
              </span>
            </span>
            . The learned tribunal has proceeded on a construction of Clause 14.2 that no
            reasonable tribunal could have reached on the plain language of the contract.
          </p>
          <p>
            Further, the tribunal has based findings on material not placed before the parties,
            thereby violating the principles of natural justice preserved by §34(2)(a)(iii).
            The principle is settled in{" "}
            <span className="inline-flex items-baseline gap-1 rounded bg-[var(--color-brand-50)] px-1.5 py-0.5 font-medium text-[var(--color-brand-700)]">
              Dyna Technologies v. Crompton Greaves
              <span className="font-mono text-[10px] text-[var(--color-brand-600)]">
                (2019) 20 SCC 1
              </span>
            </span>{" "}
            and <em>ONGC v. Saw Pipes</em>.
          </p>
          <p className="text-[var(--color-mute)]">
            <span className="font-semibold text-[var(--color-ink-2)]">[____]</span> the precise
            quantum of the counter-claim allowed is to be inserted from matter record before
            filing.
          </p>
        </article>
      </div>

      <aside className="col-span-12 border-t border-[var(--color-line)] p-5 md:col-span-4 md:border-t-0 md:p-6">
        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
          Grounding panel
        </div>
        <ul className="mt-3 space-y-3 text-[12.5px]">
          {[
            { case: "Ssangyong v. NHAI", cite: "(2019) 15 SCC 131", note: "Patent illegality — test affirmed" },
            { case: "Dyna Technologies v. Crompton Greaves", cite: "(2019) 20 SCC 1", note: "Natural justice — §34(2)(a)(iii)" },
            { case: "ONGC v. Saw Pipes", cite: "(2003) 5 SCC 705", note: "Public policy — per incuriam debate" },
          ].map((c) => (
            <li
              key={c.case}
              className="rounded-lg border border-[var(--color-line)] bg-white p-3"
            >
              <div className="text-[13px] font-semibold text-[var(--color-ink)]">{c.case}</div>
              <div className="font-mono text-[11px] text-[var(--color-mute-2)]">{c.cite}</div>
              <div className="mt-1 text-[12px] leading-relaxed text-[var(--color-mute)]">
                {c.note}
              </div>
            </li>
          ))}
        </ul>

        <div className="mt-5 rounded-lg border border-dashed border-[var(--color-line)] bg-[var(--color-bg)] p-3 text-[11.5px] leading-relaxed text-[var(--color-mute)]">
          <span className="font-semibold text-[var(--color-ink-2)]">Reviewer findings</span> —
          3 inline citations verified · 1 fact placeholder open · statute attribution clean
          (BNSS vs BNS).
        </div>
      </aside>
    </div>
  );
}

function HearingPackMock() {
  return (
    <div className="p-5 md:p-6">
      <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--color-mute)]">
        <span className="rounded-full bg-[var(--color-brand-50)] px-2 py-0.5 font-medium text-[var(--color-brand-700)]">
          Hearing pack
        </span>
        <span>22 Apr 2026 · Court 7 · Item 14</span>
        <span className="ml-auto font-semibold text-[var(--color-ink-2)]">
          Ready · 14:31
        </span>
      </div>

      <h3 className="mt-3 font-display text-xl font-normal leading-tight tracking-tight text-[var(--color-ink)]">
        Delhi High Court — hearing brief
      </h3>

      <div className="mt-5 grid gap-4 md:grid-cols-3">
        <div className="rounded-lg border border-[var(--color-line)] bg-white p-4">
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
            Chronology
          </div>
          <ol className="mt-3 space-y-2 text-[12.5px] text-[var(--color-ink-2)]">
            <li className="flex gap-2">
              <span className="font-mono text-[var(--color-mute-2)]">04 Mar</span> Award
              pronounced
            </li>
            <li className="flex gap-2">
              <span className="font-mono text-[var(--color-mute-2)]">20 Mar</span> §34 petition
              filed
            </li>
            <li className="flex gap-2">
              <span className="font-mono text-[var(--color-mute-2)]">02 Apr</span> Notice to
              respondents
            </li>
            <li className="flex gap-2">
              <span className="font-mono text-[var(--color-mute-2)]">18 Apr</span> Reply filed
              by Kappa
            </li>
            <li className="flex gap-2 text-[var(--color-ink)]">
              <span className="font-mono font-semibold">22 Apr</span>
              <span className="font-semibold">Listed — arguments</span>
            </li>
          </ol>
        </div>

        <div className="rounded-lg border border-[var(--color-line)] bg-white p-4">
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
            Oral points
          </div>
          <ul className="mt-3 space-y-2 text-[12.5px] text-[var(--color-ink-2)]">
            <li className="flex gap-2">
              <span
                aria-hidden
                className="mt-[8px] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-brand-500)]"
              />
              Patent illegality — Ssangyong frames the test; align Clause 14.2.
            </li>
            <li className="flex gap-2">
              <span
                aria-hidden
                className="mt-[8px] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-brand-500)]"
              />
              Natural justice — tribunal relied on spreadsheet never exhibited.
            </li>
            <li className="flex gap-2">
              <span
                aria-hidden
                className="mt-[8px] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-brand-500)]"
              />
              Respondents' delay point — limitation runs from receipt; file exists.
            </li>
          </ul>
        </div>

        <div className="rounded-lg border border-[var(--color-line)] bg-white p-4">
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--color-mute-2)]">
            Bench brief
          </div>
          <ul className="mt-3 space-y-2 text-[12.5px] text-[var(--color-ink-2)]">
            <li>
              <span className="font-semibold text-[var(--color-ink)]">Hon'ble Ms Justice R.</span>{" "}
              Reservation rate 62%; strict on pleadings; favours concise openings.
            </li>
            <li>
              <span className="font-semibold text-[var(--color-ink)]">Recent §34 trend</span>{" "}
              Natural-justice grounds succeed where record is documented.
            </li>
          </ul>
        </div>
      </div>

      <div className="mt-4 rounded-lg border border-dashed border-[var(--color-line)] bg-[var(--color-bg)] p-3 text-xs text-[var(--color-mute)]">
        <span className="font-semibold text-[var(--color-ink-2)]">Compile sources</span> —
        Matter record · Award PDF · 4 authorities from the CaseOps corpus · 2 internal
        precedents from Acme's own matter history.
      </div>
    </div>
  );
}

const surfaces: Surface[] = [
  {
    id: "cockpit",
    tab: "Matter cockpit",
    headline: "Every matter as one system of record.",
    blurb:
      "Parties, stage, documents, drafts, hearings, billing and audit — in one workspace, always in sync.",
    render: CockpitMock,
  },
  {
    id: "drafting",
    tab: "Drafting with citations",
    headline: "Drafts grounded in real authorities.",
    blurb:
      "Every inline citation resolves to a named judgment. Fact gaps render as placeholders, not fabrication.",
    render: DraftingMock,
  },
  {
    id: "hearing",
    tab: "Hearing pack",
    headline: "From cause list to brief in an afternoon.",
    blurb:
      "Chronology, last order, oral points and bench context compiled from the matter record in seconds.",
    render: HearingPackMock,
  },
];

export function ProductGallery() {
  const [active, setActive] = useState<Surface["id"]>("cockpit");
  const current = surfaces.find((s) => s.id === active) ?? surfaces[0];

  return (
    <section id="gallery" className="py-20 md:py-28">
      <Container>
        <SectionHeader
          eyebrow="Inside the product"
          title="Three surfaces. One matter graph."
          description="Cockpit, drafting and hearing prep share the same documents, parties and audit trail — no copy-paste between silos."
        />

        <div className="mt-12 flex flex-col items-stretch">
          <div
            role="tablist"
            aria-label="Product surfaces"
            className="mx-auto flex flex-wrap justify-center gap-1 rounded-full border border-[var(--color-line)] bg-white p-1 shadow-[var(--shadow-soft)]"
          >
            {surfaces.map((s) => (
              <button
                key={s.id}
                role="tab"
                type="button"
                aria-selected={active === s.id}
                aria-controls={`panel-${s.id}`}
                id={`tab-${s.id}`}
                onClick={() => setActive(s.id)}
                className={cn(
                  "rounded-full px-4 py-2 text-sm font-medium transition-colors",
                  active === s.id
                    ? "bg-[var(--color-ink)] text-white"
                    : "text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]",
                )}
              >
                {s.tab}
              </button>
            ))}
          </div>

          <div
            role="tabpanel"
            id={`panel-${current.id}`}
            aria-labelledby={`tab-${current.id}`}
            className="mt-8"
          >
            <div className="mx-auto max-w-2xl text-center">
              <h3 className="font-display text-2xl font-normal leading-tight tracking-tight text-[var(--color-ink)] md:text-[1.9rem]">
                {current.headline}
              </h3>
              <p className="mt-3 text-[15px] leading-relaxed text-[var(--color-mute)]">
                {current.blurb}
              </p>
            </div>

            <div className="relative mx-auto mt-8 max-w-5xl">
              <div className="relative overflow-hidden rounded-[20px] border border-[var(--color-line)] bg-white shadow-[var(--shadow-lifted)]">
                <div className="flex items-center gap-3 border-b border-[var(--color-line)] px-5 py-3">
                  <div className="flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f57]" />
                    <span className="h-2.5 w-2.5 rounded-full bg-[#febc2e]" />
                    <span className="h-2.5 w-2.5 rounded-full bg-[#28c840]" />
                  </div>
                  <div className="ml-3 flex-1 rounded-md bg-[var(--color-bg-2)] px-3 py-1 text-left text-xs text-[var(--color-mute-2)]">
                    caseops.ai / workspace / {current.id === "cockpit" ? "matters / arbitral-award-challenge" : current.id === "drafting" ? "matters / arbitral-award-challenge / drafts / v3" : "hearings / 22-apr-2026"}
                  </div>
                </div>
                {current.render()}
              </div>
            </div>
          </div>
        </div>
      </Container>
    </section>
  );
}
