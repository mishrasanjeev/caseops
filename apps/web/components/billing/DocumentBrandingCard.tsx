"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Trash2, Upload } from "lucide-react";
import { useEffect, useId, useRef, useState, type ChangeEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { apiErrorMessage } from "@/lib/api/config";
import {
  BRANDING_IMAGE_ACCEPT,
  BRANDING_TEXT_LIMITS,
  brandingImageProblem,
  fetchBrandingImage,
  fetchDocumentBranding,
  removeBrandingImage,
  updateDocumentBranding,
  uploadBrandingImage,
  type BrandingImageKind,
  type DocumentBranding,
  type DocumentBrandingUpdate,
} from "@/lib/api/document-branding";

export const documentBrandingKey = ["admin", "document-branding"] as const;

type Draft = {
  signatory_name: string;
  signatory_designation: string;
  watermark_enabled: boolean;
  watermark_text: string;
};

function draftFrom(record: DocumentBranding): Draft {
  return {
    signatory_name: record.signatory_name ?? "",
    signatory_designation: record.signatory_designation ?? "",
    watermark_enabled: record.watermark_enabled,
    watermark_text: record.watermark_text ?? "",
  };
}

/** Only the fields the admin changed are sent (PATCH). */
export function dirtyBrandingFields(saved: Draft, draft: Draft): DocumentBrandingUpdate {
  const body: DocumentBrandingUpdate = {};
  for (const key of ["signatory_name", "signatory_designation", "watermark_text"] as const) {
    if (draft[key].trim() !== saved[key].trim()) body[key] = draft[key].trim() || null;
  }
  if (draft.watermark_enabled !== saved.watermark_enabled) body.watermark_enabled = draft.watermark_enabled;
  return body;
}

const IMAGE_COPY: Record<BrandingImageKind, { title: string; hint: string }> = {
  logo: {
    title: "Firm logo",
    hint: "Printed at the top left of every invoice and receipt. PNG or JPEG, up to 2 MB.",
  },
  signature: {
    title: "Authorised signature",
    hint: "Applied only to issued invoices and receipts, never to drafts. PNG or JPEG, up to 2 MB.",
  },
};

function BrandingImage({
  kind,
  record,
  onChanged,
}: {
  kind: BrandingImageKind;
  record: DocumentBranding;
  onChanged: (next: DocumentBranding) => void;
}) {
  const inputId = useId();
  const fileInput = useRef<HTMLInputElement>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const present = kind === "logo" ? record.has_logo : record.has_signature;
  const fingerprint = kind === "logo" ? record.logo_sha256 : record.signature_sha256;
  const preview = useQuery({
    queryKey: [...documentBrandingKey, kind, fingerprint],
    queryFn: () => fetchBrandingImage(kind),
    enabled: present,
    staleTime: Infinity,
  });
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!preview.data) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(preview.data);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [preview.data]);

  const upload = useMutation({
    mutationFn: (file: File) => uploadBrandingImage(kind, file),
    onSuccess: (next) => {
      onChanged(next);
      toast.success(`${IMAGE_COPY[kind].title} saved.`);
    },
    onError: (error) => setProblem(apiErrorMessage(error, `Could not save the ${kind}.`)),
    onSettled: () => {
      if (fileInput.current) fileInput.current.value = "";
    },
  });
  const remove = useMutation({
    mutationFn: () => removeBrandingImage(kind),
    onSuccess: (next) => {
      onChanged(next);
      toast.success(`${IMAGE_COPY[kind].title} removed.`);
    },
    onError: (error) => toast.error(apiErrorMessage(error, `Could not remove the ${kind}.`)),
  });

  function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const local = brandingImageProblem(file);
    setProblem(local);
    if (local) {
      event.target.value = "";
      return;
    }
    upload.mutate(file);
  }

  const busy = upload.isPending || remove.isPending;
  return (
    <div className="flex min-w-0 flex-col gap-2" data-testid={`branding-${kind}`}>
      <span className="text-sm font-medium text-[var(--color-ink-2)]">{IMAGE_COPY[kind].title}</span>
      <div className="flex h-24 items-center justify-center rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] p-2">
        {previewUrl ? (
          // eslint-disable-next-line @next/next/no-img-element -- a private blob preview, not a page asset
          <img
            src={previewUrl}
            alt={`${IMAGE_COPY[kind].title} preview`}
            className="max-h-full max-w-full object-contain"
            data-testid={`branding-${kind}-preview`}
          />
        ) : (
          <span className="text-xs text-[var(--color-mute)]">{present ? "Loading preview…" : "None uploaded"}</span>
        )}
      </div>
      <p className="text-xs text-[var(--color-mute)]">{IMAGE_COPY[kind].hint}</p>
      <div className="flex flex-wrap gap-2">
        <label htmlFor={inputId} className="sr-only">
          {`Upload ${IMAGE_COPY[kind].title.toLowerCase()}`}
        </label>
        <input
          ref={fileInput}
          id={inputId}
          type="file"
          accept={BRANDING_IMAGE_ACCEPT}
          className="sr-only"
          onChange={onFile}
          disabled={busy}
          aria-describedby={problem ? `${inputId}-error` : undefined}
          data-testid={`branding-${kind}-input`}
        />
        <Button type="button" variant="secondary" size="sm" disabled={busy} onClick={() => fileInput.current?.click()}>
          {upload.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
          {present ? "Replace" : "Upload"}
        </Button>
        {present ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => remove.mutate()}
            data-testid={`branding-${kind}-remove`}
          >
            <Trash2 className="h-4 w-4" />
            Remove
          </Button>
        ) : null}
      </div>
      {problem ? (
        <span id={`${inputId}-error`} role="alert" className="text-xs text-[var(--color-danger)]">
          {problem}
        </span>
      ) : null}
    </div>
  );
}

export function DocumentBrandingCard({ enabled }: { enabled: boolean }) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: documentBrandingKey,
    queryFn: fetchDocumentBranding,
    enabled,
  });
  const saved = useRef<Draft | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);

  // The form becomes editable only after the saved record is loaded, and a
  // refetch never overwrites what the admin is typing.
  useEffect(() => {
    if (!query.data || draft !== null) return;
    saved.current = draftFrom(query.data);
    setDraft(draftFrom(query.data));
  }, [query.data, draft]);

  function adopt(next: DocumentBranding) {
    queryClient.setQueryData(documentBrandingKey, next);
  }

  const save = useMutation({
    mutationFn: () => {
      if (!draft || !saved.current) throw new Error("Load the branding settings before saving.");
      return updateDocumentBranding(dirtyBrandingFields(saved.current, draft));
    },
    onSuccess: (next) => {
      adopt(next);
      saved.current = draftFrom(next);
      setDraft(draftFrom(next));
      toast.success("Invoice branding saved.");
    },
    onError: (error) => toast.error(apiErrorMessage(error, "Could not save invoice branding.")),
  });

  const record = query.data;
  const dirty = draft && saved.current ? Object.keys(dirtyBrandingFields(saved.current, draft)).length > 0 : false;
  return (
    <Card data-testid="document-branding-card">
      <CardHeader>
        <CardTitle>Invoice and receipt branding</CardTitle>
        <CardDescription>
          Every invoice and receipt PDF prints the letterhead, a watermark, the authorised signatory and a
          verification QR code that anyone can scan to confirm the document.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {query.isPending ? (
          <p role="status">Loading branding…</p>
        ) : query.isError ? (
          <div role="alert" className="space-y-2">
            <p>{apiErrorMessage(query.error, "Could not load invoice branding.")}</p>
            <Button type="button" onClick={() => void query.refetch()} disabled={query.isFetching}>
              Retry loading branding
            </Button>
          </div>
        ) : record && draft ? (
          <>
            <div className="grid gap-4 md:grid-cols-2">
              <BrandingImage kind="logo" record={record} onChanged={adopt} />
              <BrandingImage kind="signature" record={record} onChanged={adopt} />
            </div>
            <fieldset className="grid min-w-0 gap-3 md:grid-cols-2" disabled={save.isPending}>
              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium text-[var(--color-ink-2)]">Authorised signatory</span>
                <Input
                  value={draft.signatory_name}
                  maxLength={BRANDING_TEXT_LIMITS.signatory_name}
                  placeholder="Full name"
                  onChange={(event) => setDraft({ ...draft, signatory_name: event.target.value })}
                  data-testid="branding-signatory-name"
                />
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-medium text-[var(--color-ink-2)]">Designation</span>
                <Input
                  value={draft.signatory_designation}
                  maxLength={BRANDING_TEXT_LIMITS.signatory_designation}
                  placeholder="Managing Partner"
                  onChange={(event) => setDraft({ ...draft, signatory_designation: event.target.value })}
                  data-testid="branding-signatory-designation"
                />
              </label>
              <label className="flex min-h-10 items-center gap-2 text-sm text-[var(--color-ink-2)] md:col-span-2">
                <input
                  type="checkbox"
                  checked={draft.watermark_enabled}
                  onChange={(event) => setDraft({ ...draft, watermark_enabled: event.target.checked })}
                  data-testid="branding-watermark-enabled"
                />
                <span>
                  Watermark issued documents. Draft, void, paid and review copies always carry their status
                  as the watermark.
                </span>
              </label>
              <label className="flex flex-col gap-1.5 md:col-span-2">
                <span className="text-sm font-medium text-[var(--color-ink-2)]">Watermark text</span>
                <Input
                  value={draft.watermark_text}
                  maxLength={BRANDING_TEXT_LIMITS.watermark_text}
                  placeholder={record.letterhead.issuer_name}
                  disabled={!draft.watermark_enabled}
                  onChange={(event) => setDraft({ ...draft, watermark_text: event.target.value })}
                  data-testid="branding-watermark-text"
                />
                <span className="text-xs text-[var(--color-mute)]">Leave empty to use the firm name.</span>
              </label>
              <div className="md:col-span-2">
                <Button
                  type="button"
                  onClick={() => save.mutate()}
                  disabled={!dirty || save.isPending}
                  data-testid="branding-save"
                >
                  {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  Save branding
                </Button>
              </div>
            </fieldset>
            <div className="rounded-md border border-[var(--color-line)] px-3 py-2" data-testid="branding-letterhead">
              <p className="text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]">Letterhead text</p>
              <p className="text-sm font-semibold text-[var(--color-ink)]">{record.letterhead.issuer_name}</p>
              {record.letterhead.detail_lines.map((line) => (
                <p key={line} className="text-xs text-[var(--color-ink-2)]">{line}</p>
              ))}
              <p className="mt-1 text-xs text-[var(--color-mute)]">
                {record.letterhead.source === "billing_profile"
                  ? "Firm name, address, GSTIN and PAN come from the default billing profile above."
                  : "Save a firm legal name in the default billing profile above to print it here."}
              </p>
            </div>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
