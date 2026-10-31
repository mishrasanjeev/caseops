#!/bin/bash
set -euo pipefail
umask 077

if [[ "$(uname -s)" != Darwin ]]; then
  echo 'An actual Mac with Xcode is required; no iOS execution is claimed on Windows.' >&2
  exit 1
fi
: "${SIMULATOR_UDID:?Select one existing dedicated simulator UDID}"
: "${EXPO_PUBLIC_API_ORIGIN:?Supply the isolated HTTPS API origin}"
: "${EXPO_PUBLIC_WEB_ORIGIN:?Supply the isolated HTTPS web origin}"
: "${CASEOPS_IOS_HOST_SOURCE_ROOT:?Owned controller must bind source root}"
: "${CASEOPS_IOS_HOST_BUILD_OUTPUT:?Owned controller must bind private output}"
repo="$CASEOPS_IOS_HOST_SOURCE_ROOT"
run="$CASEOPS_IOS_HOST_BUILD_OUTPUT"
trap 'printf "Raw build evidence retained: %s\n" "$run"' EXIT
cd "$repo/apps/mobile"
export CASEOPS_MOBILE_BUILD_PROFILE=ios-simulator-acceptance
export CASEOPS_MOBILE_AUTOMATED_TEST=1
: "${CASEOPS_MOBILE_RELEASE_SHA:?Owned controller must bind immutable Git revision}"
export NODE_ENV=production EXPO_NO_DOTENV=1
node "$repo/scripts/mobile/prepare-viewer-assets.mjs" --check 2>&1 | tee "$run/viewer-assets-check.log"
node "$repo/scripts/mobile/build-acceptance.mjs" check ios "$run/before.json" 2>&1 | tee "$run/check.log"
node ./node_modules/expo/bin/cli prebuild --platform ios --no-install 2>&1 | tee "$run/prebuild.log"
(
  cd ios
  if [[ -f Podfile.lock ]]; then pod install --deployment; else pod install; fi
) 2>&1 | tee "$run/pods.log"
cp ios/Podfile.lock "$run/Podfile.lock"
"$CASEOPS_IOS_HOST_XCODEBUILD" -workspace ios/CaseOps.xcworkspace -scheme CaseOps -configuration Release \
  -sdk iphonesimulator -destination "platform=iOS Simulator,id=$SIMULATOR_UDID" \
  -derivedDataPath "$run/DerivedData" -jobs 4 \
  "HOME=$HOME" \
  CODE_SIGNING_ALLOWED=YES CODE_SIGNING_REQUIRED=YES CODE_SIGN_IDENTITY=- CODE_SIGN_INJECT_BASE_ENTITLEMENTS=YES \
  build 2>&1 | tee "$run/xcodebuild.log"
app="$run/DerivedData/Build/Products/Release-iphonesimulator/CaseOps.app"
test -s "$app/main.jsbundle"
test "$("$CASEOPS_IOS_HOST_PLUTIL" -extract CFBundleIdentifier raw -o - "$app/Info.plist")" = ai.caseops.mobile.dev.simulatoracceptance
node "$repo/scripts/mobile/build-acceptance.mjs" finish ios "$run/before.json" "$app" \
  "$app/EXConstants.bundle/app.config" "$run/receipt.json" 2>&1 | tee "$run/finish.log"
printf 'Locally ad-hoc-signed standalone simulator build only: %s\n' "$app"
printf 'Owner/parent must separately install, launch, and run the native acceptance inventory.\n'
