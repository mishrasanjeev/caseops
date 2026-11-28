import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CourtName, courtWebsiteHref } from "@/components/matters/CourtName";

describe("CourtName (Nov 27 row 5)", () => {
  it("opens the court's official website in a new tab with an accessible name", () => {
    render(
      <CourtName
        name="Delhi High Court"
        websiteUrl="https://delhihighcourt.nic.in/"
        variant="badge"
        testId="badge"
      />,
    );
    const link = screen.getByRole("link", {
      name: "Open Delhi High Court website (opens in new tab)",
    });
    expect(link).toHaveAttribute("href", "https://delhihighcourt.nic.in/");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveTextContent("Delhi High Court");
    expect(link).toHaveAttribute("data-court-link", "official");
  });

  it("renders an unmapped court as plain text with no link affordance", () => {
    render(<CourtName name="Kamrup Metro District Court" websiteUrl={null} testId="plain" />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    const text = screen.getByTestId("plain");
    expect(text).toHaveTextContent("Kamrup Metro District Court");
    expect(text).toHaveAttribute("data-court-link", "none");
    // The old badge showed an external-link icon on a non-link; none here.
    expect(text.querySelector("svg.lucide-external-link")).toBeNull();
  });

  it("never links a non-https value and shows the fallback when there is no court", () => {
    expect(courtWebsiteHref("javascript:alert(1)")).toBeNull();
    expect(courtWebsiteHref("http://delhihighcourt.nic.in/")).toBeNull();
    expect(courtWebsiteHref("not a url")).toBeNull();
    render(<CourtName name={null} websiteUrl="https://www.sci.gov.in/" fallback="No court" />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("No court")).toBeInTheDocument();
  });

  it("does not trigger a clickable table row it sits in", () => {
    const onRow = vi.fn();
    render(
      <table>
        <tbody>
          <tr onClick={onRow} onKeyDown={onRow}>
            <td>
              <CourtName name="Bombay High Court" websiteUrl="https://bombayhighcourt.gov.in/" />
            </td>
          </tr>
        </tbody>
      </table>,
    );
    const link = screen.getByRole("link");
    link.addEventListener("click", (event) => event.preventDefault());
    fireEvent.click(link);
    fireEvent.keyDown(link, { key: "Enter" });
    expect(onRow).not.toHaveBeenCalled();
  });
});
