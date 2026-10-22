import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DemoPrivacyPage, { metadata } from "./page";
import { siteConfig } from "@/lib/site";

describe("seo_demo_20261009 request privacy page contract", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockRejectedValue(new Error("Privacy rendering must not send a lead or telemetry."));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("NEXT_PUBLIC_GA_MEASUREMENT_ID", "G-OFFLINE-PAGE-GUARD");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("publishes the exact privacy title and canonical", () => {
    expect(metadata.title).toBe("Demo request privacy notice");
    expect(metadata.alternates).toEqual({ canonical: "/demo/privacy" });
  });

  it("limits the notice to public requests and warns against client or privileged data", () => {
    render(<DemoPrivacyPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Demo request privacy notice" })).toBeInTheDocument();
    expect(screen.getByText(/Version 2026-10-21.*not tenant workspace records/)).toBeInTheDocument();
    expect(screen.getByText(/authorized platform managers with multi-factor authentication.*protected Leads dashboard.*Do not submit client names, case details, privileged material or confidential documents/)).toBeInTheDocument();
  });

  it("names minimal first-party attribution and excludes sensitive URLs and tracking", () => {
    render(<DemoPrivacyPage />);
    expect(screen.getByText(/public entry point.*practice segment, role, request intent and this notice version/)).toBeInTheDocument();
    expect(screen.getByText(/do not collect full URLs, query strings, referrers, tracking cookies, GA4 or other client-side analytics/)).toBeInTheDocument();
    expect(screen.getByText(/A click is not an accepted lead or proof of organic conversion/)).toBeInTheDocument();
  });

  it("qualifies new-only reference mail without promising activation or inbox delivery", () => {
    render(<DemoPrivacyPage />);
    expect(screen.getByText(/saved before acceptance is shown.*Once server-side notification is activated, only new submissions.*designated CaseOps enquiry recipient through SendGrid/)).toBeInTheDocument();
    expect(screen.getByText(/request reference and a protected dashboard link, not your submitted details/)).toBeInTheDocument();
    expect(screen.getByText(/Historical requests are not bulk mailed.*Notification failure does not delete your request/)).toBeInTheDocument();
    expect(screen.getByText(/Known rejected delivery may be retried within a fixed limit; uncertain delivery is held for inspection, not automatically resent/)).toBeInTheDocument();
    expect(screen.getByText(/Provider acceptance does not guarantee inbox delivery/)).toBeInTheDocument();
    expect(screen.queryByText(/Outbound notification is disabled pending sender approval/)).not.toBeInTheDocument();
  });

  it("keeps the narrow proposed expiry separate from authorized deletion and retained records", () => {
    render(<DemoPrivacyPage />);
    expect(screen.getByText(/90-day expiry is proposed only for new, unconverted public-demo requests.*automated deletion is disabled pending policy review/)).toBeInTheDocument();
    expect(screen.getByText(/Existing enrollment, account, billing and legal records are outside that proposal/)).toBeInTheDocument();
    expect(screen.getByText(/account or retained commercial note requires separate retention review/)).toBeInTheDocument();
  });

  it("does not promise payment authorization, pilot terms, provider availability or a legal outcome", () => {
    render(<DemoPrivacyPage />);
    expect(screen.getByText(/does not activate a subscription, authorize payment, or guarantee a response time, pilot terms, provider availability or legal outcome/)).toBeInTheDocument();
  });

  it("links a reference-based deletion contact and the existing public conversation surface", () => {
    render(<DemoPrivacyPage />);
    expect(screen.getByRole("link", { name: siteConfig.contact.founder })).toHaveAttribute("href", `mailto:${siteConfig.contact.founder}`);
    expect(screen.getByRole("link", { name: "Request a conversation" })).toHaveAttribute("href", "/#cta");
    expect(screen.getAllByRole("link")).toHaveLength(2);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
  });

  it("renders without telemetry, tracking cookies or background requests despite a configured GA identifier", () => {
    expect(process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID).toBeTruthy();
    render(<DemoPrivacyPage />);
    expect(document.querySelector('script,iframe,img[src*="google-analytics"],img[src*="googletagmanager"]')).toBeNull();
    expect(document.cookie).not.toMatch(/(?:^|;)\s*_(?:ga|gid|gat)/);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
