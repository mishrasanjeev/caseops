"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CreditCard, Loader2, Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { apiErrorMessage } from "@/lib/api/config";
import {
  createMatterBillingProfile,
  createMatterBillingRate,
  fetchMatterBillingProfiles,
  fetchMatterInvoiceNumberPreview,
  updateMatterBillingProfile,
} from "@/lib/api/endpoints";
import { useCapability } from "@/lib/capabilities";

function rupeesToMinor(value: string): number {
  const parsed = Number(value || "0");
  return Number.isFinite(parsed) ? Math.round(parsed * 100) : 0;
}

export default function AdminMatterBillingPage() {
  const canAdmin = useCapability("workspace:admin");
  const queryClient = useQueryClient();
  const [name, setName] = useState("GBA Law Office");
  const [firmLegalName, setFirmLegalName] = useState("GBA Law Office");
  const [firmAddress, setFirmAddress] = useState("");
  const [firmGstin, setFirmGstin] = useState("");
  const [firmPan, setFirmPan] = useState("");
  const [prefix, setPrefix] = useState("GBA");
  const [defaultRate, setDefaultRate] = useState("");
  const [sac, setSac] = useState("");
  const [placeOfSupply, setPlaceOfSupply] = useState("");
  const [gstStateCode, setGstStateCode] = useState("");
  const [igstBps, setIgstBps] = useState("1800");
  const [profileForRate, setProfileForRate] = useState("");
  const [rateScope, setRateScope] = useState<"default" | "role" | "practice_area">("default");
  const [rateValue, setRateValue] = useState("");
  const [ratePractice, setRatePractice] = useState("");
  const [rateRole, setRateRole] = useState("");

  const profilesQuery = useQuery({
    queryKey: ["admin", "matter-billing"],
    queryFn: fetchMatterBillingProfiles,
    enabled: canAdmin,
  });
  const previewQuery = useQuery({
    queryKey: ["admin", "matter-billing", "invoice-preview"],
    queryFn: () => fetchMatterInvoiceNumberPreview(),
    enabled: canAdmin,
  });

  const buildProfilePayload = () => ({
    name,
    is_default: true,
    currency: "INR",
    firm_legal_name: firmLegalName,
    firm_address: firmAddress || null,
    firm_gstin: firmGstin || null,
    firm_pan: firmPan || null,
    default_place_of_supply: placeOfSupply || null,
    default_sac_hsn: sac || null,
    gst_applicable: true,
    gstin_state_code: gstStateCode || null,
    cgst_rate_bps: 900,
    sgst_rate_bps: 900,
    igst_rate_bps: Number(igstBps || "0"),
    tax_rate_bps: Number(igstBps || "0"),
    invoice_prefix: prefix,
    next_invoice_sequence: 1,
    payment_terms_days: 30,
    billing_mode: "hourly",
    default_rate_minor_per_hour: defaultRate ? rupeesToMinor(defaultRate) : null,
    expense_categories: ["court_fee", "filing_fee", "travel", "reimbursement"],
    retainer_adjustments_enabled: true,
  });
  const saveProfileMutation = useMutation({
    mutationFn: () => {
      const payload = buildProfilePayload();
      const existingProfile =
        profilesQuery.data?.profiles.find((profile) => profile.is_default) ??
        profilesQuery.data?.profiles.find(
          (profile) => profile.name.trim().toLowerCase() === name.trim().toLowerCase(),
      );
      if (existingProfile) {
        const { next_invoice_sequence: omittedNextInvoiceSequence, ...updateBody } =
          payload;
        void omittedNextInvoiceSequence;
        return updateMatterBillingProfile({
          profileId: existingProfile.id,
          body: updateBody,
        });
      }
      return createMatterBillingProfile(payload);
    },
    onSuccess: async (profile) => {
      setProfileForRate(profile.id);
      await queryClient.invalidateQueries({ queryKey: ["admin", "matter-billing"] });
      await queryClient.invalidateQueries({
        queryKey: ["admin", "matter-billing", "invoice-preview"],
      });
      toast.success("Matter billing profile saved.");
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not save billing profile.")),
  });

  const addRateMutation = useMutation({
    mutationFn: () =>
      createMatterBillingRate({
        profileId: profileForRate || profilesQuery.data?.profiles[0]?.id || "",
        body: {
          rate_scope: rateScope,
          amount_minor_per_hour: rupeesToMinor(rateValue),
          currency: "INR",
          practice_area: rateScope === "practice_area" ? ratePractice || null : null,
          role: rateScope === "role" ? rateRole || null : null,
        },
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["admin", "matter-billing"] });
      setRateValue("");
      toast.success("Rate rule added.");
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not add rate.")),
  });

  if (!canAdmin) {
    return (
      <EmptyState
        icon={CreditCard}
        title="Matter billing is admin-only"
        description="Ask a workspace admin to configure law-firm billing profiles and rates."
      />
    );
  }

  const profiles = profilesQuery.data?.profiles ?? [];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Matter billing"
        description="Configure law-firm billing profiles, rate cards, GST invoice fields, and invoice numbering."
      />

      <section className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <Card>
          <CardHeader>
            <CardTitle>Billing profile</CardTitle>
            <CardDescription>
              Server-side invoice data uses this profile when a matter has no explicit profile.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2">
            <Field label="Profile name">
              <Input value={name} onChange={(event) => setName(event.target.value)} />
            </Field>
            <Field label="Invoice prefix">
              <Input value={prefix} onChange={(event) => setPrefix(event.target.value)} />
            </Field>
            <Field label="Firm legal name">
              <Input value={firmLegalName} onChange={(event) => setFirmLegalName(event.target.value)} />
            </Field>
            <Field label="PAN">
              <Input value={firmPan} onChange={(event) => setFirmPan(event.target.value)} />
            </Field>
            <Field label="GSTIN">
              <Input value={firmGstin} onChange={(event) => setFirmGstin(event.target.value)} />
            </Field>
            <Field label="GST state code">
              <Input value={gstStateCode} onChange={(event) => setGstStateCode(event.target.value)} />
            </Field>
            <Field label="Place of supply">
              <Input value={placeOfSupply} onChange={(event) => setPlaceOfSupply(event.target.value)} />
            </Field>
            <Field label="Default SAC/HSN">
              <Input value={sac} onChange={(event) => setSac(event.target.value)} />
            </Field>
            <Field label="Default hourly rate INR">
              <Input value={defaultRate} inputMode="decimal" onChange={(event) => setDefaultRate(event.target.value)} />
            </Field>
            <Field label="IGST bps">
              <Input value={igstBps} inputMode="numeric" onChange={(event) => setIgstBps(event.target.value)} />
            </Field>
            <Field label="Firm address" className="md:col-span-2">
              <Input value={firmAddress} onChange={(event) => setFirmAddress(event.target.value)} />
            </Field>
            <div className="md:col-span-2">
              <Button
                type="button"
                onClick={() => saveProfileMutation.mutate()}
                disabled={saveProfileMutation.isPending}
              >
                {saveProfileMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                Save default profile
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Invoice number</CardTitle>
            <CardDescription>Preview is based on the default billing profile sequence.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-md border border-[var(--color-line)] px-3 py-2 font-mono text-sm">
              {previewQuery.data?.invoice_number ?? "INV-0001"}
            </div>
            <div className="text-sm text-[var(--color-mute)]">
              Next sequence: {previewQuery.data?.next_invoice_sequence ?? 1}
            </div>
          </CardContent>
        </Card>
      </section>

      <Card>
        <CardHeader>
          <CardTitle>Rate rules</CardTitle>
          <CardDescription>Resolution order is user, role, practice area, then default.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-[1fr_1fr_1fr_auto] md:items-end">
          <Field label="Profile">
            <select
              className="h-10 rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] px-3 text-sm"
              value={profileForRate || profiles[0]?.id || ""}
              onChange={(event) => setProfileForRate(event.target.value)}
            >
              {profiles.map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {profile.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Scope">
            <select
              className="h-10 rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] px-3 text-sm"
              value={rateScope}
              onChange={(event) => setRateScope(event.target.value as typeof rateScope)}
            >
              <option value="default">Default</option>
              <option value="role">Role</option>
              <option value="practice_area">Practice area</option>
            </select>
          </Field>
          <Field label={rateScope === "role" ? "Role" : rateScope === "practice_area" ? "Practice area" : "Qualifier"}>
            <Input
              value={rateScope === "role" ? rateRole : ratePractice}
              disabled={rateScope === "default"}
              onChange={(event) =>
                rateScope === "role"
                  ? setRateRole(event.target.value)
                  : setRatePractice(event.target.value)
              }
            />
          </Field>
          <Field label="Rate INR/hr">
            <Input value={rateValue} inputMode="decimal" onChange={(event) => setRateValue(event.target.value)} />
          </Field>
          <Button
            type="button"
            onClick={() => addRateMutation.mutate()}
            disabled={addRateMutation.isPending || !rateValue}
          >
            Add rate
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Configured profiles</CardTitle>
        </CardHeader>
        <CardContent>
          {profiles.length === 0 ? (
            <EmptyState icon={CreditCard} title="No billing profiles" description="Create the default profile to enable server-side invoice fields." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[var(--color-line)] text-left text-xs uppercase tracking-[0.06em] text-[var(--color-mute)]">
                    <th className="px-3 py-2">Profile</th>
                    <th className="px-3 py-2">Firm GSTIN</th>
                    <th className="px-3 py-2">SAC/HSN</th>
                    <th className="px-3 py-2">Rates</th>
                  </tr>
                </thead>
                <tbody>
                  {profiles.map((profile) => (
                    <tr key={profile.id} className="border-b border-[var(--color-line-2)]">
                      <td className="px-3 py-2 font-medium">
                        {profile.name} {profile.is_default ? "(default)" : ""}
                      </td>
                      <td className="px-3 py-2">{profile.firm_gstin ?? "Not available"}</td>
                      <td className="px-3 py-2">{profile.default_sac_hsn ?? "Not available"}</td>
                      <td className="px-3 py-2">{profile.rates.length}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={className ? `flex flex-col gap-1.5 ${className}` : "flex flex-col gap-1.5"}>
      <span className="text-sm font-medium text-[var(--color-ink-2)]">{label}</span>
      {children}
    </label>
  );
}
