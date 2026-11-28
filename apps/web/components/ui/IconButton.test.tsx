import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Trash2 } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { IconButton } from "@/components/ui/IconButton";
import { Tooltip } from "@/components/ui/Tooltip";

// Nov 27 workbook row 10: the Bookmarks delete icon showed no tooltip and had
// no accessible name. The primitive must name the control and show the label
// on hover AND on keyboard focus, without changing what the click does.
describe("IconButton", () => {
  it("names the control from its required label", () => {
    render(
      <IconButton label="Delete bookmark" onClick={() => {}}>
        <Trash2 aria-hidden />
      </IconButton>,
    );
    expect(screen.getByRole("button", { name: "Delete bookmark" })).toBeInTheDocument();
    expect(screen.getByRole("button")).not.toHaveAttribute("title");
  });

  it("shows the label as a tooltip on hover", async () => {
    const user = userEvent.setup();
    render(
      <IconButton label="Delete bookmark">
        <Trash2 aria-hidden />
      </IconButton>,
    );
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    await user.hover(screen.getByRole("button", { name: "Delete bookmark" }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Delete bookmark");
  });

  it("shows the tooltip on keyboard focus and hides it on Escape", async () => {
    const user = userEvent.setup();
    render(
      <IconButton label="Delete bookmark">
        <Trash2 aria-hidden />
      </IconButton>,
    );
    await user.tab();
    expect(screen.getByRole("button", { name: "Delete bookmark" })).toHaveFocus();
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Delete bookmark");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("tooltip")).not.toBeInTheDocument());
  });

  it("keeps the click action and the disabled state unchanged", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    const { rerender } = render(
      <IconButton label="Delete bookmark" onClick={onClick}>
        <Trash2 aria-hidden />
      </IconButton>,
    );
    await user.click(screen.getByRole("button", { name: "Delete bookmark" }));
    expect(onClick).toHaveBeenCalledTimes(1);
    rerender(
      <IconButton label="Delete bookmark" onClick={onClick} disabled>
        <Trash2 aria-hidden />
      </IconButton>,
    );
    expect(screen.getByRole("button", { name: "Delete bookmark" })).toBeDisabled();
  });

  it("renders a link with the same name and tooltip", async () => {
    const user = userEvent.setup();
    render(
      <IconButton label="Open source" href="https://example.com/source">
        <Trash2 aria-hidden />
      </IconButton>,
    );
    await user.hover(screen.getByRole("link", { name: "Open source" }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Open source");
  });

  it("requires a label and refuses a second, drifting name", () => {
    // @ts-expect-error label is required for an icon-only control.
    const missing = <IconButton><Trash2 aria-hidden /></IconButton>;
    // @ts-expect-error aria-label would drift from the visible tooltip.
    const named = <IconButton label="Delete" aria-label="Remove"><Trash2 aria-hidden /></IconButton>;
    // @ts-expect-error a native title never shows on keyboard focus.
    const titled = <IconButton label="Delete" title="Delete"><Trash2 aria-hidden /></IconButton>;
    expect([missing, named, titled]).toHaveLength(3);
  });
});

describe("Tooltip", () => {
  it("names a raw icon-only control and shows on hover and focus", async () => {
    const user = userEvent.setup();
    render(
      <Tooltip label="Previous month">
        <button type="button">
          <Trash2 aria-hidden />
        </button>
      </Tooltip>,
    );
    const control = screen.getByRole("button", { name: "Previous month" });
    await user.hover(control);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Previous month");
  });

  it("shows on keyboard focus without a pointer", async () => {
    const user = userEvent.setup();
    render(
      <Tooltip label="Previous month">
        <button type="button">
          <Trash2 aria-hidden />
        </button>
      </Tooltip>,
    );
    await user.tab();
    expect(screen.getByRole("button", { name: "Previous month" })).toHaveFocus();
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Previous month");
  });
});

describe("Tooltip inside a dialog", () => {
  it("does not open on the dialog's initial focus, so one Escape still closes the dialog", async () => {
    const user = userEvent.setup();
    const { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } = await import(
      "@/components/ui/Dialog"
    );
    render(
      <Dialog>
        <DialogTrigger>Show events</DialogTrigger>
        <DialogContent>
          <DialogTitle>Events</DialogTitle>
          <DialogDescription>Two events</DialogDescription>
          <a href="/one">One</a>
        </DialogContent>
      </Dialog>,
    );
    await user.click(screen.getByRole("button", { name: "Show events" }));
    // Radix skips links for initial focus, so the corner Close takes it.
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

describe("Tooltip under an asChild trigger", () => {
  it("passes the parent trigger's click, state and ref through to the button", async () => {
    const user = userEvent.setup();
    const { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } = await import(
      "@/components/ui/Dialog"
    );
    render(
      <Dialog>
        <DialogTrigger asChild>
          <Tooltip label="Open navigation menu">
            <button type="button">
              <Trash2 aria-hidden />
            </button>
          </Tooltip>
        </DialogTrigger>
        <DialogContent>
          <DialogTitle>Navigation</DialogTitle>
          <DialogDescription>Menu</DialogDescription>
          <button type="button">Matters</button>
        </DialogContent>
      </Dialog>,
    );
    const trigger = screen.getByRole("button", { name: "Open navigation menu" });
    expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    await user.click(trigger);
    expect(await screen.findByRole("dialog", { name: "Navigation" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // Focus returns to the trigger, which needs the composed ref.
    expect(trigger).toHaveFocus();
  });
});
