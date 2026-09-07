"use client";

import { RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { fetchJsonWithTimeout } from "@/lib/api/client";
import { API_BASE_URL } from "@/lib/api/config";
import { DOMAIN_STAGE_LABELS, ipDomainCatalogueSchema, type IpDomainCapability } from "@/lib/ip/domain-catalog";

export function IpDomainAvailability({ domains }: { domains?: IpDomainCapability[] }) {
  const [loaded, setLoaded] = useState<IpDomainCapability[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (domains) return;
    const controller = new AbortController();
    let active = true;
    setFailed(false);
    setLoaded(null);
    void fetchJsonWithTimeout(`${API_BASE_URL}/api/ip-domains`, {
      signal: controller.signal, credentials: "omit", cache: "no-store",
    }, 5000).then((response) => {
      if (!response.ok) throw new Error("Availability request failed");
      const catalogue = ipDomainCatalogueSchema.parse(response.data);
      if (active) setLoaded(catalogue.domains);
    }).catch(() => {
      if (active) setFailed(true);
    });
    return () => { active = false; controller.abort(); };
  }, [domains, attempt]);

  const rows = domains ?? loaded;
  return (
    <section aria-label="IP domain availability" className="min-w-0 border-y border-[var(--color-line)] py-5">
      <h2 className="text-base font-semibold">IP domain availability</h2>
      {failed && !domains ? (
        <div className="mt-3 flex min-w-0 flex-wrap items-center gap-3" role="alert">
          <p className="text-sm">Current availability could not be verified.</p>
          <Button variant="secondary" size="sm" onClick={() => setAttempt((value) => value + 1)}>
            <RefreshCw className="h-4 w-4" aria-hidden /> Retry
          </Button>
        </div>
      ) : rows ? (
        <dl className="mt-3 grid min-w-0 gap-x-8 sm:grid-cols-2 xl:grid-cols-3">
          {rows.map((row) => (
            <div key={row.domain} data-testid={`ip-domain-${row.domain}`} className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-[var(--color-line)] py-3 text-sm">
              <dt className="min-w-0 break-words font-medium">{row.label}</dt>
              <dd className={row.stage === "ga" ? "text-[var(--color-brand-700)]" : "text-[var(--color-mute)]"}>
                {DOMAIN_STAGE_LABELS[row.stage]}
              </dd>
            </div>
          ))}
        </dl>
      ) : <p className="mt-3 text-sm text-[var(--color-mute)]" role="status">Checking availability...</p>}
    </section>
  );
}
