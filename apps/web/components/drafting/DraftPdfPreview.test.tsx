import { act, renderHook, waitFor } from "@testing-library/react";
import { Blob as NodeBlob } from "node:buffer";
import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDraftPdfArtifact } from "./DraftPdfPreview";

vi.mock("next/dynamic", () => ({ default: () => () => null }));

describe("BUG001 revision-bound PDF bytes", () => {
  const fetchMock = vi.fn();
  const create = vi.fn(() => "blob:approved-pdf");
  const revoke = vi.fn();
  beforeEach(() => {
    window.localStorage.clear();
    fetchMock.mockReset(); create.mockClear(); revoke.mockClear();
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("Blob", NodeBlob);
    vi.stubGlobal("crypto", webcrypto);
    vi.stubGlobal("URL", class extends URL {
      static createObjectURL = create;
      static revokeObjectURL = revoke;
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  const pdf = () => new Response("%PDF-synthetic", { headers: { "content-type": "application/pdf" } });

  it("fetches once with credentials and no cache; preview/download use the identical blob", async () => {
    fetchMock.mockResolvedValue(pdf());
    const hook = renderHook(() => useDraftPdfArtifact("https://api.test/export.pdf?version_id=v1&court_profile=delhi_hc", "approved:false"));
    await waitFor(() => expect(hook.result.current.url).toBe("blob:approved-pdf"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: "include", cache: "no-store", headers: { Accept: "application/pdf" } });
    expect(await (create.mock.calls[0] as unknown as [Blob])[0].text()).toBe("%PDF-synthetic");
    hook.unmount();
    expect(revoke).toHaveBeenCalledWith("blob:approved-pdf");
  });

  it.each(["version", "profile", "review", "edit"])("discards the artifact on %s change", async (change) => {
    fetchMock.mockResolvedValueOnce(pdf()).mockImplementation(() => new Promise(() => {}));
    const hook = renderHook(({ source, review }) => useDraftPdfArtifact(source, review), {
      initialProps: { source: "https://api.test/export.pdf?version_id=v1", review: "approved:false" } as { source: string | null; review: string },
    });
    await waitFor(() => expect(hook.result.current.url).toBeTruthy());
    hook.rerender({ source: change === "edit" ? null : `https://api.test/export.pdf?version_id=${change === "version" ? "v2" : "v1"}${change === "profile" ? "&court_profile=generic" : ""}`,
      review: change === "review" ? "draft:true" : "approved:false" });
    expect(hook.result.current.url).toBeNull();
    expect(revoke).toHaveBeenCalledWith("blob:approved-pdf");
  });

  it("never publishes an aborted older response after the profile changes", async () => {
    let resolveOld!: (response: Response) => void;
    fetchMock.mockImplementationOnce(() => new Promise<Response>((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce(pdf());
    const hook = renderHook(({ url }) => useDraftPdfArtifact(url, "approved:false"), { initialProps: { url: "https://api.test/old" } });
    hook.rerender({ url: "https://api.test/new" });
    await waitFor(() => expect(hook.result.current.url).toBeTruthy());
    await act(async () => { resolveOld(pdf()); });
    expect(create).toHaveBeenCalledTimes(1);
  });

  it("does not reuse a revoked PDF when editing is cancelled without a new revision", async () => {
    fetchMock.mockResolvedValueOnce(pdf()).mockImplementation(() => new Promise(() => {}));
    const hook = renderHook(({ source }) => useDraftPdfArtifact(source, "approved:false"), {
      initialProps: { source: "https://api.test/export.pdf?version_id=v1" } as { source: string | null },
    });
    await waitFor(() => expect(hook.result.current.url).toBeTruthy());
    hook.rerender({ source: null });
    hook.rerender({ source: "https://api.test/export.pdf?version_id=v1" });
    expect(hook.result.current.url).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(revoke).toHaveBeenCalledWith("blob:approved-pdf");
  });

  it.each([401, 403, 404, 422, 503])("preserves a %s gate without retries or stale PDF", async (status) => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ detail: "Review or permission required." }), { status, headers: { "content-type": "application/problem+json" } }));
    const hook = renderHook(() => useDraftPdfArtifact("https://api.test/pdf", "draft:true"));
    await waitFor(() => expect(hook.result.current.error).toBe("Review or permission required."));
    expect(hook.result.current.url).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(create).not.toHaveBeenCalled();
  });

  it("rejects a successful non-PDF response, and retries only on command", async () => {
    fetchMock.mockResolvedValueOnce(new Response("sign in", { headers: { "content-type": "text/html" } })).mockResolvedValueOnce(pdf());
    const hook = renderHook(() => useDraftPdfArtifact("https://api.test/pdf", "approved:false"));
    await waitFor(() => expect(hook.result.current.error).toContain("did not return a PDF"));
    expect(hook.result.current.url).toBeNull();
    act(() => hook.result.current.retry());
    await waitFor(() => expect(hook.result.current.url).toBeTruthy());
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("reauthorizes the exact version/profile before returning the displayed blob for download", async () => {
    fetchMock.mockImplementation(async () => pdf());
    const source = "https://api.test/export.pdf?version_id=v1&court_profile=delhi_hc";
    const hook = renderHook(() => useDraftPdfArtifact(source, "approved:false"));
    await waitFor(() => expect(hook.result.current.url).toBeTruthy());
    let url: string | null = null;
    await act(async () => { url = await hook.result.current.revalidate(); });
    expect(url).toBe("blob:approved-pdf");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.every(([value]) => value === source)).toBe(true);
    expect(create).toHaveBeenCalledTimes(1);
  });

  it.each([401, 403, 404, 422])("discards a retained artifact after download-time %s denial", async (status) => {
    fetchMock.mockResolvedValueOnce(pdf()).mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Access or review revoked." }), { status, headers: { "content-type": "application/problem+json" } }));
    const hook = renderHook(() => useDraftPdfArtifact("https://api.test/pdf", "approved:false"));
    await waitFor(() => expect(hook.result.current.url).toBeTruthy());
    let url: string | null = "unexpected";
    await act(async () => { url = await hook.result.current.revalidate(); });
    expect(url).toBeNull();
    expect(hook.result.current.url).toBeNull();
    expect(hook.result.current.error).toBe("Access or review revoked.");
    expect(revoke).toHaveBeenCalledWith("blob:approved-pdf");
    expect(create).toHaveBeenCalledTimes(1);
  });

  it("rejects changed export bytes instead of silently downloading unseen output", async () => {
    fetchMock.mockResolvedValueOnce(pdf()).mockResolvedValueOnce(new Response("%PDF-changed-review-or-preset", { headers: { "content-type": "application/pdf" } }));
    const hook = renderHook(() => useDraftPdfArtifact("https://api.test/pdf", "approved:false"));
    await waitFor(() => expect(hook.result.current.url).toBeTruthy());
    await act(async () => { expect(await hook.result.current.revalidate()).toBeNull(); });
    expect(hook.result.current.url).toBeNull();
    expect(hook.result.current.error).toContain("review state changed");
    expect(revoke).toHaveBeenCalledTimes(1);
  });

  it.each(["profile", "route"])("aborts an in-flight download check on %s change", async (change) => {
    let resolveCheck!: (value: Response) => void;
    fetchMock.mockResolvedValueOnce(pdf()).mockImplementationOnce(() => new Promise<Response>(resolve => { resolveCheck = resolve; }))
      .mockResolvedValueOnce(pdf());
    const hook = renderHook(({ source }) => useDraftPdfArtifact(source, "approved:false"), { initialProps: { source: "https://api.test/old" } });
    await waitFor(() => expect(hook.result.current.url).toBeTruthy());
    let pending!: Promise<string | null>;
    act(() => { pending = hook.result.current.revalidate(); });
    await expect(hook.result.current.revalidate()).resolves.toBeNull();
    if (change === "route") hook.unmount();
    else hook.rerender({ source: "https://api.test/new-profile" });
    await act(async () => { resolveCheck(pdf()); expect(await pending).toBeNull(); });
    expect(revoke).toHaveBeenCalledWith("blob:approved-pdf");
  });

  it("uses shared single-refresh recovery for an expired binary session", async () => {
    window.localStorage.setItem("caseops.session.context", "{}");
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ type: "expired_token", detail: "Expired session." }), {
      status: 401, headers: { "content-type": "application/problem+json" },
    })).mockResolvedValueOnce(new Response(JSON.stringify({ access_token: "fresh-draft-token", company: {}, user: {}, membership: {} }), {
      headers: { "content-type": "application/json" },
    })).mockResolvedValueOnce(pdf());
    const hook = renderHook(() => useDraftPdfArtifact("https://api.test/export.pdf?version_id=v1", "approved:false"));
    await waitFor(() => expect(hook.result.current.url).toBe("blob:approved-pdf"));
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(String(fetchMock.mock.calls[1][0])).toMatch(/\/api\/auth\/refresh$/);
    expect(fetchMock.mock.calls[2][1].headers).toMatchObject({ Authorization: "Bearer fresh-draft-token" });
  });

  it("does not bypass a policy denial following a successful authentication refresh", async () => {
    window.localStorage.setItem("caseops.session.context", "{}");
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ type: "expired_token", detail: "Expired session." }), {
      status: 401, headers: { "content-type": "application/problem+json" },
    })).mockResolvedValueOnce(new Response(JSON.stringify({ access_token: "fresh-draft-token", company: {}, user: {}, membership: {} }), {
      headers: { "content-type": "application/json" },
    })).mockResolvedValueOnce(new Response(JSON.stringify({ type: "permission_denied", detail: "Draft access revoked." }), {
      status: 403, headers: { "content-type": "application/problem+json" },
    }));
    const hook = renderHook(() => useDraftPdfArtifact("https://api.test/export.pdf?version_id=v1", "approved:false"));
    await waitFor(() => expect(hook.result.current.error).toBe("Draft access revoked."));
    expect(hook.result.current.url).toBeNull();
    expect(create).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
