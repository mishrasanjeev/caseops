import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DemoRequestForm } from "./DemoRequestForm";

async function fill() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Full name"), "Demo Advocate");
  await user.type(screen.getByLabelText("Work email"), "demo@example.com");
  await user.selectOptions(screen.getByLabelText("Role"), "solo_advocate");
  return user;
}

describe("seo_demo_20261009 public form", () => {
  const fetchMock = vi.fn();
  beforeEach(() => vi.stubGlobal("fetch", fetchMock.mockReset()));
  afterEach(() => vi.unstubAllGlobals());
  it("saves with explicit role, attribution and notice, without tracking", async () => {
    fetchMock.mockImplementation(async (_url, init) => Response.json({ accepted: true, id: JSON.parse(init.body).idempotency_key, status: "demo_requested" }, { status: 202 }));
    render(<DemoRequestForm source="homepage" />);
    const user = await fill();
    await user.click(screen.getByRole("button", { name: "Request a conversation" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Request saved.");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/demo-request");
    expect(JSON.parse(init.body)).toMatchObject({ source: "homepage", role: "solo_advocate", segment: "solo", privacy_notice_version: "2026-10-09" });
    expect(init).toMatchObject({ credentials: "omit", referrerPolicy: "no-referrer" });
    expect(screen.getByRole("button", { name: "Request a conversation" })).toBeDisabled();
    expect(document.cookie).toBe("");
  });
  it.each(["timeout", "503", "429", "invalid-id"])("keeps one immutable key after %s and never automatically retries", async (failure) => {
    fetchMock.mockImplementationOnce(async () => {
      if (failure === "timeout") throw new Error("timeout");
      if (failure === "invalid-id") return Response.json({ accepted: true, status: "demo_requested", id: crypto.randomUUID() });
      return Response.json({ error: "Unconfirmed request" }, { status: Number(failure) });
    });
    fetchMock.mockImplementation(async (_url, init) => Response.json({ accepted: true, id: JSON.parse(init.body).idempotency_key, status: "demo_requested" }));
    render(<DemoRequestForm source="solo_lawyers" intent="pilot" />);
    const user = await fill();
    await user.click(screen.getByRole("button", { name: "Request a conversation" }));
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Full name")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Retry the same request" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Request saved.");
    expect(fetchMock.mock.calls[0][1].body).toBe(fetchMock.mock.calls[1][1].body);
  });
  it("permits correction after explicit validation rejection", async () => {
    fetchMock.mockResolvedValue(Response.json({ error: "Review details" }, { status: 422 }));
    render(<DemoRequestForm source="homepage" />);
    const user = await fill();
    await user.click(screen.getByRole("button", { name: "Request a conversation" }));
    await screen.findByRole("alert");
    expect(screen.getByLabelText("Full name")).not.toBeDisabled();
  });
  it("updates pricing audience without attributing an incompatible plan", async () => {
    fetchMock.mockImplementation(async (_url, init) => Response.json({ accepted: true, id: JSON.parse(init.body).idempotency_key, status: "demo_requested" }));
    const { rerender } = render(<DemoRequestForm source="pricing_page" segment="solo" selectedPlan="solo_pro" />);
    rerender(<DemoRequestForm source="pricing_page" segment="gc" selectedPlan={null} />);
    await waitFor(() => expect(screen.getByLabelText("Practice / team")).toHaveValue("gc"));
    const user = await fill();
    await user.click(screen.getByRole("button", { name: "Request a conversation" }));
    await screen.findByRole("status");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ segment: "gc", selected_plan: null });
  });
});
