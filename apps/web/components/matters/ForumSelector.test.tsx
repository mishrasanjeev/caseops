import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import {
  EMPTY_FORUM_SELECTION,
  ForumSelector,
  type ForumSelection,
  forumSelectionFromEntry,
} from "@/components/matters/ForumSelector";
import type { ForumCatalogEntry } from "@/lib/api/schemas";

const ENTRIES: ForumCatalogEntry[] = [
  {
    id: "sc:india",
    parent_id: null,
    court_id: "supreme-court-india",
    name: "Supreme Court of India",
    forum_type: "supreme_court",
    forum_level: "supreme_court",
    state: null,
    district: null,
    city: "New Delhi",
    consumer_level: null,
    source_name: "CaseOps LW-S4 baseline forum catalog",
    source_url: null,
    lineage: "Supreme Court > India",
    display_order: 10,
  },
  {
    id: "hc:delhi",
    parent_id: null,
    court_id: "delhi-hc",
    name: "Delhi High Court",
    forum_type: "high_court",
    forum_level: "high_court",
    state: "Delhi",
    district: null,
    city: "New Delhi",
    consumer_level: null,
    source_name: "CaseOps LW-S4 baseline forum catalog",
    source_url: null,
    lineage: "High Court > Delhi > Delhi High Court",
    display_order: 20,
  },
  {
    id: "hc:karnataka",
    parent_id: null,
    court_id: "karnataka-hc",
    name: "Karnataka High Court",
    forum_type: "high_court",
    forum_level: "high_court",
    state: "Karnataka",
    district: null,
    city: "Bengaluru",
    consumer_level: null,
    source_name: "CaseOps LW-S4 baseline forum catalog",
    source_url: null,
    lineage: "High Court > Karnataka > Karnataka High Court",
    display_order: 21,
  },
  {
    id: "district:delhi:central",
    parent_id: null,
    court_id: null,
    name: "Central District Court, Delhi",
    forum_type: "district_court",
    forum_level: "lower_court",
    state: "Delhi",
    district: "Central",
    city: "New Delhi",
    consumer_level: null,
    source_name: "CaseOps LW-S4 baseline forum catalog",
    source_url: null,
    lineage: "District Court > Delhi > Central > New Delhi",
    display_order: 100,
  },
  {
    id: "consumer:ncdrc",
    parent_id: null,
    court_id: null,
    name: "National Consumer Disputes Redressal Commission",
    forum_type: "consumer_forum",
    forum_level: "tribunal",
    state: null,
    district: null,
    city: "New Delhi",
    consumer_level: "national",
    source_name: "CaseOps LW-S4 baseline forum catalog",
    source_url: null,
    lineage: "Consumer Forum > NCDRC",
    display_order: 200,
  },
  {
    id: "consumer:scdrc:delhi",
    parent_id: "consumer:ncdrc",
    court_id: null,
    name: "Delhi State Consumer Disputes Redressal Commission",
    forum_type: "consumer_forum",
    forum_level: "tribunal",
    state: "Delhi",
    district: null,
    city: "New Delhi",
    consumer_level: "state",
    source_name: "CaseOps LW-S4 baseline forum catalog",
    source_url: null,
    lineage: "Consumer Forum > SCDRC > Delhi",
    display_order: 210,
  },
  {
    id: "consumer:dcdrc:central-delhi",
    parent_id: "consumer:scdrc:delhi",
    court_id: null,
    name: "Central Delhi District Consumer Disputes Redressal Commission",
    forum_type: "consumer_forum",
    forum_level: "tribunal",
    state: "Delhi",
    district: "Central",
    city: "New Delhi",
    consumer_level: "district",
    source_name: "CaseOps LW-S4 baseline forum catalog",
    source_url: null,
    lineage: "Consumer Forum > DCDRC > Delhi > Central",
    display_order: 230,
  },
];

function Harness({ initial }: { initial?: ForumSelection }) {
  const [selection, setSelection] = useState<ForumSelection>(
    initial ?? forumSelectionFromEntry(ENTRIES[1]),
  );
  return (
    <ForumSelector
      entries={ENTRIES}
      value={selection}
      onChange={setSelection}
      idPrefix="test-forum"
    />
  );
}

describe("ForumSelector", () => {
  it("does not require state for Supreme Court selection", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.selectOptions(screen.getByTestId("test-forum-category"), "supreme_court");

    expect(screen.getByTestId("test-forum-supreme")).toHaveValue("sc:india");
    expect(screen.queryByTestId("test-forum-state")).toBeNull();
    expect(screen.getByText(/Supreme Court > India/i)).toBeInTheDocument();
  });

  it("requires state for High Court selection", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    expect(screen.getByTestId("test-forum-state")).toHaveValue("Delhi");
    await user.selectOptions(screen.getByTestId("test-forum-state"), "Karnataka");

    await waitFor(() =>
      expect(screen.getByTestId("test-forum-state")).toHaveValue("Karnataka"),
    );
    expect(screen.getByText(/High Court > Karnataka/i)).toBeInTheDocument();
  });

  it("requires state and district/city for District Court selection", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.selectOptions(screen.getByTestId("test-forum-category"), "district_court");

    expect(screen.getByTestId("test-forum-district-state")).toHaveValue("Delhi");
    expect(screen.getByTestId("test-forum-district")).toHaveValue(
      "district:delhi:central",
    );
    expect(screen.getByText(/District Court > Delhi > Central/i)).toBeInTheDocument();
  });

  it("supports national, state, and district consumer forum levels", async () => {
    const user = userEvent.setup();
    render(<Harness initial={EMPTY_FORUM_SELECTION} />);

    await user.selectOptions(screen.getByTestId("test-forum-category"), "consumer_forum");
    expect(screen.getByTestId("test-forum-consumer-level")).toHaveValue("national");
    expect(screen.queryByTestId("test-forum-consumer-state")).toBeNull();

    await user.selectOptions(screen.getByTestId("test-forum-consumer-level"), "state");
    expect(screen.getByTestId("test-forum-consumer-state")).toHaveValue("Delhi");

    await user.selectOptions(screen.getByTestId("test-forum-consumer-level"), "district");
    expect(screen.getByTestId("test-forum-consumer-state")).toHaveValue("Delhi");
    expect(screen.getByTestId("test-forum-consumer-district")).toHaveValue(
      "consumer:dcdrc:central-delhi",
    );
  });
});
