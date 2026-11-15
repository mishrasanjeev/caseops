import assert from 'node:assert/strict';
import { dispatchQualifiedHttpsLink as androidDispatch, terminateQualifiedApp as androidTerminate,
  assertQualifiedColdState as androidCold } from './android-https-qualification.mjs';
import { dispatchIosQualifiedHttpsLink, terminateIosQualifiedApp, assertIosQualifiedColdState } from './ios-https-qualification.mjs';

// Platform dispatch only. Authority still belongs to each module's private lease;
// neither a fixture flag nor this facade can grant it.
function select(context, android, ios) {
  assert.ok(context.platform === 'android' || context.platform === 'ios', 'QUAL_PLATFORM_REQUIRED');
  return context.platform === 'android' ? android : ios;
}
export const dispatchQualifiedHttpsLink = (context, url) => select(context, androidDispatch, dispatchIosQualifiedHttpsLink)(context, url);
export const terminateQualifiedApp = context => select(context, androidTerminate, terminateIosQualifiedApp)(context);
export const assertQualifiedColdState = context => select(context, androidCold, assertIosQualifiedColdState)(context);
