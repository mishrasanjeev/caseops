import Script from "next/script";

// Google Analytics 4 integration. Controlled by the build-time env
// var ``NEXT_PUBLIC_GA_MEASUREMENT_ID`` — when absent (dev, e2e,
// preview deploys), this renders nothing and no GA traffic leaves
// the browser. Production sets the ID via Dockerfile build-arg.
//
// Why the script strategy is "afterInteractive": blocking GA on
// first paint hurts LCP on a legal product where a 1-2s delay is
// felt. GA works fine when loaded after the page is ready — we
// don't need first-paint telemetry for the demo.
//
// Consent note: this is a legal-tech product. Before onboarding
// real customer data, wire a consent banner + gate GA load on
// user opt-in (for DPDP / GDPR compliance). See the domain
// runbook's "Consent and PII" section.
export function GoogleAnalytics() {
  const id = process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID;
  if (!id) return null;
  return (
    <>
      <Script
        src={`https://www.googletagmanager.com/gtag/js?id=${id}`}
        strategy="afterInteractive"
      />
      <Script id="ga-init" strategy="afterInteractive">
        {`
          window.dataLayer = window.dataLayer || [];
          function gtag(){dataLayer.push(arguments);}
          gtag('js', new Date());
          gtag('config', '${id}', { send_page_view: true });
        `}
      </Script>
    </>
  );
}
