import { render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { formProps, notFoundMock } = vi.hoisted(() => ({
  formProps: vi.fn(),
  notFoundMock: vi.fn(() => { throw new Error("NEXT_HTTP_ERROR_FALLBACK;404"); }),
}));

vi.mock("next/navigation", () => ({ notFound: notFoundMock }));
vi.mock("@/components/marketing/DemoRequestForm", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/marketing/DemoRequestForm")>();
  const ActualForm = actual.DemoRequestForm;
  return {
    ...actual,
    DemoRequestForm: (props: ComponentProps<typeof ActualForm>) => {
      formProps(props);
      return <ActualForm {...props} />;
    },
  };
});

import DemoPage, { metadata } from "./page";

describe("seo_demo_20261009 source page contract", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    fetchMock.mockRejectedValue(new Error("Page rendering must not submit a lead or telemetry."));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("NEXT_PUBLIC_GA_MEASUREMENT_ID", "G-OFFLINE-PAGE-GUARD");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("keeps the conversation page nonindexable without hiding followable public links", () => {
    expect(metadata.title).toBe("Request a CaseOps conversation");
    expect(metadata.robots).toEqual({ index: false, follow: true });
  });

  it.each([
    ["solo-lawyers", "solo_lawyers", "solo", "pilot"],
    ["law-firms", "law_firms", "firm", "pilot"],
    ["general-counsels", "general_counsels", "gc", "pilot"],
    ["guide", "guide", "firm", "demo"],
    ["resource", "resource", "firm", "demo"],
  ])("renders the real form with canonical attribution for %s", async (path, source, segment, intent) => {
    render(await DemoPage({ params: Promise.resolve({ source: path }) }));
    expect(screen.getByRole("heading", { level: 1, name: "Request a CaseOps conversation" })).toBeInTheDocument();
    expect(formProps).toHaveBeenLastCalledWith({ source, segment, intent });
    expect(screen.getByRole("form", { name: "Request a demo" })).toBeInTheDocument();
    expect(screen.getByLabelText("Practice / team")).toHaveValue(segment);
    expect(screen.getByLabelText("Full name")).toBeRequired();
    expect(screen.getByLabelText("Work email")).toBeRequired();
    expect(screen.getByLabelText("Role", { exact: true })).toBeRequired();
    expect(screen.getByRole("link", { name: "Request privacy notice" })).toHaveAttribute("href", "/demo/privacy");
    expect(screen.getByRole("link", { name: "CaseOps home" })).toHaveAttribute("href", "/");
    expect(screen.getByText(/Scheduling, coverage, duration and pricing are confirmed separately/)).toBeInTheDocument();
    expect(screen.getByText(/A request is not a subscription or payment authorization/)).toBeInTheDocument();
    expect(screen.queryByText(/^Request saved/)).not.toBeInTheDocument();
    expect(notFoundMock).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(document.querySelector('script[src*="googletagmanager"],script[src*="google-analytics"],iframe[src*="google-analytics"]')).toBeNull();
    expect(document.cookie).not.toMatch(/(?:^|;)\s*_(?:ga|gid|gat)/);
  });

  it.each(["invented-source", "homepage", "guide?utm_campaign=private", ""])(
    "rejects unsupported route source %s before constructing a form",
    async (source) => {
      await expect(DemoPage({ params: Promise.resolve({ source }) })).rejects.toThrow("NEXT_HTTP_ERROR_FALLBACK;404");
      expect(notFoundMock).toHaveBeenCalledOnce();
      expect(formProps).not.toHaveBeenCalled();
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it.each(["constructor", "__proto__"])(
    "rejects inherited-object key %s as an unsupported public source",
    async (source) => {
      await expect(DemoPage({ params: Promise.resolve({ source }) })).rejects.toThrow("NEXT_HTTP_ERROR_FALLBACK;404");
      expect(notFoundMock).toHaveBeenCalledOnce();
      expect(formProps).not.toHaveBeenCalled();
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );
});
