/*global navigator*/
'use strict';

const {
  REGEX_BACKSLASH,
  REGEX_SPECIAL_CHARS,
  REGEX_SPECIAL_CHARS_GLOBAL
} = require('./constants');

exports.isObject = val => val !== null && typeof val === 'object' && !Array.isArray(val);
exports.hasRegexChars = str => REGEX_SPECIAL_CHARS.test(str);
exports.isRegexChar = str => str.length === 1 && exports.hasRegexChars(str);
exports.escapeRegex = str => str.replace(REGEX_SPECIAL_CHARS_GLOBAL, '\\$1');
exports.toPosixSlashes = str => str.replace(REGEX_BACKSLASH, '/');

exports.isWindows = () => {
  if (typeof navigator !== 'undefined' && navigator.platform) {
    const platform = navigator.platform.toLowerCase();
    return platform === 'win32' || platform === 'windows';
  }

  if (typeof process !== 'undefined' && process.platform) {
    return process.platform === 'win32';
  }

  return false;
};

exports.removeBackslashes = str => {
  // Monotonic cursors prevent a fresh suffix scan for every unmatched '['.
  // The original dot excludes four line terminators; its final class may
  // consume one immediately before the closing bracket.
  const lineBreak = ch => ch === '\n' || ch === '\r' || ch === '\u2028' || ch === '\u2029';
  let closing = 0;
  let boundary = 0;
  let kept = 0;
  const output = [];
  for (let i = 0; i < str.length; i++) {
    if (str[i] === '[') {
      if (closing < i + 2) {
        closing = i + 2;
        while (closing < str.length && (str[closing] !== ']' || str[closing - 1] === '\\')) closing++;
      }
      if (boundary < i + 1) {
        boundary = i + 1;
        while (boundary < str.length && !lineBreak(str[boundary])) boundary++;
      }
      if (closing < str.length && closing <= boundary + 1) {
        i = closing;
        continue;
      }
    }
    if (str[i] === '\\' && i + 1 < str.length && !lineBreak(str[i + 1])) {
      output.push(str.slice(kept, i));
      kept = i + 1;
    }
  }
  return output.join('') + str.slice(kept);
};

exports.escapeLast = (input, char, lastIdx) => {
  const idx = input.lastIndexOf(char, lastIdx);
  if (idx === -1) return input;
  if (input[idx - 1] === '\\') return exports.escapeLast(input, char, idx - 1);
  return `${input.slice(0, idx)}\\${input.slice(idx)}`;
};

exports.removePrefix = (input, state = {}) => {
  let output = input;
  if (output.startsWith('./')) {
    output = output.slice(2);
    state.prefix = './';
  }
  return output;
};

exports.wrapOutput = (input, state = {}, options = {}) => {
  const prepend = options.contains ? '' : '^';
  const append = options.contains ? '' : '$';

  let output = `${prepend}(?:${input})${append}`;
  if (state.negated === true) {
    output = `(?:^(?!${output}).*$)`;
  }
  return output;
};

exports.basename = (path, { windows } = {}) => {
  const segs = path.split(windows ? /[\\/]/ : '/');
  const last = segs[segs.length - 1];

  if (last === '') {
    return segs[segs.length - 2];
  }

  return last;
};
