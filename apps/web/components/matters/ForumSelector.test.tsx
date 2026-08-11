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
    name: "Tis Hazari Courts Complex",
    forum_type: "district_court",
    forum_level: "lower_court",
    state: "Delhi",
    district: "Central & West",
    city: "Tis Hazari",
    consumer_level: null,
    source_name: "CaseOps LW-S4 baseline forum catalog",
    source_url: null,
    lineage: "District Court > Delhi > Central & West > Tis Hazari",
    display_order: 100,
  },
  {
    id: "district:delhi:new-delhi",
    parent_id: null,
    court_id: null,
    name: "Patiala House Courts Complex",
    forum_type: "district_court",
    forum_level: "lower_court",
    state: "Delhi",
    district: "New Delhi",
    city: "New Delhi",
    consumer_level: null,
    source_name: "CaseOps LW-S4 baseline forum catalog",
    source_url: null,
    lineage: "District Court > Delhi > New Delhi > New Delhi",
    display_order: 101,
  },
  {
    id: "district:delhi:karkardooma",
    parent_id: null,
    court_id: null,
    name: "Karkardooma Courts Complex",
    forum_type: "district_court",
    forum_level: "lower_court",
    state: "Delhi",
    district: "East, North-East & Shahdara",
    city: "Karkardooma",
    consumer_level: null,
    source_name: "CaseOps LW-S4 baseline forum catalog",
    source_url: null,
    lineage:
      "District Court > Delhi > East, North-East & Shahdara > Karkardooma",
    display_order: 102,
  },
  {
    id: "district:delhi:rohini",
    parent_id: null,
    court_id: null,
    name: "Rohini Courts Complex",
    forum_type: "district_court",
    forum_level: "lower_court",
    state: "Delhi",
    district: "North & North-West",
    city: "Rohini",
    consumer_level: null,
    source_name: "CaseOps LW-S4 baseline forum catalog",
    source_url: null,
    lineage: "District Court > Delhi > North & North-West > Rohini",
    display_order: 103,
  },
  {
    id: "district:delhi:dwarka",
    parent_id: null,
    court_id: null,
    name: "Dwarka Courts Complex",
    forum_type: "district_court",
    forum_level: "lower_court",
    state: "Delhi",
    district: "South-West",
    city: "Dwarka",
    consumer_level: null,
    source_name: "CaseOps LW-S4 baseline forum catalog",
    source_url: null,
    lineage: "District Court > Delhi > South-West > Dwarka",
    display_order: 104,
  },
  {
    id: "district:delhi:south",
    parent_id: null,
    court_id: null,
    name: "Saket Courts Complex",
    forum_type: "district_court",
    forum_level: "lower_court",
    state: "Delhi",
    district: "South & South-East",
    city: "Saket",
    consumer_level: null,
    source_name: "CaseOps LW-S4 baseline forum catalog",
    source_url: null,
    lineage: "District Court > Delhi > South & South-East > Saket",
    display_order: 105,
  },
  {
    id: "district:delhi:rouse-avenue",
    parent_id: null,
    court_id: null,
    name: "Rouse Avenue Courts Complex",
    forum_type: "district_court",
    forum_level: "lower_court",
    state: "Delhi",
    district: "Special Courts / Central",
    city: "Rouse Avenue",
    consumer_level: null,
    source_name: "CaseOps LW-S4 baseline forum catalog",
    source_url: null,
    lineage: "District Court > Delhi > Special Courts / Central > Rouse Avenue",
    display_order: 106,
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
    id: "consumer:scdrc:11070000",
    parent_id: "consumer:ncdrc",
    court_id: null,
    name: "Delhi State Consumer Disputes Redressal Commission",
    forum_type: "consumer_forum",
    forum_level: "tribunal",
    state: "Delhi",
    district: null,
    city: "New Delhi",
    consumer_level: "state",
    source_name: "e-Jagriti master commission directory",
    source_url:
      "https://e-jagriti.gov.in/services/master/master/v2/getCommissionDetailsByStateId?stateId=7",
    lineage: "Consumer Forum > SCDRC > Delhi",
    display_order: 210,
  },
  {
    id: "consumer:scdrc:11080000",
    parent_id: "consumer:ncdrc",
    court_id: null,
    name: "Rajasthan State Consumer Disputes Redressal Commission",
    forum_type: "consumer_forum",
    forum_level: "tribunal",
    state: "Rajasthan",
    district: null,
    city: null,
    consumer_level: "state",
    source_name: "e-Jagriti master commission directory",
    source_url:
      "https://e-jagriti.gov.in/services/master/master/v2/getCommissionDetailsByStateId?stateId=8",
    lineage: "Consumer Forum > SCDRC > Rajasthan",
    display_order: 280,
  },
  {
    id: "consumer:dcdrc:11070077",
    parent_id: "consumer:scdrc:11070000",
    court_id: null,
    name: "Central Delhi District Consumer Disputes Redressal Commission",
    forum_type: "consumer_forum",
    forum_level: "tribunal",
    state: "Delhi",
    district: "Central Delhi",
    city: null,
    consumer_level: "district",
    source_name: "e-Jagriti master commission directory",
    source_url:
      "https://e-jagriti.gov.in/services/master/master/v2/getCommissionDetailsByStateId?stateId=7",
    lineage: "Consumer Forum > DCDRC > Delhi > Central Delhi",
    display_order: 107001,
  },
  {
    id: "consumer:dcdrc:11080086",
    parent_id: "consumer:scdrc:11080000",
    court_id: null,
    name: "Ajmer District Consumer Disputes Redressal Commission",
    forum_type: "consumer_forum",
    forum_level: "tribunal",
    state: "Rajasthan",
    district: "Ajmer",
    city: null,
    consumer_level: "district",
    source_name: "e-Jagriti master commission directory",
    source_url:
      "https://e-jagriti.gov.in/services/master/master/v2/getCommissionDetailsByStateId?stateId=8",
    lineage: "Consumer Forum > DCDRC > Rajasthan > Ajmer",
    display_order: 108001,
  },
  {
    id: "drt:delhi:drt-1",
    parent_id: "drt:delhi:drat",
    court_id: null,
    name: "DRT-1",
    forum_type: "drt_drat",
    forum_level: "tribunal",
    state: "Delhi",
    district: null,
    city: "New Delhi",
    consumer_level: null,
    source_name: "Department of Financial Services DRT/DRAT portal",
    source_url: "https://drt.gov.in/",
    lineage: "DRAT / DRT > Delhi > DRT-1",
    display_order: 401,
  },
  {
    id: "drt:delhi:drt-2",
    parent_id: "drt:delhi:drat",
    court_id: null,
    name: "DRT-2",
    forum_type: "drt_drat",
    forum_level: "tribunal",
    state: "Delhi",
    district: null,
    city: "New Delhi",
    consumer_level: null,
    source_name: "Department of Financial Services DRT/DRAT portal",
    source_url: "https://drt.gov.in/",
    lineage: "DRAT / DRT > Delhi > DRT-2",
    display_order: 402,
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

    await user.selectOptions(
      screen.getByTestId("test-forum-category"),
      "supreme_court",
    );

    expect(screen.getByTestId("test-forum-supreme")).toHaveValue("sc:india");
    expect(screen.queryByTestId("test-forum-state")).toBeNull();
    expect(screen.getByText(/Supreme Court > India/i)).toBeInTheDocument();
  });

  it("requires state for High Court selection", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    expect(screen.getByTestId("test-forum-state")).toHaveValue("Delhi");
    await user.selectOptions(
      screen.getByTestId("test-forum-state"),
      "Karnataka",
    );

    await waitFor(() =>
      expect(screen.getByTestId("test-forum-state")).toHaveValue("Karnataka"),
    );
    expect(screen.getByText(/High Court > Karnataka/i)).toBeInTheDocument();
  });

  it("requires state and district/city for District Court selection", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.selectOptions(
      screen.getByTestId("test-forum-category"),
      "district_court",
    );

    expect(screen.getByTestId("test-forum-district-state")).toHaveValue(
      "Delhi",
    );
    expect(screen.getByTestId("test-forum-district")).toHaveValue(
      "district:delhi:central",
    );
    const options = Array.from(
      (screen.getByTestId("test-forum-district") as HTMLSelectElement).options,
    ).map((option) => option.textContent);
    expect(options).toEqual([
      "Tis Hazari Courts Complex (Central & West / Tis Hazari)",
      "Patiala House Courts Complex (New Delhi / New Delhi)",
      "Karkardooma Courts Complex (East, North-East & Shahdara / Karkardooma)",
      "Rohini Courts Complex (North & North-West / Rohini)",
      "Dwarka Courts Complex (South-West / Dwarka)",
      "Saket Courts Complex (South & South-East / Saket)",
      "Rouse Avenue Courts Complex (Special Courts / Central / Rouse Avenue)",
      "Other district court in Delhi",
    ]);
    expect(
      screen.getByText(/District Court > Delhi > Central & West/i),
    ).toBeInTheDocument();

    await user.selectOptions(
      screen.getByTestId("test-forum-district"),
      "__uncatalogued_district_court__",
    );
    expect(screen.getByTestId("test-forum-district-name")).toHaveValue("");
    expect(screen.getByTestId("test-forum-district-court")).toHaveValue("");
  });

  it("keeps every India.gov district state jurisdiction selectable and falls back for uncatalogued states", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.selectOptions(
      screen.getByTestId("test-forum-category"),
      "district_court",
    );

    const stateSelect = screen.getByTestId(
      "test-forum-district-state",
    ) as HTMLSelectElement;
    const states = Array.from(stateSelect.options).map(
      (option) => option.textContent,
    );
    expect(states).toEqual(
      [
        "Andaman and Nicobar Islands",
        "Andhra Pradesh",
        "Arunachal Pradesh",
        "Assam",
        "Bihar",
        "Chandigarh",
        "Chhattisgarh",
        "Dadra and Nagar Haveli and Daman and Diu",
        "Delhi",
        "Goa",
        "Gujarat",
        "Haryana",
        "Himachal Pradesh",
        "Jammu and Kashmir",
        "Jharkhand",
        "Karnataka",
        "Kerala",
        "Ladakh",
        "Lakshadweep",
        "Madhya Pradesh",
        "Maharashtra",
        "Manipur",
        "Meghalaya",
        "Mizoram",
        "Nagaland",
        "Odisha",
        "Puducherry",
        "Punjab",
        "Rajasthan",
        "Sikkim",
        "Tamil Nadu",
        "Telangana",
        "Tripura",
        "Uttar Pradesh",
        "Uttarakhand",
        "West Bengal",
      ].sort((left, right) => left.localeCompare(right)),
    );

    await user.selectOptions(stateSelect, "Assam");

    await waitFor(() => expect(stateSelect).toHaveValue("Assam"));
    const districtSelect = screen.getByTestId(
      "test-forum-district",
    ) as HTMLSelectElement;
    expect(districtSelect).toHaveValue("__uncatalogued_district_court__");
    expect(
      Array.from(districtSelect.options).map((option) => option.textContent),
    ).toEqual(["Other district court in Assam"]);
    expect(screen.getByTestId("test-forum-district-name")).toHaveValue("");
    expect(screen.getByTestId("test-forum-district-court")).toHaveValue("");

    await user.type(
      screen.getByTestId("test-forum-district-name"),
      "Kamrup Metro",
    );
    await user.type(
      screen.getByTestId("test-forum-district-court"),
      "Kamrup Metro District Court",
    );

    expect(screen.getByTestId("test-forum-district-name")).toHaveValue(
      "Kamrup Metro",
    );
    expect(screen.getByTestId("test-forum-district-court")).toHaveValue(
      "Kamrup Metro District Court",
    );
  });
  it("exposes national, state, and district commissions as distinct hierarchies", async () => {
    const user = userEvent.setup();
    render(<Harness initial={EMPTY_FORUM_SELECTION} />);

    await user.selectOptions(
      screen.getByTestId("test-forum-category"),
      "ncdrc",
    );
    expect(screen.getByTestId("test-forum-consumer-national")).toHaveValue(
      "consumer:ncdrc",
    );
    expect(screen.queryByTestId("test-forum-consumer-state")).toBeNull();

    await user.selectOptions(
      screen.getByTestId("test-forum-category"),
      "state_commission",
    );
    expect(screen.getByTestId("test-forum-consumer-state")).toHaveValue(
      "Delhi",
    );
    expect(screen.getByTestId("test-forum-consumer-commission")).toHaveValue(
      "consumer:scdrc:11070000",
    );

    await user.selectOptions(
      screen.getByTestId("test-forum-category"),
      "district_commission",
    );
    expect(screen.getByTestId("test-forum-consumer-state")).toHaveValue(
      "Delhi",
    );
    expect(screen.getByTestId("test-forum-consumer-district")).toHaveValue(
      "consumer:dcdrc:11070077",
    );
  });

  it("keeps every e-Jagriti consumer state jurisdiction selectable", async () => {
    const user = userEvent.setup();
    render(<Harness initial={EMPTY_FORUM_SELECTION} />);

    await user.selectOptions(
      screen.getByTestId("test-forum-category"),
      "state_commission",
    );

    const stateSelect = screen.getByTestId(
      "test-forum-consumer-state",
    ) as HTMLSelectElement;
    expect(
      Array.from(stateSelect.options).map((option) => option.textContent),
    ).toEqual(
      [
        "Andaman and Nicobar Islands",
        "Andhra Pradesh",
        "Arunachal Pradesh",
        "Assam",
        "Bihar",
        "Chandigarh",
        "Chhattisgarh",
        "Dadra and Nagar Haveli and Daman and Diu",
        "Delhi",
        "Goa",
        "Gujarat",
        "Haryana",
        "Himachal Pradesh",
        "Jammu and Kashmir",
        "Jharkhand",
        "Karnataka",
        "Kerala",
        "Ladakh",
        "Lakshadweep",
        "Madhya Pradesh",
        "Maharashtra",
        "Manipur",
        "Meghalaya",
        "Mizoram",
        "Nagaland",
        "Odisha",
        "Puducherry",
        "Punjab",
        "Rajasthan",
        "Sikkim",
        "Tamil Nadu",
        "Telangana",
        "Tripura",
        "Uttar Pradesh",
        "Uttarakhand",
        "West Bengal",
      ].sort((left, right) => left.localeCompare(right)),
    );

    await user.selectOptions(stateSelect, "Rajasthan");
    await waitFor(() => expect(stateSelect).toHaveValue("Rajasthan"));
    expect(
      screen.getByText(/Consumer Forum > SCDRC > Rajasthan/i),
    ).toBeInTheDocument();
  });

  it("supports DCDRC fallback without inheriting catalog district metadata", async () => {
    const user = userEvent.setup();
    render(<Harness initial={EMPTY_FORUM_SELECTION} />);

    await user.selectOptions(
      screen.getByTestId("test-forum-category"),
      "district_commission",
    );

    const districtSelect = screen.getByTestId(
      "test-forum-consumer-district",
    ) as HTMLSelectElement;
    expect(
      Array.from(districtSelect.options).map((option) => option.textContent),
    ).toEqual([
      "Central Delhi District Consumer Disputes Redressal Commission (Central Delhi)",
      "Other DCDRC in Delhi",
    ]);

    await user.selectOptions(
      districtSelect,
      "__uncatalogued_consumer_district__",
    );
    expect(screen.getByTestId("test-forum-consumer-district-name")).toHaveValue(
      "",
    );
    expect(screen.getByTestId("test-forum-consumer-forum-name")).toHaveValue(
      "",
    );

    await user.type(
      screen.getByTestId("test-forum-consumer-district-name"),
      "South II",
    );
    await user.type(
      screen.getByTestId("test-forum-consumer-forum-name"),
      "South II DCDRC Annex",
    );

    expect(screen.getByTestId("test-forum-consumer-district-name")).toHaveValue(
      "South II",
    );
    expect(screen.getByTestId("test-forum-consumer-forum-name")).toHaveValue(
      "South II DCDRC Annex",
    );
  });

  it("selects an exact specialist tribunal and retains its catalog lineage", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.selectOptions(
      screen.getByTestId("test-forum-category"),
      "drt_drat",
    );
    expect(screen.getByTestId("test-forum-specialist-state")).toHaveValue(
      "Delhi",
    );
    await user.selectOptions(
      screen.getByTestId("test-forum-specialist-forum"),
      "drt:delhi:drt-2",
    );

    expect(screen.getByTestId("test-forum-specialist-forum")).toHaveValue(
      "drt:delhi:drt-2",
    );
    expect(screen.getByText(/DRAT \/ DRT > Delhi > DRT-2/)).toBeInTheDocument();
  });
});
