import { describe, expect, it } from "vitest";

import { isNiceClassNumber, parseNiceClasses } from "@/lib/ip/nice-classes";

describe("parseNiceClasses", () => {
  it.each([
    ["Class 45", [45]],
    ["class 45", [45]],
    ["CLASS45", [45]],
    ["Cl. 9", [9]],
    ["cl.9", [9]],
    ["cl 9", [9]],
    ["42 45", [42, 45]],
    ["30;43", [30, 43]],
    ["30; 43", [30, 43]],
    ["Class 30, 43", [30, 43]],
    ["30, Class 43", [30, 43]],
    ["Classes 9, 42", [9, 42]],
    ["9,\n42\t45", [9, 42, 45]],
    ["  35  ", [35]],
    ["09", [9]],
    ["1, 45", [1, 45]],
    ["45, 9", [45, 9]],
  ])("reads %j as %j with no errors", (input, classes) => {
    expect(parseNiceClasses(input)).toEqual({ classes, errors: [] });
  });

  it.each([
    ["9, 9", [9]],
    ["Class 9, 9; cl. 9", [9]],
    ["35 9 35", [35, 9]],
  ])("collapses duplicates in %j to %j", (input, classes) => {
    expect(parseNiceClasses(input)).toEqual({ classes, errors: [] });
  });

  it.each(["", "   ", ",;  ,"])("returns nothing, and no error, for blank input %j", (input) => {
    expect(parseNiceClasses(input)).toEqual({ classes: [], errors: [] });
  });

  it("reports every word of '30 - Biscuits' instead of dropping it", () => {
    const result = parseNiceClasses("30 - Biscuits");
    expect(result.classes).toEqual([30]);
    expect(result.errors.map((error) => error.token)).toEqual(["-", "Biscuits"]);
    expect(result.errors[1].message).toBe(
      '"Biscuits" is not a Nice class number. Enter class numbers from 1 to 45, separated by commas.',
    );
  });

  it.each([
    ["9.5", "9.5", '"9.5" is not a Nice class number.'],
    ["0", "0", "0 is not a Nice class. Classes run from 1 to 45."],
    ["46", "46", "46 is not a Nice class. Classes run from 1 to 45."],
    ["Class 46", "Class 46", "46 is not a Nice class."],
    ["-5", "-5", '"-5" is not a Nice class number.'],
    ["4x", "4x", '"4x" is not a Nice class number.'],
    ["९", "९", '"९" is not a Nice class number.'],
    ["Class", "Class", '"Class" needs a class number after it, for example "Class 35".'],
    ["Class Biscuits", "Class", '"Class" needs a class number after it'],
  ])("rejects %j, naming the token", (input, token, message) => {
    const result = parseNiceClasses(input);
    expect(result.errors).toHaveLength(input === "Class Biscuits" ? 2 : 1);
    expect(result.errors[0].token).toBe(token);
    expect(result.errors[0].message).toContain(message);
    expect(result.classes).toEqual([]);
  });

  it("keeps the valid classes and names the bad token in a partly valid list", () => {
    expect(parseNiceClasses("Class 30, 4x, 43")).toEqual({
      classes: [30, 43],
      errors: [
        {
          token: "4x",
          message:
            '"4x" is not a Nice class number. Enter class numbers from 1 to 45, separated by commas.',
        },
      ],
    });
  });

  it.each(["Class 30, 43", "42 45", "30 - Biscuits", "9.5; 0; 46; Class 45", "cl. 9 and 42"])(
    "accounts for every token of %j as a class or an error",
    (input) => {
      const result = parseNiceClasses(input);
      const errorWords = result.errors.flatMap((error) => error.token.split(" "));
      for (const token of input.split(/[\s,;]+/).filter(Boolean)) {
        const digits = /^(?:class(?:es)?|cl\.?)?(\d+)$/i.exec(token)?.[1];
        if (digits !== undefined && result.classes.includes(Number(digits))) continue;
        if (/^(?:class(?:es)?|cl\.?)$/i.test(token) && !errorWords.includes(token)) continue;
        expect(errorWords).toContain(token);
      }
    },
  );
});

describe("isNiceClassNumber", () => {
  it.each([
    [1, true],
    [45, true],
    [0, false],
    [46, false],
    [9.5, false],
    [Number.NaN, false],
    ["9", false],
  ])("%j -> %j", (value, expected) => {
    expect(isNiceClassNumber(value)).toBe(expected);
  });
});
