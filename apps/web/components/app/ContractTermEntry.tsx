"use client";

import { useMutation } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import { createContractTermSuggestion } from "@/lib/api/endpoints";

const blank = { effective: "", expiry: "", renewal: "", duration: "", source: "", quote: "" };

export function ContractTermEntry({ contractId, attachments, onSaved }: {
  contractId: string; attachments: Array<{ id: string; original_filename: string }>; onSaved: () => Promise<unknown>;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(blank);
  const mutation = useMutation({
    mutationFn: () => createContractTermSuggestion({ contractId,
      source_attachment_id: draft.source || null,
      suggested_effective_on: draft.effective || null, suggested_expires_on: draft.expiry || null,
      suggested_renewal_on: draft.renewal || null,
      suggested_duration_months: draft.duration === "" ? null : Number(draft.duration),
      evidence_json: draft.quote.trim() ? { quote: draft.quote.trim() } : {},
    }),
    onSuccess: async () => { await onSaved(); setDraft(blank); setOpen(false); },
  });
  if (!open) return <Button size="sm" variant="outline" onClick={() => { setOpen(true); mutation.reset(); }}><Plus className="h-4 w-4" aria-hidden />Add term suggestion</Button>;
  return <form className="flex min-w-0 flex-col gap-3 border-b border-[var(--color-line)] pb-4" onSubmit={(e) => { e.preventDefault(); mutation.mutate(); }}>
    <fieldset disabled={mutation.isPending} className="grid min-w-0 gap-3 sm:grid-cols-2">
      {(["effective", "expiry", "renewal", "duration"] as const).map((key) => <div key={key} className="min-w-0">
        <Label htmlFor={`suggest-${key}`}>{key === "duration" ? "Suggested duration (months)" : `Suggested ${key} date`}</Label>
        <Input id={`suggest-${key}`} type={key === "duration" ? "number" : "date"} min={key === "duration" ? 0 : undefined} max={key === "duration" ? 1200 : undefined} step={key === "duration" ? 1 : undefined}
          value={draft[key]} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
      </div>)}
      <div className="min-w-0 sm:col-span-2"><Label htmlFor="suggest-source">Source document</Label>
        <select id="suggest-source" className="h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm" value={draft.source} onChange={(e) => setDraft({ ...draft, source: e.target.value })}>
          <option value="">No source selected</option>{attachments.map((a) => <option key={a.id} value={a.id}>{a.original_filename}</option>)}
        </select></div>
      <div className="min-w-0 sm:col-span-2"><Label htmlFor="suggest-quote">Source evidence</Label>
        <Textarea id="suggest-quote" rows={3} maxLength={2000} value={draft.quote} onChange={(e) => setDraft({ ...draft, quote: e.target.value })} /></div>
    </fieldset>
    {mutation.isError ? <p role="alert" className="text-sm text-[var(--color-danger)]">{apiErrorMessage(mutation.error, "Could not save term suggestion.")}</p> : null}
    <div className="flex flex-wrap gap-2"><Button size="sm" type="submit" disabled={mutation.isPending || ![draft.effective, draft.expiry, draft.renewal, draft.duration].some(Boolean)}><Plus className="h-4 w-4" aria-hidden />{mutation.isPending ? "Saving..." : "Save suggestion"}</Button>
      <Button size="sm" type="button" variant="ghost" disabled={mutation.isPending} onClick={() => setOpen(false)}>Cancel</Button></div>
  </form>;
}
