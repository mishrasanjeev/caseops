"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil, Save, X } from "lucide-react";
import { useId, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { apiErrorMessage } from "@/lib/api/config";
import {
  type ClientListResponse,
  type ClientRecord,
  updateClient,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

const CONTACT_FIELDS = [
  { key: "primary_contact_name", label: "Primary contact", maxLength: 255, autoComplete: "name" },
  { key: "primary_contact_email", label: "Email", maxLength: 254, autoComplete: "email" },
  { key: "primary_contact_phone", label: "Phone", maxLength: 40, autoComplete: "tel" },
  { key: "address_line_1", label: "Address line 1", maxLength: 255, autoComplete: "address-line1" },
  { key: "address_line_2", label: "Address line 2", maxLength: 255, autoComplete: "address-line2" },
  { key: "city", label: "City", maxLength: 255, autoComplete: "address-level2" },
  { key: "state", label: "State", maxLength: 120, autoComplete: "address-level1" },
  { key: "postal_code", label: "Postal code", maxLength: 20, autoComplete: "postal-code" },
  { key: "country", label: "Country", maxLength: 120, autoComplete: "country-name" },
] as const;

type ContactField = (typeof CONTACT_FIELDS)[number]["key"];
type ContactValues = Record<ContactField, string>;
type ContactPatch = Partial<Record<ContactField, string | null>>;

function contactValues(client: ClientRecord): ContactValues {
  return Object.fromEntries(
    CONTACT_FIELDS.map(({ key }) => [key, client[key] ?? ""]),
  ) as ContactValues;
}

export function ClientContactEditor({ client }: { client: ClientRecord }) {
  const canEdit = useCapability("clients:edit");
  const queryClient = useQueryClient();
  const id = useId();
  const saving = useRef(false);
  const [editor, setEditor] = useState<{
    initial: ContactValues;
    values: ContactValues;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: ({ clientId, patch }: { clientId: string; patch: ContactPatch }) =>
      updateClient(clientId, patch),
    retry: false,
    onSuccess: async (saved, { clientId }) => {
      // An older in-flight read must not replace the acknowledged update.
      await queryClient.cancelQueries({ queryKey: ["clients"] });
      queryClient.setQueryData(["clients", clientId], saved);
      queryClient.setQueriesData<ClientListResponse>(
        { queryKey: ["clients", "list"] },
        (previous) => previous && {
          ...previous,
          clients: previous.clients.map((row) => row.id === clientId ? saved : row),
        },
      );
      await queryClient.invalidateQueries({ queryKey: ["clients"] });
      setEditor(null);
      toast.success("Contact details updated.");
    },
    onError: (err) => {
      setError(apiErrorMessage(err, "Could not update contact details."));
    },
    onSettled: () => { saving.current = false; },
  });

  const patch: ContactPatch = {};
  if (editor) {
    for (const { key } of CONTACT_FIELDS) {
      const value = editor.values[key].trim() || null;
      if (value !== (editor.initial[key].trim() || null)) patch[key] = value;
    }
  }

  if (!canEdit || !client.is_active) return null;

  return (
    <Dialog
      open={editor !== null}
      onOpenChange={(open) => {
        if (saving.current) return;
        setError(null);
        if (open) {
          const values = contactValues(client);
          setEditor({ initial: values, values: { ...values } });
        } else {
          setEditor(null);
        }
      }}
    >
      <DialogTrigger asChild>
        <Button type="button" variant="outline" size="sm" data-testid="client-edit-contact">
          <Pencil className="h-4 w-4 shrink-0" aria-hidden /> Edit contact details
        </Button>
      </DialogTrigger>
      {editor ? (
        <DialogContent className="min-w-0 max-w-xl rounded-lg p-4 sm:p-6">
          <DialogHeader className="min-w-0 pr-8">
            <DialogTitle className="text-base tracking-normal">Edit contact details</DialogTitle>
            <DialogDescription className="[overflow-wrap:anywhere]">{client.name}</DialogDescription>
          </DialogHeader>
          <form
            className="flex min-w-0 flex-col gap-4"
            aria-busy={mutation.isPending}
            onSubmit={(event) => {
              event.preventDefault();
              if (saving.current || !canEdit || !client.is_active || !Object.keys(patch).length) return;
              saving.current = true;
              setError(null);
              mutation.mutate({ clientId: client.id, patch });
            }}
          >
            <fieldset disabled={mutation.isPending} className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
              {CONTACT_FIELDS.map(({ key, label, maxLength, autoComplete }) => (
                <div key={key} className={`min-w-0 ${key.startsWith("address_line") ? "sm:col-span-2" : ""}`}>
                  <Label htmlFor={`${id}-${key}`}>{label}</Label>
                  <Input
                    id={`${id}-${key}`}
                    name={key}
                    type={key === "primary_contact_email" ? "email" : key === "primary_contact_phone" ? "tel" : "text"}
                    autoComplete={autoComplete}
                    maxLength={maxLength}
                    className="mt-1 min-w-0"
                    value={editor.values[key]}
                    onChange={(event) => {
                      const value = event.target.value;
                      setEditor((current) => current && {
                        ...current, values: { ...current.values, [key]: value },
                      });
                    }}
                  />
                </div>
              ))}
            </fieldset>
            {error ? <p role="alert" className="break-words text-sm text-[var(--color-danger-500)]">{error}</p> : null}
            <DialogFooter className="min-w-0 sm:flex-wrap">
              <Button type="button" variant="outline" disabled={mutation.isPending} onClick={() => {
                if (!saving.current) setEditor(null);
              }}>
                <X className="h-4 w-4 shrink-0" aria-hidden /> Cancel
              </Button>
              <Button type="submit" disabled={mutation.isPending || !Object.keys(patch).length}>
                <Save className="h-4 w-4 shrink-0" aria-hidden />
                {mutation.isPending ? "Saving..." : "Save changes"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      ) : null}
    </Dialog>
  );
}
