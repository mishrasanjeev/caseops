"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, ScanText } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/Dialog";
import { Label } from "@/components/ui/Label";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { apiErrorMessage } from "@/lib/api/config";
import {
  createAttachmentRendition,
  listAttachmentRenditions,
  type RenditionLanguage,
} from "@/lib/api/endpoints";
import {
  RENDITION_LANGUAGES,
  languageLabel,
  ocrOnlyLanguagesPhrase,
  providerReasonLabel,
  translationTargets,
} from "@/lib/renditions";

const NO_TRANSLATION = "none";

const selectClass =
  "mt-1.5 h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm text-[var(--color-ink)] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-500)] disabled:cursor-not-allowed disabled:bg-[var(--color-bg-2)] disabled:text-[var(--color-mute)]";

export function attachmentRenditionsQueryKey(matterId: string, attachmentId: string) {
  return ["matters", matterId, "attachments", attachmentId, "renditions"] as const;
}

export function matterRenditionsQueryKey(matterId: string) {
  return ["matters", matterId, "document-renditions"] as const;
}

export function OcrTranslateDialog({
  matterId,
  attachment,
  onClose,
}: {
  matterId: string;
  /** The document to process; null keeps the dialog closed. */
  attachment: { id: string; name: string } | null;
  onClose: () => void;
}) {
  return (
    <Dialog open={attachment !== null} onOpenChange={(open) => (open ? null : onClose())}>
      {attachment ? (
        <DialogContent data-testid="ocr-translate-dialog">
          <DialogHeader>
            <DialogTitle>OCR &amp; Translate</DialogTitle>
            <DialogDescription>
              Read the text of <span className="font-medium text-[var(--color-ink-2)]">{attachment.name}</span>{" "}
              and, if you choose, produce a machine translation for review. The original file is not changed.
            </DialogDescription>
          </DialogHeader>
          <OcrTranslateForm
            key={attachment.id}
            matterId={matterId}
            attachmentId={attachment.id}
            onClose={onClose}
          />
        </DialogContent>
      ) : null}
    </Dialog>
  );
}

function OcrTranslateForm({
  matterId,
  attachmentId,
  onClose,
}: {
  matterId: string;
  attachmentId: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [source, setSource] = useState<RenditionLanguage | "">("");
  const [target, setTarget] = useState<string>(NO_TRANSLATION);
  const readiness = useQuery({
    queryKey: attachmentRenditionsQueryKey(matterId, attachmentId),
    queryFn: () => listAttachmentRenditions({ matterId, attachmentId }),
  });
  const providers = readiness.data?.providers;
  const targets = translationTargets(providers, source);
  const translationAvailable = providers?.translation_available ?? false;
  const ocrOnly = ocrOnlyLanguagesPhrase(providers);

  const startMutation = useMutation({
    mutationFn: (input: { sourceLanguage: RenditionLanguage; targetLanguage: RenditionLanguage | null }) =>
      createAttachmentRendition({ matterId, attachmentId, ...input }),
    onSuccess: async (result) => {
      if (result.created) {
        toast.success("OCR queued");
      } else {
        toast.success("Already running", {
          description: "An OCR run for this document is still in progress.",
        });
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: matterRenditionsQueryKey(matterId) }),
        queryClient.invalidateQueries({
          queryKey: attachmentRenditionsQueryKey(matterId, attachmentId),
        }),
      ]);
      onClose();
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not start OCR."));
    },
  });

  if (readiness.isPending) {
    return (
      <div className="flex flex-col gap-3" data-testid="ocr-translate-loading" aria-busy="true">
        <span className="sr-only">Loading OCR options</span>
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    );
  }
  if (readiness.isError) {
    return (
      <QueryErrorState
        title="Could not load OCR options"
        error={readiness.error}
        onRetry={readiness.refetch}
        className="py-6"
      />
    );
  }

  const ocrLanguages = RENDITION_LANGUAGES.filter(
    (item) => !providers || providers.ocr_languages.includes(item.value),
  );
  const chosenTarget =
    target !== NO_TRANSLATION && targets.includes(target as RenditionLanguage)
      ? (target as RenditionLanguage)
      : null;
  const canSubmit = source !== "" && !startMutation.isPending;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (startMutation.isPending || source === "") return;
    startMutation.mutate({
      sourceLanguage: source,
      targetLanguage: translationAvailable ? chosenTarget : null,
    });
  };

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} noValidate>
      <div>
        <Label htmlFor="ocr-source-language">Source language</Label>
        <select
          id="ocr-source-language"
          className={selectClass}
          value={source}
          required
          aria-required="true"
          onChange={(event) => {
            const next = event.target.value as RenditionLanguage | "";
            setSource(next);
            if (!translationTargets(providers, next).includes(target as RenditionLanguage)) {
              setTarget(NO_TRANSLATION);
            }
          }}
          data-testid="ocr-source-language"
        >
          <option value="" disabled>
            Choose the language of the document
          </option>
          {ocrLanguages.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <Label htmlFor="ocr-target-language">Translate to</Label>
        <select
          id="ocr-target-language"
          className={selectClass}
          value={chosenTarget ?? NO_TRANSLATION}
          disabled={!translationAvailable}
          aria-describedby="ocr-target-language-hint"
          onChange={(event) => setTarget(event.target.value)}
          data-testid="ocr-target-language"
        >
          <option value={NO_TRANSLATION}>No translation — OCR only</option>
          {translationAvailable
            ? targets.map((code) => (
                <option key={code} value={code}>
                  {languageLabel(code)}
                </option>
              ))
            : null}
        </select>
        <p
          id="ocr-target-language-hint"
          className="mt-1.5 text-xs text-[var(--color-mute)]"
          data-testid="ocr-target-language-hint"
        >
          {!translationAvailable
            ? `Translation is unavailable. ${providerReasonLabel(providers?.translation_unavailable_reason)}`
            : source === ""
              ? "Choose the source language to see translation options."
              : targets.length === 0
                ? `No translation is offered from ${languageLabel(source)}.`
                : `Machine translation is a draft for review, not a certified translation.${
                    ocrOnly ? ` ${ocrOnly} text can be read but not translated.` : ""
                  }`}
        </p>
      </div>
      {providers && !providers.ocr_provider_available ? (
        <p
          className="rounded-md border border-[var(--color-warn-border)] bg-[var(--color-warn-bg)] px-3 py-2 text-sm text-[var(--color-warn-text)]"
          data-testid="ocr-provider-unavailable"
        >
          Only pages with a text layer will be read. Scanned pages will be listed as unread.
        </p>
      ) : null}
      <DialogFooter>
        <Button type="button" variant="outline" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button
          type="submit"
          size="sm"
          disabled={!canSubmit}
          data-testid="ocr-translate-start"
        >
          {startMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <ScanText className="h-4 w-4" aria-hidden />
          )}
          Start
        </Button>
      </DialogFooter>
    </form>
  );
}
