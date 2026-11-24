"use client";

// OCR & Translate review: the original document beside its OCR text or
// machine translation, page by page. Output stays labelled as machine
// output until a reviewer with documents:manage marks it reviewed.
//
// URL: /app/matters/{id}/documents/{attachment_id}/renditions
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  Eye,
  Languages,
  Loader2,
  RefreshCw,
  ScanText,
} from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import {
  attachmentRenditionsQueryKey,
  matterRenditionsQueryKey,
} from "@/components/document/OcrTranslateDialog";
import { RenditionStatusBadge } from "@/components/document/RenditionStatusBadge";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Label } from "@/components/ui/Label";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  createRenditionTranslation,
  downloadAttachmentRendition,
  fetchAttachmentRendition,
  fetchMatterAttachmentBlob,
  listAttachmentRenditions,
  matterAttachmentDownloadUrl,
  retryAttachmentRendition,
  reviewAttachmentRendition,
  type RenditionDetail,
  type RenditionLanguage,
  type RenditionPage,
  type RenditionProviderReadiness,
  type RenditionReviewStatusInput,
  type RenditionSummary,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";
import { cn } from "@/lib/cn";
import { formatLegalDate } from "@/lib/dates";
import {
  isRenditionActive,
  languageLabel,
  pageReasonLabel,
  pageSourceLabel,
  pageStatusLabel,
  providerReasonLabel,
  renditionKindLabel,
  renditionStatusLabel,
  renditionStatusTone,
  reviewStatusLabel,
  translationFlagLabel,
  translationTargets,
} from "@/lib/renditions";

const PDFViewer = dynamic(
  () => import("@/components/document/PDFViewer").then((m) => m.PDFViewer),
  {
    ssr: false,
    loading: () => <Skeleton className="h-[480px] w-full" aria-label="Loading original" />,
  },
);

const DATE_OPTIONS: Intl.DateTimeFormatOptions = {
  day: "numeric",
  month: "short",
  year: "numeric",
};

const selectClass =
  "h-9 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm text-[var(--color-ink)] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-500)] disabled:cursor-not-allowed disabled:bg-[var(--color-bg-2)]";

type MobilePane = "original" | "processed";

function dateLabel(value: string | null | undefined): string {
  return formatLegalDate(value ?? null, DATE_OPTIONS);
}

function languagesLabel(rendition: RenditionSummary): string {
  const source = languageLabel(rendition.source_language);
  if (rendition.kind === "translation" && rendition.target_language) {
    return `${source} to ${languageLabel(rendition.target_language)}`;
  }
  return source;
}

function versionLabel(rendition: RenditionSummary): string {
  return `${renditionKindLabel(rendition.kind)} v${rendition.version}`;
}

function isImageName(name: string): boolean {
  return /\.(png|jpe?g)$/i.test(name);
}

function pageCopyText(rendition: RenditionDetail, page: RenditionPage | undefined): string {
  if (!page) return "";
  if (rendition.kind === "translation") {
    return (page.paragraphs ?? [])
      .map((paragraph) => paragraph.translated ?? "")
      .filter((text) => text.trim().length > 0)
      .join("\n\n");
  }
  return page.text ?? "";
}

function reviewLine(rendition: RenditionSummary): string {
  const machine =
    rendition.kind === "translation" ? "Machine translation" : "Machine OCR text";
  const who = rendition.reviewed_by_name ?? "a reviewer";
  if (rendition.review_status === "reviewed") {
    return `Reviewed by ${who} on ${dateLabel(rendition.reviewed_at)}`;
  }
  if (rendition.review_status === "needs_correction") {
    return `${machine} — marked as needing correction by ${who} on ${dateLabel(rendition.reviewed_at)}`;
  }
  return `${machine} — not reviewed`;
}

function isFinished(rendition: RenditionSummary): boolean {
  return (
    rendition.status === "ocr_completed" ||
    rendition.status === "translation_completed" ||
    rendition.status === "review_required"
  );
}

export default function AttachmentRenditionsPage() {
  const params = useParams<{ id: string; attachment_id: string }>();
  const matterId = params?.id ?? "";
  const attachmentId = params?.attachment_id ?? "";
  const canUpload = useCapability("documents:upload");
  const canManage = useCapability("documents:manage");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [mobilePane, setMobilePane] = useState<MobilePane>("processed");

  const documentsHref = `/app/matters/${encodeURIComponent(matterId)}/documents`;
  const viewOriginalHref = `${documentsHref}/${encodeURIComponent(attachmentId)}/view`;

  const listQuery = useQuery({
    queryKey: attachmentRenditionsQueryKey(matterId, attachmentId),
    queryFn: () => listAttachmentRenditions({ matterId, attachmentId }),
    enabled: Boolean(matterId && attachmentId),
    refetchInterval: (query) =>
      query.state.data?.renditions.some(isRenditionActive) ? 2000 : false,
  });
  const renditions = useMemo(() => listQuery.data?.renditions ?? [], [listQuery.data]);
  const selected =
    renditions.find((item) => item.id === selectedId) ?? renditions[0] ?? null;

  const detailQuery = useQuery({
    queryKey: [...attachmentRenditionsQueryKey(matterId, attachmentId), selected?.id ?? ""],
    queryFn: () =>
      fetchAttachmentRendition({ matterId, attachmentId, renditionId: selected!.id }),
    enabled: Boolean(selected),
    refetchInterval: (query) =>
      query.state.data && isRenditionActive(query.state.data) ? 2000 : false,
  });
  const detail = detailQuery.data?.id === selected?.id ? detailQuery.data : undefined;
  const filename = detail?.attachment_filename ?? "";
  const pageTotal = Math.max(detail?.page_count ?? 0, detail?.pages.length ?? 0, 1);
  const currentPage = Math.min(Math.max(page, 1), pageTotal);

  const goToPage = (next: number) => setPage(Math.min(Math.max(next, 1), pageTotal));

  const selectVersion = (id: string) => {
    setSelectedId(id);
    setPage(1);
  };

  if (listQuery.isPending) {
    return (
      <div className="flex flex-col gap-4" data-testid="renditions-loading" aria-busy="true">
        <span className="sr-only">Loading OCR and translation versions</span>
        <Skeleton className="h-7 w-72" />
        <Skeleton className="h-24 w-full" />
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-[420px] w-full" />
          <Skeleton className="h-[420px] w-full" />
        </div>
      </div>
    );
  }
  if (listQuery.isError) {
    return (
      <QueryErrorState
        title="Could not load OCR and translation versions"
        error={listQuery.error}
        onRetry={listQuery.refetch}
        secondaryAction={
          <Button variant="outline" size="sm" href={documentsHref}>
            Back to documents
          </Button>
        }
      />
    );
  }

  const providers = listQuery.data.providers;
  const relatedOcr =
    selected?.kind === "translation"
      ? (renditions.find((item) => item.id === selected.source_rendition_id) ??
        renditions.find((item) => item.kind === "ocr") ??
        null)
      : selected;
  const relatedTranslation =
    selected?.kind === "ocr"
      ? (renditions.find(
          (item) => item.kind === "translation" && item.source_rendition_id === selected.id,
        ) ??
        renditions.find((item) => item.kind === "translation") ??
        null)
      : selected;

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <header className="flex flex-col gap-3">
        <Link
          href={documentsHref}
          className="inline-flex w-fit items-center gap-1.5 text-sm text-[var(--color-mute)] hover:text-[var(--color-ink)] hover:underline"
          data-testid="renditions-back"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden />
          Back to documents
        </Link>
        <div className="flex flex-col gap-1">
          <p className="text-xs font-semibold uppercase tracking-[0.06em] text-[var(--color-mute)]">
            Original vs processed
          </p>
          <h2
            className="font-serif text-xl text-[var(--color-ink)] [overflow-wrap:anywhere]"
            data-testid="renditions-filename"
          >
            {filename ||
              (selected ? (
                <span
                  className="inline-block h-6 w-56 max-w-full animate-pulse rounded-md bg-[var(--color-bg-2)] align-middle"
                  aria-label="Loading file name"
                />
              ) : (
                "OCR & Translate"
              ))}
          </h2>
        </div>
      </header>

      {!selected ? (
        <EmptyState
          icon={ScanText}
          title="No OCR or translation versions yet"
          description="Run OCR & Translate from the document's row on the Documents page. Each run is kept here as a version you can compare with the original."
          action={
            <Button variant="outline" size="sm" href={documentsHref}>
              Back to documents
            </Button>
          }
        />
      ) : (
        <>
          <VersionPicker
            renditions={renditions}
            selectedId={selected.id}
            onSelect={selectVersion}
          />

          <div
            className="flex flex-wrap items-center gap-2"
            role="toolbar"
            aria-label="Version actions"
          >
            <Button variant="outline" size="sm" href={viewOriginalHref} data-testid="renditions-view-original">
              <Eye className="h-4 w-4" aria-hidden />
              View Original
            </Button>
            <Button
              type="button"
              variant={selected.kind === "ocr" ? "primary" : "outline"}
              size="sm"
              aria-pressed={selected.kind === "ocr"}
              disabled={!relatedOcr}
              onClick={() => relatedOcr && selectVersion(relatedOcr.id)}
              data-testid="renditions-view-ocr"
            >
              <ScanText className="h-4 w-4" aria-hidden />
              View OCR
            </Button>
            <Button
              type="button"
              variant={selected.kind === "translation" ? "primary" : "outline"}
              size="sm"
              aria-pressed={selected.kind === "translation"}
              disabled={!relatedTranslation}
              onClick={() => relatedTranslation && selectVersion(relatedTranslation.id)}
              data-testid="renditions-view-translation"
            >
              <Languages className="h-4 w-4" aria-hidden />
              View Translation
            </Button>
            {selected.has_output_file ? (
              <DownloadButton
                matterId={matterId}
                attachmentId={attachmentId}
                rendition={selected}
                filename={filename}
              />
            ) : null}
            {canUpload && selected.retry_allowed ? (
              <RetryButton matterId={matterId} attachmentId={attachmentId} rendition={selected} />
            ) : null}
          </div>

          <VersionStatus rendition={selected} detail={detail} />

          {canUpload && selected.kind === "ocr" && isFinished(selected) &&
          selected.pages_ok + selected.pages_review > 0 &&
          !renditions.some(
            (item) => item.kind === "translation" && item.source_rendition_id === selected.id,
          ) ? (
            <TranslatePanel
              key={`translate-${selected.id}`}
              matterId={matterId}
              attachmentId={attachmentId}
              rendition={selected}
              providers={providers}
              onCreated={(id) => selectVersion(id)}
            />
          ) : null}

          {canManage && isFinished(selected) ? (
            <ReviewPanel
              key={`review-${selected.id}`}
              matterId={matterId}
              attachmentId={attachmentId}
              rendition={selected}
            />
          ) : null}

          <div
            className="flex flex-col gap-3"
            data-testid="renditions-compare"
            onKeyDown={(event) => {
              if (event.defaultPrevented) return;
              const tag = (event.target as HTMLElement).tagName;
              if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
              if (event.key === "ArrowLeft") {
                event.preventDefault();
                goToPage(currentPage - 1);
              } else if (event.key === "ArrowRight") {
                event.preventDefault();
                goToPage(currentPage + 1);
              }
            }}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div
                className="inline-flex rounded-md border border-[var(--color-line)] p-0.5 lg:hidden"
                role="group"
                aria-label="Pane to show"
              >
                {(["original", "processed"] as const).map((pane) => (
                  <button
                    key={pane}
                    type="button"
                    aria-pressed={mobilePane === pane}
                    onClick={() => setMobilePane(pane)}
                    className={cn(
                      "h-8 rounded px-3 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-brand-500)]",
                      mobilePane === pane
                        ? "bg-[var(--color-ink)] text-white"
                        : "text-[var(--color-ink-2)]",
                    )}
                    data-testid={`renditions-pane-${pane}`}
                  >
                    {pane === "original" ? "Original" : "Processed"}
                  </button>
                ))}
              </div>
              <nav className="flex items-center gap-2" aria-label="Page navigation">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={currentPage <= 1}
                  onClick={() => goToPage(currentPage - 1)}
                  data-testid="renditions-prev-page"
                >
                  <ChevronLeft className="h-4 w-4" aria-hidden />
                  Previous
                </Button>
                <span
                  className="min-w-[6.5rem] text-center text-sm tabular-nums text-[var(--color-ink-2)]"
                  aria-live="polite"
                  data-testid="renditions-page-indicator"
                >
                  Page {currentPage} of {pageTotal}
                </span>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={currentPage >= pageTotal}
                  onClick={() => goToPage(currentPage + 1)}
                  data-testid="renditions-next-page"
                >
                  Next
                  <ChevronRight className="h-4 w-4" aria-hidden />
                </Button>
              </nav>
            </div>

            <div className="grid min-w-0 gap-4 lg:grid-cols-2">
              <section
                aria-label="Original document"
                className={cn(
                  "min-w-0 flex-col",
                  mobilePane === "original" ? "flex" : "hidden lg:flex",
                )}
                data-testid="renditions-original-pane"
              >
                <OriginalPane
                  matterId={matterId}
                  attachmentId={attachmentId}
                  filename={filename}
                  page={currentPage}
                  onPageChange={goToPage}
                />
              </section>
              <section
                aria-label={
                  selected.kind === "translation" ? "Machine translation" : "OCR text"
                }
                tabIndex={0}
                className={cn(
                  "min-w-0 flex-col rounded-md border border-[var(--color-line)] bg-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-brand-500)]",
                  mobilePane === "processed" ? "flex" : "hidden lg:flex",
                )}
                data-testid="renditions-processed-pane"
              >
                {detailQuery.isError ? (
                  <QueryErrorState
                    title="Could not load this version"
                    error={detailQuery.error}
                    onRetry={detailQuery.refetch}
                    className="border-0"
                  />
                ) : !detail ? (
                  <div className="flex flex-col gap-3 p-4" aria-busy="true" data-testid="renditions-detail-loading">
                    <span className="sr-only">Loading page text</span>
                    <Skeleton className="h-4 w-1/3" />
                    <Skeleton className="h-4 w-full" />
                    <Skeleton className="h-4 w-11/12" />
                    <Skeleton className="h-4 w-4/5" />
                  </div>
                ) : (
                  <ProcessedPage detail={detail} pageNumber={currentPage} />
                )}
              </section>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function VersionPicker({
  renditions,
  selectedId,
  onSelect,
}: {
  renditions: RenditionSummary[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <section aria-labelledby="renditions-versions-title" className="flex flex-col gap-2">
      <h3
        id="renditions-versions-title"
        className="text-xs font-semibold uppercase tracking-[0.06em] text-[var(--color-mute)]"
      >
        Versions
      </h3>
      <ul
        className="flex max-h-64 flex-col overflow-y-auto rounded-md border border-[var(--color-line)] bg-white"
        data-testid="renditions-version-list"
      >
        {renditions.map((rendition) => {
          const active = rendition.id === selectedId;
          return (
            <li key={rendition.id} className="border-b border-[var(--color-line-2)] last:border-0">
              <button
                type="button"
                aria-pressed={active}
                onClick={() => onSelect(rendition.id)}
                className={cn(
                  "grid w-full gap-x-4 gap-y-1 px-3 py-2 text-left text-sm focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--color-brand-500)] sm:grid-cols-[minmax(7rem,auto)_1fr_auto]",
                  active ? "bg-[var(--color-brand-50)]" : "hover:bg-[var(--color-bg)]",
                )}
                data-testid={`renditions-version-${rendition.id}`}
              >
                <span className="font-medium text-[var(--color-ink)]">
                  {versionLabel(rendition)}
                  {active ? <span className="sr-only"> (shown)</span> : null}
                </span>
                <span className="min-w-0 text-[var(--color-ink-2)]">
                  {languagesLabel(rendition)}
                  <span className="text-[var(--color-mute)]">
                    {" · "}
                    {reviewStatusLabel(rendition)}
                    {" · "}
                    {rendition.requested_by_name ?? "Unknown requester"}
                    {" · "}
                    <span className="tabular-nums">{dateLabel(rendition.created_at)}</span>
                  </span>
                </span>
                <span>
                  <RenditionStatusBadge
                    label={renditionStatusLabel(rendition)}
                    tone={renditionStatusTone(rendition.status)}
                  />
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function VersionStatus({
  rendition,
  detail,
}: {
  rendition: RenditionSummary;
  detail: RenditionDetail | undefined;
}) {
  const active = isRenditionActive(rendition);
  return (
    <div className="flex flex-col gap-2 text-sm" data-testid="renditions-version-status">
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[var(--color-ink-2)]">
        <span className="font-medium text-[var(--color-ink)]">{versionLabel(rendition)}</span>
        <RenditionStatusBadge
          label={renditionStatusLabel(rendition)}
          tone={renditionStatusTone(rendition.status)}
        />
        <span className="tabular-nums">
          {rendition.pages_ok} read · {rendition.pages_review} need review · {rendition.pages_failed}{" "}
          unread of {rendition.page_count} pages
        </span>
      </p>
      <p
        className={cn(
          "w-fit rounded-md border px-2.5 py-1 text-sm",
          rendition.review_status === "reviewed"
            ? "border-[var(--color-success-300)] bg-[var(--color-success-50)] text-[var(--color-success-700)]"
            : "border-[var(--color-warn-border)] bg-[var(--color-warn-bg)] text-[var(--color-warn-text)]",
        )}
        data-testid="renditions-review-line"
      >
        {reviewLine(rendition)}
      </p>
      {rendition.review_note ? (
        <p className="text-[var(--color-mute)]">Review note: {rendition.review_note}</p>
      ) : null}
      {active ? (
        <p className="inline-flex items-center gap-2 text-[var(--color-mute)]" role="status">
          <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden />
          Processing. This page updates on its own.
        </p>
      ) : null}
      {rendition.status === "failed" || rendition.error_message ? (
        <p
          role="alert"
          className="rounded-md border border-[var(--color-danger-border)] bg-[var(--color-danger-bg)] px-3 py-2 text-[var(--color-danger-text)]"
          data-testid="renditions-error"
        >
          {rendition.error_message ?? "This version failed."}
        </p>
      ) : null}
      {detail && detail.failed_pages.length > 0 ? (
        <p className="text-[var(--color-ink-2)]" data-testid="renditions-failed-pages">
          Unread pages:{" "}
          <span className="tabular-nums">{detail.failed_pages.join(", ")}</span>
        </p>
      ) : null}
      {detail && detail.review_pages.length > 0 ? (
        <p className="text-[var(--color-ink-2)]" data-testid="renditions-review-pages">
          Pages needing review:{" "}
          <span className="tabular-nums">{detail.review_pages.join(", ")}</span>
        </p>
      ) : null}
    </div>
  );
}

function OriginalPane({
  matterId,
  attachmentId,
  filename,
  page,
  onPageChange,
}: {
  matterId: string;
  attachmentId: string;
  filename: string;
  page: number;
  onPageChange: (page: number) => void;
}) {
  const image = isImageName(filename);
  const imageQuery = useQuery({
    queryKey: ["matter-attachment-image", matterId, attachmentId],
    queryFn: ({ signal }) =>
      fetchMatterAttachmentBlob({ matterId, attachmentId, inline: true, signal }),
    enabled: Boolean(filename) && image,
  });
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!imageQuery.data) {
      setImageUrl(null);
      return;
    }
    const objectUrl = URL.createObjectURL(imageQuery.data);
    setImageUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [imageQuery.data]);

  if (!filename) {
    return <Skeleton className="h-[420px] w-full" />;
  }
  if (image) {
    return (
      <div className="flex min-h-[320px] items-start justify-center overflow-auto rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] p-3">
        {imageUrl ? (
          <img src={imageUrl} alt={`Original: ${filename}`} className="h-auto max-w-full" />
        ) : imageQuery.isError ? (
          <p className="text-sm text-[var(--color-danger-text)]">
            The original image could not be shown. Use View Original to open it.
          </p>
        ) : (
          <Skeleton className="h-[320px] w-full" />
        )}
      </div>
    );
  }
  return (
    <PDFViewer
      url={matterAttachmentDownloadUrl({ matterId, attachmentId, inline: true })}
      filename={filename}
      page={page}
      onPageChange={onPageChange}
      className="min-h-[480px]"
    />
  );
}

function ProcessedPage({ detail, pageNumber }: { detail: RenditionDetail; pageNumber: number }) {
  const page = detail.pages.find((item) => item.page === pageNumber);
  const copy = async (text: string, success: string) => {
    if (!text.trim()) {
      toast.error("There is no text to copy.");
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      toast.success(success);
    } catch {
      toast.error("Could not copy to the clipboard.");
    }
  };
  const copyAll = () =>
    copy(
      detail.pages
        .map((item) => {
          const text = pageCopyText(detail, item);
          return text.trim() ? `Page ${item.page}\n\n${text}` : "";
        })
        .filter(Boolean)
        .join("\n\n"),
      "All pages copied",
    );

  return (
    <div className="flex min-w-0 flex-col">
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-[var(--color-line)] px-4 py-3">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-sm" data-testid="renditions-page-meta">
          <dt className="text-[var(--color-mute)]">Read from</dt>
          <dd className="text-[var(--color-ink)]">{page ? pageSourceLabel(page.source) : "Not read"}</dd>
          <dt className="text-[var(--color-mute)]">Status</dt>
          <dd className="text-[var(--color-ink)]">
            {page ? pageStatusLabel(page.status) : "Not available"}
            {page && (page.reasons ?? []).length > 0 ? (
              <span className="text-[var(--color-mute)]">
                {" — "}
                {(page.reasons ?? []).map(pageReasonLabel).join("; ")}
              </span>
            ) : null}
          </dd>
        </dl>
        <div className="flex gap-1">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => void copy(pageCopyText(detail, page), "Page copied")}
            data-testid="renditions-copy-page"
          >
            <Copy className="h-4 w-4" aria-hidden />
            Copy page
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => void copyAll()}
            data-testid="renditions-copy-all"
          >
            <Copy className="h-4 w-4" aria-hidden />
            Copy all
          </Button>
        </div>
      </div>
      <div className="max-h-[70vh] overflow-y-auto px-4 py-4">
        {!page ? (
          <p className="text-sm text-[var(--color-mute)]">
            This page has not been processed yet.
          </p>
        ) : detail.kind === "translation" ? (
          <TranslationParagraphs detail={detail} page={page} />
        ) : page.text && page.text.trim() ? (
          <div
            className="max-w-[70ch] whitespace-pre-wrap text-[0.9375rem] leading-relaxed text-[var(--color-ink)] [overflow-wrap:anywhere]"
            lang={detail.source_language}
            data-testid="renditions-ocr-text"
          >
            {page.text}
          </div>
        ) : (
          <p className="text-sm text-[var(--color-mute)]" data-testid="renditions-no-text">
            No text was read from this page.
          </p>
        )}
      </div>
    </div>
  );
}

function TranslationParagraphs({ detail, page }: { detail: RenditionDetail; page: RenditionPage }) {
  if (!page.paragraphs?.length) {
    return <p className="text-sm text-[var(--color-mute)]">No text on this page to translate.</p>;
  }
  const sourceName = languageLabel(detail.source_language);
  const targetName = languageLabel(detail.target_language);
  return (
    <ol className="flex flex-col gap-4" data-testid="renditions-paragraphs">
      {page.paragraphs.map((paragraph) => {
        const details = [
          ["Missing numbers", paragraph.missing_numbers ?? []],
          ["Added numbers", paragraph.added_numbers ?? []],
          ["Missing identifiers", paragraph.missing_identifiers ?? []],
          ["Missing abbreviations", paragraph.missing_abbreviations ?? []],
        ] as const;
        return (
          <li
            key={paragraph.index}
            className="flex flex-col gap-2 border-b border-[var(--color-line-2)] pb-4 last:border-0"
            data-testid={`renditions-paragraph-${paragraph.index}`}
          >
            {paragraph.flags?.length ? (
              <ul className="flex flex-wrap gap-1.5" aria-label="Review flags">
                {paragraph.flags.map((flag) => (
                  <li key={flag}>
                    <RenditionStatusBadge label={translationFlagLabel(flag)} tone="warning" />
                  </li>
                ))}
              </ul>
            ) : null}
            <div className="grid gap-3 md:grid-cols-2">
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-[0.06em] text-[var(--color-mute)]">
                  Source ({sourceName})
                </p>
                {paragraph.source_unavailable ? (
                  <p className="mt-1 text-sm text-[var(--color-mute)]">Source page unreadable.</p>
                ) : (
                  <p
                    className="mt-1 max-w-[70ch] whitespace-pre-wrap text-sm leading-relaxed text-[var(--color-ink-2)] [overflow-wrap:anywhere]"
                    lang={detail.source_language}
                  >
                    {paragraph.source}
                  </p>
                )}
              </div>
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-[0.06em] text-[var(--color-mute)]">
                  Translation ({targetName})
                </p>
                <p
                  className="mt-1 max-w-[70ch] whitespace-pre-wrap text-[0.9375rem] leading-relaxed text-[var(--color-ink)] [overflow-wrap:anywhere]"
                  lang={detail.target_language ?? undefined}
                >
                  {paragraph.translated ?? (
                    <span className="text-sm text-[var(--color-mute)]">Not translated.</span>
                  )}
                </p>
              </div>
            </div>
            {details.some(([, values]) => values.length > 0) ? (
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
                {details
                  .filter(([, values]) => values.length > 0)
                  .map(([label, values]) => (
                    <div key={label} className="contents">
                      <dt className="text-[var(--color-mute)]">{label}</dt>
                      <dd className="font-mono tabular-nums text-[var(--color-ink-2)] [overflow-wrap:anywhere]">
                        {values.join(", ")}
                      </dd>
                    </div>
                  ))}
              </dl>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

function useRenditionInvalidation(matterId: string, attachmentId: string) {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({
        queryKey: attachmentRenditionsQueryKey(matterId, attachmentId),
      }),
      queryClient.invalidateQueries({ queryKey: matterRenditionsQueryKey(matterId) }),
    ]);
}

function DownloadButton({
  matterId,
  attachmentId,
  rendition,
  filename,
}: {
  matterId: string;
  attachmentId: string;
  rendition: RenditionSummary;
  filename: string;
}) {
  const download = useMutation({
    mutationFn: () =>
      downloadAttachmentRendition({
        matterId,
        attachmentId,
        renditionId: rendition.id,
        fallbackName: `${filename.replace(/\.[^.]+$/, "") || "document"}-translation-v${rendition.version}.pdf`,
      }),
    onError: (err) => toast.error(apiErrorMessage(err, "Could not download the translated PDF.")),
  });
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      disabled={download.isPending}
      onClick={() => download.mutate()}
      data-testid="renditions-download"
    >
      {download.isPending ? (
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      ) : (
        <Download className="h-4 w-4" aria-hidden />
      )}
      Download Translated PDF
    </Button>
  );
}

function RetryButton({
  matterId,
  attachmentId,
  rendition,
}: {
  matterId: string;
  attachmentId: string;
  rendition: RenditionSummary;
}) {
  const invalidate = useRenditionInvalidation(matterId, attachmentId);
  const retry = useMutation({
    mutationFn: () =>
      retryAttachmentRendition({ matterId, attachmentId, renditionId: rendition.id }),
    onSuccess: async (result) => {
      toast.success(result.created ? "Retry queued" : "Already running");
      await invalidate();
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not retry this version.")),
  });
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      disabled={retry.isPending}
      onClick={() => retry.mutate()}
      data-testid="renditions-retry"
    >
      {retry.isPending ? (
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      ) : (
        <RefreshCw className="h-4 w-4" aria-hidden />
      )}
      Retry
    </Button>
  );
}

function TranslatePanel({
  matterId,
  attachmentId,
  rendition,
  providers,
  onCreated,
}: {
  matterId: string;
  attachmentId: string;
  rendition: RenditionSummary;
  providers: RenditionProviderReadiness;
  onCreated: (id: string) => void;
}) {
  const targets = translationTargets(providers, rendition.source_language);
  const [target, setTarget] = useState<RenditionLanguage | "">(targets[0] ?? "");
  const invalidate = useRenditionInvalidation(matterId, attachmentId);
  const translate = useMutation({
    mutationFn: (targetLanguage: RenditionLanguage) =>
      createRenditionTranslation({
        matterId,
        attachmentId,
        ocrRenditionId: rendition.id,
        targetLanguage,
      }),
    onSuccess: async (result) => {
      toast.success(result.created ? "Translation queued" : "Already running");
      await invalidate();
      onCreated(result.rendition.id);
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not start the translation.")),
  });
  const unavailable = !providers.translation_available || targets.length === 0;
  const reason = !providers.translation_available
    ? `Translation is unavailable. ${providerReasonLabel(providers.translation_unavailable_reason)}`
    : targets.length === 0
      ? `No translation is offered from ${languageLabel(rendition.source_language)}.`
      : null;

  return (
    <form
      className="flex flex-col gap-2 rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] p-3 sm:flex-row sm:flex-wrap sm:items-end"
      onSubmit={(event) => {
        event.preventDefault();
        if (target && !unavailable && !translate.isPending) translate.mutate(target);
      }}
      data-testid="renditions-translate"
    >
      <div className="min-w-0 flex-1 sm:max-w-xs">
        <Label htmlFor="renditions-translate-target">Translate this OCR version to</Label>
        <select
          id="renditions-translate-target"
          className={cn(selectClass, "mt-1.5")}
          value={target}
          disabled={unavailable}
          aria-describedby={reason ? "renditions-translate-reason" : undefined}
          onChange={(event) => setTarget(event.target.value as RenditionLanguage)}
        >
          {targets.map((code) => (
            <option key={code} value={code}>
              {languageLabel(code)}
            </option>
          ))}
        </select>
      </div>
      <Button
        type="submit"
        size="sm"
        disabled={unavailable || !target || translate.isPending}
        data-testid="renditions-translate-start"
      >
        {translate.isPending ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        ) : (
          <Languages className="h-4 w-4" aria-hidden />
        )}
        Translate
      </Button>
      {reason ? (
        <p id="renditions-translate-reason" className="text-xs text-[var(--color-mute)] sm:basis-full">
          {reason}
        </p>
      ) : null}
    </form>
  );
}

function ReviewPanel({
  matterId,
  attachmentId,
  rendition,
}: {
  matterId: string;
  attachmentId: string;
  rendition: RenditionSummary;
}) {
  const [note, setNote] = useState("");
  const [noteError, setNoteError] = useState<string | null>(null);
  const invalidate = useRenditionInvalidation(matterId, attachmentId);
  const noteRequired = rendition.pages_failed > 0;
  const review = useMutation({
    mutationFn: (reviewStatus: RenditionReviewStatusInput) =>
      reviewAttachmentRendition({
        matterId,
        attachmentId,
        renditionId: rendition.id,
        reviewStatus,
        note: note.trim() ? note.trim() : null,
      }),
    onSuccess: async (result) => {
      toast.success(
        result.review_status === "reviewed" ? "Marked reviewed" : "Marked as needing correction",
      );
      setNote("");
      await invalidate();
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not record the review.")),
  });
  const submit = (status: RenditionReviewStatusInput) => {
    if (review.isPending) return;
    if (status === "reviewed" && noteRequired && !note.trim()) {
      setNoteError("Add a note explaining how the unread pages were checked.");
      return;
    }
    setNoteError(null);
    review.mutate(status);
  };

  return (
    <section
      aria-labelledby="renditions-review-title"
      className="flex flex-col gap-2 rounded-md border border-[var(--color-line)] p-3"
      data-testid="renditions-review"
    >
      <h3 id="renditions-review-title" className="text-sm font-semibold text-[var(--color-ink)]">
        Review this version
      </h3>
      <div>
        <Label htmlFor="renditions-review-note">
          Note{noteRequired ? " (required — this version has unread pages)" : " (optional)"}
        </Label>
        <Textarea
          id="renditions-review-note"
          className="mt-1.5"
          rows={2}
          maxLength={2000}
          value={note}
          aria-invalid={noteError ? true : undefined}
          aria-describedby={noteError ? "renditions-review-note-error" : undefined}
          onChange={(event) => {
            setNote(event.target.value);
            if (noteError) setNoteError(null);
          }}
        />
        {noteError ? (
          <p
            id="renditions-review-note-error"
            role="alert"
            className="mt-1 text-xs text-[var(--color-danger-text)]"
          >
            {noteError}
          </p>
        ) : null}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          disabled={review.isPending}
          onClick={() => submit("reviewed")}
          data-testid="renditions-mark-reviewed"
        >
          Mark reviewed
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={review.isPending}
          onClick={() => submit("needs_correction")}
          data-testid="renditions-needs-correction"
        >
          Needs correction
        </Button>
      </div>
    </section>
  );
}
