import type { ComponentType, ReactNode } from "react";

import { Container } from "@/components/ui/Container";
import { cn } from "@/lib/cn";

export type SlideTone = "light" | "ink" | "brand";

export function Slide({
  id,
  index,
  eyebrow,
  title,
  description,
  tone,
  className,
  children,
}: {
  id: string;
  index: string;
  eyebrow: string;
  title: string;
  description: string;
  tone: SlideTone;
  className?: string;
  children: ReactNode;
}) {
  const isDark = tone === "ink";

  return (
    <section
      id={id}
      className={cn(
        "relative overflow-hidden border-b border-[var(--color-line)]",
        tone === "light" && "bg-white",
        tone === "ink" && "bg-[var(--color-ink)] text-white",
        tone === "brand" && "bg-[var(--color-bg-2)]",
        className,
      )}
    >
      <Container className="relative grid min-h-[88svh] content-center gap-10 py-16 md:min-h-[92svh] md:py-24">
        <div
          aria-hidden
          className={cn(
            "pointer-events-none absolute right-0 top-6 font-display text-[6rem] leading-none tracking-tight md:text-[10rem]",
            isDark ? "text-white/[0.06]" : "text-[var(--color-ink)]/[0.05]",
          )}
        >
          {index}
        </div>

        <div className="relative max-w-3xl">
          <div
            className={cn(
              "text-xs font-semibold uppercase tracking-[0.22em]",
              isDark ? "text-white/65" : "text-[var(--color-brand-600)]",
            )}
          >
            {eyebrow}
          </div>
          <h2
            className={cn(
              "mt-4 font-display text-4xl font-normal leading-[1.05] tracking-tight md:text-[3.25rem]",
              isDark ? "text-white" : "text-[var(--color-ink)]",
            )}
          >
            {title}
          </h2>
          <p
            className={cn(
              "mt-5 max-w-2xl text-[16.5px] leading-relaxed md:text-lg",
              isDark ? "text-white/75" : "text-[var(--color-mute)]",
            )}
          >
            {description}
          </p>
        </div>

        <div className={cn("relative", className)}>{children}</div>
      </Container>
    </section>
  );
}

export function PitchCard({
  title,
  body,
  icon: Icon,
  className,
  inverse,
}: {
  title: string;
  body: string;
  icon?: ComponentType<{ className?: string }>;
  className?: string;
  inverse?: boolean;
}) {
  const base = inverse
    ? "border-white/10 bg-white/5 text-white"
    : "border-[var(--color-line)] bg-white text-[var(--color-ink)]";
  const titleCls = inverse ? "text-white" : "text-[var(--color-ink)]";
  const bodyCls = inverse ? "text-white/75" : "text-[var(--color-mute)]";
  const iconBg = inverse
    ? "bg-white/10 text-white"
    : "bg-[var(--color-brand-50)] text-[var(--color-brand-700)]";
  return (
    <article
      className={cn(
        "flex flex-col gap-3 rounded-2xl border p-6 shadow-[var(--shadow-soft)]",
        base,
        className,
      )}
    >
      {Icon ? (
        <span
          className={cn(
            "inline-flex h-10 w-10 items-center justify-center rounded-xl",
            iconBg,
          )}
        >
          <Icon className="h-5 w-5" />
        </span>
      ) : null}
      <h3 className={cn("text-[15.5px] font-semibold leading-snug", titleCls)}>
        {title}
      </h3>
      <p className={cn("text-[14px] leading-relaxed", bodyCls)}>{body}</p>
    </article>
  );
}

export function ReviewRow({
  icon: Icon,
  title,
  body,
  inverse,
}: {
  icon: ComponentType<{ className?: string }>;
  title: string;
  body: string;
  inverse?: boolean;
}) {
  const titleCls = inverse ? "text-white" : "text-[var(--color-ink)]";
  const bodyCls = inverse ? "text-white/75" : "text-[var(--color-mute)]";
  const iconBg = inverse
    ? "bg-white/10 text-white"
    : "bg-[var(--color-brand-50)] text-[var(--color-brand-700)]";
  return (
    <div className="flex items-start gap-4">
      <span
        className={cn(
          "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
          iconBg,
        )}
      >
        <Icon className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className={cn("text-[14px] font-semibold", titleCls)}>{title}</div>
        <p className={cn("mt-1 text-[13px] leading-relaxed", bodyCls)}>{body}</p>
      </div>
    </div>
  );
}

export function MetricCard({
  label,
  value,
  note,
  inverse,
}: {
  label: string;
  value: string;
  note?: string;
  inverse?: boolean;
}) {
  const base = inverse
    ? "border-white/10 bg-white/5"
    : "border-[var(--color-line)] bg-white shadow-[var(--shadow-soft)]";
  const labelCls = inverse
    ? "text-white/55"
    : "text-[var(--color-mute-2)]";
  const valueCls = inverse ? "text-white" : "text-[var(--color-ink)]";
  const noteCls = inverse ? "text-white/60" : "text-[var(--color-mute)]";
  return (
    <div className={cn("rounded-2xl border p-5", base)}>
      <div className={cn("font-mono text-3xl font-medium leading-none tabular-nums", valueCls)}>
        {value}
      </div>
      <div
        className={cn(
          "mt-2 text-[11px] font-semibold uppercase tracking-[0.14em]",
          labelCls,
        )}
      >
        {label}
      </div>
      {note ? (
        <div className={cn("mt-1 text-[12.5px] leading-relaxed", noteCls)}>
          {note}
        </div>
      ) : null}
    </div>
  );
}

export function PitchNav({
  persona,
  slides,
  contactEmail,
}: {
  persona: "Law firms" | "General counsels" | "Solo lawyers";
  slides: readonly { id: string; label: string }[];
  contactEmail: string;
}) {
  return (
    <header className="sticky top-0 z-40 border-b border-[var(--color-line)] bg-white/92 backdrop-blur">
      <Container className="flex min-h-16 items-center justify-between gap-6 py-3">
        <a href="/" className="flex items-center gap-3 text-sm">
          <span className="font-display text-lg tracking-tight text-[var(--color-ink)]">
            CaseOps
          </span>
          <span className="hidden text-[var(--color-mute-2)] md:inline">
            · for {persona.toLowerCase()}
          </span>
        </a>

        <nav aria-label="Pitch sections" className="hidden items-center gap-5 lg:flex">
          {slides.map((slide) => (
            <a
              key={slide.id}
              href={`#${slide.id}`}
              className="text-[13.5px] text-[var(--color-mute)] transition-colors hover:text-[var(--color-ink)]"
            >
              {slide.label}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <a
            href="/"
            className="hidden rounded-full px-3 py-1.5 text-sm font-medium text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)] md:inline-flex"
          >
            Home
          </a>
          <a
            href={`mailto:${contactEmail}`}
            className="inline-flex items-center rounded-full bg-[var(--color-ink)] px-4 py-1.5 text-sm font-semibold text-white hover:bg-[var(--color-ink-2)]"
          >
            Talk to us
          </a>
        </div>
      </Container>
    </header>
  );
}

export function PersonaSwitch({
  active,
}: {
  active: "firms" | "gcs" | "solos";
}) {
  const items: { id: typeof active; label: string; href: string }[] = [
    { id: "firms", label: "Law firms", href: "/law-firms" },
    { id: "gcs", label: "General counsels", href: "/general-counsels" },
    { id: "solos", label: "Solo lawyers", href: "/solo-lawyers" },
  ];
  return (
    <div className="flex flex-wrap gap-1 rounded-full border border-[var(--color-line)] bg-white p-1 text-sm shadow-[var(--shadow-soft)]">
      {items.map((it) => (
        <a
          key={it.id}
          href={it.href}
          aria-current={active === it.id ? "page" : undefined}
          className={cn(
            "rounded-full px-4 py-1.5 font-medium transition-colors",
            active === it.id
              ? "bg-[var(--color-ink)] text-white"
              : "text-[var(--color-ink-2)] hover:bg-[var(--color-bg-2)]",
          )}
        >
          {it.label}
        </a>
      ))}
    </div>
  );
}
