import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { IpIndiaSources } from "./IpIndiaSources";

afterEach(() => vi.unstubAllGlobals());

it("offers bounded content search without registry/provider/network calls", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  render(<IpIndiaSources />);
  fireEvent.click(screen.getByText("IP India official sources and form references"));
  expect(screen.getByRole("status")).toHaveTextContent("7 of 7 references");
  fireEvent.change(screen.getByLabelText("Search official references"), { target: { value: "nationality" } });
  expect(screen.getByRole("status")).toHaveTextContent("1 of 7 references");
  expect(screen.getByText("Applicant name, nationality and address")).toBeVisible();
  expect(screen.getByText(/not a completed form or filing validation/)).toBeVisible();
  expect(screen.queryByText("IP India trademark public search")).not.toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
});

it("distinguishes filtered forms, rule and register access boundaries", () => {
  render(<IpIndiaSources />);
  fireEvent.click(screen.getByText("IP India official sources and form references"));
  fireEvent.change(screen.getByLabelText("Source type"), { target: { value: "register" } });
  expect(screen.getByRole("status")).toHaveTextContent("3 of 7 references");
  expect(screen.getByText(/OTP and CAPTCHA/)).toBeVisible();
  expect(screen.getByText(/No register records are imported/)).toBeVisible();
  fireEvent.change(screen.getByLabelText("Search official references"), { target: { value: "unknown-right-999" } });
  expect(screen.getByRole("status")).toHaveTextContent("0 of 7 references");
  expect(screen.getByText(/does not mean a right or official record does not exist/)).toBeVisible();
});

it("keeps external sources referrer-free and makes duplicate instances accessible", () => {
  render(<><IpIndiaSources /><IpIndiaSources /></>);
  const summaries = screen.getAllByText("IP India official sources and form references");
  for (const summary of summaries) fireEvent.click(summary);
  const regions = screen.getAllByRole("region", { name: "IP India reference search" });
  const ids = regions.map((region) => within(region).getByLabelText("Search official references").id);
  expect(new Set(ids).size).toBe(2);
  for (const region of regions) for (const link of within(region).getAllByRole("link")) {
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(link).toHaveAttribute("target", "_blank");
  }
});
