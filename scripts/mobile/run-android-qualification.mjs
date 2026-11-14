// Local qualification and separately gated unchanged-byte promotion. Never upload.
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promoteAndroidQualification } from './android-qualification-promotion.mjs';
import { executeAndroidQualification, pendingAndroidQualification } from './store-packaging-execution.mjs';

export async function main(args = process.argv.slice(2)) {
  if (args.length === 0) return pendingAndroidQualification();
  if (args.length !== 3 || !['--execute', '--promote'].includes(args[0])) throw Error('QUALIFICATION_EXACT_ARGUMENTS_REQUIRED');
  return (args[0] === '--promote' ? promoteAndroidQualification : executeAndroidQualification)({ path: args[1], sha256: args[2] });
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const result = await main();
    console.log(JSON.stringify({ kind: result.kind, observed: result.observed ?? false,
      qualificationOnly: result.qualificationOnly ?? false, submissionAllowed: result.submissionAllowed ?? false, uploaded: false }));
    if (result.readyForLocalBuild || result.observed === false) process.exitCode = 1;
  } catch { console.error('ANDROID_QUALIFICATION_REFUSED'); process.exitCode = 1; }
}
