import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ record: vi.fn(), publications: vi.fn(), submit: vi.fn() }));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "docket-1" }) }));
vi.mock("@/lib/api/portal", () => ({ fetchPortalIpRecord: mocks.record, fetchPortalPublications: mocks.publications, submitPortalInstruction: mocks.submit }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import PortalIpRecordPage from "@/app/portal/ip/[id]/page";

describe("PortalIpRecordPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.record.mockResolvedValue({ id: "docket-1", title: "ASTER DEVICE", record_type: "trademark", status: "filed", primary_identifier: "TM-421", identifiers: ["TM-421", "OPP-88"], events: [], upcoming_dates: [], grant_expires_at: null });
    mocks.publications.mockResolvedValue({ publications: [{ id: "pub-1", publication_kind: "report", title: "Opposition status", status: "published", access_state: "available", delivery_status: "delivered", summary: { published_record_count: 1 }, rows: [{ opposition_numbers: ["OPP-88"] }], document_filename: null, targets: [{ ip_docket_record_id: "docket-1", docket_title: "ASTER DEVICE", current: true }] }] });
    mocks.submit.mockResolvedValue({ id: "instruction-1", status: "pending" });
  });

  it("shows approved data and sends a structured instruction", async () => {
    const user = userEvent.setup();
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><PortalIpRecordPage /></QueryClientProvider>);
    expect(await screen.findByText("OPP-88")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Approved publication"), "pub-1");
    await user.selectOptions(screen.getByLabelText("Instruction type"), "proceeding");
    await user.type(screen.getByLabelText("Instruction details"), "Proceed with the opposition response.");
    await user.click(screen.getByRole("button", { name: "Send for firm acknowledgement" }));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledWith(expect.objectContaining({ publicationId: "pub-1", docketId: "docket-1", instructionKind: "proceeding", decision: "proceed" })));
  });
});
