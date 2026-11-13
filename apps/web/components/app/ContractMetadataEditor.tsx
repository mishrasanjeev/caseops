"use client";

import { useMutation } from "@tanstack/react-query";
import { Pencil, Save, X } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage, ApiError } from "@/lib/api/config";
import { updateContractDetails, type EditableContractMetadata } from "@/lib/api/contracts";
import { CONTRACT_TYPE_OPTIONS, type ContractTypeKey } from "@/lib/api/endpoints";

export function ContractMetadataEditor({ contractId, contract, canEdit, onSaved }: {
  contractId: string; contract: EditableContractMetadata; canEdit: boolean; onSaved: () => Promise<unknown>;
}) {
  const [draft, setDraft] = useState<EditableContractMetadata | null>(null);
  const [base, setBase] = useState(contract);
  const fields = draft ? Object.fromEntries(
    Object.entries(draft).filter(([key, value]) => key !== "updated_at" && value !== base[key as keyof EditableContractMetadata]),
  ) : {};
  const mutation = useMutation({
    mutationFn: () => updateContractDetails(contractId, { ...fields, expected_updated_at: base.updated_at }),
    onSuccess: async () => { await onSaved(); setDraft(null); },
  });
  const set = <K extends keyof EditableContractMetadata>(key: K, value: EditableContractMetadata[K]) =>
    setDraft((current) => current ? { ...current, [key]: value } : current);
  const stale = mutation.error instanceof ApiError && mutation.error.status === 409;

  return <section className="min-w-0" aria-labelledby="contract-metadata-heading">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 id="contract-metadata-heading" className="text-sm font-semibold">Contract details</h2>
      {canEdit && !draft ? <Button size="sm" variant="outline" onClick={() => {
        setBase(contract); setDraft({ ...contract }); mutation.reset();
      }}><Pencil className="h-4 w-4" aria-hidden />Edit contract</Button> : null}
    </div>
    {!draft || !canEdit ? <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
      <div><dt className="text-xs text-[var(--color-mute)]">Type</dt><dd className="break-words">{contract.contract_type}</dd></div>
      <div><dt className="text-xs text-[var(--color-mute)]">Legacy / other label</dt><dd className="break-words">{contract.contract_type_notes || "Not recorded"}</dd></div>
    </dl> : <form className="mt-4 flex min-w-0 flex-col gap-3" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
      <fieldset disabled={mutation.isPending} className="grid min-w-0 gap-3 sm:grid-cols-2">
        <div className="min-w-0 sm:col-span-2"><Label htmlFor="edit-contract-title">Contract title</Label>
          <Input id="edit-contract-title" required minLength={3} maxLength={255} value={draft.title} onChange={(e) => set("title", e.target.value)} /></div>
        <div className="min-w-0 sm:col-span-2"><Label htmlFor="edit-contract-counterparty">Counterparty</Label>
          <Input id="edit-contract-counterparty" minLength={2} maxLength={255} value={draft.counterparty_name ?? ""} onChange={(e) => set("counterparty_name", e.target.value || null)} /></div>
        <div className="min-w-0"><Label htmlFor="edit-contract-type">Contract type</Label>
          <select id="edit-contract-type" className="h-10 w-full min-w-0 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
            value={draft.contract_type_key ?? "other"} onChange={(e) => {
              const key = e.target.value as ContractTypeKey;
              setDraft({ ...draft, contract_type_key: key,
                contract_type: key === "other" ? draft.contract_type_notes || draft.contract_type : CONTRACT_TYPE_OPTIONS.find((o) => o.value === key)!.label });
            }}>
            {CONTRACT_TYPE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select></div>
        <div className="min-w-0"><Label htmlFor="edit-contract-type-notes">Legacy / other label</Label>
          <Input id="edit-contract-type-notes" maxLength={1000} value={draft.contract_type_notes ?? ""} onChange={(e) => {
            const value = e.target.value;
            setDraft({ ...draft, contract_type_notes: value || null,
              contract_type: draft.contract_type_key === "other" ? value || "Other" : draft.contract_type });
          }} /></div>
        {(["effective_on", "expires_on", "renewal_on"] as const).map((key) => <div key={key} className="min-w-0">
          <Label htmlFor={`edit-contract-${key}`}>{key === "effective_on" ? "Effective date" : key === "expires_on" ? "Expiry date" : "Renewal date"}</Label>
          <Input id={`edit-contract-${key}`} type="date" value={draft[key] ?? ""} onChange={(e) => set(key, e.target.value || null)} />
        </div>)}
        <label className="flex min-h-10 items-center gap-2 text-sm"><input type="checkbox" checked={draft.auto_renewal} onChange={(e) => set("auto_renewal", e.target.checked)} />Auto-renewal</label>
        <div className="min-w-0 sm:col-span-2"><Label htmlFor="edit-contract-summary">Description</Label>
          <Textarea id="edit-contract-summary" rows={4} maxLength={4000} value={draft.summary ?? ""} onChange={(e) => set("summary", e.target.value || null)} /></div>
      </fieldset>
      {mutation.isError ? <div role="alert" className="text-sm text-[var(--color-danger)]">
        {apiErrorMessage(mutation.error, "Could not save contract details.")}
        {stale ? <Button type="button" variant="ghost" size="sm" onClick={async () => {
          await onSaved(); setDraft(null); mutation.reset();
        }}>Reload contract</Button> : null}
      </div> : null}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" type="submit" disabled={mutation.isPending || stale || !Object.keys(fields).length}><Save className="h-4 w-4" aria-hidden />{mutation.isPending ? "Saving..." : "Save contract"}</Button>
        <Button size="sm" type="button" variant="ghost" disabled={mutation.isPending} onClick={() => setDraft(null)}><X className="h-4 w-4" aria-hidden />Cancel</Button>
      </div>
    </form>}
  </section>;
}
