"use client";

import { useMutation } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import { createContractTermSuggestion, updateContractTermSuggestion, type ContractTermSuggestionRecord } from "@/lib/api/endpoints";

const blank = { effective: "", expiry: "", renewal: "", duration: "", source: "", quote: "" };

export function ContractTermEntry({ contractId, attachments, onSaved, original, onClose }: {
  contractId: string; attachments: Array<{ id: string; original_filename: string }>; onSaved: () => Promise<unknown>;
  original?: ContractTermSuggestionRecord;
  onClose?: () => void;
}) {
  const [open, setOpen] = useState(Boolean(original));
  const [draft, setDraft] = useState(() => original ? {
    effective: original.suggested_effective_on ?? "",
    expiry: original.suggested_expires_on ?? "",
    renewal: original.suggested_renewal_on ?? "",
    duration: String(original.suggested_duration_months ?? ""),
    source: "", quote: "",
  } : blank);
  function close() {
    setOpen(false);
    setDraft(blank);
    onClose?.();
  }
  const mutation = useMutation({
    mutationFn: () => {
      const terms = {
        suggested_effective_on: draft.effective || null,
        suggested_expires_on: draft.expiry || null,
        suggested_renewal_on: draft.renewal || null,
        suggested_duration_months: draft.duration === "" ? null : Number(draft.duration),
      };
      if (original) return updateContractTermSuggestion({
        contractId, suggestionId: original.id, expected_updated_at: original.updated_at, ...terms,
      });
      return createContractTermSuggestion({
        contractId, ...terms, source_attachment_id: draft.source || null,
        evidence_json: draft.quote.trim() ? { quote: draft.quote.trim() } : {},
      });
    },
    onSuccess: async () => { await onSaved(); close(); },
    onError: async () => { if (original) await onSaved(); },
  });
  if (!open) return <Button size="sm" variant="outline" onClick={() => { setOpen(true); mutation.reset(); }}><Plus className="h-4 w-4" aria-hidden />Add term suggestion</Button>;
  const fieldId = (key: string) => original ? `suggest-${original.id}-${key}` : `suggest-${key}`;
  return <form aria-label={original ? "Edit term suggestion" : "Add term suggestion"} className="flex min-w-0 flex-col gap-3 border-b border-[var(--color-line)] pb-4" onSubmit={(e) => { e.preventDefault(); mutation.mutate(); }}>
    <fieldset disabled={mutation.isPending} className="grid min-w-0 gap-3 sm:grid-cols-2">
      {(["effective", "expiry", "renewal", "duration"] as const).map((key) => <div key={key} className="min-w-0">
        <Label htmlFor={fieldId(key)}>{key === "duration" ? "Suggested duration (months)" : `Suggested ${key} date`}</Label>
        <Input id={fieldId(key)} type={key === "duration" ? "number" : "date"} min={key === "duration" ? 0 : undefined} max={key === "duration" ? 1200 : undefined} step={key === "duration" ? 1 : undefined}
          value={draft[key]} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
      </div>)}
      {!original ? <>
        <div className="min-w-0 sm:col-span-2"><Label htmlFor="suggest-source">Source document</Label>
        <select id="suggest-source" className="h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={draft.source} onChange={(e) => setDraft({ ...draft, source: e.target.value })}>
          <option value="">No source selected</option>{attachments.map((a) => <option key={a.id} value={a.id}>{a.original_filename}</option>)}
        </select></div>
      <div className="min-w-0 sm:col-span-2"><Label htmlFor="suggest-quote">Source evidence</Label>
        <Textarea id="suggest-quote" rows={3} maxLength={2000} value={draft.quote} onChange={(e) => setDraft({ ...draft, quote: e.target.value })} /></div>
      </> : null}
    </fieldset>
    {mutation.isError ? <p role="alert" className="text-sm text-[var(--color-danger)]">{apiErrorMessage(mutation.error, "Could not save term suggestion.")}</p> : null}
    <div className="flex flex-wrap gap-2"><Button size="sm" type="submit" disabled={mutation.isPending || ![draft.effective, draft.expiry, draft.renewal, draft.duration].some(Boolean)}><Plus className="h-4 w-4" aria-hidden />{mutation.isPending ? "Saving..." : "Save suggestion"}</Button>
      <Button size="sm" type="button" variant="ghost" disabled={mutation.isPending} onClick={() => original ? close() : setOpen(false)}>Cancel</Button></div>
  </form>;
}
