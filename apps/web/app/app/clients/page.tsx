"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Contact, Plus, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { PageHeader } from "@/components/ui/PageHeader";
import { QueryErrorState } from "@/components/ui/QueryErrorState";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { ApiError } from "@/lib/api/config";
import {
  type ClientRecord,
  type ClientType,
  createClient,
  listClients,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

const CLIENT_TYPES: { value: ClientType; label: string }[] = [
  { value: "individual", label: "Individual" },
  { value: "corporate", label: "Corporate" },
  { value: "government", label: "Government" },
  { value: "nonprofit", label: "Nonprofit" },
];

type BadgeTone = "neutral" | "brand" | "success" | "warning";

const KYC_LABEL: Record<string, { label: string; tone: BadgeTone }> = {
  not_started: { label: "KYC not started", tone: "neutral" },
  pending: { label: "KYC pending", tone: "warning" },
  verified: { label: "KYC verified", tone: "success" },
  rejected: { label: "KYC rejected", tone: "warning" },
};


export default function ClientsIndexPage() {
  const canCreate = useCapability("clients:create");
  const query = useQuery({
    queryKey: ["clients", "list"],
    queryFn: () => listClients(),
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Clients"
        title="Clients & engagements"
        description="The law firm's client book — individuals and companies represented on one or more matters."
        actions={canCreate ? <NewClientDialog /> : null}
      />

      {query.isPending ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      ) : query.isError ? (
        <QueryErrorState
          title="Could not load clients"
          error={query.error}
          onRetry={query.refetch}
        />
      ) : query.data.clients.length === 0 ? (
        <EmptyState
          icon={Contact}
          title="No clients yet"
          description={
            canCreate
              ? "Add the first client. Once created you can assign them to any matter."
              : "A fee-earner on your team can add the first client."
          }
          action={canCreate ? <NewClientDialog /> : undefined}
        />
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {query.data.clients.map((c) => (
            <ClientCard key={c.id} client={c} />
          ))}
        </div>
      )}
    </div>
  );
}


function ClientCard({ client }: { client: ClientRecord }): React.JSX.Element {
  const kyc = KYC_LABEL[client.kyc_status] ?? KYC_LABEL.not_started;
  return (
    <Link
      href={`/app/clients/${client.id}`}
      className="block"
      data-testid={`client-card-${client.id}`}
    >
      <Card className={!client.is_active ? "opacity-60" : undefined}>
        <CardContent className="flex flex-col gap-3 py-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-[var(--color-ink)]">
                {client.name}
              </div>
              <div className="mt-0.5 text-xs text-[var(--color-mute)] capitalize">
                {client.client_type}
                {client.city ? ` · ${client.city}` : ""}
                {!client.is_active ? " · archived" : ""}
              </div>
            </div>
            {client.kyc_status === "verified" ? (
              <ShieldCheck
                className="h-5 w-5 shrink-0 text-[var(--color-brand-600)]"
                aria-label="KYC verified"
              />
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--color-mute)]">
            <Badge tone={kyc.tone}>{kyc.label}</Badge>
            <span>
              {client.active_matters_count} active ·{" "}
              {client.total_matters_count} total
            </span>
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}


function NewClientDialog(): React.JSX.Element {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [clientType, setClientType] = useState<ClientType>("individual");
  const [contactName, setContactName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  // Strict Ledger #4 (BUG-022, 2026-04-22): the form now captures
  // the full mailing address — line_1, line_2, city, state,
  // postal_code, country. The backend gained address_line_1 +
  // address_line_2 + postal_code columns in migration 20260422_0002
  // so what the user types round-trips end-to-end.
  const [addressLine1, setAddressLine1] = useState("");
  const [addressLine2, setAddressLine2] = useState("");
  const [city, setCity] = useState("");
  const [stateName, setStateName] = useState("");
  const [postalCode, setPostalCode] = useState("");
  const [country, setCountry] = useState("India");

  const mutation = useMutation({
    mutationFn: () =>
      createClient({
        name: name.trim(),
        client_type: clientType,
        primary_contact_name: contactName.trim() || null,
        primary_contact_email: email.trim() || null,
        primary_contact_phone: phone.trim() || null,
        address_line_1: addressLine1.trim() || null,
        address_line_2: addressLine2.trim() || null,
        city: city.trim() || null,
        state: stateName.trim() || null,
        postal_code: postalCode.trim() || null,
        country: country.trim() || null,
      }),
    onSuccess: async () => {
      toast.success("Client added.");
      setOpen(false);
      setName("");
      setContactName("");
      setEmail("");
      setPhone("");
      setAddressLine1("");
      setAddressLine2("");
      setCity("");
      setStateName("");
      setPostalCode("");
      setCountry("India");
      setClientType("individual");
      await queryClient.invalidateQueries({ queryKey: ["clients", "list"] });
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.detail : "Could not add client.");
    },
  });

  const canSubmit = name.trim().length >= 2 && !mutation.isPending;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" data-testid="new-client-open">
          <Plus className="h-4 w-4" aria-hidden /> New client
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add a client</DialogTitle>
          <DialogDescription>
            Clients are reusable across matters. You can edit details or add KYC later.
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (canSubmit) mutation.mutate();
          }}
        >
          <div>
            <Label htmlFor="client-name">Name</Label>
            <Input
              id="client-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Acme Industries Pvt Ltd"
              required
              minLength={2}
              maxLength={255}
              data-testid="new-client-name"
            />
          </div>
          <div>
            <Label htmlFor="client-type">Type</Label>
            <Select
              value={clientType}
              onValueChange={(value) => setClientType(value as ClientType)}
            >
              <SelectTrigger id="client-type" data-testid="new-client-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CLIENT_TYPES.map((t) => (
                  <SelectItem key={t.value} value={t.value}>
                    {t.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <Label htmlFor="client-contact">Contact name</Label>
              <Input
                id="client-contact"
                value={contactName}
                onChange={(e) => setContactName(e.target.value)}
                maxLength={255}
              />
            </div>
            <div>
              <Label htmlFor="client-city">City</Label>
              <Input
                id="client-city"
                value={city}
                onChange={(e) => setCity(e.target.value)}
                maxLength={255}
              />
            </div>
            <div>
              <Label htmlFor="client-email">Email</Label>
              <Input
                id="client-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                maxLength={320}
              />
            </div>
            <div>
              <Label htmlFor="client-phone">Phone</Label>
              <Input
                id="client-phone"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                maxLength={40}
              />
            </div>
            <div>
              <Label htmlFor="client-state">State</Label>
              <Input
                id="client-state"
                value={stateName}
                onChange={(e) => setStateName(e.target.value)}
                maxLength={120}
              />
            </div>
            <div>
              <Label htmlFor="client-postal">Postal code</Label>
              <Input
                id="client-postal"
                value={postalCode}
                onChange={(e) => setPostalCode(e.target.value)}
                maxLength={20}
              />
            </div>
            <div>
              <Label htmlFor="client-country">Country</Label>
              <Input
                id="client-country"
                value={country}
                onChange={(e) => setCountry(e.target.value)}
                maxLength={120}
              />
            </div>
          </div>
          {/* Strict Ledger #4 (BUG-022): full street address. */}
          <div>
            <Label htmlFor="client-address-1">Address line 1</Label>
            <Input
              id="client-address-1"
              value={addressLine1}
              onChange={(e) => setAddressLine1(e.target.value)}
              maxLength={255}
              placeholder="Door no., street"
            />
          </div>
          <div>
            <Label htmlFor="client-address-2">Address line 2 (optional)</Label>
            <Input
              id="client-address-2"
              value={addressLine2}
              onChange={(e) => setAddressLine2(e.target.value)}
              maxLength={255}
              placeholder="Locality, landmark"
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={!canSubmit}
              data-testid="new-client-submit"
            >
              {mutation.isPending ? "Adding…" : "Add client"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
