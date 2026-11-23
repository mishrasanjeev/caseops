"use client";

import { useMutation } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PersonPicker } from "@/components/ui/PersonPicker";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  createContractObligation,
  type ContractObligationRecord,
} from "@/lib/api/endpoints";

type Priority = ContractObligationRecord["priority"];

export function ContractObligationEntry({
  contractId,
  onSaved,
}: {
  contractId: string;
  onSaved: () => Promise<unknown>;
}) {
  const [open, setOpen] = useState(false);

  if (!open) {
    return (
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        <Plus className="h-4 w-4" aria-hidden /> Add obligation
      </Button>
    );
  }

  return (
    <ObligationForm
      contractId={contractId}
      onSaved={onSaved}
      close={() => setOpen(false)}
    />
  );
}

function ObligationForm({
  contractId,
  onSaved,
  close,
}: {
  contractId: string;
  onSaved: () => Promise<unknown>;
  close: () => void;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [dueOn, setDueOn] = useState("");
  const [owner, setOwner] = useState("");
  const [priority, setPriority] = useState<Priority>("medium");

  const save = useMutation({
    mutationFn: () => createContractObligation(contractId, {
      title: title.trim(),
      description: description.trim() || null,
      due_on: dueOn || null,
      owner_membership_id: owner || null,
      priority,
      status: "pending",
    }),
    onSuccess: async () => {
      await onSaved();
      close();
    },
  });

  return (
    <form
      aria-label="Add obligation"
      className="space-y-4 rounded-lg border border-[var(--color-line)] p-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!save.isPending && title.trim().length >= 2) save.mutate();
      }}
    >
      <fieldset disabled={save.isPending} className="grid min-w-0 gap-4 sm:grid-cols-2">
        <div className="min-w-0 sm:col-span-2">
          <Label htmlFor="obligation-title">Obligation title</Label>
          <Input id="obligation-title" required minLength={2} maxLength={255}
            value={title} onChange={(event) => setTitle(event.target.value)} />
        </div>
        <div className="min-w-0 sm:col-span-2">
          <Label htmlFor="obligation-description">Obligation details</Label>
          <Textarea id="obligation-description" rows={3} maxLength={4000}
            value={description} onChange={(event) => setDescription(event.target.value)} />
        </div>
        <div className="min-w-0">
          <Label htmlFor="obligation-due-on">Due date</Label>
          <Input id="obligation-due-on" type="date"
            value={dueOn} onChange={(event) => setDueOn(event.target.value)} />
        </div>
        <div className="min-w-0">
          <Label htmlFor="obligation-priority">Priority</Label>
          <select id="obligation-priority" value={priority}
            onChange={(event) => setPriority(event.target.value as Priority)}
            className="h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm">
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
        </div>
        <div className="min-w-0 sm:col-span-2">
          <Label htmlFor="obligation-owner">Owner</Label>
          <PersonPicker id="obligation-owner" value={owner} onChange={setOwner}
            placeholder="Unassigned" disabled={save.isPending} />
        </div>
      </fieldset>
      {save.isError ? (
        <p role="alert" className="text-sm text-[var(--color-danger)]">
          {apiErrorMessage(save.error, "Could not save the obligation.")}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="sm" disabled={save.isPending || title.trim().length < 2}>
          {save.isPending ? "Saving…" : "Save obligation"}
        </Button>
        <Button type="button" size="sm" variant="ghost" disabled={save.isPending} onClick={close}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
