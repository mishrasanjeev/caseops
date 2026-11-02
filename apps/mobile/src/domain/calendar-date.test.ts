import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";
import { ContractError, displayDay } from "./contracts.ts";
import {
  adjacentCalendarDay,
  dateOnlyToPickerDate,
  pickerDateToDateOnly,
} from "./calendar-date.ts";

for (const day of [
  "0001-01-01",
  "0099-12-31",
  "1900-03-01",
  "2000-02-29",
  "2026-03-08",
  "2026-11-01",
  "2028-02-29",
  "9999-12-31",
]) {
  test(`native picker date round-trip preserves ${day} at UTC midnight`, () => {
    const date = dateOnlyToPickerDate(day);
    assert.equal(date.toISOString(), `${day}T00:00:00.000Z`);
    assert.equal(pickerDateToDateOnly(date), day);
  });
}
for (const day of [
  "2026-02-29",
  "2026-04-31",
  "0000-01-01",
  "10000-01-01",
  "2026-1-01",
  "2026-10-25T00:00:00Z",
  "",
  " 2026-10-25",
]) {
  test(`invalid typed date is rejected before native conversion: ${JSON.stringify(day)}`, () => {
    assert.throws(() => dateOnlyToPickerDate(day), ContractError);
  });
}
test("invalid native callback dates and years outside the API date-only domain fail closed", () => {
  for (const value of [
    new Date(NaN),
    new Date("0000-01-01T00:00:00Z"),
    new Date("+010000-01-01T00:00:00Z"),
    null,
    "2026-10-25",
    0,
  ])
    assert.throws(() => pickerDateToDateOnly(value as Date), ContractError);
});
for (const zone of [
  "Pacific/Kiritimati",
  "Pacific/Honolulu",
  "Etc/GMT+12",
  "Asia/Kolkata",
  "America/New_York",
  "Europe/London",
]) {
  test(`MOB-14 UTC picker/day/display round-trips across ${zone}, including DST boundaries`, () => {
    const original = process.env.TZ;
    try {
      process.env.TZ = zone;
      for (const day of [
        "2026-03-08",
        "2026-03-29",
        "2026-10-25",
        "2026-11-01",
        "2028-02-29",
      ]) {
        const native = dateOnlyToPickerDate(day);
        assert.equal(pickerDateToDateOnly(native), day);
        assert.equal(
          pickerDateToDateOnly(new Date(`${day}T23:59:59.999Z`)),
          day,
        );
        const baseline = new Intl.DateTimeFormat(undefined, {
          weekday: "short",
          day: "numeric",
          month: "short",
          year: "numeric",
          timeZone: "UTC",
        }).format(native);
        assert.equal(displayDay(pickerDateToDateOnly(native)), baseline);
      }
      if (zone === "Pacific/Honolulu") {
        const date = dateOnlyToPickerDate("2026-10-25");
        assert.equal(date.getDate(), 24); // A local-field decoder would select the wrong day.
        assert.equal(pickerDateToDateOnly(date), "2026-10-25");
      }
    } finally {
      if (original === undefined) delete process.env.TZ;
      else process.env.TZ = original;
    }
  });
}
test("picker callbacks do not mutate the native Date instance", () => {
  const value = new Date("2026-10-25T18:47:29.123Z");
  const before = value.getTime();
  assert.equal(pickerDateToDateOnly(value), "2026-10-25");
  assert.equal(value.getTime(), before);
});
for (const [day, offset, expected] of [
  ["2028-02-28", 1, "2028-02-29"],
  ["2028-03-01", -1, "2028-02-29"],
  ["2026-12-31", 1, "2027-01-01"],
  ["2027-01-01", -1, "2026-12-31"],
  ["2026-03-08", 7, "2026-03-15"],
  ["2026-11-01", -7, "2026-10-25"],
  ["0001-01-01", -1, null],
  ["0001-01-07", -7, null],
  ["9999-12-31", 1, null],
  ["9999-12-25", 7, null],
  ["0001-01-08", -7, "0001-01-01"],
  ["9999-12-24", 7, "9999-12-31"],
] as const) {
  test(`calendar navigation ${day} by ${offset} yields ${expected ?? "disabled"}`, () => {
    assert.equal(adjacentCalendarDay(day, offset), expected);
  });
}
test("invalid navigation never silently normalizes an impossible selected day or unsupported jump", () => {
  assert.throws(() => adjacentCalendarDay("2026-02-30", 1), ContractError);
  for (const value of [0, 2, 0.5, Infinity, NaN])
    assert.throws(
      () => adjacentCalendarDay("2026-10-25", value as 1),
      ContractError,
    );
});

// These are source-binding checks, not native rendering or device acceptance.
function source(path: string) {
  return ts.createSourceFile(
    path,
    readFileSync(new URL(path, import.meta.url), "utf8"),
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
}
function nodes(
  root: ts.Node,
  predicate: (node: ts.Node) => boolean,
): ts.Node[] {
  const found: ts.Node[] = [];
  const visit = (node: ts.Node) => {
    if (predicate(node)) found.push(node);
    ts.forEachChild(node, visit);
  };
  visit(root);
  return found;
}
test("native picker source binds actual installed Compose dialog and SwiftUI date-only UTC control", () => {
  const file = source("../components/NativeDatePicker.tsx");
  const text = (node: ts.Node) => node.getText(file);
  const tags = nodes(
    file,
    (node) => ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node),
  );
  assert.ok(
    tags.some(
      (tag) =>
        ts.isJsxSelfClosingElement(tag) &&
        text(tag.tagName) === "DatePickerDialog",
    ),
  );
  const picker = tags.find(
    (tag) =>
      ts.isJsxSelfClosingElement(tag) && text(tag.tagName) === "DatePicker",
  );
  assert.ok(picker);
  assert.ok(ts.isJsxSelfClosingElement(picker));
  const attributes = picker.attributes.properties;
  const pickerId = attributes.find(
    (node) => ts.isJsxAttribute(node) && text(node.name) === "testID",
  );
  assert.ok(
    pickerId &&
      ts.isJsxAttribute(pickerId) &&
      pickerId.initializer &&
      ts.isStringLiteral(pickerId.initializer),
  );
  assert.equal(pickerId.initializer.text, "date-picker");
  const displayed = attributes.find(
    (node) =>
      ts.isJsxAttribute(node) && text(node.name) === "displayedComponents",
  );
  assert.ok(
    displayed &&
      ts.isJsxAttribute(displayed) &&
      displayed.initializer &&
      ts.isJsxExpression(displayed.initializer),
  );
  assert.ok(
    displayed.initializer.expression &&
      ts.isArrayLiteralExpression(displayed.initializer.expression),
  );
  assert.deepEqual(
    displayed.initializer.expression.elements.map((node) => {
      assert.ok(ts.isStringLiteral(node));
      return node.text;
    }),
    ["date"],
  );
  const environments = nodes(
    picker,
    (node) =>
      ts.isCallExpression(node) && text(node.expression) === "environment",
  );
  assert.equal(environments.length, 1);
  assert.ok(ts.isCallExpression(environments[0]));
  const config = environments[0].arguments[0];
  assert.ok(ts.isObjectLiteralExpression(config));
  const settings = Object.fromEntries(
    config.properties.map((property) => {
      assert.ok(ts.isPropertyAssignment(property));
      assert.ok(ts.isStringLiteral(property.initializer));
      return [property.name.getText(file), property.initializer.text];
    }),
  );
  assert.deepEqual(settings, { key: "timeZone", value: "UTC" });
  const nativeSelections = nodes(
    file,
    (node) =>
      ts.isCallExpression(node) &&
      text(node.expression) === "dateOnlyToPickerDate",
  );
  assert.equal(nativeSelections.length, 2);
  assert.equal(
    nodes(
      file,
      (node) =>
        ts.isCallExpression(node) &&
        text(node.expression) === "pickerDateToDateOnly",
    ).length,
    1,
  );
});
test("Calendar source exposes exact stable controls and renders each event's actual occurs_on", () => {
  const file = source("../application/screens/CalendarScreen.tsx");
  const text = (node: ts.Node) => node.getText(file);
  const literalIds = nodes(
    file,
    (node) =>
      ts.isJsxAttribute(node) &&
      text(node.name) === "testID" &&
      !!node.initializer &&
      ts.isStringLiteral(node.initializer),
  ) as ts.JsxAttribute[];
  const ids = literalIds.map(
    (node) => (node.initializer as ts.StringLiteral).text,
  );
  for (const id of [
    "calendar-selected-day",
    "previous-day",
    "next-day",
    "previous-week",
    "next-week",
    "calendar-date-input",
    "calendar-go-date",
    "reload",
  ])
    assert.ok(ids.includes(id), `Missing stable ID ${id}`);
  const row = nodes(
    file,
    (node) =>
      ts.isJsxSelfClosingElement(node) && text(node.tagName) === "RecordRow",
  )[0];
  assert.ok(row);
  assert.equal(
    nodes(
      row,
      (node) =>
        ts.isCallExpression(node) &&
        text(node.expression) === "displayDay" &&
        text(node.arguments[0]) === "event.occurs_on",
    ).length,
    1,
  );
  const rowId = nodes(
    row,
    (node) => ts.isJsxAttribute(node) && text(node.name) === "testID",
  )[0];
  assert.ok(
    rowId &&
      ts.isJsxAttribute(rowId) &&
      rowId.initializer &&
      ts.isJsxExpression(rowId.initializer),
  );
  assert.ok(
    rowId.initializer.expression &&
      ts.isTemplateExpression(rowId.initializer.expression),
  );
  assert.equal(rowId.initializer.expression.head.text, "event-");
  assert.equal(
    text(rowId.initializer.expression.templateSpans[0].expression),
    "event.id",
  );
});
