import { notFound } from "next/navigation";
import { DemoRequestForm } from "@/components/marketing/DemoRequestForm";
import { Logo } from "@/components/marketing/Logo";
import type { DemoSegment, DemoSource } from "@/lib/demo-admission";

const entries: Record<string, { source: DemoSource; segment: DemoSegment; intent: "demo" | "pilot" }> = {
  "solo-lawyers": { source: "solo_lawyers", segment: "solo", intent: "pilot" },
  "law-firms": { source: "law_firms", segment: "firm", intent: "pilot" },
  "general-counsels": { source: "general_counsels", segment: "gc", intent: "pilot" },
  guide: { source: "guide", segment: "firm", intent: "demo" },
  resource: { source: "resource", segment: "firm", intent: "demo" },
};

export const metadata = { title: "Request a CaseOps conversation", robots: { index: false, follow: true } };

export default async function DemoPage({ params }: { params: Promise<{ source: string }> }) {
  const { source } = await params;
  const entry = Object.hasOwn(entries, source) ? entries[source] : undefined;
  if (!entry) notFound();
  return <main className="mx-auto max-w-2xl px-5 py-10">
    <Logo />
    <h1 className="mt-8 text-3xl font-semibold">Request a CaseOps conversation</h1>
    <p className="mb-8 mt-3 text-sm leading-relaxed text-[var(--color-mute)]">Discuss supported workflows and a possible pilot. Scheduling, coverage, duration and pricing are confirmed separately. A request is not a subscription or payment authorization.</p>
    <DemoRequestForm {...entry} />
  </main>;
}
