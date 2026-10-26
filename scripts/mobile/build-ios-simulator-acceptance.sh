#!/bin/bash
set -euo pipefail

if [[ "$(uname -s)" != Darwin ]]; then
  echo 'An actual Mac with Xcode is required; no iOS execution is claimed on Windows.' >&2
  exit 1
fi
: "${SIMULATOR_UDID:?Select one existing dedicated simulator UDID}"
: "${EXPO_PUBLIC_API_ORIGIN:?Supply the isolated HTTPS API origin}"
: "${EXPO_PUBLIC_WEB_ORIGIN:?Supply the isolated HTTPS web origin}"
repo="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "$HOME/.cache/caseops-mobile"
run="$(mktemp -d "$HOME/.cache/caseops-mobile/ios-build-XXXXXXXX")"
trap 'printf "Raw build evidence retained: %s\n" "$run"' EXIT
cd "$repo/apps/mobile"
export CASEOPS_MOBILE_BUILD_PROFILE=ios-simulator-acceptance
export CASEOPS_MOBILE_AUTOMATED_TEST=1
export CASEOPS_MOBILE_RELEASE_SHA="$(git rev-parse HEAD)"
export NODE_ENV=production EXPO_NO_DOTENV=1
node "$repo/scripts/mobile/build-acceptance.mjs" check ios "$run/before.json" 2>&1 | tee "$run/check.log"
node ./node_modules/expo/bin/cli prebuild --platform ios --no-install 2>&1 | tee "$run/prebuild.log"
(
  cd ios
  if [[ -f Podfile.lock ]]; then pod install --deployment; else pod install; fi
) 2>&1 | tee "$run/pods.log"
cp ios/Podfile.lock "$run/Podfile.lock"
xcodebuild -workspace ios/CaseOps.xcworkspace -scheme CaseOps -configuration Release \
  -sdk iphonesimulator -destination "platform=iOS Simulator,id=$SIMULATOR_UDID" \
  -derivedDataPath "$run/DerivedData" -jobs 4 \
  CODE_SIGNING_ALLOWED=YES CODE_SIGNING_REQUIRED=YES CODE_SIGN_IDENTITY=- CODE_SIGN_INJECT_BASE_ENTITLEMENTS=YES \
  build 2>&1 | tee "$run/xcodebuild.log"
app="$run/DerivedData/Build/Products/Release-iphonesimulator/CaseOps.app"
test -s "$app/main.jsbundle"
test "$(plutil -extract CFBundleIdentifier raw -o - "$app/Info.plist")" = ai.caseops.mobile.dev.simulatoracceptance
node "$repo/scripts/mobile/build-acceptance.mjs" finish ios "$run/before.json" "$app" \
  "$app/EXConstants.bundle/app.config" "$run/receipt.json" 2>&1 | tee "$run/finish.log"
printf 'Locally ad-hoc-signed standalone simulator build only: %s\n' "$app"
printf 'Owner/parent must separately install, launch, and run the native acceptance inventory.\n'
