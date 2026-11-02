/**
 * One strict parser for typed Nice class lists (BUG-002 / BUG-014).
 *
 * Lawyers type classes the way they appear in journals and instructions:
 * "Class 45", "42 45", "30;43", "Class 30, 43". Every one of those must read
 * as the classes the person meant, and anything that is not a class number
 * must come back as an error naming the token. A token is never dropped
 * silently: the previous per-page parsers turned "Class 45" into [] and
 * "Class 30, 43" into [43], and the published record was quietly wrong.
 *
 * The parser does not decide whether a class is required; callers that need
 * at least one class check `classes.length` and say so next to their field.
 */

export const NICE_CLASS_MIN = 1;
export const NICE_CLASS_MAX = 45;

export type NiceClassParseError = {
  /** The text the person typed, exactly as it appeared between separators. */
  token: string;
  message: string;
};

export type NiceClassParseResult = {
  /** Unique class numbers in the order they were first typed. */
  classes: number[];
  errors: NiceClassParseError[];
};

const SEPARATORS = /[\s,;]+/;
const PREFIX_ONLY = /^(?:class(?:es)?|cl\.?)$/i;
const PREFIXED_NUMBER = /^(?:class(?:es)?|cl\.?)(\d+)$/i;
const DIGITS = /^\d+$/;

export function isNiceClassNumber(value: unknown): value is number {
  return (
    typeof value === "number" &&
    Number.isInteger(value) &&
    value >= NICE_CLASS_MIN &&
    value <= NICE_CLASS_MAX
  );
}

function notAClass(token: string): NiceClassParseError {
  return {
    token,
    message: `"${token}" is not a Nice class number. Enter class numbers from ${NICE_CLASS_MIN} to ${NICE_CLASS_MAX}, separated by commas.`,
  };
}

function outOfRange(token: string, value: number): NiceClassParseError {
  return {
    token,
    message: `${value} is not a Nice class. Classes run from ${NICE_CLASS_MIN} to ${NICE_CLASS_MAX}.`,
  };
}

export function parseNiceClasses(input: string): NiceClassParseResult {
  const tokens = input.split(SEPARATORS).filter((token) => token.length > 0);
  const classes: number[] = [];
  const errors: NiceClassParseError[] = [];

  const accept = (token: string, digits: string) => {
    const value = Number(digits);
    if (!isNiceClassNumber(value)) {
      errors.push(outOfRange(token, value));
      return;
    }
    if (!classes.includes(value)) classes.push(value);
  };

  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (DIGITS.test(token)) {
      accept(token, token);
      continue;
    }
    const prefixed = PREFIXED_NUMBER.exec(token);
    if (prefixed) {
      accept(token, prefixed[1]);
      continue;
    }
    if (PREFIX_ONLY.test(token)) {
      const next = tokens[index + 1];
      if (next !== undefined && DIGITS.test(next)) {
        accept(`${token} ${next}`, next);
        index += 1;
      } else {
        errors.push({
          token,
          message: `"${token}" needs a class number after it, for example "${token} 35".`,
        });
      }
      continue;
    }
    errors.push(notAClass(token));
  }

  return { classes, errors };
}
