import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IpDomainAvailability } from "./IpDomainAvailability";
import { ipDomainCatalogueSchema, type IpDomainCapability } from "@/lib/ip/domain-catalog";

const patent: IpDomainCapability = {
  domain: "patent", label: "Patents", stage: "unavailable", contract_version: "pending",
  jurisdictions: [], offices: [], intake_available: false,
  authoritative_automation_available: false, blockers: ["domain_implementation_missing"],
  required_journeys: ["UJ-29", "UJ-39", "UJ-40"],
};
const catalogue = { catalogue_version: "test-v1", domains: [patent] };

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("IPLF-079 domain availability", () => {
  it("uses readiness data without another supporting request", () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    render(<IpDomainAvailability domains={[patent]} />);
    expect(within(screen.getByTestId("ip-domain-patent")).getByText("Unavailable")).toBeVisible();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("publishes the public server catalogue without tenant credentials", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => catalogue });
    vi.stubGlobal("fetch", fetcher);
    render(<IpDomainAvailability />);
    expect(await screen.findByText("Patents")).toBeVisible();
    expect(fetcher).toHaveBeenCalledWith(expect.stringContaining("/api/ip-domains"),
      expect.objectContaining({ credentials: "omit", cache: "no-store", signal: expect.any(AbortSignal) }));
  });

  it("does not invent availability after an outage and supports explicit retry", async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ ok: true, json: async () => catalogue });
    vi.stubGlobal("fetch", fetcher);
    render(<IpDomainAvailability />);
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be verified");
    expect(screen.queryByText("Patents")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Patents")).toBeVisible();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("rejects incomplete, duplicate and contradictory API payloads", async () => {
    for (const domains of [[], [patent, patent], [{ ...patent, stage: "ga" }],
      [{ ...patent, authoritative_automation_available: true }]]) {
      expect(ipDomainCatalogueSchema.safeParse({ ...catalogue, domains }).success).toBe(false);
    }
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ domains: [] }) }));
    render(<IpDomainAvailability />);
    expect(await screen.findByRole("alert")).toBeVisible();
  });

  it("uses later authoritative readiness after an earlier public fetch failed", async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error("offline"));
    vi.stubGlobal("fetch", fetcher);
    const view = render(<IpDomainAvailability />);
    expect(await screen.findByRole("alert")).toBeVisible();
    view.rerender(<IpDomainAvailability domains={[patent]} />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("Patents")).toBeVisible();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("aborts its request when unmounted", async () => {
    const fetcher = vi.fn().mockImplementation((_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => reject(new Error("aborted")));
    }));
    vi.stubGlobal("fetch", fetcher);
    const view = render(<IpDomainAvailability />);
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    const signal = fetcher.mock.calls[0][1].signal;
    view.unmount();
    expect(signal.aborted).toBe(true);
  });

  it.each(["headers", "body"])("bounds stalled %s, makes no automatic retry, and recovers", async (phase) => {
    vi.useFakeTimers();
    const fetcher = vi.fn().mockImplementationOnce((_url, options) => {
      const stalled = () => new Promise((_resolve, reject) => {
        options.signal.addEventListener("abort", () => reject(options.signal.reason));
      });
      return phase === "headers" ? stalled() : Promise.resolve({ ok: true, json: stalled });
    }).mockResolvedValueOnce({ ok: true, json: async () => catalogue });
    vi.stubGlobal("fetch", fetcher);
    render(<IpDomainAvailability />);
    await act(async () => { await vi.advanceTimersByTimeAsync(4999); });
    expect(screen.getByRole("status")).toBeVisible();
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(screen.getByRole("alert")).toBeVisible();
    expect(screen.queryByText("Patents")).not.toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Retry" })); });
    expect(screen.getByText("Patents")).toBeVisible();
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(0);
  });
});
