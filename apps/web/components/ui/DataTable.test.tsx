import type { ColumnDef } from "@tanstack/react-table";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DataTable } from "@/components/ui/DataTable";

type Row = { id: string; name: string; due: string };

const rows: Row[] = [
  { id: "1", name: "Alpha", due: "2026-05-10" },
  { id: "2", name: "Bravo", due: "2026-04-15" },
  { id: "3", name: "Charlie", due: "2026-06-01" },
];

const columns: ColumnDef<Row, unknown>[] = [
  { accessorKey: "name", header: "Name" },
  { accessorKey: "due", header: "Due" },
];

describe("DataTable", () => {
  it("filters rows via the accessible text input", async () => {
    const user = userEvent.setup();
    render(<DataTable columns={columns} data={rows} />);
    const filter = screen.getByRole("textbox", { name: "Filter rows" });
    await user.type(filter, "brav");
    expect(screen.getByText("Bravo")).toBeInTheDocument();
    expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
    expect(screen.queryByText("Charlie")).not.toBeInTheDocument();
    expect(screen.getByText(/1-1 of 1/)).toBeInTheDocument();
  });

  it("activates rows by mouse click AND Enter/Space on keyboard", async () => {
    const user = userEvent.setup();
    const onRowClick = vi.fn();
    render(
      <DataTable
        columns={columns}
        data={rows}
        onRowClick={onRowClick}
        getRowId={(r) => r.id}
      />,
    );

    const bravoCell = screen.getByText("Bravo");
    // <tr> is the interactive element; walk up to it.
    const row = bravoCell.closest("tr");
    expect(row).not.toBeNull();
    expect(row).toHaveAttribute("role", "button");
    expect(row).toHaveAttribute("tabindex", "0");

    await user.click(bravoCell);
    expect(onRowClick).toHaveBeenNthCalledWith(1, rows[1]);

    // Keyboard — focus the row, press Enter, then Space.
    (row as HTMLElement).focus();
    await user.keyboard("{Enter}");
    expect(onRowClick).toHaveBeenNthCalledWith(2, rows[1]);
    await user.keyboard(" ");
    expect(onRowClick).toHaveBeenNthCalledWith(3, rows[1]);
  });

  it("pins only the last column when the caller asks, so row actions stay on screen", () => {
    const { unmount } = render(<DataTable columns={columns} data={rows} pinLastColumn />);
    const pinnedRow = screen.getByText("Bravo").closest("tr") as HTMLElement;
    const cells = Array.from(pinnedRow.querySelectorAll("td"));
    expect(cells.at(-1)?.className).toMatch(/sticky right-0/);
    expect(cells[0].className).not.toMatch(/sticky/);
    expect(screen.getByRole("columnheader", { name: "Due" }).className).toMatch(/sticky right-0/);
    unmount();
    render(<DataTable columns={columns} data={rows} />);
    const plainRow = screen.getByText("Bravo").closest("tr") as HTMLElement;
    expect(plainRow.innerHTML).not.toMatch(/sticky/);
  });

  it("labels Previous and Next pagination buttons for screen readers", () => {
    render(<DataTable columns={columns} data={rows} />);
    expect(screen.getByRole("button", { name: /Previous page/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Next page/i })).toBeInTheDocument();
  });
});
