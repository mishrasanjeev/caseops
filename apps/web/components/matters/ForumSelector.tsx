"use client";

import { useMemo } from "react";

import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import type { ForumCatalogEntry } from "@/lib/api/schemas";

export type ForumSelection = {
  forum_category?: ForumCategory;
  forum_level: string;
  court_id: string | null;
  court_name: string | null;
  forum_catalog_entry_id: string | null;
  forum_state: string | null;
  forum_district: string | null;
  forum_city: string | null;
  forum_consumer_level: string | null;
};

export type ForumCategory =
  | "supreme_court"
  | "high_court"
  | "district_court"
  | "ncdrc"
  | "state_commission"
  | "district_commission"
  | "drt_drat"
  | "recovery_forum"
  | "company_law_tribunal"
  | "tdsat"
  | "appellate_tribunal"
  // Compatibility for an unsaved selection created by an older client.
  | "consumer_forum"
  | "legacy";

const CATEGORY_OPTIONS: Array<{ value: ForumCategory; label: string }> = [
  { value: "supreme_court", label: "Supreme Court" },
  { value: "high_court", label: "High Court" },
  { value: "district_court", label: "District Court" },
  { value: "ncdrc", label: "NCDRC" },
  { value: "state_commission", label: "State Commission" },
  { value: "district_commission", label: "District Commission" },
  { value: "drt_drat", label: "DRAT / DRT" },
  { value: "recovery_forum", label: "Recovery Forums" },
  { value: "company_law_tribunal", label: "NCLAT / NCLT" },
  { value: "tdsat", label: "TDSAT" },
  { value: "appellate_tribunal", label: "Appellate Tribunal" },
  { value: "legacy", label: "Other / uncatalogued" },
];

const SPECIALIST_CATEGORIES: ForumCategory[] = [
  "drt_drat",
  "recovery_forum",
  "company_law_tribunal",
  "tdsat",
  "appellate_tribunal",
];

const LEGACY_FORUM_LEVELS = [
  { value: "lower_court", label: "Lower court" },
  { value: "high_court", label: "High Court" },
  { value: "supreme_court", label: "Supreme Court" },
  { value: "tribunal", label: "Tribunal" },
  { value: "arbitration", label: "Arbitration" },
  { value: "advisory", label: "Advisory" },
];

const INDIA_DISTRICT_FORUM_STATES = [
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
];

const DISTRICT_FALLBACK_OPTION = "__uncatalogued_district_court__";
const CONSUMER_FORUM_STATES = INDIA_DISTRICT_FORUM_STATES;
const CONSUMER_DISTRICT_FALLBACK_OPTION = "__uncatalogued_consumer_district__";

export const EMPTY_FORUM_SELECTION: ForumSelection = {
  forum_category: "high_court",
  forum_level: "high_court",
  court_id: null,
  court_name: null,
  forum_catalog_entry_id: null,
  forum_state: null,
  forum_district: null,
  forum_city: null,
  forum_consumer_level: null,
};

export function isLegacyForumSelection(value: ForumSelection): boolean {
  return (
    value.forum_category === "legacy" ||
    (value.forum_category === undefined &&
      !value.forum_catalog_entry_id &&
      !value.court_id &&
      Boolean(value.court_name?.trim()))
  );
}

export function isDistrictFallbackForumSelection(
  value: ForumSelection,
): boolean {
  return (
    value.forum_category === "district_court" &&
    value.forum_level === "lower_court" &&
    !value.forum_catalog_entry_id &&
    !value.court_id
  );
}

export function isConsumerDistrictFallbackForumSelection(
  value: ForumSelection,
): boolean {
  return (
    ["consumer_forum", "district_commission"].includes(
      value.forum_category ?? "",
    ) &&
    value.forum_level === "tribunal" &&
    value.forum_consumer_level === "district" &&
    !value.forum_catalog_entry_id &&
    !value.court_id
  );
}

function districtFallbackSelection(
  state: string,
  current: ForumSelection,
): ForumSelection {
  const preserveCurrentFallback =
    current.forum_state === state &&
    !current.forum_catalog_entry_id &&
    !current.court_id;
  return {
    ...EMPTY_FORUM_SELECTION,
    forum_category: "district_court",
    forum_level: "lower_court",
    court_id: null,
    court_name: preserveCurrentFallback ? current.court_name : null,
    forum_catalog_entry_id: null,
    forum_state: state,
    forum_district: preserveCurrentFallback ? current.forum_district : null,
    forum_city: preserveCurrentFallback ? current.forum_city : null,
    forum_consumer_level: null,
  };
}

function consumerStateFallbackSelection(
  state: string,
  current: ForumSelection,
): ForumSelection {
  const preserveCurrentFallback =
    current.forum_state === state &&
    current.forum_consumer_level === "state" &&
    !current.forum_catalog_entry_id &&
    !current.court_id;
  return {
    ...EMPTY_FORUM_SELECTION,
    forum_category: "state_commission",
    forum_level: "tribunal",
    court_id: null,
    court_name: preserveCurrentFallback
      ? current.court_name
      : `${state} State Consumer Disputes Redressal Commission`,
    forum_catalog_entry_id: null,
    forum_state: state,
    forum_district: null,
    forum_city: null,
    forum_consumer_level: "state",
  };
}

function consumerDistrictFallbackSelection(
  state: string,
  current: ForumSelection,
): ForumSelection {
  const preserveCurrentFallback =
    current.forum_state === state &&
    current.forum_consumer_level === "district" &&
    !current.forum_catalog_entry_id &&
    !current.court_id;
  return {
    ...EMPTY_FORUM_SELECTION,
    forum_category: "district_commission",
    forum_level: "tribunal",
    court_id: null,
    court_name: preserveCurrentFallback ? current.court_name : null,
    forum_catalog_entry_id: null,
    forum_state: state,
    forum_district: preserveCurrentFallback ? current.forum_district : null,
    forum_city: preserveCurrentFallback ? current.forum_city : null,
    forum_consumer_level: "district",
  };
}

function selectClassName() {
  return "h-10 w-full rounded-md border border-[var(--color-line)] bg-white px-3 text-sm text-[var(--color-ink)] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brand-500)]";
}

function statusClassName(tone: "info" | "warning" | "error") {
  if (tone === "error") {
    return "md:col-span-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800";
  }
  if (tone === "warning") {
    return "md:col-span-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900";
  }
  return "md:col-span-2 rounded-md border border-[var(--color-line)] bg-[var(--color-bg)] px-3 py-2 text-xs text-[var(--color-mute)]";
}

function unique(values: Array<string | null | undefined>): string[] {
  return Array.from(new Set(values.filter(Boolean) as string[])).sort((a, b) =>
    a.localeCompare(b),
  );
}

function byOrder(left: ForumCatalogEntry, right: ForumCatalogEntry) {
  return (
    left.display_order - right.display_order ||
    (left.state ?? "").localeCompare(right.state ?? "") ||
    (left.district ?? "").localeCompare(right.district ?? "") ||
    left.name.localeCompare(right.name)
  );
}

function forumPlaceLabel(entry: ForumCatalogEntry) {
  const place = [entry.district, entry.city].filter(Boolean).join(" / ");
  return place ? `${entry.name} (${place})` : entry.name;
}

export function forumSelectionFromEntry(
  entry: ForumCatalogEntry,
): ForumSelection {
  return {
    forum_category: categoryFromEntry(entry),
    forum_level: entry.forum_level,
    court_id: entry.court_id ?? null,
    court_name: entry.name,
    forum_catalog_entry_id: entry.id,
    forum_state: entry.state ?? null,
    forum_district: entry.district ?? null,
    forum_city: entry.city ?? null,
    forum_consumer_level: entry.consumer_level ?? null,
  };
}

function categoryFromEntry(entry: ForumCatalogEntry): ForumCategory {
  if (entry.forum_type !== "consumer_forum") {
    return entry.forum_type as ForumCategory;
  }
  if (entry.consumer_level === "national") return "ncdrc";
  if (entry.consumer_level === "state") return "state_commission";
  return "district_commission";
}

function categoryFromSelection(
  value: ForumSelection,
  selectedEntry: ForumCatalogEntry | undefined,
): ForumCategory {
  if (selectedEntry?.forum_type) return categoryFromEntry(selectedEntry);
  if (value.forum_category === "consumer_forum") {
    if (value.forum_consumer_level === "national") return "ncdrc";
    if (value.forum_consumer_level === "state") return "state_commission";
    if (value.forum_consumer_level === "district") return "district_commission";
  }
  if (value.forum_category) return value.forum_category;
  if (value.forum_level === "supreme_court") return "supreme_court";
  if (value.forum_level === "high_court") return "high_court";
  if (value.forum_level === "lower_court") return "district_court";
  if (
    value.forum_level === "tribunal" &&
    value.forum_consumer_level === "national"
  ) {
    return "ncdrc";
  }
  if (
    value.forum_level === "tribunal" &&
    value.forum_consumer_level === "state"
  ) {
    return "state_commission";
  }
  if (
    value.forum_level === "tribunal" &&
    value.forum_consumer_level === "district"
  ) {
    return "district_commission";
  }
  return "legacy";
}

function firstEntry(
  entries: ForumCatalogEntry[],
  predicate: (entry: ForumCatalogEntry) => boolean,
) {
  return [...entries].sort(byOrder).find(predicate);
}

export function ForumSelector({
  entries,
  value,
  onChange,
  disabled = false,
  idPrefix = "forum-selector",
  statusMessage = null,
  statusTone = "info",
}: {
  entries: ForumCatalogEntry[];
  value: ForumSelection;
  onChange: (selection: ForumSelection) => void;
  disabled?: boolean;
  idPrefix?: string;
  statusMessage?: string | null;
  statusTone?: "info" | "warning" | "error";
}) {
  const sortedEntries = useMemo(() => [...entries].sort(byOrder), [entries]);
  const selectedEntry = sortedEntries.find(
    (entry) => entry.id === value.forum_catalog_entry_id,
  );
  const category = categoryFromSelection(value, selectedEntry);
  const highCourts = sortedEntries.filter(
    (entry) => entry.forum_type === "high_court",
  );
  const districtCourts = sortedEntries.filter(
    (entry) => entry.forum_type === "district_court",
  );
  const consumerForums = sortedEntries.filter(
    (entry) => entry.forum_type === "consumer_forum",
  );

  const chooseEntry = (entry: ForumCatalogEntry | undefined) => {
    if (entry) onChange(forumSelectionFromEntry(entry));
  };

  const chooseCategory = (next: ForumCategory) => {
    if (next === "legacy") {
      onChange({
        ...EMPTY_FORUM_SELECTION,
        forum_category: "legacy",
        forum_level: value.forum_level || "high_court",
        court_name: value.court_name,
      });
      return;
    }
    if (next === "district_court") {
      const currentState = value.forum_state;
      const entry =
        firstEntry(
          sortedEntries,
          (item) => item.forum_type === next && item.state === currentState,
        ) ?? firstEntry(sortedEntries, (item) => item.forum_type === next);
      if (entry) {
        chooseEntry(entry);
        return;
      }
      onChange(
        districtFallbackSelection(
          currentState || INDIA_DISTRICT_FORUM_STATES[0],
          value,
        ),
      );
      return;
    }
    if (["ncdrc", "state_commission", "district_commission"].includes(next)) {
      const consumerLevel =
        next === "ncdrc"
          ? "national"
          : next === "state_commission"
            ? "state"
            : "district";
      const entry =
        firstEntry(
          sortedEntries,
          (item) =>
            item.forum_type === "consumer_forum" &&
            item.consumer_level === consumerLevel &&
            item.state === value.forum_state,
        ) ??
        firstEntry(
          sortedEntries,
          (item) =>
            item.forum_type === "consumer_forum" &&
            item.consumer_level === consumerLevel,
        );
      if (entry) {
        chooseEntry(entry);
        return;
      }
      const state = value.forum_state || CONSUMER_FORUM_STATES[0];
      onChange(
        consumerLevel === "district"
          ? consumerDistrictFallbackSelection(state, value)
          : consumerStateFallbackSelection(state, value),
      );
      return;
    }
    chooseEntry(
      firstEntry(sortedEntries, (entry) => entry.forum_type === next),
    );
  };

  const highCourtStates = unique(highCourts.map((entry) => entry.state));
  const districtStates = unique([
    ...INDIA_DISTRICT_FORUM_STATES,
    ...districtCourts.map((entry) => entry.state),
  ]);
  const selectedDistrictState =
    selectedEntry?.state ?? value.forum_state ?? districtStates[0] ?? "";
  const districtOptions = districtCourts.filter(
    (entry) => entry.state === selectedDistrictState,
  );
  const districtFallbackSelected =
    category === "district_court" && isDistrictFallbackForumSelection(value);
  const districtSelectValue = selectedEntry?.id ?? DISTRICT_FALLBACK_OPTION;
  const consumerLevel =
    category === "ncdrc"
      ? "national"
      : category === "state_commission"
        ? "state"
        : category === "district_commission"
          ? "district"
          : (selectedEntry?.consumer_level ??
            value.forum_consumer_level ??
            "national");
  const consumerLevelOptions = consumerForums.filter(
    (entry) => entry.consumer_level === consumerLevel,
  );
  const consumerStates = unique([
    ...CONSUMER_FORUM_STATES,
    ...consumerLevelOptions.map((entry) => entry.state),
  ]);
  const selectedConsumerState =
    selectedEntry?.state ?? value.forum_state ?? consumerStates[0] ?? "";
  const consumerDistrictOptions = consumerLevelOptions.filter(
    (entry) => entry.state === selectedConsumerState,
  );
  const consumerDistrictFallbackSelected =
    category === "district_commission" &&
    isConsumerDistrictFallbackForumSelection(value);
  const consumerDistrictSelectValue =
    selectedEntry?.id ?? CONSUMER_DISTRICT_FALLBACK_OPTION;
  const specialistEntries = sortedEntries.filter(
    (entry) => entry.forum_type === category,
  );
  const specialistStates = unique(
    specialistEntries.map((entry) => entry.state),
  );
  const selectedSpecialistState =
    selectedEntry?.state ?? value.forum_state ?? specialistStates[0] ?? "";
  const specialistOptions = specialistEntries.filter(
    (entry) =>
      !specialistStates.length || entry.state === selectedSpecialistState,
  );

  return (
    <div className="grid gap-3 md:grid-cols-2" data-testid={`${idPrefix}-root`}>
      {statusMessage ? (
        <div
          className={statusClassName(statusTone)}
          role={statusTone === "error" ? "alert" : "status"}
        >
          {statusMessage}
        </div>
      ) : null}

      <div>
        <Label htmlFor={`${idPrefix}-category`}>Forum hierarchy</Label>
        <select
          id={`${idPrefix}-category`}
          className={`${selectClassName()} mt-1.5`}
          value={category}
          disabled={disabled}
          onChange={(event) =>
            chooseCategory(event.target.value as ForumCategory)
          }
          data-testid={`${idPrefix}-category`}
        >
          {CATEGORY_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {category === "supreme_court" ? (
        <div>
          <Label htmlFor={`${idPrefix}-supreme`}>Court</Label>
          <select
            id={`${idPrefix}-supreme`}
            className={`${selectClassName()} mt-1.5`}
            value={selectedEntry?.id ?? ""}
            disabled={disabled}
            onChange={(event) =>
              chooseEntry(
                sortedEntries.find((entry) => entry.id === event.target.value),
              )
            }
            data-testid={`${idPrefix}-supreme`}
          >
            {sortedEntries
              .filter((entry) => entry.forum_type === "supreme_court")
              .map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.name}
                </option>
              ))}
          </select>
        </div>
      ) : null}

      {category === "high_court" ? (
        <>
          <div>
            <Label htmlFor={`${idPrefix}-state`}>State</Label>
            <select
              id={`${idPrefix}-state`}
              className={`${selectClassName()} mt-1.5`}
              value={selectedEntry?.state ?? value.forum_state ?? ""}
              disabled={disabled}
              onChange={(event) =>
                chooseEntry(
                  firstEntry(
                    highCourts,
                    (entry) => entry.state === event.target.value,
                  ),
                )
              }
              data-testid={`${idPrefix}-state`}
            >
              {highCourtStates.map((state) => (
                <option key={state} value={state}>
                  {state}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor={`${idPrefix}-high-court`}>Exact court</Label>
            <select
              id={`${idPrefix}-high-court`}
              className={`${selectClassName()} mt-1.5`}
              value={selectedEntry?.id ?? ""}
              disabled={disabled}
              onChange={(event) =>
                chooseEntry(
                  highCourts.find((entry) => entry.id === event.target.value),
                )
              }
              data-testid={`${idPrefix}-high-court`}
            >
              {highCourts
                .filter(
                  (entry) =>
                    entry.state === (selectedEntry?.state ?? value.forum_state),
                )
                .map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.name}
                  </option>
                ))}
            </select>
          </div>
        </>
      ) : null}

      {category === "district_court" ? (
        <>
          <div>
            <Label htmlFor={`${idPrefix}-district-state`}>State</Label>
            <select
              id={`${idPrefix}-district-state`}
              className={`${selectClassName()} mt-1.5`}
              value={selectedDistrictState}
              disabled={disabled}
              onChange={(event) => {
                const entry = firstEntry(
                  districtCourts,
                  (item) => item.state === event.target.value,
                );
                if (entry) chooseEntry(entry);
                else
                  onChange(
                    districtFallbackSelection(event.target.value, value),
                  );
              }}
              data-testid={`${idPrefix}-district-state`}
            >
              {districtStates.map((state) => (
                <option key={state} value={state}>
                  {state}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor={`${idPrefix}-district`}>District / city</Label>
            <select
              id={`${idPrefix}-district`}
              className={`${selectClassName()} mt-1.5`}
              value={districtSelectValue}
              disabled={disabled}
              onChange={(event) => {
                if (event.target.value === DISTRICT_FALLBACK_OPTION) {
                  onChange(
                    districtFallbackSelection(selectedDistrictState, value),
                  );
                  return;
                }
                chooseEntry(
                  districtCourts.find(
                    (entry) => entry.id === event.target.value,
                  ),
                );
              }}
              data-testid={`${idPrefix}-district`}
            >
              {districtOptions.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {forumPlaceLabel(entry)}
                </option>
              ))}
              <option value={DISTRICT_FALLBACK_OPTION}>
                Other district court in {selectedDistrictState}
              </option>
            </select>
          </div>
          {districtFallbackSelected ? (
            <>
              <div>
                <Label htmlFor={`${idPrefix}-district-name`}>District</Label>
                <Input
                  id={`${idPrefix}-district-name`}
                  className="mt-1.5"
                  value={value.forum_district ?? ""}
                  disabled={disabled}
                  onChange={(event) =>
                    onChange({
                      ...value,
                      forum_category: "district_court",
                      forum_level: "lower_court",
                      forum_district: event.target.value,
                      forum_catalog_entry_id: null,
                      court_id: null,
                    })
                  }
                  placeholder="e.g. Pune"
                  data-testid={`${idPrefix}-district-name`}
                />
              </div>
              <div>
                <Label htmlFor={`${idPrefix}-district-court`}>
                  Court / forum name
                </Label>
                <Input
                  id={`${idPrefix}-district-court`}
                  className="mt-1.5"
                  value={value.court_name ?? ""}
                  disabled={disabled}
                  onChange={(event) =>
                    onChange({
                      ...value,
                      forum_category: "district_court",
                      forum_level: "lower_court",
                      court_name: event.target.value,
                      forum_catalog_entry_id: null,
                      court_id: null,
                    })
                  }
                  placeholder="e.g. Pune District Court"
                  data-testid={`${idPrefix}-district-court`}
                />
              </div>
            </>
          ) : null}
        </>
      ) : null}

      {["ncdrc", "state_commission", "district_commission"].includes(
        category,
      ) ? (
        <>
          {consumerLevel === "national" ? (
            <div>
              <Label htmlFor={`${idPrefix}-consumer-national`}>
                Exact commission
              </Label>
              <select
                id={`${idPrefix}-consumer-national`}
                className={`${selectClassName()} mt-1.5`}
                value={selectedEntry?.id ?? ""}
                disabled={disabled}
                onChange={(event) =>
                  chooseEntry(
                    consumerForums.find(
                      (entry) => entry.id === event.target.value,
                    ),
                  )
                }
                data-testid={`${idPrefix}-consumer-national`}
              >
                {consumerLevelOptions.map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.name}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          {consumerLevel !== "national" ? (
            <div>
              <Label htmlFor={`${idPrefix}-consumer-state`}>State</Label>
              <select
                id={`${idPrefix}-consumer-state`}
                className={`${selectClassName()} mt-1.5`}
                value={selectedConsumerState}
                disabled={disabled}
                onChange={(event) => {
                  const nextState = event.target.value;
                  const entry = firstEntry(
                    consumerLevelOptions,
                    (item) => item.state === nextState,
                  );
                  if (entry) {
                    chooseEntry(entry);
                    return;
                  }
                  if (consumerLevel === "state") {
                    onChange(consumerStateFallbackSelection(nextState, value));
                  } else {
                    onChange(
                      consumerDistrictFallbackSelection(nextState, value),
                    );
                  }
                }}
                data-testid={`${idPrefix}-consumer-state`}
              >
                {consumerStates.map((state) => (
                  <option key={state} value={state}>
                    {state}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          {consumerLevel === "state" ? (
            <div>
              <Label htmlFor={`${idPrefix}-consumer-commission`}>
                Exact commission
              </Label>
              <select
                id={`${idPrefix}-consumer-commission`}
                className={`${selectClassName()} mt-1.5`}
                value={selectedEntry?.id ?? ""}
                disabled={disabled}
                onChange={(event) =>
                  chooseEntry(
                    consumerLevelOptions.find(
                      (entry) => entry.id === event.target.value,
                    ),
                  )
                }
                data-testid={`${idPrefix}-consumer-commission`}
              >
                {consumerLevelOptions
                  .filter((entry) => entry.state === selectedConsumerState)
                  .map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {entry.name}
                    </option>
                  ))}
              </select>
            </div>
          ) : null}
          {consumerLevel === "district" ? (
            <div>
              <Label htmlFor={`${idPrefix}-consumer-district`}>
                District / city
              </Label>
              <select
                id={`${idPrefix}-consumer-district`}
                className={`${selectClassName()} mt-1.5`}
                value={consumerDistrictSelectValue}
                disabled={disabled}
                onChange={(event) => {
                  if (
                    event.target.value === CONSUMER_DISTRICT_FALLBACK_OPTION
                  ) {
                    onChange(
                      consumerDistrictFallbackSelection(
                        selectedConsumerState,
                        value,
                      ),
                    );
                    return;
                  }
                  chooseEntry(
                    consumerForums.find(
                      (entry) => entry.id === event.target.value,
                    ),
                  );
                }}
                data-testid={`${idPrefix}-consumer-district`}
              >
                {consumerDistrictOptions.map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {forumPlaceLabel(entry)}
                  </option>
                ))}
                <option value={CONSUMER_DISTRICT_FALLBACK_OPTION}>
                  Other DCDRC in {selectedConsumerState}
                </option>
              </select>
            </div>
          ) : null}
          {consumerDistrictFallbackSelected ? (
            <>
              <div>
                <Label htmlFor={`${idPrefix}-consumer-district-name`}>
                  District
                </Label>
                <Input
                  id={`${idPrefix}-consumer-district-name`}
                  className="mt-1.5"
                  value={value.forum_district ?? ""}
                  disabled={disabled}
                  onChange={(event) =>
                    onChange({
                      ...value,
                      forum_category: "district_commission",
                      forum_level: "tribunal",
                      forum_consumer_level: "district",
                      forum_district: event.target.value,
                      forum_catalog_entry_id: null,
                      court_id: null,
                    })
                  }
                  placeholder="e.g. Jaipur"
                  data-testid={`${idPrefix}-consumer-district-name`}
                />
              </div>
              <div>
                <Label htmlFor={`${idPrefix}-consumer-forum-name`}>
                  Consumer forum name
                </Label>
                <Input
                  id={`${idPrefix}-consumer-forum-name`}
                  className="mt-1.5"
                  value={value.court_name ?? ""}
                  disabled={disabled}
                  onChange={(event) =>
                    onChange({
                      ...value,
                      forum_category: "district_commission",
                      forum_level: "tribunal",
                      forum_consumer_level: "district",
                      court_name: event.target.value,
                      forum_catalog_entry_id: null,
                      court_id: null,
                    })
                  }
                  placeholder="e.g. Jaipur DCDRC"
                  data-testid={`${idPrefix}-consumer-forum-name`}
                />
              </div>
            </>
          ) : null}
        </>
      ) : null}

      {SPECIALIST_CATEGORIES.includes(category) ? (
        <>
          {specialistStates.length ? (
            <div>
              <Label htmlFor={`${idPrefix}-specialist-state`}>State</Label>
              <select
                id={`${idPrefix}-specialist-state`}
                className={`${selectClassName()} mt-1.5`}
                value={selectedSpecialistState}
                disabled={disabled}
                onChange={(event) =>
                  chooseEntry(
                    firstEntry(
                      specialistEntries,
                      (entry) => entry.state === event.target.value,
                    ),
                  )
                }
                data-testid={`${idPrefix}-specialist-state`}
              >
                {specialistStates.map((state) => (
                  <option key={state} value={state}>
                    {state}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          <div>
            <Label htmlFor={`${idPrefix}-specialist-forum`}>
              Exact court / tribunal
            </Label>
            <select
              id={`${idPrefix}-specialist-forum`}
              className={`${selectClassName()} mt-1.5`}
              value={selectedEntry?.id ?? ""}
              disabled={disabled}
              onChange={(event) =>
                chooseEntry(
                  specialistEntries.find(
                    (entry) => entry.id === event.target.value,
                  ),
                )
              }
              data-testid={`${idPrefix}-specialist-forum`}
            >
              {specialistOptions.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.name}
                </option>
              ))}
            </select>
          </div>
        </>
      ) : null}

      {category === "legacy" ? (
        <>
          <div>
            <Label htmlFor={`${idPrefix}-legacy-level`}>Forum level</Label>
            <select
              id={`${idPrefix}-legacy-level`}
              className={`${selectClassName()} mt-1.5`}
              value={value.forum_level}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...value,
                  forum_level: event.target.value,
                  forum_category: "legacy",
                  forum_catalog_entry_id: null,
                  court_id: null,
                })
              }
              data-testid={`${idPrefix}-legacy-level`}
            >
              {LEGACY_FORUM_LEVELS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor={`${idPrefix}-legacy-court`}>
              Court / forum name
            </Label>
            <Input
              id={`${idPrefix}-legacy-court`}
              className="mt-1.5"
              value={value.court_name ?? ""}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...value,
                  court_name: event.target.value,
                  forum_category: "legacy",
                  forum_catalog_entry_id: null,
                  court_id: null,
                })
              }
              placeholder="SIAC / local tribunal / uncatalogued court"
              data-testid={`${idPrefix}-legacy-court`}
            />
          </div>
        </>
      ) : null}

      {selectedEntry ? (
        <div className="md:col-span-2 text-xs text-[var(--color-mute)]">
          {selectedEntry.lineage}
          {selectedEntry.court_id
            ? " - linked court profile"
            : " - catalog selection"}
        </div>
      ) : null}
    </div>
  );
}
