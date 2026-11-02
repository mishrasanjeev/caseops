// Explicit local execution only. The existing prepare-store-packaging --plan
// recipe remains the default preparation contract and is never activated here.
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { executeStorePackaging, pendingStoreExecution } from './store-packaging-execution.mjs';

export async function main(args = process.argv.slice(2)) {
  if (args.length === 0) return { preparedOnly: true, readyForBuild: false, executionEnabled: false,
    instruction: 'Use the existing plan-only recipe. Local execution requires a new complete reviewed request and explicit GO.' };
  if (args.length === 2 && args[0] === '--pending') return pendingStoreExecution(args[1]);
  if (args.length !== 3 || args[0] !== '--execute') throw new Error('STORE_EXACT_EXECUTION_ARGUMENTS_REQUIRED');
  return executeStorePackaging({ path: args[1], sha256: args[2] });
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const result = await main();
    // Do not print a request, profile, keychain result, passwords or tool text.
    console.log(JSON.stringify(result?.kind === 'caseops-local-store-build-result'
      ? { kind: result.kind, observed: result.observed, contractOnly: result.contractOnly,
        distributionSigningVerified: result.distributionSigningVerified, cleanupComplete: result.cleanup.complete,
        storeAcceptance: false, uploaded: false } : result));
    if (result?.kind === 'caseops-local-store-build-result' && (!result.observed || !result.cleanup.complete)) process.exitCode = 1;
  } catch { console.error('STORE_LOCAL_PACKAGING_REFUSED'); process.exitCode = 1; }
}
