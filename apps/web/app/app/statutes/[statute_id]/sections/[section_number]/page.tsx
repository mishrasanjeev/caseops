"use client";

/**
 * MOD-TS-017 Slice S2 (2026-04-25). One section's bare text +
 * parent/children cross-refs.
 *
 * v1: section_text is nullable (Slice S3 backfill populates it from
 * the source). When NULL, render an empty state pointing at the
 * source URL so the lawyer can verify the bare text directly.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  FileText,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { SourceAction } from "@/components/app/SourceAction";
import { apiErrorMessage } from "@/lib/api/config";
import {
  decideStatuteSourceVersion,
  fetchStatuteSection,
  listStatuteSourceVersions,
  proposeStatuteSourceVersion,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

function SourceBadge({ source }: { source: string | null | undefined }) {
  if (!source) return null;
  const label =
    source === "indiacode_scrape"
      ? "indiacode"
      : source === "haiku_generated"
        ? "AI-generated"
        : source === "manual"
          ? "manual"
          : source;
  const tone =
    source === "haiku_generated"
      ? "border-amber-300 bg-amber-50 text-amber-900"
      : "border-[var(--color-line)] bg-[var(--color-bg-2)] text-[var(--color-mute-2)]";
  return (
    <span
      data-testid={`statute-section-source-${source}`}
      className={`ml-1 inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${tone}`}
    >
      {label}
    </span>
  );
}

function Metadata({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium text-[var(--color-mute)]">{label}</dt>
      <dd className="break-words text-[var(--color-ink)]">{value || "Not recorded"}</dd>
    </div>
  );
}

function ContentPanel({ title, label, text }: { title: string; label: string; text: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{label}</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="whitespace-pre-wrap text-sm text-[var(--color-ink-2)]">{text}</p>
      </CardContent>
    </Card>
  );
}

function SourceReviewPanel({
  section,
}: {
  section: Awaited<ReturnType<typeof fetchStatuteSection>>["section"];
}) {
  const queryClient = useQueryClient();
  const [candidateText, setCandidateText] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [publisher, setPublisher] = useState("India Code");
  const [issuingBody, setIssuingBody] = useState(
    "Legislative Department, Ministry of Law and Justice",
  );
  const [exactVersion, setExactVersion] = useState("");
  const [reason, setReason] = useState("");
  const versions = useQuery({
    queryKey: ["statutes", "source-versions", section.id],
    queryFn: () => listStatuteSourceVersions(section.id),
  });
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ["statutes", "source-versions", section.id],
      }),
      queryClient.invalidateQueries({
        queryKey: ["statutes", section.statute_id, "section"],
      }),
    ]);
  };
  const propose = useMutation({
    mutationFn: () =>
      proposeStatuteSourceVersion({
        sectionId: section.id,
        expected_source_version: section.source_version,
        candidate_text: candidateText,
        source_url: sourceUrl,
        source_publisher: publisher,
        issuing_body: issuingBody,
        source_status: "official",
        exact_source_version: exactVersion,
        retrieved_at: new Date().toISOString(),
      }),
    onSuccess: refresh,
  });
  const decide = useMutation({
    mutationFn: (input: {
      proposalId: string;
      decision: "approve" | "reject";
    }) =>
      decideStatuteSourceVersion({
        ...input,
        expected_source_version: section.source_version,
        reason,
      }),
    onSuccess: refresh,
  });

  return (
    <Card data-testid="statute-source-review-panel">
      <CardHeader>
        <CardTitle>Curator source review</CardTitle>
        <CardDescription>
          Proposals are immutable. A different legal reviewer must approve or reject them.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <form
          className="flex min-w-0 flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            propose.mutate();
          }}
        >
          <textarea
            aria-label="Candidate statutory text"
            data-testid="statute-source-candidate"
            className="min-h-36 w-full min-w-0 rounded-md border border-[var(--color-line)] p-3 text-sm"
            value={candidateText}
            onChange={(event) => setCandidateText(event.target.value)}
            placeholder="Exact statutory text from the proposed source"
          />
          <div className="grid min-w-0 gap-3 md:grid-cols-2">
            <Input aria-label="Section deep link" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="Official section-level HTTPS link" />
            <Input aria-label="Exact source version" value={exactVersion} onChange={(event) => setExactVersion(event.target.value)} placeholder="Exact consolidation or publication version" />
            <Input aria-label="Source publisher" value={publisher} onChange={(event) => setPublisher(event.target.value)} />
            <Input aria-label="Issuing body" value={issuingBody} onChange={(event) => setIssuingBody(event.target.value)} />
          </div>
          <div className="flex w-full min-w-0 flex-wrap gap-2">
            <Button type="submit" disabled={propose.isPending || candidateText.trim().length < 20 || !sourceUrl || !exactVersion}>
              Propose source version
            </Button>
          </div>
        </form>
        {propose.isError ? (
          <p className="text-sm text-[var(--color-danger)]">
            {apiErrorMessage(propose.error, "Could not create the source proposal.")}
          </p>
        ) : null}

        <div className="space-y-3">
          <Input aria-label="Independent review reason" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Independent comparison and decision reason" />
          {versions.data?.versions.map((version) => (
            <div key={version.id} className="min-w-0 rounded-md border border-[var(--color-line)] p-3 text-sm" data-testid={`statute-source-version-${version.id}`}>
              <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <p className="font-medium">Version {version.proposed_source_version} · {version.status}</p>
                  <p className="break-all text-xs text-[var(--color-mute)]">SHA-256 {version.candidate_sha256}</p>
                </div>
                {version.status === "pending" ? (
                  <div className="flex w-full min-w-0 flex-wrap gap-2 sm:w-auto">
                    <Button type="button" size="sm" disabled={decide.isPending || reason.trim().length < 5} onClick={() => decide.mutate({ proposalId: version.id, decision: "approve" })}>Approve</Button>
                    <Button type="button" size="sm" variant="outline" disabled={decide.isPending || reason.trim().length < 5} onClick={() => decide.mutate({ proposalId: version.id, decision: "reject" })}>Reject</Button>
                  </div>
                ) : null}
              </div>
              <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-[var(--color-bg-2)] p-2 text-xs">{version.diff_unified || "No textual difference."}</pre>
            </div>
          ))}
          {decide.isError ? (
            <p className="text-sm text-[var(--color-danger)]">
              {apiErrorMessage(decide.error, "Could not record the independent decision.")}
            </p>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

export default function StatuteSectionDetailPage() {
  const params = useParams<{
    statute_id: string;
    section_number: string;
  }>();
  const statuteId = params.statute_id;
  const sectionNumber = decodeURIComponent(params.section_number);
  const canCurate = useCapability("notifications:manage");

  const query = useQuery({
    queryKey: ["statutes", statuteId, "section", sectionNumber],
    queryFn: () => fetchStatuteSection(statuteId, sectionNumber),
    enabled: Boolean(statuteId && sectionNumber),
    staleTime: 30 * 60_000,
  });

  if (query.isPending) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (query.isError) {
    return (
      <QueryErrorState
        title="Could not load this section"
        error={query.error}
        onRetry={() => query.refetch()}
      />
    );
  }
  const data = query.data;
  if (!data) return null;
  const { statute, section, parent_section, child_sections } = data;
  const authoritative =
    section.verification_status === "verified_official" ||
    section.verification_status === "verified_licensed";

  return (
    <div className="flex flex-col gap-6">
      <Link
        href={`/app/statutes/${statute.id}`}
        className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--color-mute)] hover:text-[var(--color-ink)]"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Back to{" "}
        {statute.short_name}
      </Link>

      <PageHeader
        eyebrow={`${statute.short_name} · ${statute.long_name}`}
        title={section.section_number}
        description={section.section_label ?? "Section of the Act"}
        actions={
          <SourceAction action={section.source_action} originSurface="statute" />
        }
      />

      <Card data-testid="statute-section-text-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-4 w-4" aria-hidden /> Bare text
            <SourceBadge source={section.section_text_source} />
          </CardTitle>
          <CardDescription>
            {section.verification_status === "quarantined" || section.verification_status === "retired"
              ? `Quarantined: ${section.quarantine_reason ?? "curator verification required"}. The text is withheld.`
              : section.verification_status === "verified_official" || section.verification_status === "verified_licensed"
                ? `${section.source_publisher ?? "Verified publisher"}; curator-verified source version ${section.source_version}${section.source_sha256 ? ` (SHA-256 ${section.source_sha256.slice(0, 12)}â€¦)` : ""}.`
                : "Unverified legal text is withheld until curator verification."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {section.is_provisional ? (
            <div
              className="mb-4 flex items-start gap-2 rounded-[var(--radius-md)] border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900"
              data-testid="statute-section-provisional-warning"
            >
              <AlertTriangle
                className="mt-0.5 h-3.5 w-3.5 shrink-0"
                aria-hidden
              />
              <span>
                <strong className="font-semibold">Not activated:</strong>{" "}
                this material has not completed independent source review and
                cannot be used as binding statutory text.
              </span>
            </div>
          ) : null}
          {authoritative && section.section_text ? (
            <pre
              className="whitespace-pre-wrap text-sm text-[var(--color-ink)]"
              data-testid="statute-section-text"
            >
              {section.section_text}
            </pre>
          ) : (
            <EmptyState
              icon={FileText}
              title="Verified statutory text unavailable"
              description={
                section.verification_status === "quarantined"
                  ? "A credible source conflict is under legal review. Text and source actions remain disabled."
                  : "Only independently reviewed official or lawfully licensed section text is displayed here."
              }
            />
          )}
        </CardContent>
      </Card>

      <Card data-testid="statute-source-metadata">
        <CardHeader>
          <CardTitle>Source and legal status</CardTitle>
          <CardDescription>
            Provenance applies to this exact section version, not merely the Act landing page.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid min-w-0 gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
            <Metadata label="Publisher" value={section.source_publisher} />
            <Metadata label="Issuing body" value={section.issuing_body} />
            <Metadata label="Legal status" value={section.legal_status} />
            <Metadata label="Exact source version" value={section.exact_source_version} />
            <Metadata label="Effective from" value={section.effective_from} />
            <Metadata label="Effective to" value={section.effective_to ?? "Current / not recorded"} />
            <Metadata label="History coverage" value={section.history_status} />
            <Metadata label="Source locator" value={section.source_locator_type} />
            <Metadata label="Link health" value={section.link_health_status} />
            <Metadata label="Last checked" value={section.link_last_checked_at} />
          </dl>
          {statute.source_url ? (
            <a
              href={statute.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-4 inline-flex max-w-full items-center rounded-md border border-[var(--color-line)] px-3 py-2 text-sm font-medium"
              data-testid="statute-act-landing-page"
            >
              Open Act landing page (not a section deep link)
            </a>
          ) : null}
        </CardContent>
      </Card>

      {section.editorial_notes ? (
        <ContentPanel title="Editorial notes" label="Non-binding editorial material" text={section.editorial_notes} />
      ) : null}
      {section.case_annotations ? (
        <ContentPanel title="Case annotations" label="Non-binding research aid" text={section.case_annotations} />
      ) : null}
      {section.ai_explanation ? (
        <ContentPanel title="AI explanation" label="AI-generated; non-binding and not statutory text" text={section.ai_explanation} />
      ) : null}

      {canCurate ? <SourceReviewPanel section={section} /> : null}

      {parent_section ? (
        <Card>
          <CardHeader>
            <CardTitle>Parent section</CardTitle>
          </CardHeader>
          <CardContent>
            <Link
              href={`/app/statutes/${statute.id}/sections/${encodeURIComponent(parent_section.section_number)}`}
              className="block hover:text-[var(--color-brand-600)] hover:underline"
            >
              <div className="font-mono text-sm font-semibold">
                {parent_section.section_number}
              </div>
              {parent_section.section_label ? (
                <div className="text-xs text-[var(--color-mute)]">
                  {parent_section.section_label}
                </div>
              ) : null}
            </Link>
          </CardContent>
        </Card>
      ) : null}

      {child_sections.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Sub-sections</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="divide-y divide-[var(--color-line-2)]">
              {child_sections.map((c) => (
                <li key={c.id} className="py-2.5">
                  <Link
                    href={`/app/statutes/${statute.id}/sections/${encodeURIComponent(c.section_number)}`}
                    className="block hover:text-[var(--color-brand-600)]"
                  >
                    <div className="font-mono text-sm font-semibold">
                      {c.section_number}
                    </div>
                    {c.section_label ? (
                      <div className="text-xs text-[var(--color-mute)]">
                        {c.section_label}
                      </div>
                    ) : null}
                  </Link>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
