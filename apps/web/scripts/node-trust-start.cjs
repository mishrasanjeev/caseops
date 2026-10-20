"use strict";

try {
  require("./node-trust.cjs").verifyRuntime();
} catch {
  console.error("CaseOps Node trust policy refused startup.");
  process.exit(1);
}
