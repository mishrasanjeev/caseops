import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { capabilityMock } = vi.hoisted(() => ({ capabilityMock: vi.fn() }));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => capabilityMock(capability),
}));

import PlatformAdminPage from "@/app/app/platform-admin/page";
import { platformEnrollmentRecord } from "@/lib/api/schemas";
import { enrollments, jsonResponse, mockBillingFetch } from "@/test/billing-fixtures";

const demoEnrollment = {
  ...enrollments.enrollments[0],
  id: "seo-demo-local-reference",
  company_id: null,
  company_name: "Offline Practice",
  contact_name: "Offline Demo Partner",
  contact_email: "seo-admin-readback@example.com",
  contact_mobile: "5550100",
  notes: "Discuss a scoped pilot; no client records.",
  source: "law_firms",
  status: "demo_requested",
  selected_plan: null,
  attribution: {
    entry_point: "law_firms", role: "partner", intent: "pilot",
    privacy_notice_version: "2026-10-09", attribution_qualified: true,
  },
  demo_notification: {
    notification_status: "pending", attempts: 0, last_error_code: "sender_approval_pending",
    next_attempt_at: "2026-10-09T12:05:00+00:00", expires_at: "2027-01-07T12:00:00+00:00",
  },
};

function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("PlatformAdminPage", () => {
  const fetchMock = vi.fn();
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    fetchMock.mockReset();
    mockBillingFetch(fetchMock);
    originalFetch = globalThis.fetch;
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("denies tenant admins without platform capability", () => {
    capabilityMock.mockReturnValue(false);
    renderWithQuery(<PlatformAdminPage />);

    expect(screen.getByText("Access denied")).toBeInTheDocument();
    expect(screen.getByText(/tenant admin roles do not grant/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("renders founder-only overview, enrollments, and margin alerts", async () => {
    capabilityMock.mockReturnValue(true);
    renderWithQuery(<PlatformAdminPage />);

    expect(await screen.findByText("Monthly recurring revenue")).toBeInTheDocument();
    expect(screen.getAllByText("Acme Law").length).toBeGreaterThan(0);
    expect(screen.getByText(/stress-case margin/i)).toBeInTheDocument();
  });

  it("seo_demo_20261009 preserves the complete protected enrollment DTO", () => {
    expect(platformEnrollmentRecord.parse(demoEnrollment)).toEqual(demoEnrollment);
  });

  it("seo_demo_20261009 accepts legacy rows without inventing attribution or delivery", () => {
    const parsed = platformEnrollmentRecord.parse(enrollments.enrollments[0]);
    expect(parsed.id).toBe("enroll-1");
    expect(parsed.attribution?.attribution_qualified).not.toBe(true);
    expect(parsed.demo_notification?.notification_status).toBeUndefined();
  });

  it("seo_demo_20261009 renders persisted contact and qualification through the real parser", async () => {
    capabilityMock.mockReturnValue(true);
    const fallback = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) =>
      String(input).includes("/api/platform-admin/enrollments")
        ? jsonResponse({ enrollments: [demoEnrollment, enrollments.enrollments[0]] })
        : fallback(input, init));
    renderWithQuery(<PlatformAdminPage />);
    const row = (await screen.findByText(demoEnrollment.contact_email)).closest("tr")!;
    const cells = within(row);
    for (const value of [demoEnrollment.contact_name, demoEnrollment.contact_mobile, demoEnrollment.notes,
      "Law firms", "Role: Partner", "Intent: Pilot discussion", "Pending sender approval", "Error code: sender_approval_pending"])
      expect(cells.getByText(value, { exact: true })).toBeInTheDocument();
    expect(cells.getByText(demoEnrollment.id, { exact: false })).toBeInTheDocument();
    expect(cells.queryByText(/^Sent/)).not.toBeInTheDocument();
    const legacy = screen.getByText("owner@example.com").closest("tr")!;
    expect(within(legacy).getByText("Unqualified attribution")).toBeInTheDocument();
    expect(within(legacy).getAllByText("Not recorded")).toHaveLength(2);
  });

  it.each([
    ["retry_pending", "Retry pending"], ["exhausted", "Attempts exhausted"],
    ["sent", "Sent (transport accepted)"],
  ])("seo_demo_20261009 renders actual notification state %s", async (state, label) => {
    capabilityMock.mockReturnValue(true);
    const fallback = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) =>
      String(input).includes("/api/platform-admin/enrollments")
        ? jsonResponse({ enrollments: [{ ...demoEnrollment,
          demo_notification: { ...demoEnrollment.demo_notification, notification_status: state, last_error_code: null } }] })
        : fallback(input, init));
    renderWithQuery(<PlatformAdminPage />);
    expect(await screen.findByText(label)).toBeInTheDocument();
  });

  it("seo_demo_20261009 keeps load errors distinct from an empty enrollment list", async () => {
    capabilityMock.mockReturnValue(true);
    const fallback = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) =>
      String(input).includes("/api/platform-admin/enrollments")
        ? jsonResponse({ detail: "Readback unavailable" }, 503) : fallback(input, init));
    renderWithQuery(<PlatformAdminPage />);
    expect(await screen.findByText("Unable to load enrollments.")).toBeInTheDocument();
    expect(screen.queryByText("No enrollment activity yet.")).not.toBeInTheDocument();
  });
});
