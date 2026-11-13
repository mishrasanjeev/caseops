import { render } from "@testing-library/react";
import { isBlob, loadFromFile } from "react-pdf/dist/shared/utils.js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DraftPdfPages from "./DraftPdfPages";

const documentInput = vi.hoisted(() => vi.fn());
vi.mock("react-pdf", () => ({
  Document: ({ file }: { file: Blob }) => { documentInput(file); return null; },
  Page: () => null,
  pdfjs: { GlobalWorkerOptions: {} },
}));

describe("BUG001 CSP-safe PDF source boundary", () => {
  beforeEach(() => {
    documentInput.mockClear();
    vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("CSP blocks blob URL connections")));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("passes the authorized Blob to Document and reads complete bytes through React-PDF's real FileReader boundary", async () => {
    const bytes = new Uint8Array([37, 80, 68, 70, 45, 0, 255, 10]);
    const file = new Blob([bytes], { type: "application/pdf" });
    render(<DraftPdfPages file={file} />);
    const source = documentInput.mock.calls[0][0];
    expect(source).toBe(file);
    expect(isBlob(source)).toBe(true);
    expect(new Uint8Array(await loadFromFile(source))).toEqual(bytes);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("resolves replacement profile bytes instead of retaining the previous source", async () => {
    const first = new Blob(["%PDF-first-profile"], { type: "application/pdf" });
    const second = new Blob(["%PDF-selected-profile"], { type: "application/pdf" });
    const view = render(<DraftPdfPages key="first" file={first} />);
    expect(documentInput).toHaveBeenCalledTimes(1);
    view.rerender(<DraftPdfPages key="second" file={second} />);
    expect(documentInput).toHaveBeenCalledTimes(2);
    const source = documentInput.mock.calls[1][0];
    expect(source).toBe(second);
    expect(new TextDecoder().decode(await loadFromFile(source))).toBe("%PDF-selected-profile");
    expect(fetch).not.toHaveBeenCalled();
  });
});
